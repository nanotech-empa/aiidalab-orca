"""Fixed-orbital CASCI: one charge and spin multiplicity per small WorkChain."""

import hashlib
import json
import math
import re

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from .artifacts import resolve_electronic, storage_builder, storage_policy
from .common_orbitals import attach_orbital, copy_orbital, options, source_spec
from .input import render_input
from .reference import single_point_parameters

PROCESS_TYPE = 'aiida.workflows:empa_orca.casci'
HARTREE_TO_EV = 27.211386245988


def active_space(values, reference):
    """Keep the exact same spatial active orbitals in all charge sectors.

    Initial scope: a contiguous window in the prepared ordering. Reordering is
    a separate future orbital-preparation operation, never an implicit swap.
    """
    if set(values) != {'electrons', 'orbitals'}:
        raise ValueError('Active space requires electrons and explicit zero-based orbital indices')
    nel, indices = values['electrons'], values['orbitals']
    if type(nel) is not int or not isinstance(indices, list) or not indices or any(type(i) is not int for i in indices):
        raise ValueError('Provide an integer electron count and a list of orbital indices')
    n = len(indices)
    if not 0 <= nel <= 2*n or (reference['n_electrons']-nel) % 2:
        raise ValueError('Active electrons must leave an even number of inactive electrons')
    inactive = (reference['n_electrons']-nel)//2
    if nel < reference['source_multiplicity']-1 or 2*n-nel < reference['source_multiplicity']-1:
        raise ValueError('The active space must contain the reference singly occupied orbitals')
    if inactive < 0 or indices != list(range(inactive, inactive+n)) or indices[-1] >= reference['n_orbitals']:
        raise ValueError(f'This draft requires the contiguous orbital window starting at ORCA index {inactive}; orbital reordering is not implemented')
    return {'electrons': nel, 'orbitals': list(indices)}


def casci_settings(values, reference, space):
    defaults = {'charge':reference['charge'], 'multiplicity':reference['source_multiplicity'], 'nroots':1,
                'nprocs':reference['settings']['nprocs'], 'memory_mb':reference['settings']['memory_mb'],
                'wallclock_seconds':reference['settings']['wallclock_seconds'],
                'auxiliary_basis': (reference['settings']['basis']+'/C' if reference['settings']['basis'] in
                                    ('def2-SVP','def2-TZVP','def2-TZVPP') else 'AutoAux'), 'tprintwf':1e-6}
    if set(values)-set(defaults):
        raise ValueError('Unknown CASCI setting')
    s = defaults | values
    for key in ('charge', 'multiplicity', 'nroots', 'nprocs', 'memory_mb', 'wallclock_seconds'):
        if type(s[key]) is not int or (key != 'charge' and s[key] < 1):
            raise ValueError(f'{key} must be an integer'+('' if key == 'charge' else ' greater than zero'))
    if s['memory_mb'] < 256*s['nprocs']:
        raise ValueError('Provide at least 256 MiB per process')
    if abs(s['charge']-reference['charge']) > 1:
        raise ValueError('This step supports the reference charge and its N±1 neighbours')
    from .protocols import _token
    s['auxiliary_basis'] = _token(s['auxiliary_basis'], 'CASCI correlation auxiliary basis')
    if type(s['tprintwf']) not in (float, int) or not math.isfinite(s['tprintwf']) or not 0 < s['tprintwf'] <= 1e-2:
        raise ValueError('Determinant printing threshold must be >0 and ≤0.01')
    electrons = space['electrons']-(s['charge']-reference['charge'])
    m, unpaired = len(space['orbitals']), s['multiplicity']-1
    if not 0 <= electrons <= 2*m or electrons < unpaired or (electrons-unpaired) % 2:
        raise ValueError('Charge/multiplicity is incompatible with the active electron count')
    alpha, beta = (electrons+unpaired)//2, (electrons-unpaired)//2
    def choose(n, k):
        return math.comb(n, k) if 0 <= k <= n else 0
    dimension = choose(m, alpha)*choose(m, beta)-choose(m, alpha+1)*choose(m, beta-1)
    if s['nroots'] > dimension:
        raise ValueError(f'This spin sector contains only {dimension} states; request fewer roots')
    return s


