"""Native Block2 DMRG-CI on a preserved restricted-orbital FCIDUMP.

Block2 owns the numerical algorithm. This adapter renders its public input
format, preserves MPS checkpoints and reports sweep convergence separately
from convergence with respect to the MPS bond dimension.
"""
import hashlib
import io
import math
import re
import json
from pathlib import PurePosixPath
import numpy as np
from aiida import common, engine, orm
from aiida.parsers import Parser
from .energy_storage import hamiltonian_identity, hamiltonian_location, stage_hamiltonian
from .dmrg_storage import (ARRAY_LIMIT, VERIFY_SCRIPT, checkpoint_manifest, collector_script,
                           compact_arrays, validate_checkpoint, validate_manifest)


def file_sha256(node):
    if isinstance(node, orm.Dict):
        return hamiltonian_identity(node)
    value = hashlib.sha256()
    with node.open(mode='rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            value.update(block)
    return value.hexdigest()


def header_parameters(text):
    head = re.split(r'&END|/', text, maxsplit=1, flags=re.I)[0]
    values = {}
    for key in ['NORB', 'NELEC', 'MS2']:
        match = re.search(r'\b' + key + r'\s*=\s*(-?\d+)', head, re.I)
        if not match:
            raise ValueError('FCIDUMP requires NORB, NELEC and MS2')
        values[key] = int(match.group(1))
    if not 3 <= values['NORB'] <= 64 or not 0 < values['NELEC'] <= 2 * values['NORB']:
        raise ValueError('Unsupported active space')
    if values['MS2'] != 0 or values['NELEC'] % 2:
        raise ValueError('This recipe currently targets even-electron singlets')
    symmetry = re.search(r'\bORBSYM\s*=\s*(.*?)(?:\bISYM|&END|$)', head, re.S | re.I)
    if symmetry and any(int(v) != 1 for v in re.findall(r'\d+', symmetry.group(1))):
        raise ValueError('This initial DMRG recipe requires trivial orbital symmetry')
    return values


def hamiltonian_parameters(data, native_export=None):
    """Use the checked native export for remote files, without retrieving integrals."""
    if isinstance(data, orm.SinglefileData):
        with data.open() as stream:
            return header_parameters(stream.read(16384))
    hamiltonian_location(data)  # Verify the immutable producer and file manifest.
    producer = data.creator
    if (native_export is None or native_export.creator is None
            or native_export.creator.uuid != producer.uuid):
        raise ValueError('Use the Hamiltonian and manifest from the same native export')
    record = native_export.get_dict()
    if record['hamiltonian_sha256'] != hamiltonian_identity(data):
        raise ValueError('Hamiltonian and native export manifest differ')
    space = record['active_space']
    # Export already verified the portable spin header and unchanged integrals.
    # The same singlet/size validation applies to repository and remote inputs.
    return header_parameters(f'&FCI NORB={len(space["orbitals"])}, '
        f'NELEC={space["electrons"]}, MS2={record["multiplicity"] - 1}, &END')


def dmrg_input(parameters, settings, parent_bond=None, continue_sweeps=False):
    fields = {'nroots', 'max_bond_dimension', 'threads', 'memory_gb', 'max_sweeps',
              'ordering', 'sweep_tolerance', 'davidson_tolerance'}
    if set(settings) != fields:
        raise ValueError('Specify the complete supported DMRG settings')
    for key, low, high in [('nroots', 1, 3), ('max_bond_dimension', 32, 8192),
                           ('threads', 1, 46), ('memory_gb', 1, 128), ('max_sweeps', 32, 100)]:
        if type(settings[key]) is not int or not low <= settings[key] <= high:
            raise ValueError('Invalid DMRG setting: ' + key)
    for key in ['sweep_tolerance', 'davidson_tolerance']:
        if type(settings[key]) not in [float, int] or not math.isfinite(settings[key]) or not 1e-12 <= settings[key] <= 1e-7:
            raise ValueError('Invalid DMRG tolerance')
    if settings['ordering'] not in ['none', 'fiedler']:
        raise ValueError('Specify none or fiedler ordering')
    maximum = settings['max_bond_dimension']
    tolerance = settings['davidson_tolerance']
    rows = [(0, min(64, maximum), 1e-6, 1e-4),
            (4, min(max(64, maximum // 2), maximum), 1e-7, 1e-5),
            (8, maximum, 1e-8, 1e-5), (12, maximum, tolerance, 1e-6),
            (16, maximum, tolerance, 0)]
    if parent_bond is not None:
        if type(parent_bond) is not int or not 32 <= parent_bond <= maximum:
            raise ValueError('Restart must retain or increase the parent bond dimension')
        rows = [(0, parent_bond, 1e-7, 1e-5),
                (4, (parent_bond + maximum) // 2, 1e-8, 1e-6),
                (8, maximum, tolerance, 1e-6),
                (12, maximum, tolerance, 1e-7), (16, maximum, tolerance, 0)]
    if continue_sweeps:
        if parent_bond != maximum:
            raise ValueError('Sweep continuation requires a checkpoint at the same bond dimension')
        rows = [(0, maximum, tolerance, 0)]
    lines = ['sym c1', 'orbitals hamiltonian.fcidump', f'nelec {parameters["NELEC"]}',
             'spin 0', 'irrep 1', f'nroots {settings["nroots"]}',
             'prefix scratch', 'mps_dir mps', f'mem {settings["memory_gb"]} g',
             f'num_thrds {settings["threads"]}', 'mkl_thrds 1',
             'noreorder' if settings['ordering'] == 'none' else 'fiedler',
             'integral_tol 0', 'integral_rescale none',
             'onedot' if continue_sweeps else 'twodot_to_onedot 24', 'schedule']
    if settings['nroots'] > 1:
        lines.insert(6, 'weights ' + ' '.join([str(1 / settings['nroots'])] * settings['nroots']))
    lines += [f'{sweep} {bond} {dav:.12g} {noise:.12g}' for sweep, bond, dav, noise in rows]
    # The two-site phase always completes before the native one-site stop.
    # A single root can use energy stopping; balanced roots are checked
    # independently after their complete requested schedule.
    stopping = settings['sweep_tolerance'] if settings['nroots'] == 1 else 0
    lines += ['end', f'maxiter {settings["max_sweeps"]}',
              f'sweep_tol {stopping:.12g}', 'oh', 'onepdm', 'outputlevel 2']
    if parent_bond is not None:
        lines.append('fullrestart')
    return '\n'.join(lines) + '\n'


def summarize_dmrg(energies, bonds, discarded, expectation, densities, settings, nelec, continue_sweeps=False):
    energies = np.asarray(energies, dtype=float)
    bonds = np.asarray(bonds, dtype=int)
    discarded = np.asarray(discarded, dtype=float)
    expectation = np.atleast_1d(expectation).astype(float)
    nroots = settings['nroots']
    minimum = 2 if continue_sweeps else 25
    complete = minimum <= len(energies) <= settings['max_sweeps'] if nroots == 1 else len(energies) == settings['max_sweeps']
    if (energies.ndim != 2 or energies.shape[1] != nroots or not complete or
            len(bonds) != len(energies) or len(discarded) != len(energies) or
            expectation.shape != (nroots,) or not np.isfinite(energies).all() or
            not np.isfinite(expectation).all() or not np.isfinite(discarded).all() or
            (discarded < 0).any() or np.any(np.diff(expectation) < -1e-8)):
        raise ValueError('Incomplete or invalid native DMRG results')
    if not np.all(bonds[-2:] == settings['max_bond_dimension']):
        raise ValueError('Target bond dimension was not reached')
    if continue_sweeps and not np.all(bonds == settings['max_bond_dimension']):
        raise ValueError('A fixed-M continuation changed bond dimension')
    delta = float(np.max(np.abs(energies[-1] - energies[-2])))
    discrepancy = float(np.max(np.abs(expectation - energies[-1])))
    density_checks = []
    if len(densities) != nroots:
        raise ValueError('Missing root densities')
    for density in densities:
        density = np.asarray(density)
        if density.ndim != 3 or density.shape[0] != 2 or density.shape[1] != density.shape[2]:
            raise ValueError('Unexpected native one-particle density format')
        spatial = density.sum(axis=0)
        values = np.linalg.eigvalsh(spatial)
        trace = float(np.trace(spatial))
        if (not np.isfinite(density).all() or abs(trace - nelec) > 1e-7 or
                np.max(np.abs(spatial - spatial.T)) > 1e-8 or
                values.min() < -1e-7 or values.max() > 2 + 1e-7):
            raise ValueError('Root density failed normalization or occupation checks')
        density_checks.append({'trace': trace, 'natural_occupations': values[::-1].tolist()})
    return {'energies_hartree': expectation.tolist(),
            'excitation_energies_ev': ((expectation - expectation[0]) * 27.211386245988).tolist(),
            'last_sweep_max_root_energy_change_hartree': delta,
            'expectation_vs_last_sweep_max_difference_hartree': discrepancy,
            'last_two_discarded_weights': discarded[-2:].tolist(),
            'last_two_site_discarded_weights': [] if continue_sweeps else discarded[22:24].tolist(),
            'two_site_to_one_site_at_sweep': None if continue_sweeps else 24,
            'fixed_m_sweep_continuation': bool(continue_sweeps),
            'sweeps_completed': len(energies), 'density_checks': density_checks,
            'sweep_converged': delta <= 10 * settings['sweep_tolerance'] and discrepancy <= 5e-6,
            'bond_dimension_convergence_established': False,
            'full_CAS_computed': False, 'spin_convention': 'Spin-adapted SU(2), S=0',
            'qpu_jobs_submitted': 0}


class DmrgCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('hamiltonian', valid_type=(orm.SinglefileData, orm.Dict))
        spec.input('native_export', valid_type=orm.Dict, required=False)
        spec.input('settings', valid_type=orm.Dict)
        spec.input('parent_states', valid_type=(orm.FolderData, orm.RemoteData), required=False)
        spec.input('continue_sweeps', valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.input('maxsizeoutput', valid_type=orm.Int, default=lambda: orm.Int(5 * 1024**2))
        spec.input('metadata.options.output_filename', valid_type=str, default='dmrg.out')
        spec.input('metadata.options.parser_name', default='empa_orca.dmrg')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('results', valid_type=orm.Dict, required=False)
        spec.exit_code(310, 'ERROR_DMRG', message='Native DMRG output is missing or invalid.')
        spec.exit_code(311, 'ERROR_SWEEP_CONVERGENCE', message='DMRG sweeps need further convergence; checkpoints preserved.')

    def prepare_for_submission(self, folder):
        if PurePosixPath(str(self.inputs.code.filepath_executable)).name != 'block2main':
            raise ValueError('Select the installed Block2 block2main executable')
        if self.inputs.code.base.extras.get('block2', {}).get('version') != '0.5.4':
            raise ValueError('Select the verified Block2 deployment')
        parameters = hamiltonian_parameters(self.inputs.hamiltonian, self.inputs.get('native_export'))
        continuation = self.inputs.continue_sweeps.value
        parent_bond = None
        if 'parent_states' in self.inputs:
            parent_bond = validate_checkpoint(self.inputs.parent_states, self.inputs.code,
                self.inputs.settings.get_dict(), file_sha256(self.inputs.hamiltonian), continuation=continuation)
            with folder.open('parent-mps.sha256', 'w') as stream:
                stream.write(checkpoint_manifest(self.inputs.parent_states))
            with folder.open('dmrg-verify.sh', 'w') as stream:
                stream.write(VERIFY_SCRIPT)
        with folder.open('dmrg.conf', 'w') as stream:
            stream.write(dmrg_input(parameters, self.inputs.settings.get_dict(), parent_bond, continuation))
        from pathlib import Path
        with folder.open('input-adapter.json', 'w') as stream:
            json.dump({'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       'fixed_m_sweep_continuation': continuation}, stream)
        with folder.open('dmrg-collect.sh', 'w') as stream:
            stream.write(collector_script(self.inputs.settings.get_dict()['nroots'], self.inputs.maxsizeoutput.value))
        info = common.CalcInfo()
        info.local_copy_list = []
        stage_hamiltonian(info, self.inputs.hamiltonian, self.inputs.code.computer, folder)
        if 'parent_states' in self.inputs:
            info.prepend_text = 'sh dmrg-verify.sh || exit 1'
            states = self.inputs.parent_states
            if isinstance(states, orm.RemoteData):
                info.remote_copy_list = (info.remote_copy_list or []) + [(str(states.computer.uuid),
                    str(PurePosixPath(states.get_remote_path()) / 'mps'), 'mps')]
            else:
                info.local_copy_list.append((states.uuid, 'mps', 'mps'))
        if isinstance(self.inputs.hamiltonian, orm.Dict):
            with folder.open('hamiltonian.sha256', 'w') as stream:
                stream.write(file_sha256(self.inputs.hamiltonian) + '  hamiltonian.fcidump\n')
            verify = ('if command -v sha256sum >/dev/null 2>&1; then '
                      'sha256sum -c hamiltonian.sha256; else '
                      'shasum -a 256 -c hamiltonian.sha256; fi || exit 1')
            info.prepend_text = verify + '\n' + (info.prepend_text or '')
        code = common.CodeInfo()
        code.code_uuid = self.inputs.code.uuid
        code.cmdline_params = ['dmrg.conf']
        code.stdout_name = 'dmrg.out'
        code.join_files = True
        info.codes_info = [code]
        # No recursive MPS or raw-output retrieval, even after native failure.
        files = ('dmrg.out', 'dmrg_summary.out', 'dmrg-storage.json', 'mps.sha256') + compact_arrays(self.inputs.settings.get_dict()['nroots'])
        info.retrieve_list = [('compact/' + name, '.', 1) for name in files]
        info.append_text = 'sh dmrg-collect.sh "$?"'
        return info


class DmrgParser(Parser):
    def parse(self, **kwargs):
        try:
            repository = self.retrieved.base.repository
            log = repository.get_object_content('dmrg.out')
            modern = 'dmrg-storage.json' in repository.list_object_names()
            storage = json.loads(repository.get_object_content('dmrg-storage.json')) if modern else {}
            if (modern and (storage.get('schema_version') != 1 or storage.get('native_exit_status') != 0
                    or storage.get('traceback') is not False or storage.get('spin_adapted') is not True)):
                raise ValueError('Native DMRG or its compact collector failed')
            if not modern and ('Traceback' in log or 'SPIN ADAPTED - REAL DOMAIN - DOUBLE PREC' not in log):
                raise ValueError('Native Block2 execution failed')
            def read(name):
                content = repository.get_object_content(('' if modern else 'mps/') + name, mode='rb')
                if len(content) > ARRAY_LIMIT:
                    raise ValueError('Unexpected oversized compact DMRG array')
                return np.load(io.BytesIO(content), allow_pickle=False)
            settings = self.node.inputs.settings.get_dict()
            parameters = hamiltonian_parameters(self.node.inputs.hamiltonian, self.node.inputs.native_export if 'native_export' in self.node.inputs else None)
            densities = [read('1pdm.npy' if settings['nroots'] == 1 else f'1pdm-{i}-{i}.npy') for i in range(settings['nroots'])]
            continuation = 'continue_sweeps' in self.node.inputs and self.node.inputs.continue_sweeps.value
            result = summarize_dmrg(read('sweep_energies.npy'), read('bond_dims.npy'), read('discarded_weights.npy'), read('E_oh.npy'), densities, settings, parameters['NELEC'], continuation)
            result['hamiltonian_sha256'] = file_sha256(self.node.inputs.hamiltonian)
            result.update(settings=settings, active_space=parameters,
                          software=self.node.inputs.code.base.extras.get('block2'),
                          checkpoints_preserved_in_retrieved=not modern,
                          checkpoint_storage='remote' if modern else 'retrieved')
            if modern:
                manifest = repository.get_object_content('mps.sha256')
                result['checkpoint_files'] = validate_manifest(manifest)
                result['checkpoint_manifest_sha256'] = hashlib.sha256(manifest.encode()).hexdigest()
                result['checkpoint_remote_folder_uuid'] = str(self.node.outputs.remote_folder.uuid)
                result['native_output'] = storage
                if storage.get('output_is_summary'):
                    self.logger.warning('Output exceeds maxsizeoutput; retrieved dmrg_summary.out and an outputcat notice. Full output and MPS remain remote.')
            if 'input-adapter.json' in self.node.base.repository.list_object_names():
                result['input_adapter'] = json.loads(self.node.base.repository.get_object_content('input-adapter.json'))
            if 'parent_states' in self.node.inputs:
                result['parent_states_uuid'] = str(self.node.inputs.parent_states.uuid)
            self.out('results', orm.Dict(dict=result))
            if not result['sweep_converged']:
                return self.exit_codes.ERROR_SWEEP_CONVERGENCE
        except (KeyError, OSError, ValueError, TypeError):
            self.logger.exception('Native DMRG result validation failed')
            return self.exit_codes.ERROR_DMRG
