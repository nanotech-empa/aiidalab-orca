"""Fixed-geometry, site-resolved K-edge ΔSCF photoelectron spectroscopy."""

import hashlib
import copy
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
    if (s['multiplicity'], reference(s)) not in ((1, 'RKS'), (2, 'UKS')):
        raise ValueError('This XPS protocol requires a closed-shell RKS singlet or a UKS doublet reference.')
    if set(structure.get_ase().numbers) - {1, 6, 7, 8, 9, 27}:
        raise ValueError('This XPS draft supports H/C/N/O/F and all-electron Co.')
    if list(structure.get_ase().numbers).count(27) > 1:
        raise ValueError('The initial Co extension supports one cobalt centre.')
    if any(v.get('ecp', 'none').lower() != 'none' for v in s['element_settings'].values()):
        raise ValueError('Core-ionization XPS requires an all-electron reference; ECPs are not supported.')
    if s['block_parameters']:
        raise ValueError('Expert block overrides require separate validation before use in this XPS draft.')
    return s


def core_parameters(settings):
    p = single_point_parameters(settings)
    p['input_keywords'] += ['MOREAD', 'NoIter', 'CalcGuessEnergy']
    p['input_blocks']['scf'] = {'MaxIter': 0}
    p['input_blocks']['output'] = {'Print[P_AtPopMO_L]': 1}
    return p


