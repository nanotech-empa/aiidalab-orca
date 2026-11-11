"""External checkpoints, bounded retrieval, and preservation of native inputs."""

import io
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
from aiida import orm
from aiida.common import AttributeDict, LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process

from aiida_empa_orca.dmrg import DmrgCalculation, DmrgParser, file_sha256
from aiida_empa_orca.dmrg_storage import ARRAY_LIMIT, VERIFY_SCRIPT, collector_script, compact_arrays, validate_manifest
from aiida_empa_orca.dmrg_workchain import DmrgConvergenceWorkChain


def seed_files(folder, roots=1):
    (folder / 'mps').mkdir()
    for name in compact_arrays(roots):
        np.save(folder / 'mps' / name, np.array([1.]))
    (folder / 'mps/mps_info.bin').write_bytes(b'checkpoint-metadata')
    (folder / 'mps/state.bin').write_bytes(b'full-native-wavefunction')
    (folder / 'dmrg.out').write_text('SPIN ADAPTED - REAL DOMAIN - DOUBLE PREC\nNative results\n')


@pytest.mark.parametrize('threshold', [5 * 1024**2, 1, 0])
def test_collector_keeps_native_files_and_never_copies_mps(tmp_path, threshold):
    seed_files(tmp_path)
    original = (tmp_path / 'dmrg.out').read_bytes()
    script = tmp_path / 'collect.sh'
    script.write_text(collector_script(1, threshold))
    subprocess.run(['sh', str(script), '0'], cwd=tmp_path, check=True)
    stored = json.loads((tmp_path / 'compact/dmrg-storage.json').read_text())
    assert stored['checkpoint_storage'] == 'remote'
    assert stored['spin_adapted'] and not stored['traceback']
    assert (tmp_path / 'dmrg.out').read_bytes() == original
    assert not list((tmp_path / 'compact').glob('*.bin'))
    assert not (tmp_path / 'compact/mps').exists()
    if threshold > len(original):
        assert (tmp_path / 'compact/dmrg.out').read_bytes() == original
    else:
        assert stored['output_is_summary']
        assert 'exceeds maxsizeoutput' in (tmp_path / 'compact/dmrg.out').read_text()


def test_native_failure_in_middle_of_long_log_is_retained(tmp_path):
    seed_files(tmp_path)
    (tmp_path / 'dmrg.out').write_text('SPIN ADAPTED - REAL DOMAIN - DOUBLE PREC\n' +
        'step\n' * 100 + 'Traceback: native failure\n' + 'step\n' * 1000)
    script = tmp_path / 'collect.sh'
    script.write_text(collector_script(1, 10))
    subprocess.run(['sh', str(script), '0'], cwd=tmp_path, check=True)
    assert json.loads((tmp_path / 'compact/dmrg-storage.json').read_text())['traceback'] is True


def test_changed_remote_checkpoint_is_rejected_before_native_restart(tmp_path):
    seed_files(tmp_path)
    collector = tmp_path / 'collect.sh'
    collector.write_text(collector_script(1, 5 * 1024**2))
    subprocess.run(['sh', str(collector), '0'], cwd=tmp_path, check=True)
    manifest = (tmp_path / 'compact/mps.sha256').read_text()
    assert validate_manifest(manifest) == len(compact_arrays(1)) + 2
    (tmp_path / 'parent-mps.sha256').write_text(manifest)
    verify = tmp_path / 'verify.sh'; verify.write_text(VERIFY_SCRIPT)
    assert subprocess.run(['sh', str(verify)], cwd=tmp_path, capture_output=True).returncode == 0
    (tmp_path / 'mps/state.bin').write_bytes(b'changed-wavefunction')
    assert subprocess.run(['sh', str(verify)], cwd=tmp_path, capture_output=True).returncode != 0


@pytest.mark.parametrize('manifest', ['', 'x  mps/mps_info.bin\n', 'a' * 64 + '  mps/../outside\n',
    ('a' * 64 + '  mps/mps_info.bin\n') * 2])
def test_invalid_checkpoint_identity_fails(manifest):
    with pytest.raises(ValueError):
        validate_manifest(manifest)


def test_oversized_array_blocks_compact_acceptance(tmp_path):
    seed_files(tmp_path)
    (tmp_path / 'mps/E_oh.npy').write_bytes(b'x' * (ARRAY_LIMIT + 1))
    script = tmp_path / 'collect.sh'
    script.write_text(collector_script(1, 5 * 1024**2))
    assert subprocess.run(['sh', str(script), '0'], cwd=tmp_path).returncode != 0
    assert not (tmp_path / 'compact/dmrg-storage.json').exists()
    assert not (tmp_path / 'compact/E_oh.npy').exists()


def test_remote_checkpoint_is_never_cleaned(monkeypatch):
    node = SimpleNamespace(outputs=AttributeDict({'results': SimpleNamespace(
        get_dict=lambda: {'checkpoint_storage': 'remote'})}))
    from aiida_empa_orca import dmrg_workchain
    monkeypatch.setattr(dmrg_workchain.orm, 'load_node', lambda _: node)
    process = SimpleNamespace(inputs=SimpleNamespace(clean_workdirs=SimpleNamespace(value=True)),
                              ctx=AttributeDict({'cleanup': []}))
    DmrgConvergenceWorkChain.clean(process, 'checkpoint')
    assert process.ctx.cleanup[0]['scratch_cleaned'] is False
    assert 'retained remotely' in process.ctx.cleanup[0]['reason']