def casci_input(reference, space, settings):
    space = active_space(space, reference)
    s = casci_settings(settings, reference, space)
    source = single_point_parameters(reference['settings'])
    # Carry the orbital basis and element overrides, not the DFT functional:
    # CASCI uses the electronic Hamiltonian in the fixed orbital basis.
    params = {'charge':s['charge'], 'multiplicity':s['multiplicity'],
              'input_keywords':[reference['settings']['basis'], s['auxiliary_basis'], 'MOREAD', 'NoIter'],
              'input_blocks':{'pal':{'nprocs':s['nprocs']}}}
    if 'basis' in source['input_blocks']:
        params['input_blocks']['basis'] = source['input_blocks']['basis']
    nel = space['electrons']-s['charge']+reference['charge']
    text = ('%moinp "reference.gbw"\n'
            f'%casscf\n nel {nel}\n norb {len(space["orbitals"])}\n mult {s["multiplicity"]}\n'
            f' nroots {s["nroots"]}\n maxiter 1\n TrafoStep RI\n'
            ' ActOrbs unchanged\n IntOrbs unchanged\n ExtOrbs unchanged\n printwf det\n'
            f' ci\n  TPrintWF {s["tprintwf"]:.12g}\n end\nend\n'
            '%output\n Print[P_Basis] 2\n Print[P_MOs] 1\nend\n')
    return text + render_input(params, int(.75*s['memory_mb']/s['nprocs']), 'aiida.coords.xyz')


def parse_states(text, reference, space, settings):
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('ORCA did not terminate normally')
    nel = space['electrons']-settings['charge']+reference['charge']
    expected_counts = {'Number of active electrons':nel, 'Number of active orbitals':len(space['orbitals']),
                       'Total number of electrons':reference['n_electrons']-settings['charge']+reference['charge']}
    for label, expected_count in expected_counts.items():
        values = re.findall(label+r'\s+\.\.\.\s+(\d+)',text)
        if not values or int(values[-1]) != expected_count:
            raise ValueError('ORCA active-space/electron count does not match the request: '+label)
    ranges = re.findall(r'Active\s+(\d+)\s*-\s*(\d+)\s*\(',text)
    if not ranges or list(map(int,ranges[-1])) != [space['orbitals'][0],space['orbitals'][-1]]:
        raise ValueError('ORCA used different active orbital indices')
    if 'CI-PROBLEM SOLVED' not in text:
        raise ValueError('CI convergence was not confirmed')
    if '>>> CAS-CI.' not in text:
        raise ValueError('ORCA did not confirm a CASCI calculation')
    for kind in ('Active', 'Internal', 'External'):
        if not re.search(kind+r'\s+Orbitals\s+\.\.\.\s+unchanged', text):
            raise ValueError('ORCA did not preserve every orbital subspace')
    blocks = list(re.finditer(r'CAS-SCF STATES FOR BLOCK\s+\d+\s+MULT=\s*(\d+)\s+NROOTS=\s*(\d+)', text))
    if len(blocks) != 1 or tuple(map(int, blocks[0].groups())) != (settings['multiplicity'], settings['nroots']):
        raise ValueError('Missing or unexpected final CASCI multiplicity/root block')
    block = text[blocks[0].end():].split('Spin-Determinant CI Printing')[0].split('DENSITY MATRIX')[0]
    found = {}
    for root, energy in re.findall(r'ROOT\s+(\d+)\s*:\s*E=\s*([-+\d.Ee]+)\s+Eh', block):
        key, value = (settings['multiplicity'], int(root)), float(energy)
        if not math.isfinite(value):
            raise ValueError('Non-finite state energy')
        found[key] = value
    expected = {(settings['multiplicity'], root) for root in range(settings['nroots'])}
    if set(found) != expected:
        raise ValueError(f'Incomplete CASCI states: expected {sorted(expected)}, found {sorted(found)}')
    return {'schema_version':1, 'method':'CASCI', 'geometry_mode':'fixed', 'energy_unit':'hartree',
            'active_space':space, 'model':{'integral_transform':'RI','auxiliary_basis':settings['auxiliary_basis']},
            'reference_charge':reference['charge'],
            'active_electrons':space['electrons']-settings['charge']+reference['charge'],
            'states':[{'charge':settings['charge'], 'multiplicity':mult, 'root':root,
                       'energy_hartree':found[(mult, root)]} for mult, root in sorted(expected)]}


def validate_reference(reference_node, source_remote):
    from .fixed_orbitals_data import CALCULATION, PREPARATION
    producer = reference_node.creator
    if (producer is None or not producer.is_finished_ok or producer.process_type not in (
            'aiida.calculations:empa_orca.common_orbitals', CALCULATION)
            or producer.outputs.remote_folder.uuid != source_remote.uuid):
        raise ValueError('The common-orbital metadata and folder must share their preparation CalcJob')
    if producer.process_type == CALCULATION and reference_node.get_dict().get('preparation') != PREPARATION:
        raise ValueError('External orbitals require a verified frozen-CASCI import')
    return reference_node.get_dict()


