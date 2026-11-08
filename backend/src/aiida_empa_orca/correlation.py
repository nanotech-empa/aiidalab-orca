"""Fixed-geometry correlation energies, separate from orbital/state-vector sources."""
import math
import re

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from . import casscf
from .common_orbitals import copy_orbital, validate_source
from .input import render_input
from .reference import single_point_parameters

PROCESS_TYPE = 'aiida.calculations:empa_orca.correlation'
NEVPT_METHODS = ('SC-NEVPT2', 'FIC-NEVPT2', 'DLPNO-NEVPT2')
CAS_METHODS = (*NEVPT_METHODS, 'CASPT2')
METHODS = ('RI-MP2', *CAS_METHODS)
CASPT2_SHIFTS = {'imaginary_shift_hartree': 'CASPT2_ishift',
                'real_shift_hartree': 'CASPT2_rshift', 'ipea_shift_hartree': 'CASPT2_IPEAshift'}
NUMBER = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?'


def settings(values, electronic, optimized=None):
    defaults = {'method': 'RI-MP2', 'frozen_core': True,
                'auxiliary_basis': (optimized['auxiliary_basis'] if optimized else
                    electronic['basis'] + '/C' if electronic['basis'] in
                    ('def2-SVP', 'def2-TZVP', 'def2-TZVPP') else 'AutoAux'),
                **{key: electronic[key] for key in ('nprocs', 'memory_mb', 'wallclock_seconds')}}
    if isinstance(values, dict) and values.get('method') == 'DLPNO-NEVPT2':
        defaults['pno_preset'] = 'NormalPNO'
    if isinstance(values, dict) and values.get('method') == 'CASPT2':
        defaults.update({key: 0. for key in CASPT2_SHIFTS})
    if not isinstance(values, dict) or set(values) - set(defaults):
        raise ValueError('Unknown correlation setting')
    result = defaults | values
    if result['method'] not in METHODS or type(result['frozen_core']) is not bool:
        raise ValueError('Choose a supported correlation method and an explicit frozen-core policy')
    if result.get('pno_preset', 'NormalPNO') not in ('NormalPNO', 'TightPNO'):
        raise ValueError('Choose NormalPNO or TightPNO explicitly')
    for key in CASPT2_SHIFTS.keys() & result.keys():
        if type(result[key]) not in (int, float) or not math.isfinite(result[key]) or result[key] < 0:
            raise ValueError('CASPT2 shifts must be finite nonnegative numbers in Hartree')
    for key in ('nprocs', 'memory_mb', 'wallclock_seconds'):
        if type(result[key]) is not int or result[key] < 1:
            raise ValueError(key + ' must be a positive integer')
    if result['memory_mb'] < 256 * result['nprocs']:
        raise ValueError('Provide at least 256 MiB per process')
    from .protocols import _token
    result['auxiliary_basis'] = _token(result['auxiliary_basis'], 'Correlation auxiliary basis')
    if result['method'] in CAS_METHODS and (not optimized or
            result['auxiliary_basis'] != optimized['auxiliary_basis']):
        raise ValueError('The correction requires the same integral model as its verified CASSCF reference')
    return result


def correlation_input(electronic, values, reference=None):
    optimized = reference['casscf_settings'] if reference else None
    s = settings(values, electronic, optimized)
    if s['method'] in CAS_METHODS:
        if reference.get('preparation') != casscf.PREPARATION:
            raise ValueError('Select a verified CASSCF reference')
        objective = optimized | {key: s[key] for key in ('nprocs', 'memory_mb', 'wallclock_seconds')}
        text = casscf.casscf_input(reference, reference['optimized_active_space'], objective, readback=True)
        text = text.replace('%moinp "aiida.gbw"', '%moinp "reference.gbw"')
        pt = ' PTMethod ' + ('FIC_CASPT2' if s['method'] == 'CASPT2' else s['method'].replace('-', '_')) + '\n'
        if s['method'] == 'SC-NEVPT2':
            pt += ' PTSettings\n  CanonStep canonical\n end\n'
        elif s['method'] == 'CASPT2':
            pt += ' PTSettings\n' + ''.join(f'  {native} {float(s[key])}\n' for key, native in CASPT2_SHIFTS.items()) + ' end\n'
        text = text.replace(' maxiter 1\n', ' maxiter 1\n' + pt)
        if s['method'] == 'DLPNO-NEVPT2':
            text = re.sub(r'^(! .+)$', lambda m: m[1] + ' ' + s['pno_preset'], text, flags=re.M)
    else:
        source = single_point_parameters(electronic)
        params = {'charge': electronic['charge'], 'multiplicity': electronic['multiplicity'],
                  'input_keywords': ['RHF' if electronic['multiplicity'] == 1 else 'UHF',
                    'RI-MP2', electronic['basis'], s['auxiliary_basis'], 'TightSCF'], 'input_blocks': {
                    'pal': {'nprocs': s['nprocs']}, 'scf': {'MaxIter': electronic['max_scf_steps']}}}
        if 'basis' in source['input_blocks']:
            params['input_blocks']['basis'] = source['input_blocks']['basis']
        text = render_input(params, int(.75 * s['memory_mb'] / s['nprocs']), 'aiida.coords.xyz')
    return text + '\n%method\n FrozenCore ' + ('FC_ELECTRONS' if s['frozen_core'] else 'FC_NONE') + '\nend\n'


def native_guard(text):
    if text.count('ORCA TERMINATED NORMALLY') != 1 or re.search(
            r'ORCA finished by error|Segmentation fault|poorly\s+normalized|'
            r'project(?:ing|ion|ed)\s+(?:the\s+)?CMatrix|'
            r'(?:SCF|CI|CASSCF).*?(?:NOT CONVERGED|DID NOT CONVERGE)', text, re.I):
        raise ValueError('Native failure, unconverged reference, projection or normalization warning')


def one_number(pattern, text, label):
    values = re.findall(pattern, text, re.I | re.M)
    if len(values) != 1:
        raise ValueError('Missing or ambiguous native ' + label)
    result = float(values[0].replace('D', 'E').replace('d', 'e'))
    if not math.isfinite(result):
        raise ValueError('Nonfinite native ' + label)
    return result


def electron_count(text):
    counts = re.findall(r'Number of Electrons\s+NEL\s+\.{2,}\s+(\d+)', text)
    if not counts or len(set(counts)) != 1:
        raise ValueError('Missing or inconsistent electron count')
    return int(counts[0])


def dlpno_checks(text, preset):
    """Check every native iterative solve, including each eigenchannel."""
    if not re.search(r'^.*\|\s*\d+>\s*! .+\b' + preset + r'\b', text, re.M):
        raise ValueError('The requested PNO preset was not recorded in the native input')
    blocks = re.split(r'DLPNO-NEVPT2 SETTINGS', text)[1:]
    if not blocks:
        raise ValueError('No native DLPNO settings')
    thresholds, cycles = [], 0
    for block in blocks:
        values = {key: float(value) for key, value in re.findall(r'^(TCut\w+):\s*(' + NUMBER + ')', block, re.M)}
        if not {'TCutPNO', 'TCutDO', 'TCutMKN'} <= values.keys() or any(
                not math.isfinite(v) or v <= 0 for v in values.values()):
            raise ValueError('Missing or invalid native PNO thresholds')
        thresholds.append(values)
        etol = one_number(r'Energy convergence tolerance\s+\.{2,}\s*(' + NUMBER + ')', block, 'DLPNO energy tolerance')
        rtol = one_number(r'Residual convergence tolerance\s+\.{2,}\s*(' + NUMBER + ')', block, 'DLPNO residual tolerance')
        if etol <= 0 or rtol <= 0:
            raise ValueError('Invalid native DLPNO convergence tolerances')
        iterations = re.findall(r'LMP2-Iter=\s*(\d+):[^\n]*?DE=\s*(' + NUMBER + r')\s+RMAX=\s*(' + NUMBER + r')([^\n]*)', block)
        for i, (iteration, de, residual, suffix) in enumerate(iterations):
            final = i == len(iterations) - 1 or int(iterations[i + 1][0]) == 0
            if final:
                if ('CONVERGED' not in suffix or abs(float(de)) > etol or
                        not 0 <= float(residual) <= rtol):
                    raise ValueError('An individual DLPNO amplitude solve did not converge')
                cycles += 1
    # A state with no iterative amplitudes is possible when all classes are
    # empty/exact. Native class summaries must still account for the result.
    if text.count('DLPNO-NEVPT2 Results') != len(blocks):
        raise ValueError('Incomplete native DLPNO class summaries')
    return {'pno_preset': preset, 'native_pno_thresholds': thresholds,
            'dlpno_states_checked': len(blocks), 'amplitude_solves_checked': cycles}


