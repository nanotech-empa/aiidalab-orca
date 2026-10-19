"""Fixed-geometry, site-resolved K-edge ΔSCF photoelectron spectroscopy."""

import hashlib
import json
import math
import re
from importlib.resources import files

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from .artifacts import resolve_electronic, storage_builder, storage_policy
from .common_orbitals import attach_orbital, copy_orbital, options, source_spec, validate_source
from .input import render_input
from .protocols import reference
from .reference import reference_settings, single_point_parameters

PROCESS_TYPE = 'aiida.workflows:empa_orca.xps'
CORE_PROCESS = 'aiida.workflows:empa_orca.xps_core'
SITE_PROCESS = 'aiida.calculations:empa_orca.xps_site'


def validate_reference(structure, settings):
    s = reference_settings(settings)
    from .settings import validate_molecule
    validate_molecule(structure, s)
    if s['multiplicity'] != 1 or reference(s) != 'RKS':
        raise ValueError('This XPS draft requires a closed-shell RKS singlet; open-shell multiplets need a separate validated treatment.')
    if set(structure.get_ase().numbers) - {1, 6, 7, 8, 9}:
        raise ValueError('This K-edge draft supports molecules containing H, C, N, O and F, with C/O 1s ionization.')
    if any(v.get('ecp', 'none').lower() != 'none' for v in s['element_settings'].values()):
        raise ValueError('Core-ionization XPS requires an all-electron reference; ECPs are not supported.')
    if s['block_parameters']:
        raise ValueError('Expert block overrides require separate validation before use in this XPS draft.')
    return s


def core_parameters(settings):
    p = single_point_parameters(settings)
    p['input_keywords'] += ['MOREAD', 'NoIter']
    p['input_blocks']['scf'] = {'MaxIter': 0}
    p['input_blocks']['output'] = {'Print[P_AtPopMO_L]': 1}
    return p


def site_parameters(settings, orbital_index):
    p = single_point_parameters(settings)
    p['input_keywords'] = ['UKS' if x == 'RKS' else x for x in p['input_keywords']]
    p['input_keywords'] += ['MOREAD', 'DeltaSCF', 'NoDIIS', 'NoTRAH']
    p['input_blocks']['scf'].update(IonizeAlpha=int(orbital_index))
    # ORCA 6.1.1 skips Löwdin analysis after IonizeAlpha because its population
    # routine still expects the reference NEL. Native Mulliken MO populations
    # remain available; electron counts are checked independently below.
    p['input_blocks']['output'] = {'Print[P_AtPopMO_M]': 1}
    # IonizeAlpha changes electron count/spin internally: retain the reference
    # charge and multiplicity in the XYZ declaration (ORCA 6.1 manual 5.34.3.2).
    return p


class CoreOrbitalsCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, kind in {'structure': orm.StructureData, 'settings': orm.Dict,
                          'source_retrieved': orm.FolderData, 'helper_code': orm.AbstractCode}.items():
            spec.input(key, valid_type=kind)
        source_spec(spec)
        spec.input('metadata.options.parser_name', default='empa_orca.xps_core')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('core_reference', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_CORE', message='Core-orbital preparation/assignment failed; inspect core.log and aiida.out.')

    def prepare_for_submission(self, folder):
        s = validate_reference(self.inputs.structure, self.inputs.settings.get_dict())
        if self.inputs.code.computer.uuid != self.inputs.helper_code.computer.uuid:
            raise ValueError('ORCA and ORCA tools must use the same computer')
        text = '%moinp "reference.gbw"\n' + render_input(core_parameters(s), int(.75*s['memory_mb']/s['nprocs']), 'aiida.coords.xyz')
        with folder.open('aiida.inp', 'w') as handle:
            handle.write(text)
        OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
        with folder.open('localized_check.inp', 'w') as handle:
            handle.write(text.replace('"reference.gbw"', '"localized.gbw"'))
        with folder.open('core_orbitals.py', 'w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('scripts/core_orbitals.py').read_text())
        with folder.open('request.json', 'w') as handle:
            json.dump({'numbers': self.inputs.structure.get_ase().numbers.tolist(),
                       'orca': str(self.inputs.code.filepath_executable)}, handle)
        info = common.CalcInfo()
        copy_orbital(info, self.inputs)
        native, helper = common.CodeInfo(), common.CodeInfo()
        native.code_uuid, native.cmdline_params = self.inputs.code.uuid, ['aiida.inp']
        native.stdout_name, native.join_files = 'aiida.out', True
        helper.code_uuid, helper.cmdline_params = self.inputs.helper_code.uuid, ['core_orbitals.py']
        helper.stdout_name, helper.join_files = 'core.log', True
        info.codes_info = [native, helper]
        info.retrieve_list = ['aiida.out', 'core.json', 'core.log', 'localized.out', 'localize.log']
        return info


class CoreOrbitalsParser(Parser):
    def parse(self, **kwargs):
        try:
            data = json.loads(self.retrieved.base.repository.get_object_content('core.json'))
            if data.get('schema_version') != 1 or not data.get('assignments'):
                raise ValueError('No verified core-orbital assignments')
            from .scripts.core_orbitals import assignments
            localized = data['method'] == 'core_only_pipek_mezey'
            text = self.retrieved.base.repository.get_object_content('localized.out' if localized else 'aiida.out')
            rows, verified = assignments(text, self.node.inputs.structure.get_ase().numbers.tolist(), localized=localized)
            if not verified or rows != data['assignments']:
                raise ValueError('Stored core assignments differ from the native population analysis')
            self.out('core_reference', orm.Dict(dict=data))
        except (OSError, ValueError, KeyError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CORE


def source_energy(retrieved):
    from .parser import reference_summary
    return reference_summary(retrieved.base.repository.get_object_content('aiida.out'))['energy_hartree']


def core_runs(retrieved_uuid, code_uuid):
    query = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': str(retrieved_uuid)}, tag='source').append(
        orm.WorkChainNode, with_incoming='source', edge_filters={'label': 'source_retrieved'}, tag='run',
        filters={'process_type': CORE_PROCESS, 'attributes.exit_status': 0,
                 'attributes.process_state': 'finished'}, project=['uuid'])
    for uuid in query.order_by({'run': {'ctime': 'desc'}}).all(flat=True):
        node = orm.load_node(uuid)
        if str(node.inputs.code.uuid) == str(code_uuid):
            yield str(uuid)


class CoreOrbitalsWorkChain(engine.WorkChain):
    """Reusable preparation, including explicit recovery of a lost source GBW."""
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, kind in {'structure': orm.StructureData, 'settings': orm.Dict, 'code': orm.AbstractCode,
                          'helper_code': orm.AbstractCode, 'storage_policy': orm.Dict,
                          'source_retrieved': orm.FolderData, 'source_remote': orm.RemoteData}.items():
            spec.input(key, valid_type=kind)
        spec.input('force_recompute', valid_type=orm.Bool, default=lambda: orm.Bool(False))
        for key, kind in {'core_reference': orm.Dict, 'remote_folder': orm.RemoteData, 'retrieved': orm.FolderData}.items():
            spec.output(key, valid_type=kind)
        spec.outline(cls.setup, engine.if_(cls.needs_scf)(cls.recover_scf, cls.inspect_scf),
                     engine.if_(cls.needs_preparation)(cls.prepare, cls.inspect, cls.preserve, cls.inspect_storage), cls.results)
        spec.exit_code(400, 'ERROR_SOURCE', message='Invalid or unavailable core reference; see report.')
        spec.exit_code(401, 'ERROR_CORE', message='Core preparation failed; inspect the native output and assignment report.')
        spec.exit_code(402, 'ERROR_STORAGE', message='Prepared core wavefunction preservation failed.')

    def setup(self):
        self.ctx.reuse_uuid, self.ctx.recover = None, False
        try:
            validate_reference(self.inputs.structure, self.inputs.settings.get_dict())
            validate_source(self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code,
                            self.inputs.source_retrieved, self.inputs.source_remote)
            storage_policy(self.inputs.storage_policy.get_dict())
            if self.inputs.helper_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('The ORCA tools code must use the ORCA computer')
            if not self.inputs.force_recompute.value:
                for uuid in core_runs(self.inputs.source_retrieved.uuid, self.inputs.code.uuid):
                    node = orm.load_node(uuid)
                    try:
                        resolve_electronic(node.outputs.remote_folder, names=['aiida.gbw'])
                    except (FileNotFoundError, ValueError, KeyError):
                        continue
                    self.ctx.reuse_uuid = uuid
                    self.report('Reusing verified core orbitals from ' + uuid)
                    return
            try:
                self.ctx.location = resolve_electronic(self.inputs.source_remote, names=['aiida.gbw'])
            except (FileNotFoundError, ValueError):
                self.ctx.recover = True
                self.report('The source wavefunction is gone. Recomputing only the fixed-geometry SCF with caching disabled.')
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_scf(self):
        return self.ctx.recover

    def needs_preparation(self):
        return self.ctx.reuse_uuid is None

    def recover_scf(self):
        from .reference import get_reference_builder
        b = get_reference_builder(self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code, force_recompute=True)
        b.bypass_cache = orm.Bool(True)
        b.storage_code, b.storage_policy = self.inputs.helper_code, self.inputs.storage_policy
        return engine.ToContext(scf=self.submit(b))

    def inspect_scf(self):
        try:
            if not self.ctx.scf.is_finished_ok:
                raise ValueError('The replacement SCF did not finish successfully')
            if abs(source_energy(self.ctx.scf.outputs.retrieved)-source_energy(self.inputs.source_retrieved)) > 1e-6:
                raise ValueError('The regenerated SCF energy differs from the reviewed reference; inspect the electronic solution before continuing')
            self.ctx.location = resolve_electronic(self.ctx.scf.outputs.remote_folder, names=['aiida.gbw'])
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def prepare(self):
        b = CoreOrbitalsCalculation.get_builder()
        for key in ('structure', 'settings', 'code', 'helper_code'):
            b[key] = self.inputs[key]
        b.source_retrieved = self.ctx.scf.outputs.retrieved if self.ctx.recover else self.inputs.source_retrieved
        attach_orbital(b, self.ctx.location, 'aiida.gbw')
        b.metadata.options = options(self.inputs.settings.get_dict())
        b.metadata.disable_cache = True
        return engine.ToContext(preparation=self.submit(b))

    def inspect(self):
        if not self.ctx.preparation.is_finished_ok:
            return self.exit_codes.ERROR_CORE

    def preserve(self):
        b = storage_builder(self.ctx.preparation.outputs.remote_folder, self.inputs.helper_code,
                            self.inputs.storage_policy.get_dict(), names=['aiida.gbw'])
        return engine.ToContext(storage=self.submit(b))

    def inspect_storage(self):
        if not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE

    def results(self):
        node = orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.preparation
        for key in ('core_reference', 'remote_folder', 'retrieved'):
            self.out(key, node.outputs[key])


def site_signature(structure, settings, code_uuid, retrieved_uuid, atom_index):
    from aiida.orm.implementation import clean_value
    atoms = structure.get_ase()
    payload = {'model': 'rks_1s_delta_scf_v1', 'numbers': atoms.numbers.tolist(),
               'positions': atoms.positions.tolist(), 'parameters': clean_value(single_point_parameters(settings)),
               'code_uuid': str(code_uuid), 'source_retrieved_uuid': str(retrieved_uuid), 'atom_index': atom_index}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def parse_site(text, core_reference, atom_index, electron_count, ground_energy):
    from .scripts.core_orbitals import levels, populations
    from .parser import reference_summary
    summary = reference_summary(text)
    channels = levels(text)
    if len(channels) != 2:
        raise ValueError('The core-ionized calculation must have two spin channels')
    counts = [sum(row['occupation'] for row in c) for c in channels]
    if abs(sum(counts)-(electron_count-1)) > 1e-6 or abs(abs(counts[0]-counts[1])-1) > 1e-6:
        raise ValueError('The final electron count or spin projection is not that of a singly ionized doublet')
    holes = [(spin, row) for spin, channel in enumerate(channels) for row in channel
             if row['energy_hartree'] < -5 and row['occupation'] < .01]
    if len(holes) != 1:
        raise ValueError('Exactly one empty deep-core orbital is required; the core hole may have collapsed')
    spin, hole = holes[0]
    tables = populations(text, len(core_reference['assignments'][0]['atomic_populations']), method='MULLIKEN')
    if len(tables) != 2:
        raise ValueError('Both spin-resolved native MO population tables are required')
    values = tables[spin][hole['index']]
    if max(range(len(values)), key=values.__getitem__) != atom_index or values[atom_index] < .95:
        raise ValueError('The final core hole is not localized on the requested atom')
    spin_squared = summary.get('spin_squared')
    if spin_squared is None or not math.isfinite(spin_squared):
        raise ValueError('The final spin diagnostic is missing')
    binding = (summary['energy_hartree'] - ground_energy)*27.211386245988
    if not math.isfinite(binding) or binding <= 0:
        raise ValueError('Invalid core binding energy')
    return {'schema_version': 1, 'atom_index': atom_index, 'shell': '1s',
            'ground_energy_hartree': ground_energy, 'ionized_energy_hartree': summary['energy_hartree'],
            'binding_energy_ev': binding, 'initial_multiplicity': 1, 'final_multiplicity': 2,
            'electron_counts': counts, 'spin_squared': spin_squared, 'hole_spin_channel': spin,
            'hole_orbital_index': hole['index'], 'hole_population': values[atom_index],
            'hole_population_method': 'ORCA Mulliken atomic population per MO',
            'localization': core_reference['method'], 'energy_reference': 'isolated molecule, vertical removal to vacuum',
            'warnings': ['The UKS spin diagnostic differs appreciably from the doublet value 0.75.'] if abs(spin_squared-.75) > .1 else []}


class XpsSiteCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, kind in {'structure': orm.StructureData, 'settings': orm.Dict,
                          'source_retrieved': orm.FolderData, 'core_reference': orm.Dict,
                          'atom_index': orm.Int}.items():
            spec.input(key, valid_type=kind)
        source_spec(spec)
        spec.input('metadata.options.parser_name', default='empa_orca.xps_site')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('site_result', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_SITE', message='Core-ionization calculation or validation failed; inspect aiida.out.')

    def prepare_for_submission(self, folder):
        s = validate_reference(self.inputs.structure, self.inputs.settings.get_dict())
        atom = self.inputs.atom_index.value
        if not 0 <= atom < len(self.inputs.structure.sites) or self.inputs.structure.get_ase().numbers[atom] not in (6, 8):
            raise ValueError('Select a C or O atom for 1s ionization')
        rows = [r for r in self.inputs.core_reference.get_dict()['assignments'] if r['atom_index'] == atom]
        if len(rows) != 1 or rows[0]['population'] < .95:
            raise ValueError('The requested atom has no unique verified core orbital')
        text = '%moinp "reference.gbw"\n' + render_input(site_parameters(s, rows[0]['index']), int(.75*s['memory_mb']/s['nprocs']), 'aiida.coords.xyz')
        with folder.open('aiida.inp', 'w') as handle:
            handle.write(text)
        OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
        info, code = common.CalcInfo(), common.CodeInfo()
        copy_orbital(info, self.inputs)
        code.code_uuid, code.cmdline_params = self.inputs.code.uuid, ['aiida.inp']
        code.stdout_name, code.join_files = 'aiida.out', True
        info.codes_info, info.retrieve_list = [code], ['aiida.out']
        return info


class XpsSiteParser(Parser):
    def parse(self, **kwargs):
        try:
            inputs = self.node.inputs
            text = self.retrieved.base.repository.get_object_content('aiida.out')
            result = parse_site(text, inputs.core_reference.get_dict(), inputs.atom_index.value,
                                int(inputs.structure.get_ase().numbers.sum())-inputs.settings.get_dict()['charge'],
                                source_energy(inputs.source_retrieved))
            result['signature'] = site_signature(inputs.structure, inputs.settings.get_dict(), inputs.code.uuid,
                                                  inputs.source_retrieved.uuid, inputs.atom_index.value)
            self.out('site_result', orm.Dict(dict=result))
        except (OSError, ValueError, KeyError, IndexError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_SITE


def validated_site(node):
    from aiida.orm.implementation import clean_value
    if node.process_type != SITE_PROCESS or not node.is_finished_ok or 'site_result' not in node.outputs:
        raise ValueError('No successful site-ionization result')
    saved = node.outputs.site_result.get_dict()
    parsed = parse_site(node.outputs.retrieved.base.repository.get_object_content('aiida.out'),
                        node.inputs.core_reference.get_dict(), node.inputs.atom_index.value,
                        int(node.inputs.structure.get_ase().numbers.sum())-node.inputs.settings.get_dict()['charge'],
                        source_energy(node.inputs.source_retrieved))
    expected = site_signature(node.inputs.structure, node.inputs.settings.get_dict(), node.inputs.code.uuid,
                              node.inputs.source_retrieved.uuid, node.inputs.atom_index.value)
    if saved != clean_value(parsed | {'signature': expected}):
        raise ValueError('The saved site result differs from the native ORCA output')
    return saved


def matching_sites(structure, settings, code_uuid, retrieved_uuid):
    result = {}
    query = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': str(retrieved_uuid)}, tag='source').append(
        orm.CalcJobNode, with_incoming='source', edge_filters={'label': 'source_retrieved'}, tag='site',
        filters={'process_type': SITE_PROCESS, 'attributes.exit_status': 0,
                 'attributes.process_state': 'finished'}, project=['uuid'])
    for uuid in query.order_by({'site': {'ctime': 'desc'}}).all(flat=True):
        node = orm.load_node(uuid)
        atom = node.inputs.atom_index.value
        if atom in result:
            continue
        try:
            data = validated_site(node)
            if data['signature'] == site_signature(structure, settings, code_uuid, retrieved_uuid, atom):
                result[atom] = str(uuid)
        except (ValueError, KeyError, OSError):
            continue
    return result


class XpsWorkChain(engine.WorkChain):
    """Collect independently reusable atom calculations, submitting them serially."""
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, kind in {'structure': orm.StructureData, 'settings': orm.Dict, 'code': orm.AbstractCode,
                          'helper_code': orm.AbstractCode, 'storage_policy': orm.Dict, 'atom_indices': orm.List,
                          'source_retrieved': orm.FolderData, 'source_remote': orm.RemoteData}.items():
            spec.input(key, valid_type=kind)
        spec.input('force_recompute', valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.output_namespace('sites', dynamic=True, valid_type=orm.Dict)
        spec.output('core_reference', valid_type=orm.Dict, required=False)
        spec.outline(cls.setup, engine.if_(cls.needs_core)(cls.prepare_core, cls.inspect_core),
                     engine.while_(cls.has_sites)(cls.run_site, cls.inspect_site, cls.preserve_site, cls.inspect_site_storage))
        spec.exit_code(400, 'ERROR_INPUT', message='Invalid XPS request; see report.')
        spec.exit_code(401, 'ERROR_CORE', message='The core reference is unavailable or ambiguous.')
        spec.exit_code(402, 'ERROR_SITE', message='A site calculation failed; completed sites remain reusable.')
        spec.exit_code(403, 'ERROR_STORAGE', message='Site energies are available, but core-hole wavefunction preservation failed.')

    def setup(self):
        try:
            validate_reference(self.inputs.structure, self.inputs.settings.get_dict())
            validate_source(self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code,
                            self.inputs.source_retrieved, self.inputs.source_remote)
            storage_policy(self.inputs.storage_policy.get_dict())
            if self.inputs.helper_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('The ORCA tools code must use the ORCA computer')
            atoms = self.inputs.atom_indices.get_list()
            numbers = self.inputs.structure.get_ase().numbers
            if not atoms or len(set(atoms)) != len(atoms) or any(type(i) is not int or not 0 <= i < len(numbers) or numbers[i] not in (6, 8) for i in atoms):
                raise ValueError('Select distinct C/O atom indices for 1s ionization')
            previous = {} if self.inputs.force_recompute.value else matching_sites(
                self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code.uuid, self.inputs.source_retrieved.uuid)
            self.ctx.pending, self.ctx.index = [], 0
            for atom in atoms:
                if atom in previous:
                    node = orm.load_node(previous[atom])
                    self.out(f'sites.atom_{atom:04d}', node.outputs.site_result)
                    self.report(f'Reusing atom {atom+1} from {node.uuid}; no scratch files are required.')
                else:
                    self.ctx.pending.append(atom)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INPUT

    def needs_core(self):
        return bool(self.ctx.pending)

    def prepare_core(self):
        b = CoreOrbitalsWorkChain.get_builder()
        for key in ('structure', 'settings', 'code', 'helper_code', 'storage_policy', 'source_retrieved', 'source_remote'):
            b[key] = self.inputs[key]
        return engine.ToContext(core=self.submit(b))

    def inspect_core(self):
        if not self.ctx.core.is_finished_ok:
            return self.exit_codes.ERROR_CORE
        self.out('core_reference', self.ctx.core.outputs.core_reference)

    def has_sites(self):
        return self.ctx.index < len(self.ctx.pending)

    def run_site(self):
        try:
            b = XpsSiteCalculation.get_builder()
            for key in ('structure', 'settings', 'code', 'source_retrieved'):
                b[key] = self.inputs[key]
            b.core_reference = self.ctx.core.outputs.core_reference
            b.atom_index = orm.Int(self.ctx.pending[self.ctx.index])
            attach_orbital(b, resolve_electronic(self.ctx.core.outputs.remote_folder, names=['aiida.gbw']), 'aiida.gbw')
            b.metadata.options = options(self.inputs.settings.get_dict())
            b.metadata.disable_cache = True
            b.metadata.label = f'Atom {b.atom_index.value+1} · 1s core ionization · doublet'
            return engine.ToContext(site=self.submit(b))
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_CORE

    def inspect_site(self):
        node = self.ctx.site
        if not node.is_finished_ok:
            self.report(f'Atom {self.ctx.pending[self.ctx.index]+1} failed: inspect {node.uuid}')
            return self.exit_codes.ERROR_SITE
        self.out(f'sites.atom_{self.ctx.pending[self.ctx.index]:04d}', node.outputs.site_result)
        self.ctx.index += 1

    def preserve_site(self):
        try:
            b = storage_builder(self.ctx.site.outputs.remote_folder, self.inputs.helper_code,
                                self.inputs.storage_policy.get_dict())
            return engine.ToContext(site_storage=self.submit(b))
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_STORAGE

    def inspect_site_storage(self):
        if not self.ctx.site_storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE
