"""Vertical DFT excitations and native NTOs, independent of CAS state vectors."""

import math
import re

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from .artifacts import resolve_electronic, storage_builder
from .common_orbitals import attach_orbital, copy_orbital, options, source_spec, validate_source
from .input import render_input
from .protocols import reference as reference_type
from .reference import reference_settings, single_point_parameters
from .choices import PURE_DFT, HYBRID_DFT

PROCESS_TYPE = 'aiida.calculations:empa_orca.optical'
NTO_PROCESS = 'aiida.workflows:empa_orca.nto_cubes'
NUMBER = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?'
HARTREE_TO_EV = 27.211386245988
HC_EV_NM = 1239.8419843320026


def settings(values, electronic):
    electronic = reference_settings(electronic)
    if electronic['method'].upper() == 'HF':
        raise ValueError('Optical TDDFT requires a DFT reference; HF would produce CIS/RPA instead')
    if electronic['method'].upper() not in {m.upper() for m in (*PURE_DFT, *HYBRID_DFT)}:
        raise ValueError('Select a supported pure or hybrid DFT reference; double hybrids and composite methods need a separate route')
    unrestricted = reference_type(electronic) == 'UKS'
    defaults = {'method': 'TDA', 'nroots': 5, 'triplets': False, 'nto': True,
                'nto_states': [], 'nto_family': 'singlet', 'maxiter': 100,
                **{k: electronic[k] for k in ('nprocs', 'memory_mb', 'wallclock_seconds')}}
    if not isinstance(values, dict) or set(values) - defaults.keys():
        raise ValueError('Unknown optical-excitation setting')
    s = defaults | values
    if s['method'] not in ('TDA', 'TDDFT'):
        raise ValueError('Choose TDA or full TDDFT')
    if type(s['nroots']) is not int or not 1 <= s['nroots'] <= 100:
        raise ValueError('Request 1–100 excited roots per calculated family')
    for key in ('nprocs', 'memory_mb', 'wallclock_seconds', 'maxiter'):
        if type(s[key]) is not int or s[key] < 1:
            raise ValueError('Resources and maximum iterations must be positive integers')
    if s['memory_mb'] < 256 * s['nprocs']:
        raise ValueError('Provide at least 256 MiB per process')
    if any(type(s[k]) is not bool for k in ('triplets', 'nto')):
        raise ValueError('Choose explicit triplet and NTO options')
    if unrestricted and s['triplets']:
        raise ValueError('Spin-adapted singlet/triplet families require an RKS singlet; UKS uses spin-conserving response')
    if s['nto_family'] != 'singlet':
        raise ValueError('Triplet NTO generation is not qualified in this draft; singlet NTOs and triplet energies are separate')
    roots = s['nto_states']
    if (not isinstance(roots, list) or any(type(i) is not int or not 1 <= i <= s['nroots'] for i in roots)
            or len(set(roots)) != len(roots)):
        raise ValueError('NTO state numbers start at 1 and must belong to the requested roots')
    s['nto_states'] = sorted(roots)
    return s


def optical_input(electronic, values):
    electronic = reference_settings(electronic)
    s = settings(values, electronic)
    params = single_point_parameters(electronic)
    if any(k.lower() in ('cis', 'tddft') for k in params['input_blocks']):
        raise ValueError('The optical workspace owns the TDDFT block; remove conflicting expert settings')
    params['input_keywords'].append('MOREAD')
    params['input_blocks']['pal']['nprocs'] = s['nprocs']
    td = {'TDA': s['method'] == 'TDA', 'NRoots': s['nroots'], 'MaxIter': s['maxiter'],
          'Triplets': s['triplets'], 'DoNTO': s['nto'], 'TPrint': .0001, 'NTOThresh': .0001}
    if s['nto']:
        if s['nto_states']:
            td['NTOStates'] = ','.join(map(str, s['nto_states']))
        if s['nto_family'] == 'triplet':
            td['IRootMult'] = 'triplet'
    params['input_blocks']['tddft'] = td
    return '%moinp "reference.gbw"\n' + render_input(params, int(.75*s['memory_mb']/s['nprocs']), 'aiida.coords.xyz')


def number(value):
    result = float(value.replace('D', 'E').replace('d', 'e'))
    if not math.isfinite(result):
        raise ValueError('Nonfinite optical result')
    return result