def caspt2_checks(text, pt, settings):
    """Read shifts and each state's actual residual solve, not CASPT2-D."""
    labels = {'real_shift_hartree': 'Real', 'imaginary_shift_hartree': r'Im\.', 'ipea_shift_hartree': 'IPEA'}
    native_shifts = {}
    for key, label in labels.items():
        echo = one_number(r'\|\s*\d+>\s*' + CASPT2_SHIFTS[key] + r'\s+(' + NUMBER + ')', text, key + ' input')
        if echo != settings[key]:
            raise ValueError('CASPT2 shift input differs from the reviewed value')
        token = re.findall(r'CASPT2\s+' + label + r'\s+Levelshift\s+\.{2,}\s*(' + NUMBER + ')', pt)
        if len(token) != 1:
            raise ValueError('Missing or ambiguous native CASPT2 shift')
        value = float(token[0])
        # ORCA prints native shifts at three significant figures. Preserve
        # the exact echoed request and allow only this output rounding.
        mantissa, _, exponent = token[0].lower().partition('e')
        decimals = len(mantissa.split('.')[1]) if '.' in mantissa else 0
        rounding = .5 * 10 ** (int(exponent or 0) - decimals)
        if not math.isfinite(value) or (value == 0 and settings[key] != 0) or abs(value - settings[key]) > rounding + 1e-14:
            raise ValueError('The native CASPT2 shift differs from the reviewed value')
        native_shifts[key] = value
    prefix = pt.split('CASPT2 Results', 1)[0]
    blocks = re.split(r'\bMULT\s+(\d+),\s*ROOT\s+(\d+)', prefix)
    states = {}
    for i in range(1, len(blocks), 3):
        key, body = (int(blocks[i]), int(blocks[i + 1])), blocks[i + 2]
        if key in states:
            raise ValueError('Duplicated CASPT2 residual solve')
        converged = re.findall(r'CASPT2 calculation converged in\s+(\d+)\s+iterations', body)
        header = re.search(r'Iter\s+EPT2\s+EHylleraas\s+residual norm\s+Time', body)
        if len(converged) != 1 or header is None:
            raise ValueError('A CASPT2 residual solve did not converge')
        iterations = re.findall(r'^\s*(\d+)\s+(' + NUMBER + r')\s+(' + NUMBER + r')\s+(' + NUMBER + r')\s+(' + NUMBER + r')\s*$', body[header.end():], re.M)
        if not iterations or [int(row[0]) for row in iterations] != list(range(1, int(converged[0]) + 1)):
            raise ValueError('Incomplete CASPT2 residual iteration table')
        if any(not math.isfinite(float(v)) for row in iterations for v in row[1:]) or float(iterations[-1][3]) < 0:
            raise ValueError('Invalid CASPT2 residual diagnostics')
        denominators = {kind: float(value) for kind, value in re.findall(
            r'smallest energy denominator\s+(\w+)\s*=\s*(' + NUMBER + ')', body)}
        if set(denominators) != {'IJAB', 'ITAB', 'IJTA', 'TUAB', 'IJTU', 'ITAU', 'TUVA', 'ITUV'}:
            raise ValueError('Incomplete CASPT2 denominator diagnostics')
        if any(not math.isfinite(v) or v <= 0 for v in denominators.values()):
            raise ValueError('A nonpositive CASPT2 denominator requires scientific review')
        states[key] = {'smallest_denominators_hartree': denominators,
                       'caspt2_iterations': int(converged[0]),
                       'final_residual_norm': float(iterations[-1][3])}
    if not states:
        raise ValueError('No state-resolved CASPT2 residual solves')
    if re.search(r'WARNING[^\n]*(?:intruder|denominator)|CASPT2 calculation[^\n]*(?:not converged|did not converge)', pt, re.I):
        raise ValueError('Native CASPT2 convergence/intruder warning requires review')
    return native_shifts, states


