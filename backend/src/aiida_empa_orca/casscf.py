"""Fixed-geometry CASSCF references, with an independent frozen-CASCI readback."""

import math
import re

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from .artifacts import resolve_electronic, storage_builder, stash_options
from .casci import active_space, spin_sector_dimension, validate_reference
from .common_orbitals import attach_orbital, copy_orbital, options, source_spec
from .input import render_input
from .pdos_workflow import OrbitalCharacterMixin
from .reference import single_point_parameters
from .native_logs import DIRECTORY, output_policy
from .native_output import output_content, compact_spec, prepare_compact, read_manifest

PROCESS_TYPE = 'aiida.workflows:empa_orca.casscf'
PREPARATION = 'casscf_verified_v1'
READBACK_TOLERANCE = 1e-7  # Hartree, for each individual state, not the average.


def casscf_settings(values, reference, space):
    """One charge and an explicit normalized objective, distinct from populations."""
    active_space(space, reference)
    defaults = {
        'mode': 'state_specific',
        'states': [{'multiplicity': reference['source_multiplicity'], 'weights': [1.0]}],
        'maxiter': 75, 'gtol': 1e-3, 'etol': 1e-8,
        'auxiliary_basis': (reference['settings']['basis'] + '/C'
                            if reference['settings']['basis'] in ('def2-SVP', 'def2-TZVP', 'def2-TZVPP')
                            else 'AutoAux'),
        **{k: reference['settings'][k] for k in ('nprocs', 'memory_mb', 'wallclock_seconds')},
    }
    if set(values) - set(defaults):
        raise ValueError('Unknown CASSCF setting; the charge and geometry belong to the selected reference')
    settings = defaults | values
    if settings['mode'] not in ('state_specific', 'state_average'):
        raise ValueError('Choose state-specific or state-averaged CASSCF')
    for key in ('maxiter', 'nprocs', 'memory_mb', 'wallclock_seconds'):
        if type(settings[key]) is not int or settings[key] < (2 if key == 'maxiter' else 1):
            raise ValueError(f'{key} must be a positive integer; CASSCF needs at least two macro-iterations')
    if settings['memory_mb'] < 256 * settings['nprocs']:
        raise ValueError('Provide at least 256 MiB per process')
    for key in ('gtol', 'etol'):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= defaults[key]:
            raise ValueError(f'{key} must be positive and no looser than the ORCA default {defaults[key]}')
    from .protocols import _token
    settings['auxiliary_basis'] = _token(settings['auxiliary_basis'], 'CASSCF correlation auxiliary basis')
    blocks = settings['states']
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('Choose at least one spin/root block')
    seen, positive, normalized = set(), 0, []
    for block in blocks:
        if not isinstance(block, dict) or set(block) != {'multiplicity', 'weights'}:
            raise ValueError('Each block requires multiplicity and explicit root weights')
        mult, weights = block['multiplicity'], block['weights']
        if type(mult) is not int or mult in seen:
            raise ValueError('Provide each integer multiplicity once')
        seen.add(mult)
        dimension = spin_sector_dimension(len(space['orbitals']), space['electrons'], mult)
        if not isinstance(weights, list) or not weights or len(weights) > dimension:
            raise ValueError(f'Multiplicity {mult} allows {dimension} roots in this active space')
        if any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in weights):
            raise ValueError('Root weights must be finite nonnegative numbers')
        total = sum(weights)
        if not math.isfinite(total) or total <= 0:
            raise ValueError('Each multiplicity block needs a positive total weight')
        positive += sum(w > 0 for w in weights)
        normalized.append({'multiplicity': mult, 'weights': list(weights)})
    total = sum(sum(b['weights']) for b in normalized)
    if not math.isfinite(total):
        raise ValueError('The total state weight must be finite')
    if (settings['mode'] == 'state_specific' and positive != 1) or (
            settings['mode'] == 'state_average' and positive < 2):
        raise ValueError('State-specific CASSCF weights one root; state averaging requires at least two')
    normalizer = 1.0 if abs(total - 1.0) < 1e-14 else total
    settings['states'] = [{'multiplicity': b['multiplicity'], 'weights': [w / normalizer for w in b['weights']]}
                          for b in normalized]
    return settings