def reference_orca_code(reference_node):
    """Imported references are validated by a helper, not the future ORCA code."""
    from .fixed_orbitals_data import CALCULATION, PROCESS
    producer = reference_node.creator
    if producer.process_type != CALCULATION:
        return str(producer.inputs.code.uuid)
    candidates = set()
    for triple in reference_node.base.links.get_incoming(link_type=common.LinkType.RETURN).all():
        parent = triple.node
        if (parent.process_type == PROCESS and parent.is_finished_ok and
                parent.outputs.remote_folder.uuid == producer.outputs.remote_folder.uuid):
            candidates.add(str(parent.inputs.code.uuid))
    if len(candidates) != 1:
        raise ValueError('Imported orbitals require their successful preparation workflow and declared ORCA code')
    return candidates.pop()


class CasciCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('structure', valid_type=orm.StructureData)
        spec.input('orbital_reference', valid_type=orm.Dict)
        spec.input('active_space', valid_type=orm.Dict)
        spec.input('settings', valid_type=orm.Dict)
        source_spec(spec)
        spec.input('metadata.options.parser_name', default='empa_orca.casci')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('state_energies', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_STATES', message='CASCI states are missing or invalid; inspect aiida.out.')

    def prepare_for_submission(self, folder):
        reference = self.inputs.orbital_reference.get_dict()
        if str(self.inputs.structure.uuid) != reference['structure_uuid']:
            raise ValueError('CASCI must use the exact prepared geometry node')
        with folder.open('aiida.inp', 'w') as handle:
            handle.write(casci_input(reference, self.inputs.active_space.get_dict(), self.inputs.settings.get_dict()))
        OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
        info = common.CalcInfo()
        copy_orbital(info, self.inputs)
        code = common.CodeInfo()
        code.code_uuid, code.cmdline_params = self.inputs.code.uuid, ['aiida.inp']
        code.stdout_name, code.join_files = 'aiida.out', True
        info.codes_info, info.retrieve_list = [code], ['aiida.out', 'aiida.property.txt']
        return info


class CasciParser(Parser):
    def parse(self, **kwargs):
        try:
            reference = self.node.inputs.orbital_reference.get_dict()
            space = active_space(self.node.inputs.active_space.get_dict(), reference)
            settings = casci_settings(self.node.inputs.settings.get_dict(), reference, space)
            text = self.retrieved.base.repository.get_object_content('aiida.out')
            data = parse_states(text, reference, space, settings)
            data['orbital_reference_uuid'] = str(self.node.inputs.orbital_reference.uuid)
            data['structure_uuid'] = str(self.node.inputs.structure.uuid)
            self.out('state_energies', orm.Dict(dict=data))
        except (KeyError, ValueError, OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_STATES


def signature(reference_uuid, space, settings, code_uuid):
    payload = {'reference':str(reference_uuid), 'space':space, 'settings':settings, 'code':str(code_uuid)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def existing_calculations(reference_uuid):
    return orm.QueryBuilder().append(orm.Dict, filters={'uuid':str(reference_uuid)}, tag='reference').append(
        orm.WorkChainNode, with_incoming='reference', edge_filters={'label':'orbital_reference'}, tag='run',
        filters={'process_type':PROCESS_TYPE}, project=['uuid']).order_by({'run':{'ctime':'desc'}}).all(flat=True)


class CasciWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'orbital_reference':orm.Dict, 'source_remote':orm.RemoteData, 'active_space':orm.Dict,
                         'settings':orm.Dict, 'code':orm.AbstractCode, 'storage_code':orm.AbstractCode,
                         'storage_policy':orm.Dict}.items():
            spec.input(key, valid_type=typ)
        spec.input('force_recompute', valid_type=orm.Bool, default=lambda:orm.Bool(False))
        for key, typ in {'state_energies':orm.Dict, 'retrieved':orm.FolderData, 'remote_folder':orm.RemoteData}.items():
            spec.output(key, valid_type=typ)
        spec.outline(cls.setup, engine.if_(cls.needs_calculation)(cls.run_casci, cls.inspect,
                     cls.preserve, cls.inspect_storage), cls.results)
        spec.exit_code(400, 'ERROR_INPUT', message='Invalid CASCI request or missing common orbitals; see report.')
        spec.exit_code(401, 'ERROR_CASCI', message='CASCI calculation failed; inspect the child calculation.')
        spec.exit_code(402, 'ERROR_STORAGE', message='State energies are available, but CASCI orbital preservation failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            ref = validate_reference(self.inputs.orbital_reference, self.inputs.source_remote)
            self.ctx.space = active_space(self.inputs.active_space.get_dict(), ref)
            self.ctx.settings = casci_settings(self.inputs.settings.get_dict(), ref, self.ctx.space)
            storage_policy(self.inputs.storage_policy.get_dict())
            if self.inputs.code.computer.uuid != self.inputs.storage_code.computer.uuid:
                raise ValueError('ORCA and storage codes must use the same computer')
            if str(self.inputs.code.uuid) != reference_orca_code(self.inputs.orbital_reference):
                raise ValueError('Use the same ORCA code as the common-orbital preparation')
            expected = signature(self.inputs.orbital_reference.uuid, self.ctx.space, self.ctx.settings, self.inputs.code.uuid)
            if not self.inputs.force_recompute.value:
                for uuid in existing_calculations(self.inputs.orbital_reference.uuid):
                    node = orm.load_node(uuid)
                    if not (node.is_finished_ok or (node.is_finished and node.exit_status == 402)):
                        continue
                    previous = signature(node.inputs.orbital_reference.uuid, node.inputs.active_space.get_dict(),
                                         casci_settings(node.inputs.settings.get_dict(), ref, self.ctx.space), node.inputs.code.uuid)
                    if previous != expected:
                        continue
                    # Energies and CI printout survive scratch deletion. Later
                    # Dyson consumers must separately check their required GBW.
                    text = node.outputs.retrieved.base.repository.get_object_content('aiida.out')
                    parsed = parse_states(text, ref, self.ctx.space, self.ctx.settings)
                    if parsed['model'] != node.outputs.state_energies.get_dict().get('model'):
                        continue
                    if parsed['states'] != node.outputs.state_energies.get_dict()['states']:
                        raise ValueError('CASCI energies differ from the retrieved output')
                    self.ctx.reuse_uuid = str(uuid)
                    self.report(f'Reusing state energies from {uuid}; no ORCA calculation is needed')
                    return
            self.ctx.location = resolve_electronic(self.inputs.source_remote, names=[ref['filename']])
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INPUT

    def needs_calculation(self):
        return self.ctx.reuse_uuid is None

    def run_casci(self):
        ref = self.inputs.orbital_reference.get_dict()
        b = CasciCalculation.get_builder()
        b.structure = orm.load_node(ref['structure_uuid'])
        b.orbital_reference, b.active_space = self.inputs.orbital_reference, orm.Dict(dict=self.ctx.space)
        b.settings, b.code = orm.Dict(dict=self.ctx.settings), self.inputs.code
        attach_orbital(b, self.ctx.location, ref['filename'])
        b.metadata.options = options(self.ctx.settings)
        # Explicit reuse above needs only durable state energies/CI text. A real
        # run also promises a new GBW, so a stale cached scratch must not win.
        b.metadata.disable_cache = True
        return engine.ToContext(casci=self.submit(b))

    def inspect(self):
        if not self.ctx.casci.is_finished_ok:
            return self.exit_codes.ERROR_CASCI
        # Preserve useful energies even if the subsequent archive step fails.
        for key in ('state_energies', 'retrieved', 'remote_folder'):
            self.out(key, self.ctx.casci.outputs[key])

    def preserve(self):
        b = storage_builder(self.ctx.casci.outputs.remote_folder, self.inputs.storage_code,
                            self.inputs.storage_policy.get_dict(), names=['aiida.gbw'])
        return engine.ToContext(storage=self.submit(b))

    def inspect_storage(self):
        if not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE

    def results(self):
        if self.ctx.reuse_uuid:
            node = orm.load_node(self.ctx.reuse_uuid)
            for key in ('state_energies', 'retrieved', 'remote_folder'):
                self.out(key, node.outputs[key])


def energy_diagram(datasets, reference_state=None):
    """Plain data for a common total-energy scale; never zero each spin sector."""
    if not datasets:
        return {'states':[], 'reference_state':None}
    first = datasets[0]
    identity = ('orbital_reference_uuid', 'structure_uuid', 'active_space', 'model', 'method', 'geometry_mode')
    if any(any(data[key] != first[key] for key in identity) for data in datasets):
        raise ValueError('State comparison requires the same geometry, common orbitals, active space and CASCI integral model')
    states = {}
    for data in datasets:
        for row in data['states']:
            key = f"q{row['charge']}:m{row['multiplicity']}:r{row['root']}"
            if key in states and abs(states[key]['energy_hartree']-row['energy_hartree']) > 1e-8:
                raise ValueError('Conflicting calculations for the same state; select a single consistent set')
            states[key] = dict(row, id=key)
    candidates = [row for row in states.values() if row['charge'] == first['reference_charge']]
    if reference_state is None:
        reference_state = min(candidates or list(states.values()), key=lambda row:row['energy_hartree'])['id']
    if reference_state not in states:
        raise ValueError('Select a reference state from this diagram')
    zero = states[reference_state]['energy_hartree']
    for row in states.values():
        row['relative_energy_ev'] = (row['energy_hartree']-zero)*HARTREE_TO_EV
    return {'states':list(states.values()), 'reference_state':reference_state,
            'reference_energy_hartree':zero, 'energy_convention':'total energy relative to selected state',
            'orbital_reference_uuid':first['orbital_reference_uuid'], 'active_space':first['active_space']}