def parse_result(text, electronic, values, expected_electrons, reference=None, reference_states=None):
    native_guard(text)
    s = settings(values, electronic, reference['casscf_settings'] if reference else None)
    checks = {'native_normal_termination': True}
    version = re.search(r'Program Version\s+(\S+)', text)
    if version is None:
        raise ValueError('The native ORCA version was not recorded')
    checks['orca_version'] = version[1]
    if electron_count(text) != expected_electrons:
        raise ValueError('Native electron count differs from the source geometry/basis/charge')
    rows = []
    if s['method'] == 'RI-MP2':
        hf = 'RHF' if electronic['multiplicity'] == 1 else 'UHF'
        if not re.search(r'Hartree-Fock type\s+HFTyp\s+\.{2,}\s+' + hf + r'\b', text):
            raise ValueError('MP2 requires its own HF reference, not frozen DFT/CAS orbitals')
        if 'SCF CONVERGED AFTER' not in text or 'Guess MOs are being read' in text:
            raise ValueError('A newly converged HF calculation is required')
        for name, target in [('Charge', electronic['charge']), ('Mult', electronic['multiplicity'])]:
            found = re.findall(r'\b' + name + r'\s+\.{2,}\s+(-?\d+)', text)
            if not found or int(found[-1]) != target:
                raise ValueError('The fresh HF charge/multiplicity differs from the request')
        hf_text = re.split(r'ORCA\s+MP2\s*\n', text, maxsplit=1)[0]
        energy = one_number(r'^\s*Total Energy\s*:\s*(' + NUMBER + r')\s+Eh', hf_text, 'HF energy')
        correction = one_number(r'RI-MP2 CORRELATION ENERGY:\s*(' + NUMBER + r')\s+Eh', text, 'MP2 correction')
        total = one_number(r'MP2 TOTAL ENERGY:\s*(' + NUMBER + ')', text, 'MP2 total')
        final = one_number(r'FINAL SINGLE POINT ENERGY\s+(' + NUMBER + ')', text, 'final energy')
        if abs(final - total) > 1e-8:
            raise ValueError('Native final and MP2 energies disagree')
        core = re.findall(r'Freezing NCore=(\d+) chemical core electrons', text)
        if not core:
            core = re.findall(r'Number of frozen core electrons\s*[:.]\s*(\d+)', text, re.I)
        starts = re.findall(r'Orbital Range Operator\s+\d+:\s*(\d+)\s*-\s*\d+\s+to', text)
        if len(core) == 1:
            frozen = int(core[0])
            checks['frozen_core_count_evidence'] = 'native_NCore'
        elif not core and starts and set(starts) == {'0'}:
            # With FC_NONE, ORCA 6.1.1 omits NCore altogether. Its actual
            # correlated occupied ranges starting at MO 0 establish zero.
            frozen = 0
            checks['frozen_core_count_evidence'] = 'native_correlated_ranges_start_at_zero'
        else:
            raise ValueError('The native MP2 frozen-core count was not established')
        spin = one_number(r'Expectation value of <S\*\*2>\s*:\s*(' + NUMBER + ')', hf_text, 'UHF spin') if hf == 'UHF' else 0.
        target = (electronic['multiplicity'] - 1) / 2
        checks.update(fresh_hf_converged=True, hf_reference=hf, hf_spin_squared=spin,
                      hf_target_spin_squared=target * (target + 1))
        rows = [{'charge': electronic['charge'], 'multiplicity': electronic['multiplicity'], 'root': 0,
                 'reference_energy_hartree': energy, 'correction_hartree': correction, 'energy_hartree': total}]
    else:
        family = 'CASPT2' if s['method'] == 'CASPT2' else 'NEVPT2'
        start = re.search(r'<\s*' + family + r'\s*>', text)
        if start is None:
            raise ValueError('No native ' + family + ' stage')
        marker = start.start()
        # Keep the actual reference section and actual termination footer. PT2
        # prints its own repeated block headers, which are not a second CASCI.
        before = text[:marker]
        methods = re.findall(r'\bPT2\s*=\s*((?:SC|FIC|DLPNO)-NEVPT2|CASPT2(?:-K)?)\b', before)
        if methods != [s['method']]:
            raise ValueError('The native perturbation method differs from the reviewed method')
        excerpt = before + text[text.rfind('ORCA TERMINATED NORMALLY'):]
        objective = reference['casscf_settings']
        space = reference['optimized_active_space']
        native = casscf.state_table(excerpt, reference, space, objective)
        if ('>>> CAS-CI.' not in before or 'THE CAS-SCF GRADIENT HAS CONVERGED' in before or
                any(not re.search(kind + r'\s+Orbitals\s+\.\.\.\s+unchanged', before)
                    for kind in ('Active', 'Internal', 'External'))):
            raise ValueError('The correction must read the verified orbitals without hidden optimization')
        if ('Guess MOs are being read from file: reference.gbw' not in before or
                'Input Geometry matches current geometry' not in before or
                'Input basis set matches current basis set' not in before):
            raise ValueError('Saved CASSCF geometry/basis/read source was not confirmed')
        expected = {(r['multiplicity'], r['root']): r['energy_hartree'] for r in reference_states['states']}
        error = max(abs(row['energy_hartree'] - expected[(row['multiplicity'], row['root'])]) for row in native)
        if {(r['multiplicity'], r['root']) for r in native} != set(expected) or error > 1e-7:
            raise ValueError('The frozen reference state energies changed; do not apply a correction')
        pt = text[marker:]
        if re.search(r'Denominator is negative|Koopmans matrices have at least one negative eigenvalue', pt, re.I):
            raise ValueError('Native intruder-state/negative-denominator warning; inspect the reference and approximations')
        if not re.search(r'Orbitals\s+\.\.\.\s+canonical for each state', pt):
            raise ValueError('The reviewed per-state canonicalization was not confirmed')
        if s['method'] == 'DLPNO-NEVPT2':
            checks.update(dlpno_checks(text, s['pno_preset']))
        elif 'DLPNO-NEVPT2 SETTINGS' in pt:
            raise ValueError('Unexpected local approximation in a canonical NEVPT2 request')
        diagnostics = {}
        if s['method'] == 'CASPT2':
            shifts, diagnostics = caspt2_checks(text, pt, s)
            checks.update(native_caspt2_shifts_hartree=shifts, caspt2_states_converged=len(diagnostics))
        if family + ' Results' not in pt:
            raise ValueError('Missing state-resolved correction results')
        summary = pt[pt.find(family + ' Results'):]
        pattern = (r'MULT\s+(\d+),\s*ROOT\s+(\d+).*?Total Energy Correction\s*:\s*dE\s*=\s*(' + NUMBER +
                   r').*?Reference\s+Energy\s*:\s*E0\s*=\s*(' + NUMBER +
                   r').*?Total Energy \(E0\+dE\)\s*:\s*E\s*=\s*(' + NUMBER + ')')
        for mult, root, correction, energy, total in re.findall(pattern, summary, re.S):
            key = int(mult), int(root)
            if key not in expected or any((r['multiplicity'], r['root']) == key for r in rows):
                raise ValueError('Unexpected or duplicated corrected state')
            if abs(float(energy) - expected[key]) > 1e-7:
                raise ValueError('The correction zero-order energy differs from the verified reference')
            rows.append({'charge': reference['charge'], 'multiplicity': key[0], 'root': key[1],
                         'reference_energy_hartree': float(energy), 'correction_hartree': float(correction),
                         'energy_hartree': float(total),
                         'averaging_weight': next(row['averaging_weight'] for row in reference_states['states']
                                                  if (row['multiplicity'], row['root']) == key)})
        if s['method'] == 'CASPT2':
            weights = re.findall(r'MULT\s+(\d+),\s*ROOT\s+(\d+).*?Reference\s+Weight\s*:\s*W0\s*=\s*(' + NUMBER + ')', summary, re.S)
            weight_map = {(int(mult), int(root)): float(value) for mult, root, value in weights}
            if len(weight_map) != len(weights) or set(weight_map) != set(expected) or set(diagnostics) != set(expected):
                raise ValueError('Incomplete CASPT2 reference-weight/solver diagnostics')
            for row in rows:
                key = row['multiplicity'], row['root']
                weight = weight_map[key]
                if not math.isfinite(weight) or not 0 < weight <= 1:
                    raise ValueError('Invalid CASPT2 reference weight')
                row.update(reference_weight=weight, **diagnostics[key])
        if {(r['multiplicity'], r['root']) for r in rows} != set(expected):
            raise ValueError('Incomplete correction table')
        if s['method'] == 'DLPNO-NEVPT2' and checks['dlpno_states_checked'] != len(rows):
            raise ValueError('Native PNO/solver evidence is incomplete for the requested states')
        counts = re.findall(r'Last\s+frozen\s+orbital\s+\.{2,}\s+(-?\d+)', pt)
        starts = re.findall(r'Orbital Range Operator\s+\d+:\s*(\d+)\s*-\s*\d+\s+to', pt)
        if counts and len(set(counts)) == 1:
            frozen = 2 * (int(counts[0]) + 1)
            checks['frozen_core_count_evidence'] = 'native_last_frozen_orbital'
        elif not counts and starts and set(starts) == {'0'}:
            frozen = 0
            checks['frozen_core_count_evidence'] = 'native_correlated_ranges_start_at_zero'
        else:
            raise ValueError('The correction frozen-core count was not established')
        if frozen > reference['n_electrons'] - space['electrons']:
            raise ValueError('Frozen core overlaps the active space')
        checks.update(reference_readback_max_error_hartree=error, reference_orbitals_unchanged=True,
                      canonicalization='per_state')
    if frozen < 0 or frozen > expected_electrons or frozen % 2 or (not s['frozen_core'] and frozen != 0):
        raise ValueError('The native frozen-core count conflicts with the requested policy')
    if any(not math.isfinite(r[k]) for r in rows for k in
           ('reference_energy_hartree', 'correction_hartree', 'energy_hartree')):
        raise ValueError('A correlation energy is nonfinite')
    error = max(abs(r['reference_energy_hartree'] + r['correction_hartree'] - r['energy_hartree']) for r in rows)
    if error > 1e-8:
        raise ValueError('Reference plus correlation correction does not equal the total')
    checks['energy_sum_max_error_hartree'] = error
    model = {'basis': electronic['basis'], 'auxiliary_basis': s['auxiliary_basis'],
             'integral_transform': 'RI', 'frozen_core': s['frozen_core'], 'frozen_core_electrons': frozen}
    if s['method'] in CAS_METHODS:
        model['contraction'] = 'strongly_contracted' if s['method'] == 'SC-NEVPT2' else 'fully_internally_contracted'
        model['local_approximation'] = s['method'] == 'DLPNO-NEVPT2'
    if s['method'] == 'DLPNO-NEVPT2':
        model['pno_preset'] = s['pno_preset']
    elif s['method'] == 'CASPT2':
        model['shifts_hartree'] = {key: float(s[key]) for key in CASPT2_SHIFTS}
    return {'schema_version': 1, 'method': s['method'], 'geometry_mode': 'fixed', 'energy_unit': 'hartree',
            'reference_method': 'HF' if s['method'] == 'RI-MP2' else 'CASSCF',
            'states': sorted(rows, key=lambda r: (r['multiplicity'], r['root'])),
            'model': model,
            'checks': checks, 'provides_transition_amplitudes': False, 'dyson_compatible': False}


class CorrelationCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure': orm.StructureData, 'electronic_settings': orm.Dict, 'settings': orm.Dict}.items():
            spec.input(key, valid_type=typ)
        for key, typ in {'source_retrieved': orm.FolderData, 'orbital_reference': orm.Dict,
                         'reference_states': orm.Dict, 'source_remote': orm.RemoteData,
                         'source_repository': orm.FolderData, 'source_folder': orm.RemoteData,
                         'source_stash': orm.RemoteStashFolderData, 'source_filename': orm.Str}.items():
            spec.input(key, valid_type=typ, required=False)
        spec.input('metadata.options.parser_name', default='empa_orca.correlation')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('correlation_energies', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_CORRELATION', message='Correlation/reference validation failed: {reason}')

    def prepare_for_submission(self, folder):
        electronic = self.inputs.electronic_settings.get_dict()
        ref = self.inputs.orbital_reference.get_dict() if 'orbital_reference' in self.inputs else None
        s = settings(self.inputs.settings.get_dict(), electronic, ref['casscf_settings'] if ref else None)
        if (self.inputs.metadata.options.resources.get('num_mpiprocs_per_machine', 1) != s['nprocs']
                or self.inputs.metadata.options.withmpi):
            raise ValueError('Allocate the reviewed ORCA processes; ORCA manages MPI internally')
        if self.inputs.code.computer.label == 'tigu' and s['nprocs'] > 12:
            raise ValueError('The current tigu allocation is limited to 12 processes per submission')
        info = common.CalcInfo()
        if s['method'] == 'RI-MP2':
            if ref or any(key in self.inputs for key in ('source_filename', 'source_repository', 'source_folder', 'source_stash')):
                raise ValueError('MP2 must converge a fresh HF reference')
            retrieved = self.inputs.source_retrieved
            validate_source(self.inputs.structure, electronic, self.inputs.code, retrieved,
                            retrieved.creator.outputs.remote_folder)
        else:
            producer = self.inputs.orbital_reference.creator
            states = self.inputs.reference_states
            if (not producer.is_finished_ok or producer.process_type != 'aiida.calculations:empa_orca.casscf' or
                    states.creator.uuid != producer.uuid or self.inputs.source_remote.uuid != producer.outputs.remote_folder.uuid or
                    str(self.inputs.structure.uuid) != ref['structure_uuid'] or electronic != ref['settings'] or
                    self.inputs.code.uuid != producer.inputs.code.uuid or
                    states.get_dict()['readback_max_error_hartree'] > 1e-7):
                raise ValueError('Select the intact, verified CASSCF source and its exact geometry/code')
            from .artifacts import resolve_electronic
            location = resolve_electronic(self.inputs.source_remote, names=['aiida.gbw'])
            key = {'repository': 'source_repository', 'remote': 'source_folder', 'stash': 'source_stash'}[location['kind']]
            if (key not in self.inputs or str(self.inputs[key].uuid) != location['uuid']
                    or self.inputs.source_filename.value != 'aiida.gbw'):
                raise ValueError('The staged orbitals differ from the preserved CASSCF source')
            copy_orbital(info, self.inputs)
        with folder.open('aiida.inp', 'w') as handle:
            handle.write(correlation_input(electronic, s, ref))
        OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
        code = common.CodeInfo()
        code.code_uuid, code.cmdline_params, code.stdout_name, code.join_files = self.inputs.code.uuid, ['aiida.inp'], 'aiida.out', True
        info.codes_info = [code]
        info.retrieve_list = ['aiida.out', 'aiida.property.txt']
        return info


class CorrelationParser(Parser):
    def parse(self, **kwargs):
        try:
            ref = self.node.inputs.orbital_reference.get_dict() if 'orbital_reference' in self.node.inputs else None
            expected = ref['n_electrons'] if ref else electron_count(
                self.node.inputs.source_retrieved.base.repository.get_object_content('aiida.out'))
            states = self.node.inputs.reference_states.get_dict() if ref else None
            data = parse_result(self.retrieved.base.repository.get_object_content('aiida.out'),
                self.node.inputs.electronic_settings.get_dict(), self.node.inputs.settings.get_dict(), expected, ref, states)
            data['structure_uuid'] = str(self.node.inputs.structure.uuid)
            if ref:
                data['source_orbital_reference_uuid'] = str(self.node.inputs.orbital_reference.uuid)
                data['source_state_energies_uuid'] = str(self.node.inputs.reference_states.uuid)
            else:
                data['source_retrieved_uuid'] = str(self.node.inputs.source_retrieved.uuid)
            self.out('correlation_energies', orm.Dict(dict=data))
        except (KeyError, ValueError, OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CORRELATION.format(reason=str(exc))