def casscf_input(reference, space, values, *, readback=False):
    s = casscf_settings(values, reference, space)
    source = single_point_parameters(reference['settings'])
    params = {
        'charge': reference['charge'], 'multiplicity': s['states'][0]['multiplicity'],
        'input_keywords': [reference['settings']['basis'], s['auxiliary_basis'], 'MOREAD', 'NoIter'],
        'input_blocks': {'pal': {'nprocs': s['nprocs']}},
    }
    if 'basis' in source['input_blocks']:
        params['input_blocks']['basis'] = source['input_blocks']['basis']
    # Render simple keywords first: no later TightSCF-like keyword can reset the objective/tolerances.
    text = render_input(params, int(.75 * s['memory_mb'] / s['nprocs']), 'aiida.coords.xyz')
    blocks = s['states']
    lines = [f'%moinp "{"aiida.gbw" if readback else "reference.gbw"}"', '%casscf',
             f' nel {space["electrons"]}', f' norb {len(space["orbitals"])}',
             ' mult ' + ','.join(str(b['multiplicity']) for b in blocks),
             ' nroots ' + ','.join(str(len(b['weights'])) for b in blocks),
             ' bweight ' + ','.join(f'{sum(b["weights"]):.16g}' for b in blocks)]
    for index, block in enumerate(blocks):
        lines.append(f' weights[{index}] = ' + ','.join(f'{w:.16g}' for w in block['weights']))
    lines += [f' maxiter {1 if readback else s["maxiter"]}', ' TrafoStep RI',
              f' GTol {s["gtol"]:.12g}', f' ETol {s["etol"]:.12g}',
              ' ActOrbs ' + ('unchanged' if readback else 'NatOrbs'),
              ' IntOrbs unchanged', ' ExtOrbs unchanged', ' PrintGState true', 'end']
    return text + '\n' + '\n'.join(lines) + '\n'