def site_parameters(settings, orbital_index, spin_channel='alpha', solver='standard', *, electron_count=None):
    if spin_channel not in ('alpha', 'beta'):
        raise ValueError('Choose alpha or beta ionization')
    p = single_point_parameters(settings)
    p['input_keywords'] = ['UKS' if x == 'RKS' else x for x in p['input_keywords']]
    p['input_keywords'] += ['MOREAD', 'DeltaSCF', 'NoDIIS', 'NoTRAH']
    p['input_blocks']['scf']['IonizeAlpha' if spin_channel == 'alpha' else 'IonizeBeta'] = int(orbital_index)
    if solver == 'freeze_release':
        p['input_keywords'] += ['FreezeAndRelease', 'SCFCheckGrad']
        p['input_blocks']['scf'].update(DoMOM='false', SOSCFMaxStep=.1, SOSCFConstrainedMaxStep=.1, SOSCFConvFactor=100)
        if electron_count is not None and p['multiplicity'] == 2:
            if type(electron_count) is not int or electron_count % 2 != 1:
                raise ValueError('Compact doublet ionization requires an odd electron count')
            spin = 0 if spin_channel == 'alpha' else 1
            counts = [(electron_count+1)//2, (electron_count-1)//2]
            frontier = counts[spin]-2
            if not 0 <= orbital_index < frontier:
                raise ValueError('The core orbital must lie below the occupied frontier')
            p['charge'] += 1
            p['multiplicity'] = 1 if spin == 0 else 3
            p['input_blocks']['scf'].pop('IonizeAlpha' if spin == 0 else 'IonizeBeta')
            p['input_blocks']['scf'].update({
                'AlphaConf' if spin == 0 else 'BetaConf': '0,1',
                'Rotate': f'\n {{{orbital_index},{frontier},90,{spin},{spin}}}\nend',
            })
    elif solver != 'standard':
        raise ValueError('Choose standard or freeze_release DeltaSCF convergence')
    # ORCA 6.1.1 skips Löwdin analysis after IonizeAlpha because its population
    # routine still expects the reference NEL. Native Mulliken MO populations
    # remain available; electron counts are checked independently below.
    p['input_blocks']['output'] = {'Print[P_AtPopMO_M]': 1}
    # IonizeAlpha changes electron count/spin internally: retain the reference
    # charge and multiplicity in the XYZ declaration (ORCA 6.1 manual 5.34.3.2).
    return p


def strict_stage_parameters(settings, orbital_index, spin_channel, electron_count, solver):
    """Same core hole, followed by a precision polish and frozen-density readback."""
    from .scripts.xps_validation import GRADIENT_TARGETS
    if settings['multiplicity'] != 2 or settings['scf_convergence'] not in GRADIENT_TARGETS:
        raise ValueError('The validated doublet XPS protocol requires TightSCF or stricter')
    preparation = site_parameters(settings, orbital_index, spin_channel, solver,
                                  electron_count=electron_count)
    preparation['input_keywords'] = list(dict.fromkeys(preparation['input_keywords']+['SCFCheckGrad']))
    preparation['input_blocks']['output'] = {'Print[P_AtPopMO_M]': 1, 'Print[P_AtPopMO_L]': 1}
    refinement = copy.deepcopy(preparation)
    refinement['charge'] = settings['charge']+1
    refinement['multiplicity'] = 1 if spin_channel == 'alpha' else 3
    refinement['input_keywords'] = [v for v in refinement['input_keywords'] if v != 'FreezeAndRelease']
    refinement['input_keywords'] = list(dict.fromkeys(refinement['input_keywords']+['SOSCF']))
    refinement['input_blocks']['scf'] = {
        'MaxIter': min(100, settings['max_scf_steps']), 'DeltaSCFFromGS': 'false',
        'DoMOM': 'false', 'SOSCFBlockDiag': 'true', 'SOSCFMaxStep': .02,
        'DirectResetFreq': 1, 'TolG': min(1e-6, GRADIENT_TARGETS[settings['scf_convergence']]),
    }
    readback = copy.deepcopy(refinement)
    readback['input_keywords'] = [v for v in readback['input_keywords']
        if v not in ('DeltaSCF', 'SOSCF', 'SCFCheckGrad', 'NoDIIS', 'NoTRAH')]
    readback['input_keywords'] = list(dict.fromkeys(readback['input_keywords']+['NoIter', 'CalcGuessEnergy']))
    readback['input_blocks']['scf'] = {'MaxIter': 0}
    return preparation, refinement, readback


def validation_request(inputs):
    settings = reference_settings(inputs.settings.get_dict())
    return {'schema_version': 1, 'solver': inputs.solver.value,
        'orca_executable': str(inputs.code.filepath_executable),
        'atom_index': inputs.atom_index.value, 'spin_channel': inputs.spin_channel.value,
        'electron_count': int(inputs.structure.get_ase().numbers.sum())-settings['charge'],
        'scf_convergence': settings['scf_convergence'],
        'core_reference': inputs.core_reference.get_dict(),
        'ground_energy_hartree': source_energy(inputs.source_retrieved)}


def strict_validation(inputs):
    return 'strict_validation' in inputs and inputs.strict_validation.value


def parse_site_outputs(inputs, retrieved):
    if strict_validation(inputs):
        from .scripts.xps_validation import validate_bundle, validate_stage
        request = validation_request(inputs)
        preparation = retrieved.base.repository.get_object_content('preparation.out')
        validate_stage(preparation, request, 'preparation')
        result = validate_bundle(preparation, retrieved.base.repository.get_object_content('aiida.out'),
            retrieved.base.repository.get_object_content('wavefunction_check.out'), request)
        saved = json.loads(retrieved.base.repository.get_object_content('xps_validation.json'))
        if saved != result:
            raise ValueError('Stored validation differs from the native XPS outputs')
        return result
    text = retrieved.base.repository.get_object_content('aiida.out')
    return parse_site(text, inputs.core_reference.get_dict(), inputs.atom_index.value,
        int(inputs.structure.get_ase().numbers.sum())-inputs.settings.get_dict()['charge'],
        source_energy(inputs.source_retrieved), initial_multiplicity=inputs.settings.get_dict()['multiplicity'],
        spin_channel=inputs.spin_channel.value if 'spin_channel' in inputs else 'alpha')


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
        with folder.open('spin_core.py', 'w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('scripts/spin_core.py').read_text())
        with folder.open('request.json', 'w') as handle:
            json.dump({'numbers': self.inputs.structure.get_ase().numbers.tolist(),
                       'schema_version': 2 if s['multiplicity'] == 2 or any(z in (7, 27) for z in self.inputs.structure.get_ase().numbers) else 1,
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
            if data.get('schema_version') not in (1, 2) or not data.get('assignments'):
                raise ValueError('No verified core-orbital assignments')
            from .scripts.core_orbitals import assignments
            localized = 'pipek_mezey' in data['method']
            text = self.retrieved.base.repository.get_object_content('localized.out' if localized else 'aiida.out')
            if data['schema_version'] == 2:
                from .scripts.spin_core import spin_assignments
                rows, verified, _ = spin_assignments(text, self.node.inputs.structure.get_ase().numbers.tolist(),
                    original=data['original_assignments'] if localized else None)
            else:
                rows, verified = assignments(text, self.node.inputs.structure.get_ase().numbers.tolist(), localized=localized)
            if not verified or rows != data['assignments']:
                raise ValueError('Stored core assignments differ from the native population analysis')
            initial = self.retrieved.base.repository.get_object_content('aiida.out')
            if re.search(r'^\|.*!.*\bCalcGuessEnergy\b', initial, re.M | re.I):
                from .scripts.xps_validation import density_summary, ENERGY_TOLERANCE
                expected = source_energy(self.node.inputs.source_retrieved)
                energies = [density_summary(value, require_scf=False, strict=True)['energy_hartree']
                            for value in (initial, text)]
                if any(abs(value-expected) > ENERGY_TOLERANCE for value in energies):
                    raise ValueError('Prepared core wavefunction does not reproduce the neutral reference energy')
                data['energy_audit'] = {'reference_energy_hartree': expected,
                    'input_gbw_energy_hartree': energies[0], 'prepared_gbw_energy_hartree': energies[1],
                    'tolerance_hartree': ENERGY_TOLERANCE, 'no_orbital_optimization': True}
            self.out('core_reference', orm.Dict(dict=data))
        except (OSError, ValueError, KeyError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CORE


def source_energy(retrieved):
    from .parser import reference_summary
    return reference_summary(retrieved.base.repository.get_object_content('aiida.out'))['energy_hartree']


def core_runs(retrieved_uuid, code_uuid, *, require_energy_audit=False):
    query = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': str(retrieved_uuid)}, tag='source').append(
        orm.WorkChainNode, with_incoming='source', edge_filters={'label': 'source_retrieved'}, tag='run',
        filters={'process_type': CORE_PROCESS, 'attributes.exit_status': 0,
                 'attributes.process_state': 'finished'}, project=['uuid'])
    for uuid in query.order_by({'run': {'ctime': 'desc'}}).all(flat=True):
        node = orm.load_node(uuid)
        if str(node.inputs.code.uuid) == str(code_uuid):
            if require_energy_audit and 'energy_audit' not in node.outputs.core_reference.get_dict():
                continue
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
                for uuid in core_runs(self.inputs.source_retrieved.uuid, self.inputs.code.uuid,
                                      require_energy_audit=self.inputs.settings.get_dict()['multiplicity'] == 2):
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
        if (self.inputs.settings.get_dict()['multiplicity'] == 2
                and 'energy_audit' not in self.ctx.preparation.outputs.core_reference.get_dict()):
            self.report('The prepared neutral GBW has no independent energy readback audit.')
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


def site_signature(structure, settings, code_uuid, retrieved_uuid, atom_index, spin_channel='alpha'):
    from aiida.orm.implementation import clean_value
    atoms = structure.get_ase()
    payload = {'model': 'rks_1s_delta_scf_v1', 'numbers': atoms.numbers.tolist(),
               'positions': atoms.positions.tolist(), 'parameters': clean_value(single_point_parameters(settings)),
               'code_uuid': str(code_uuid), 'source_retrieved_uuid': str(retrieved_uuid), 'atom_index': atom_index}
    if settings['multiplicity'] == 2 or spin_channel != 'alpha':
        payload.update(model='uks_1s_delta_scf_v2', spin_channel=spin_channel)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def parse_site(text, core_reference, atom_index, electron_count, ground_energy, *, initial_multiplicity=1, spin_channel='alpha'):
    if core_reference.get('schema_version') == 2:
        from .xps_multiplets import parse_spin_site
        return parse_spin_site(text, core_reference, atom_index, electron_count, ground_energy, initial_multiplicity, spin_channel)
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
        spec.input('spin_channel', valid_type=orm.Str, default=lambda: orm.Str('alpha'))
        spec.input('solver', valid_type=orm.Str, default=lambda: orm.Str('standard'))
        spec.input('strict_validation', valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.input('helper_code', valid_type=orm.AbstractCode, required=False)
        spec.input('metadata.options.parser_name', default='empa_orca.xps_site')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('site_result', valid_type=orm.Dict)
        spec.output('validation_diagnostics', valid_type=orm.Dict, required=False)
        spec.exit_code(310, 'ERROR_SITE', message='Core-ionization calculation or validation failed; inspect aiida.out.')

    def prepare_for_submission(self, folder):
        s = validate_reference(self.inputs.structure, self.inputs.settings.get_dict())
        atom = self.inputs.atom_index.value
        if not 0 <= atom < len(self.inputs.structure.sites) or self.inputs.structure.get_ase().numbers[atom] not in (6, 7, 8, 9, 27):
            raise ValueError('Select a C/N/O/F/Co atom for 1s ionization')
        spin = self.inputs.spin_channel.value
        rows = [r for r in self.inputs.core_reference.get_dict()['assignments'] if r['atom_index'] == atom
                and r.get('shell', '1s') == '1s' and r.get('spin_channel', 'alpha') == spin]
        if len(rows) != 1 or rows[0]['population'] < .95:
            raise ValueError('The requested atom has no unique verified core orbital')
        maxcore = int(.75*s['memory_mb']/s['nprocs'])
        if strict_validation(self.inputs):
            if 'helper_code' not in self.inputs or self.inputs.helper_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('Validated XPS needs the matching ORCA tools code on the same computer')
            stages = strict_stage_parameters(s, rows[0]['index'], spin,
                int(self.inputs.structure.get_ase().numbers.sum())-s['charge'], self.inputs.solver.value)
            for filename, source, parameters in zip(
                    ('preparation.inp', 'aiida.inp', 'wavefunction_check.inp'),
                    ('reference.gbw', 'preparation.gbw', 'aiida.gbw'), stages):
                with folder.open(filename, 'w') as handle:
                    handle.write(f'%moinp "{source}"\n'+render_input(parameters, maxcore, 'aiida.coords.xyz'))
            with folder.open('xps_request.json', 'w') as handle:
                json.dump(validation_request(self.inputs), handle)
            for script in ('core_orbitals.py', 'xps_validation.py', 'xps_finalize.py'):
                with folder.open(script, 'w') as handle:
                    handle.write(files('aiida_empa_orca').joinpath('scripts', script).read_text())
            OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
            info = common.CalcInfo()
            copy_orbital(info, self.inputs)
            native, helper = common.CodeInfo(), common.CodeInfo()
            native.code_uuid, native.cmdline_params = self.inputs.code.uuid, ['preparation.inp']
            native.stdout_name, native.join_files = 'preparation.out', True
            helper.code_uuid, helper.cmdline_params = self.inputs.helper_code.uuid, ['xps_finalize.py']
            helper.stdout_name, helper.join_files = 'validation.log', True
            info.codes_info = [native, helper]
            info.codes_run_mode = common.CodeRunMode.SERIAL
            info.retrieve_list = ['preparation.out', 'aiida.out', 'wavefunction_check.out',
                                  'xps_validation.json', 'validation.log']
            return info
        text = '%moinp "reference.gbw"\n' + render_input(site_parameters(s, rows[0]['index'], spin, self.inputs.solver.value), maxcore, 'aiida.coords.xyz')
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
            result = parse_site_outputs(inputs, self.retrieved)
            result['signature'] = site_signature(inputs.structure, inputs.settings.get_dict(), inputs.code.uuid,
                                                  inputs.source_retrieved.uuid, inputs.atom_index.value, inputs.spin_channel.value)
            self.out('site_result', orm.Dict(dict=result))
        except (OSError, ValueError, KeyError, IndexError) as exc:
            self.logger.error(str(exc))
            if strict_validation(self.node.inputs):
                self.out('validation_diagnostics', orm.Dict(dict={
                    'accepted': False, 'reason': str(exc),
                    'guidance': ('Inspect preparation.out and validation.log before resubmitting. '
                                 'Do not reuse a collapsed or poorly normalized core-hole wavefunction. '
                                 'More SCF cycles help only when the native convergence trace is improving.'),
                }))
            return self.exit_codes.ERROR_SITE


def validated_site(node):
    from aiida.orm.implementation import clean_value
    if node.process_type != SITE_PROCESS or not node.is_finished_ok or 'site_result' not in node.outputs:
        raise ValueError('No successful site-ionization result')
    saved = node.outputs.site_result.get_dict()
    parsed = parse_site_outputs(node.inputs, node.outputs.retrieved)
    expected = site_signature(node.inputs.structure, node.inputs.settings.get_dict(), node.inputs.code.uuid,
                              node.inputs.source_retrieved.uuid, node.inputs.atom_index.value,
                              node.inputs.spin_channel.value if 'spin_channel' in node.inputs else 'alpha')
    if saved != clean_value(parsed | {'signature': expected}):
        raise ValueError('The saved site result differs from the native ORCA output')
    return saved


def matching_sites(structure, settings, code_uuid, retrieved_uuid, spin_channel='alpha', *, require_readback=False):
    result = {}
    query = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': str(retrieved_uuid)}, tag='source').append(
        orm.CalcJobNode, with_incoming='source', edge_filters={'label': 'source_retrieved'}, tag='site',
        filters={'process_type': SITE_PROCESS, 'attributes.exit_status': 0,
                 'attributes.process_state': 'finished'}, project=['uuid'])
    for uuid in query.order_by({'site': {'ctime': 'desc'}}).all(flat=True):
        node = orm.load_node(uuid)
        if require_readback and not strict_validation(node.inputs):
            continue
        atom = node.inputs.atom_index.value
        if atom in result:
            continue
        try:
            data = validated_site(node)
            if data['signature'] == site_signature(structure, settings, code_uuid, retrieved_uuid, atom, spin_channel):
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
        spec.input('spin_channel', valid_type=orm.Str, default=lambda: orm.Str('alpha'))
        spec.input('solver', valid_type=orm.Str, default=lambda: orm.Str('standard'))
        spec.input('strict_validation', valid_type=orm.Bool, default=lambda: orm.Bool(True))
        spec.output_namespace('sites', dynamic=True, valid_type=orm.Dict)
        spec.output_namespace('diagnostics', dynamic=True, valid_type=orm.Dict)
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
            if self.inputs.spin_channel.value not in ('alpha', 'beta'):
                raise ValueError('Choose alpha or beta ionization')
            if self.inputs.spin_channel.value == 'beta' and self.inputs.settings.get_dict()['multiplicity'] == 1:
                raise ValueError('Use the alpha representative for a closed-shell singlet')
            validate_source(self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code,
                            self.inputs.source_retrieved, self.inputs.source_remote)
            storage_policy(self.inputs.storage_policy.get_dict())
            if self.inputs.helper_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('The ORCA tools code must use the ORCA computer')
            atoms = self.inputs.atom_indices.get_list()
            self.ctx.strict = (self.inputs.settings.get_dict()['multiplicity'] == 2
                and ('strict_validation' not in self.inputs or self.inputs.strict_validation.value))
            numbers = self.inputs.structure.get_ase().numbers
            if not atoms or len(set(atoms)) != len(atoms) or any(type(i) is not int or not 0 <= i < len(numbers) or numbers[i] not in (6, 7, 8, 9, 27) for i in atoms):
                raise ValueError('Select distinct C/N/O/F/Co atom indices for 1s ionization')
            previous = {} if self.inputs.force_recompute.value else matching_sites(
                self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code.uuid, self.inputs.source_retrieved.uuid,
                self.inputs.spin_channel.value, require_readback=self.ctx.strict)
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
            b.spin_channel = self.inputs.spin_channel
            b.solver = self.inputs.solver
            b.strict_validation = orm.Bool(getattr(self.ctx, 'strict', False))
            if b.strict_validation.value:
                b.helper_code = self.inputs.helper_code
            attach_orbital(b, resolve_electronic(self.ctx.core.outputs.remote_folder, names=['aiida.gbw']), 'aiida.gbw')
            b.metadata.options = options(self.inputs.settings.get_dict())
            b.metadata.disable_cache = True
            b.metadata.label = f'Atom {b.atom_index.value+1} · 1s core ionization · {self.inputs.spin_channel.value}'
            return engine.ToContext(site=self.submit(b))
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_CORE

    def inspect_site(self):
        node = self.ctx.site
        if not node.is_finished_ok:
            if 'validation_diagnostics' in node.outputs:
                self.out(f'diagnostics.atom_{self.ctx.pending[self.ctx.index]:04d}', node.outputs.validation_diagnostics)
                self.report(node.outputs.validation_diagnostics.get_dict()['reason'])
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