def test_restart_copies_only_on_the_same_computer(aiida_profile_clean, aiida_localhost, aiida_manager):
    code = orm.InstalledCode(label='block2-remote', computer=aiida_localhost,
        filepath_executable='/configured/block2main', default_calc_job_plugin='empa_orca.dmrg').store()
    code.base.extras.set('block2', {'version': '0.5.4'})
    h = orm.SinglefileData(file=io.BytesIO(b'&FCI NORB=4, NELEC=4, MS2=0, ORBSYM=1,1,1,1, ISYM=1,\n&END\n'), filename='FCIDUMP').store()
    settings = orm.Dict(dict={'nroots': 1, 'max_bond_dimension': 64, 'threads': 1, 'memory_gb': 1,
        'max_sweeps': 32, 'ordering': 'none', 'sweep_tolerance': 1e-9, 'davidson_tolerance': 1e-10}).store()
    parent = orm.CalcJobNode(computer=aiida_localhost, process_type='aiida.calculations:empa_orca.dmrg')
    for name, value in [('code', code), ('hamiltonian', h), ('settings', settings)]:
        parent.base.links.add_incoming(value, link_type=LinkType.INPUT_CALC, link_label=name)
    parent.store()
    result = orm.Dict(dict={'hamiltonian_sha256': file_sha256(h), 'sweeps_completed': 32,
        'two_site_to_one_site_at_sweep': 24, 'checkpoint_storage': 'remote'})
    result.base.links.add_incoming(parent, link_type=LinkType.CREATE, link_label='results'); result.store()
    remote = orm.RemoteData(computer=aiida_localhost, remote_path='/verified/parent')
    remote.base.links.add_incoming(parent, link_type=LinkType.CREATE, link_label='remote_folder'); remote.store()
    parent.set_process_state(ProcessState.FINISHED); parent.set_exit_status(0)
    saved = orm.FolderData()
    saved.base.repository.put_object_from_filelike(io.BytesIO(b'checkpoint'), 'mps/mps_info.bin')
    saved.base.links.add_incoming(parent, link_type=LinkType.CREATE, link_label='retrieved'); saved.store()
    builder = DmrgCalculation.get_builder()
    builder.code, builder.hamiltonian, builder.settings = code, h, settings
    builder.parent_states, builder.continue_sweeps = remote, orm.Bool(True)
    builder.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    process = instantiate_process(aiida_manager.get_runner(), DmrgCalculation, **builder._inputs())
    with SandboxFolder() as folder:
        info = process.prepare_for_submission(folder)
        assert info.remote_copy_list == [(str(aiida_localhost.uuid), '/verified/parent/mps', 'mps')]
        assert len(info.local_copy_list) == 1  # Hamiltonian only, no checkpoint transfer through the app.
        assert 'onedot\n' in Path(folder.abspath, 'dmrg.conf').read_text()
        assert info.prepend_text == 'sh dmrg-verify.sh || exit 1'
        assert 'mps/mps_info.bin' in Path(folder.abspath, 'parent-mps.sha256').read_text()
    other = orm.Computer(label='other', hostname='other', transport_type='core.local', scheduler_type='core.direct').store()
    foreign_code = orm.InstalledCode(computer=other, filepath_executable='/configured/block2main').store()
    from aiida_empa_orca.dmrg_storage import validate_checkpoint
    with pytest.raises(ValueError, match='calculation computer'):
        validate_checkpoint(remote, foreign_code, settings.get_dict(), file_sha256(h), continuation=True)


def test_compact_parser_accepts_native_arrays_and_records_remote_checkpoint(aiida_profile_clean, aiida_localhost):
    node = orm.CalcJobNode(computer=aiida_localhost, process_type='aiida.calculations:empa_orca.dmrg')
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/configured/block2main').store()
    code.base.extras.set('block2', {'version': '0.5.4'})
    h = orm.SinglefileData(file=io.BytesIO(b'&FCI NORB=4, NELEC=4, MS2=0,\n&END\n'), filename='FCIDUMP').store()
    s = orm.Dict(dict={'nroots': 1, 'max_bond_dimension': 64, 'threads': 1, 'memory_gb': 1,
        'max_sweeps': 32, 'ordering': 'none', 'sweep_tolerance': 1e-9, 'davidson_tolerance': 1e-10}).store()
    for name, value in [('code', code), ('hamiltonian', h), ('settings', s)]:
        node.base.links.add_incoming(value, link_type=LinkType.INPUT_CALC, link_label=name)
    node.store()
    remote = orm.RemoteData(computer=aiida_localhost, remote_path='/verified/native')
    remote.base.links.add_incoming(node, link_type=LinkType.CREATE, link_label='remote_folder'); remote.store()
    retrieved = orm.FolderData()
    repo = retrieved.base.repository
    def put(name, data):
        repo.put_object_from_filelike(io.BytesIO(data), name)
    put('dmrg.out', b'SPIN ADAPTED - REAL DOMAIN - DOUBLE PREC\n')
    put('dmrg-storage.json', json.dumps({'schema_version': 1, 'native_exit_status': 0,
        'traceback': False, 'spin_adapted': True}).encode())
    put('mps.sha256', ('a' * 64 + '  mps/mps_info.bin\n').encode())
    for name, array in {'sweep_energies.npy':np.full((32,1),-1.), 'bond_dims.npy':np.full(32,64),
            'discarded_weights.npy':np.zeros(32), 'E_oh.npy':np.array([-1.]),
            '1pdm.npy':np.array([np.diag([1.,1.,0,0])]*2)}.items():
        stream=io.BytesIO();np.save(stream,array);put(name,stream.getvalue())
    retrieved.base.links.add_incoming(node, link_type=LinkType.CREATE, link_label='retrieved'); retrieved.store()
    parser = DmrgParser(node)
    assert parser.parse() is None
    result = parser.outputs['results'].get_dict()
    assert result['checkpoint_storage']=='remote' and result['checkpoint_remote_folder_uuid']==str(remote.uuid)
    assert result['energies_hartree']==[-1.] and result['sweep_converged']