def state_table(text, reference, space, settings):
    """Read the final complete state family, never the averaged total energy."""
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('ORCA did not terminate normally')
    if re.search(r'(?:CI|CAS[- ]?SCF).*?(?:NOT CONVERGED|DID NOT CONVERGE)', text, re.I):
        raise ValueError('The native output reports unconverged CI/CASSCF')
    for label, count in {'Number of active electrons': space['electrons'],
                         'Number of active orbitals': len(space['orbitals']),
                         'Total number of electrons': reference['n_electrons']}.items():
        found = re.findall(re.escape(label) + r'\s+\.\.\.\s+(\d+)', text)
        if not found or int(found[-1]) != count:
            raise ValueError('CASSCF electron/orbital count differs from the reviewed input: ' + label)
    ranges = re.findall(r'Active\s+(\d+)\s*-\s*(\d+)\s*\(', text)
    if not ranges or list(map(int, ranges[-1])) != [space['orbitals'][0], space['orbitals'][-1]]:
        raise ValueError('CASSCF active-orbital partition differs from the reviewed input')
    if 'CI-PROBLEM SOLVED' not in text:
        raise ValueError('CI convergence was not confirmed')
    # ORCA can reorder multiplicity blocks. Match physical spin/root identities,
    # not the input row number, and check the objective it actually used.
    expected = {b['multiplicity']: b['weights'] for b in settings['states']}
    printed = {}
    for match in re.finditer(r'BLOCK\s+\d+\s+WEIGHT=[^\n]+\n\s+Multiplicity\s+\.\.\.\s+(\d+)(.*?)'
                             r'(?=\nBLOCK\s+\d+\s+WEIGHT=|\n\s+PrintLevel)', text, re.S):
        mult = int(match[1])
        weights = re.findall(r'ROOT=(\d+)\s+WEIGHT=\s*([-+\d.Ee]+)', match[2])
        if mult in printed or [int(r) for r, _ in weights] != list(range(len(expected.get(mult, [])))):
            raise ValueError('The native state-average objective has unexpected spin/root identities')
        printed[mult] = [float(w) for _, w in weights]
    if set(printed) != set(expected) or any(
            abs(a - b) > 1e-6 for mult in expected for a, b in zip(printed[mult], expected[mult])):
        raise ValueError('The native orbital-optimization weights differ from the reviewed objective')
    start = text.rfind('DOING ONE FINAL ITERATION FOR PRINTING')
    final = text[start:] if start >= 0 else text
    headers = list(re.finditer(r'CAS-SCF STATES FOR BLOCK\s+(\d+)\s+MULT=\s*(\d+)\s+NROOTS=\s*(\d+)', final))
    if (len(headers) != len(expected) or len({int(h[1]) for h in headers}) != len(expected)
            or {int(h[2]): int(h[3]) for h in headers} != {m: len(w) for m, w in expected.items()}):
        raise ValueError('Missing or unexpected final CASSCF multiplicity/root blocks')
    states = []
    for index, header in enumerate(headers):
        mult = int(header[2])
        segment = final[header.end():headers[index + 1].start() if index + 1 < len(headers) else len(final)]
        segment = segment.split('Spin-Determinant CI Printing')[0].split('DENSITY MATRIX')[0]
        roots = re.findall(r'ROOT\s+(\d+)\s*:\s*E=\s*([-+\d.Ee]+)\s+Eh', segment)
        if [int(root) for root, _ in roots] != list(range(len(expected[mult]))):
            raise ValueError('Incomplete or duplicated CASSCF roots')
        for root, energy in roots:
            value = float(energy)
            if not math.isfinite(value):
                raise ValueError('Non-finite CASSCF state energy')
            states.append({'charge': reference['charge'], 'multiplicity': mult,
                           'root': int(root), 'energy_hartree': value,
                           'averaging_weight': expected[mult][int(root)]})
    return sorted(states, key=lambda row: (row['multiplicity'], row['root']))


def verified_result(optimized, frozen, reference, space, values):
    settings = casscf_settings(values, reference, space)
    for text, filename in ((optimized, 'reference.gbw'), (frozen, 'aiida.gbw')):
        if (f'Guess MOs are being read from file: {filename}' not in text or
                'Input Geometry matches current geometry' not in text or
                'Input basis set matches current basis set' not in text):
            raise ValueError('ORCA did not confirm reading the expected orbitals at matching geometry/basis')
    if 'THE CAS-SCF GRADIENT HAS CONVERGED' not in optimized:
        raise ValueError('CASSCF orbital-gradient convergence was not confirmed; normal termination is insufficient')
    if '>>> CAS-CI.' in optimized:
        raise ValueError('A frozen CASCI calculation cannot be presented as orbital-optimized CASSCF')
    if '>>> CAS-CI.' not in frozen:
        raise ValueError('The independent readback was not frozen CASCI')
    for kind in ('Active', 'Internal', 'External'):
        if not re.search(kind + r'\s+Orbitals\s+\.\.\.\s+unchanged', frozen):
            raise ValueError('The readback changed an orbital subspace')
    states, checked = (state_table(text, reference, space, settings) for text in (optimized, frozen))
    error = max(abs(a['energy_hartree'] - b['energy_hartree']) for a, b in zip(states, checked))
    if error > READBACK_TOLERANCE:
        raise ValueError(f'Saved-orbital readback differs by {error:.6g} Hartree; inspect before using this reference')
    return {'schema_version': 1, 'method': 'CASSCF', 'geometry_mode': 'fixed', 'energy_unit': 'hartree',
            'mode': settings['mode'], 'active_space': space, 'reference_charge': reference['charge'],
            'states': states, 'readback_max_error_hartree': error,
            'readback_tolerance_hartree': READBACK_TOLERANCE,
            'model': {'integral_transform': 'RI', 'auxiliary_basis': settings['auxiliary_basis']}}


class CasscfCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure': orm.StructureData, 'orbital_reference': orm.Dict,
                         'active_space': orm.Dict, 'settings': orm.Dict}.items():
            spec.input(key, valid_type=typ)
        source_spec(spec)
        compact_spec(spec)
        spec.input('metadata.options.parser_name', default='empa_orca.casscf')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('orbital_reference', valid_type=orm.Dict)
        spec.output('state_energies', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_CASSCF', message='CASSCF convergence or saved-orbital readback failed; inspect both outputs.')

    def prepare_for_submission(self, folder):
        ref, space, settings = (self.inputs[k].get_dict() for k in ('orbital_reference', 'active_space', 'settings'))
        if str(self.inputs.structure.uuid) != ref['structure_uuid']:
            raise ValueError('CASSCF must keep the exact selected geometry')
        for name, readback in (('aiida', False), ('verify', True)):
            with folder.open(name + '.inp', 'w') as handle:
                handle.write(casscf_input(ref, space, settings, readback=readback))
        OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
        info = common.CalcInfo()
        copy_orbital(info, self.inputs)
        info.codes_info = []
        for name in ('aiida', 'verify'):
            code = common.CodeInfo()
            code.code_uuid, code.cmdline_params = self.inputs.code.uuid, [name + '.inp']
            code.stdout_name, code.join_files = name + '.out', True
            info.codes_info.append(code)
        info.codes_run_mode = common.CodeRunMode.SERIAL
        return prepare_compact(info, self.inputs, folder, 'casscf-v1')


class CasscfParser(Parser):
    def parse(self, **kwargs):
        try:
            ref = self.node.inputs.orbital_reference.get_dict()
            space = active_space(self.node.inputs.active_space.get_dict(), ref)
            settings = casscf_settings(self.node.inputs.settings.get_dict(), ref, space)
            repository = self.retrieved.base.repository
            manifest = read_manifest(self.node, repository, 'casscf-v1', logger=self.logger)
            data = verified_result(output_content(repository, 'aiida.out'),
                                   output_content(repository, 'verify.out'), ref, space, settings)
            from .artifacts import remote_files
            remote_files(self.node.computer, self.node.outputs.remote_folder.get_remote_path(), names=['aiida.gbw'])
            data['structure_uuid'] = str(self.node.inputs.structure.uuid)
            data['input_orbital_reference_uuid'] = str(self.node.inputs.orbital_reference.uuid)
            orbital = dict(ref, preparation=PREPARATION, kind='CASSCF', filename='aiida.gbw',
                           source_multiplicity=settings['states'][0]['multiplicity'],
                           parent_orbital_reference_uuid=str(self.node.inputs.orbital_reference.uuid),
                           optimized_active_space=space, casscf_settings=settings,
                           readback_max_error_hartree=data['readback_max_error_hartree'])
            if 'orbital_mapping' in orbital:
                # Optimized orbitals are new functions, not a permutation of
                # the original QROs. Retain the mapping as starting-guess history.
                orbital['starting_orbital_mapping'] = orbital.pop('orbital_mapping')
            orbital['settings'] = ref['settings'] | {k: settings[k] for k in ('nprocs', 'memory_mb', 'wallclock_seconds')}
            orbital_node = orm.Dict(dict=orbital)
            data['orbital_reference_uuid'] = str(orbital_node.uuid)
            self.out('orbital_reference', orbital_node)
            self.out('state_energies', orm.Dict(dict=data))
            if manifest is not None:
                self.out('native_output_manifest', orm.Dict(dict=manifest))
        except (KeyError, ValueError, OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CASSCF


class CasscfWorkChain(OrbitalCharacterMixin, engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure': orm.StructureData, 'orbital_reference': orm.Dict,
                         'source_remote': orm.RemoteData, 'active_space': orm.Dict, 'settings': orm.Dict,
                         'code': orm.AbstractCode, 'storage_code': orm.AbstractCode, 'storage_policy': orm.Dict}.items():
            spec.input(key, valid_type=typ)
        for key, typ in {'orbital_reference': orm.Dict, 'state_energies': orm.Dict,
                         'remote_folder': orm.RemoteData, 'retrieved': orm.FolderData}.items():
            spec.output(key, valid_type=typ)
        spec.input('native_output_policy', valid_type=orm.Dict,
                   default=lambda: orm.Dict(dict={'mode': 'remote'}))
        spec.output('native_output_manifest', valid_type=orm.Dict, required=False)
        cls.character_spec(spec)
        spec.outline(cls.setup, cls.calculate, cls.inspect,
                     engine.if_(cls.should_stash)(cls.preserve, cls.inspect_storage),
                     cls.results, cls.run_orbital_character, cls.inspect_orbital_character)
        spec.exit_code(400, 'ERROR_INPUT', message='Invalid CASSCF request or unavailable input orbitals; see report.')
        spec.exit_code(401, 'ERROR_CASSCF', message='CASSCF optimization/readback failed; do not reuse this candidate.')
        spec.exit_code(402, 'ERROR_STORAGE', message='CASSCF reference preservation failed.')

    def setup(self):
        try:
            ref = validate_reference(self.inputs.orbital_reference, self.inputs.source_remote)
            if str(self.inputs.structure.uuid) != ref['structure_uuid']:
                raise ValueError('CASSCF requires the exact prepared geometry')
            self.ctx.settings = casscf_settings(self.inputs.settings.get_dict(), ref, self.inputs.active_space.get_dict())
            if str(self.inputs.code.uuid) != str(self.inputs.orbital_reference.creator.inputs.code.uuid):
                raise ValueError('Use the same ORCA code as the orbital source')
            if self.inputs.storage_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('Preserve the reference on its calculation computer')
            self.ctx.retention = output_policy(self.inputs.native_output_policy.get_dict())
            self.ctx.location = resolve_electronic(self.inputs.source_remote, names=[ref['filename']])
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INPUT

    def calculate(self):
        b = CasscfCalculation.get_builder()
        for key in ('structure', 'orbital_reference', 'active_space', 'code'):
            b[key] = self.inputs[key]
        b.settings = orm.Dict(dict=self.ctx.settings)
        b.compact_code = self.inputs.storage_code
        b.native_output_policy = orm.Dict(dict=self.ctx.retention)
        attach_orbital(b, self.ctx.location, self.inputs.orbital_reference.get_dict()['filename'])
        b.metadata.options = options(self.ctx.settings)
        if self.ctx.retention['mode'] == 'stash':
            b.metadata.options.stash = stash_options(self.ctx.retention['stash_directory'], DIRECTORY)
        b.metadata.disable_cache = True
        return engine.ToContext(calculation=self.submit(b))

    def inspect(self):
        if not self.ctx.calculation.is_finished_ok:
            return self.exit_codes.ERROR_CASSCF

    def preserve(self):
        b = storage_builder(self.ctx.calculation.outputs.remote_folder, self.inputs.storage_code,
                            {'threshold_mb': 0, 'stash_directory': self.ctx.retention['stash_directory']},
                            names=['aiida.gbw'])
        return engine.ToContext(storage=self.submit(b))

    def inspect_storage(self):
        if not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE

    def should_stash(self):
        return self.ctx.retention['mode'] == 'stash'

    def results(self):
        for key in ('orbital_reference', 'state_energies', 'remote_folder', 'retrieved'):
            self.out(key, self.ctx.calculation.outputs[key])
        if 'native_output_manifest' in self.ctx.calculation.outputs:
            self.out('native_output_manifest', self.ctx.calculation.outputs.native_output_manifest)