def parse_result(text, electronic, values, *, expected_electrons=None, expected_energy=None):
    """Read labelled native roots, length-gauge strengths and unmodified NTO weights."""
    s = settings(values, electronic)
    unrestricted = reference_type(reference_settings(electronic)) == 'UKS'
    if (text.count('ORCA TERMINATED NORMALLY') != 1 or
            'ORCA-CIS/TD-DFT FINISHED WITHOUT ERROR' not in text or
            re.search(r'NOT CONVERGED|DID NOT CONVERGE|ORCA finished by error|Segmentation fault|'
                      r'poorly\s+normalized|imaginary\s+excitation|negative\s+excitation', text, re.I)):
        raise ValueError('Native failure, unconverged response or unstable excitation; inspect the output')
    version = re.search(r'Program Version\s+(\S+)', text)
    if not version or not version[1].startswith('6.1'):
        raise ValueError('This optical parser requires the validated ORCA 6.1 output contract')
    if not re.search(r'SCF CONVERGED AFTER\s+\d+\s+CYCLES', text):
        raise ValueError('The DFT reference did not converge')
    operative = re.findall(r'Tamm-Dancoff approximation\s*\.\.\.\s*(\w+)', text)
    if operative != [('operative' if s['method'] == 'TDA' else 'deactivated')]:
        raise ValueError('Native TDA/full-TDDFT identity differs from the reviewed method')
    electrons = re.findall(r'Number of Electrons\s+NEL\s+\.+\s*(\d+)', text)
    spins = re.findall(r'Multiplicity\s+Mult\s+\.+\s*(\d+)', text)
    charges = re.findall(r'Total Charge\s+Charge\s+\.+\s*(-?\d+)', text)
    if (not electrons or len(set(electrons)) != 1 or not spins or set(map(int, spins)) != {electronic['multiplicity']}
            or not charges or set(map(int, charges)) != {electronic['charge']}):
        raise ValueError('Native electron, charge or reference spin identity is inconsistent')
    if expected_electrons is not None and int(electrons[0]) != expected_electrons:
        raise ValueError('Electron count differs from the selected reference; ECP counting is not validated here')
    # FINAL SINGLE POINT ENERGY can be the IRoot excited-state total, not E(SCF).
    ground = re.findall(r'^\s*Total Energy\s*:\s*(' + NUMBER + r')\s+Eh', text, re.M)
    if len(ground) != 1:
        raise ValueError('Missing or ambiguous ground-state SCF energy')
    ground = number(ground[0])
    if expected_energy is not None and abs(ground - expected_energy) > 1e-7:
        raise ValueError('The continued DFT state changed energy; review the reference before optical analysis')
    solves = re.split(r'Number of roots to be determined\s*\.{2,}\s*', text)[1:]
    if len(solves) != (2 if s['triplets'] else 1):
        raise ValueError('Missing or unexpected response-solver families')
    residuals = []
    for solve in solves:
        if not solve.startswith(str(s['nroots']) + '\n'):
            raise ValueError('Native root request differs from the reviewed number')
        tolerance = re.search(r'Convergence tolerance for the residual\s*\.{2,}\s*(' + NUMBER + ')', solve)
        end = solve.find('CONVERGENCE OF RESIDUAL NORM REACHED')
        values_r = re.findall(r'Maximum residual norm\s*:\s*(' + NUMBER + ')', solve[:end]) if end >= 0 else []
        if not tolerance or not values_r or not 0 <= number(values_r[-1]) <= number(tolerance[1]):
            raise ValueError('A response family did not satisfy its native residual tolerance')
        residuals.append({'residual': number(values_r[-1]), 'tolerance': number(tolerance[1])})
    states, sector, current = {}, None, None
    for line in text.splitlines():
        heading = re.match(r'^TD-DFT(?:/TDA)? EXCITED STATES(?:\s*\((\w+)\))?', line)
        if heading:
            sector = 'uks' if unrestricted else ('triplet' if heading[1] == 'TRIPLETS' else 'singlet')
            current = None
        if line.startswith('NATURAL TRANSITION ORBITALS'):
            sector, current = None, None
        row = re.match(r'^STATE\s+(\d+):\s+E=\s*(' + NUMBER + r') au\s+(' + NUMBER + r') eV', line)
        if row and sector:
            native_root = int(row[1])
            family_root = native_root - s['nroots'] if sector == 'triplet' else native_root
            key = sector + ':' + str(family_root)
            if key in states:
                raise ValueError('Duplicated excited-state identity')
            spin = re.search(r'<S\*\*2>\s*=\s*(' + NUMBER + ')', line)
            current = {'id': key, 'family': sector, 'root': family_root, 'native_state_index': native_root,
                       'excitation_hartree': number(row[2]), 'excitation_ev_rounded': number(row[3]),
                       'spin_squared': number(spin[1]) if spin else None, 'contributions': [], 'nto': None}
            states[key] = current
        contribution = re.match(r'^\s*(\d+)([ab])\s*->\s*(\d+)([ab])\s*:\s*(' + NUMBER + r')(?:\s+\(c=\s*(' + NUMBER + r')\))?\s*$', line)
        if contribution and current:
            current['contributions'].append({'hole': int(contribution[1]), 'hole_spin': contribution[2],
                'particle': int(contribution[3]), 'particle_spin': contribution[4],
                'native_weight': number(contribution[5]), 'coefficient': number(contribution[6]) if contribution[6] else None})
    families = ['uks'] if unrestricted else ['singlet', 'triplet'] if s['triplets'] else ['singlet']
    expected = {family + ':' + str(root) for family in families for root in range(1, s['nroots'] + 1)}
    if set(states) != expected:
        raise ValueError('Incomplete or unexpected labelled excited-state family')
    title = 'ABSORPTION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS'
    if text.count(title) != 1:
        raise ValueError('Missing or ambiguous length-gauge absorption table')
    table = text.split(title)[1].split('ABSORPTION SPECTRUM VIA TRANSITION VELOCITY')[0]
    found = set()
    pattern = (r'^\s*(\d+)-(\d+)\S*\s+->\s+(\d+)-(\d+)\S*\s+' +
               r'\s+'.join(['(' + NUMBER + ')'] * 8) + r'\s*$')
    for row in re.findall(pattern, table, re.M):
        initial, initial_mult, root, mult = map(int, row[:4])
        if initial != 0:
            continue
        family = 'uks' if unrestricted else 'singlet' if mult == 1 else 'triplet' if mult == 3 else 'unknown'
        key = family + ':' + str(root)
        if key not in states or key in found:
            raise ValueError('Unexpected or duplicated absorption-state identity')
        energy, wavenumber, wavelength, strength, dipole2, dx, dy, dz = map(number, row[4:])
        state = states[key]
        if energy <= 0 or strength < 0 or wavelength <= 0 or dipole2 < 0:
            raise ValueError('Nonpositive excitation or invalid native oscillator strength')
        if abs(energy - state['excitation_hartree']*HARTREE_TO_EV) > 2e-5:
            raise ValueError('Absorption and eigenstate energies disagree')
        if abs(HC_EV_NM / energy - wavelength) > .06:
            raise ValueError('Native wavelength and excitation energy disagree')
        state.update(energy_ev=energy, wavelength_nm=wavelength, oscillator_strength=strength,
                     transition_dipole_au=[dx, dy, dz], native_multiplicity_label=mult,
                     multiplicity=None if unrestricted else mult)
        found.add(key)
    if found != expected:
        raise ValueError('The optical table omits requested states, including dark states')
    ntos = re.split(r'NATURAL TRANSITION ORBITALS FOR STATE\s+(\d+)', text)
    nto_found = set()
    for i in range(1, len(ntos), 2):
        root, block = int(ntos[i]), ntos[i+1]
        filename = re.search(r'Natural Transition Orbitals were saved in\s+(aiida\.[A-Za-z0-9_.-]+\.nto)', block)
        if not filename:
            raise ValueError('Native NTO file identity is missing')
        family = 'uks' if unrestricted else s['nto_family']
        key = family + ':' + str(root)
        if key not in states or key in nto_found:
            raise ValueError('NTO state identity is inconsistent')
        if filename[1] != f'aiida.s{root}.nto':
            raise ValueError('Native NTO file does not match its state index')
        energy = re.search(r'^\s*E=\s*(' + NUMBER + r') au', block, re.M)
        if not energy or abs(number(energy[1])-states[key]['excitation_hartree']) > 1e-6:
            raise ValueError('NTO energy does not match its selected excited state')
        pairs = [{'hole': int(h), 'hole_spin': hs, 'particle': int(p), 'particle_spin': ps, 'weight': number(w)}
                 for h, hs, p, ps, w in re.findall(r'^\s*(\d+)([ab])\s*->\s*(\d+)([ab])\s*:\s*n=\s*(' + NUMBER + ')', block, re.M)]
        if not pairs or any(pair['weight'] < 0 or pair['hole_spin'] != pair['particle_spin'] for pair in pairs):
            raise ValueError('Invalid or missing native NTO pairs')
        states[key]['nto'] = {'filename': filename[1], 'pairs': pairs,
                             'printed_weight_sum': sum(pair['weight'] for pair in pairs),
                             'weight_convention': 'native pseudodensity eigenvalues; not renormalized'}
        nto_found.add(key)
    expected_nto = ({('uks' if unrestricted else s['nto_family']) + ':' + str(i)
                     for i in (s['nto_states'] or list(range(1, s['nroots']+1)))} if s['nto'] else set())
    if nto_found != expected_nto:
        raise ValueError('Requested NTO state files are incomplete')
    return {'schema_version': 1, 'method': s['method'], 'states': sorted(states.values(), key=lambda r: r['energy_ev']),
            'ground_energy_hartree': ground, 'reference_charge': electronic['charge'],
            'reference_multiplicity': electronic['multiplicity'], 'reference_type': 'UKS' if unrestricted else 'RKS',
            'electronic_settings': electronic, 'settings': s, 'native_version': version[1],
            'energy_reference': 'Vertical excitation from the continued DFT state at this fixed geometry',
            'oscillator_convention': 'native electric-dipole length gauge; no SOC',
            'checks': {'native_normal_termination': True, 'response_solves': residuals,
                       'reference_energy_error_hartree': abs(ground-expected_energy) if expected_energy is not None else None},
            'dyson_compatible': False, 'provides_casci_vectors': False}


class OpticalCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure': orm.StructureData, 'electronic_settings': orm.Dict,
                         'settings': orm.Dict, 'source_retrieved': orm.FolderData,
                         'source_remote': orm.RemoteData}.items():
            spec.input(key, valid_type=typ)
        source_spec(spec)
        spec.input('metadata.options.parser_name', default='empa_orca.optical')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('excitations', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_OPTICAL', message='Optical validation failed; inspect the native output and process report.')

    def prepare_for_submission(self, folder):
        electronic = self.inputs.electronic_settings.get_dict()
        validate_source(self.inputs.structure, electronic, self.inputs.code,
                        self.inputs.source_retrieved, self.inputs.source_remote)
        with folder.open('aiida.inp', 'w') as handle:
            handle.write(optical_input(electronic, self.inputs.settings.get_dict()))
        OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
        info = common.CalcInfo()
        copy_orbital(info, self.inputs)
        code = common.CodeInfo()
        code.code_uuid, code.cmdline_params = self.inputs.code.uuid, ['aiida.inp']
        code.stdout_name, code.join_files = 'aiida.out', True
        info.codes_info, info.retrieve_list = [code], ['aiida.out']
        return info


class OpticalParser(Parser):
    def parse(self, **kwargs):
        try:
            electronic = self.node.inputs.electronic_settings.get_dict()
            source = self.node.inputs.source_retrieved.base.repository.get_object_content('aiida.out')
            from .parser import reference_summary
            expected = reference_summary(source)['energy_hartree']
            result = parse_result(self.retrieved.base.repository.get_object_content('aiida.out'), electronic,
                self.node.inputs.settings.get_dict(), expected_electrons=int(self.node.inputs.structure.get_ase().numbers.sum())-electronic['charge'],
                expected_energy=expected)
            result.update(structure_uuid=str(self.node.inputs.structure.uuid), source_retrieved_uuid=str(self.node.inputs.source_retrieved.uuid))
            self.out('excitations', orm.Dict(dict=result))
        except (KeyError, ValueError, OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_OPTICAL


def nto_selection(data, values):
    """Derive both members of each selected native pair; never invent an MO window."""
    if set(values) != {'state_id', 'pairs'}:
        raise ValueError('Choose one stored excited state and NTO pair numbers')
    state = next((r for r in data['states'] if r['id'] == values['state_id']), None)
    if not state or not state['nto']:
        raise ValueError('No qualified NTO files are stored for this state; select a state with NTO analysis')
    chosen = values['pairs']
    if (not isinstance(chosen, list) or not chosen or len(set(chosen)) != len(chosen) or
            any(type(i) is not int or not 1 <= i <= len(state['nto']['pairs']) for i in chosen)):
        raise ValueError('Select available NTO pairs, counting from 1')
    orbitals = set()
    for i in chosen:
        pair = state['nto']['pairs'][i-1]
        orbitals.update([(0 if pair['hole_spin'] == 'a' else 1, pair['hole']),
                         (0 if pair['particle_spin'] == 'a' else 1, pair['particle'])])
    return state, [list(p) for p in sorted(orbitals)]


class NtoCubesWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'excitations': orm.Dict, 'source_remote': orm.RemoteData, 'selection': orm.Dict,
                         'parameters': orm.Dict, 'storage_policy': orm.Dict, 'code': orm.AbstractCode,
                         'plot_code': orm.AbstractCode, 'cubehandler_code': orm.AbstractCode}.items():
            spec.input(key, valid_type=typ)
        for key, typ in {'manifest': orm.Dict, 'retrieved': orm.FolderData, 'remote_folder': orm.RemoteData}.items():
            spec.output(key, valid_type=typ)
        spec.output('remote_stash', valid_type=orm.RemoteStashFolderData, required=False)
        spec.outline(cls.setup, engine.if_(cls.needs_storage)(cls.store, cls.inspect_store),
                     cls.cubes, cls.inspect_cubes, cls.results)
        spec.exit_code(400, 'ERROR_SOURCE', message='Invalid or unavailable NTO source; inspect the report.')
        spec.exit_code(401, 'ERROR_STORAGE', message='NTO electronic-file preservation failed.')
        spec.exit_code(402, 'ERROR_CUBES', message='NTO cube generation or reduction failed.')

    def setup(self):
        from .orbitals import cube_parameters
        try:
            producer = self.inputs.excitations.creator
            if (producer is None or not producer.is_finished_ok or producer.process_type != PROCESS_TYPE or
                    self.inputs.source_remote.creator.uuid != producer.uuid):
                raise ValueError('NTO files and excitation data must have the same successful optical producer')
            data = self.inputs.excitations.get_dict()
            state, orbitals = nto_selection(data, self.inputs.selection.get_dict())
            parameters = cube_parameters(self.inputs.parameters.get_dict())
            if parameters['orbitals'] != orbitals or parameters['spin_density']:
                raise ValueError('NTO previews must contain the recorded hole/particle pairs')
            computer = self.inputs.source_remote.computer.uuid
            if any(self.inputs[key].computer.uuid != computer for key in ('code', 'plot_code', 'cubehandler_code')):
                raise ValueError('NTO tools must run on the optical calculation computer')
            self.ctx.filename = state['nto']['filename']
            self.ctx.location = resolve_electronic(self.inputs.source_remote, names=[self.ctx.filename])
            self.ctx.identity = {'kind': 'NTO', 'state_id': state['id'], 'pairs': self.inputs.selection.get_dict()['pairs'],
                                 'excitations_uuid': str(self.inputs.excitations.uuid),
                                 'structure_uuid': data['structure_uuid'], 'optical_method': data['method']}
        except (ValueError, KeyError, OSError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_storage(self):
        return self.ctx.location['kind'] == 'remote'

    def store(self):
        b = storage_builder(self.inputs.source_remote, self.inputs.code,
                            self.inputs.storage_policy.get_dict(), names=[self.ctx.filename])
        b.metadata.call_link_label = 'preserve_nto'
        return engine.ToContext(storage=self.submit(b))

    def inspect_store(self):
        if not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE
        self.ctx.location = resolve_electronic(self.inputs.source_remote, names=[self.ctx.filename])

    def cubes(self):
        from .orbitals import OrbitalCubesCalculation, attach_source
        from .artifacts import stash_options
        from .rendering import calcjob_options
        b = OrbitalCubesCalculation.get_builder()
        b.code, b.plot_code, b.cubehandler_code = self.inputs.code, self.inputs.plot_code, self.inputs.cubehandler_code
        b.parameters = self.inputs.parameters
        b.orbital_filename, b.orbital_identity = orm.Str(self.ctx.filename), orm.Dict(dict=self.ctx.identity)
        attach_source(b, self.ctx.location)
        b.metadata.options = calcjob_options(self.inputs.source_remote)
        p = self.inputs.parameters.get_dict()
        if p['retention'] == 'stash':
            b.metadata.options.stash = stash_options(p['stash_directory'], 'full_cubes')
        b.metadata.disable_cache = True
        b.metadata.call_link_label = 'nto_cubes'
        return engine.ToContext(calculation=self.submit(b))

    def inspect_cubes(self):
        if not self.ctx.calculation.is_finished_ok:
            return self.exit_codes.ERROR_CUBES

    def results(self):
        for key in ('manifest', 'retrieved', 'remote_folder', 'remote_stash'):
            if key in self.ctx.calculation.outputs:
                self.out(key, self.ctx.calculation.outputs[key])
