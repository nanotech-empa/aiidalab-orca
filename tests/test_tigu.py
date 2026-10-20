"""Queued execution and explicit in-place electronic files, on disposable storage."""
import hashlib
import json
from pathlib import Path

import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca import artifacts, reference
from aiida_empa_orca.scripts import store_electronic
from aiida_empa_orca.protocols import protocol_settings
from test_reference import electronic_source


def test_remote_policy_never_copies_retrieves_or_stashes(electronic_source, aiida_manager, tmp_path, monkeypatch):
    uuid, original = electronic_source()
    source = orm.load_node(uuid)
    policy = artifacts.storage_policy({'mode': 'remote'})
    builder = artifacts.storage_builder(source.outputs.remote_folder, source.inputs.code, policy)
    process = instantiate_process(aiida_manager.get_runner(), builder)
    work = tmp_path/'manifest'
    work.mkdir()
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            request = json.loads(Path(folder.get_abs_path('request.json')).read_text())
            assert request['storage'] == 'remote'
            assert not process.node.get_option('stash')
            assert info.retrieve_list == ['manifest.json', 'storage.log']
            assert info.remote_symlink_list[0][1] == str(original)
    finally:
        process.close()
    (work/'source').symlink_to(original, target_is_directory=True)
    (work/'request.json').write_text(json.dumps(request))
    monkeypatch.chdir(work)
    store_electronic.main()
    assert not (work/'electronic').exists()
    manifest = json.loads((work/'manifest.json').read_text())
    assert manifest['storage'] == 'remote'
    for item in manifest['files']:
        data = (original/item['name']).read_bytes()
        assert item['sha256'] == hashlib.sha256(data).hexdigest()
    calc = orm.CalcJobNode(process_type=artifacts.STORAGE_PROCESS)
    for name, node in {'source_folder': source.outputs.remote_folder, 'policy': orm.Dict(dict=policy).store()}.items():
        calc.base.links.add_incoming(node, link_type=LinkType.INPUT_CALC, link_label=name)
    calc.store()
    retrieved = orm.FolderData()
    with (work/'manifest.json').open('rb') as handle:
        retrieved.base.repository.put_object_from_filelike(handle, 'manifest.json')
    for name, node in {'retrieved': retrieved, 'manifest': orm.Dict(dict=manifest)}.items():
        node.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label=name)
        node.store()
    calc.set_process_state(ProcessState.FINISHED)
    calc.set_exit_status(0)
    location = artifacts.resolve_electronic(source.outputs.remote_folder)
    assert location['kind'] == 'remote'
    assert location['uuid'] == str(source.outputs.remote_folder.uuid)
    b = reference.get_reference_builder(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code)
    b.storage_policy, b.storage_code = orm.Dict(dict=policy), source.inputs.code
    outputs, reused = run_get_node(b)
    assert reused.is_finished_ok and not reused.called_descendants
    assert outputs['electronic_remote'].uuid == source.outputs.remote_folder.uuid
    assert 'electronic_repository' not in outputs and 'electronic_stash' not in outputs
    (original/'aiida.gbw').unlink()
    with pytest.raises(FileNotFoundError):
        artifacts.resolve_electronic(source.outputs.remote_folder)
    assert reference.plan_reference(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code)['action'] == 'compute'


def test_slurm_reference_uses_requested_single_node_allocation(aiida_profile_clean, aiida_manager):
    from aiidalab_orca.services import codes
    computer = orm.Computer(label='tigu-test', hostname='test.invalid', transport_type='core.ssh', scheduler_type='core.slurm', workdir='/scratch/{username}/aiida').store()
    code = orm.InstalledCode(label='orca', computer=computer, filepath_executable='/opt/orca/orca', default_calc_job_plugin='orca.orca', with_mpi=False).store()
    assert ('orca@tigu-test', str(code.uuid)) in codes()
    structure = orm.StructureData(ase=Atoms('NO', positions=[[0,0,0],[0,0,1.16]]))
    settings = protocol_settings(overrides={'nprocs':12,'memory_mb':24576,'wallclock_seconds':14400})
    b = reference.get_reference_builder(structure, settings, code, force_recompute=True)
    process = instantiate_process(aiida_manager.get_runner(), b)
    captured = []
    try:
        assert process.setup() is None
        process.submit = lambda child: captured.append(child) or orm.WorkChainNode().store()
        process.run_scf()
        options = captured[0].orca.metadata.options
        assert options.resources == {'num_machines':1,'num_mpiprocs_per_machine':12}
        assert not options.withmpi
        assert options.max_memory_kb == 24576*1024
        assert options.max_wallclock_seconds == 14400
        assert captured[0].orca.parameters.get_dict()['input_blocks']['pal']['nprocs'] == 12
        assert 'Opt' not in captured[0].orca.parameters.get_dict()['input_keywords']
    finally:
        process.close()


def test_remote_storage_controls_and_invalid_modes(aiida_profile_clean, aiida_localhost):
    from aiidalab_orca.storage import WavefunctionStorage
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true', default_calc_job_plugin='empa_orca.electronic_storage').store()
    widget = WavefunctionStorage()
    try:
        widget.mode.value = 'remote'
        assert widget.threshold.layout.display == 'none'
        policy = widget.values(code.uuid)['policy']
        assert policy['mode'] == 'remote' and policy['stash_directory'] == ''
        widget.mode.value = 'auto'
        assert widget.threshold.layout.display == ''
        assert 'mode' not in widget.values(code.uuid)['policy']
    finally:
        widget.close()
    with pytest.raises(ValueError, match='automatic preservation'):
        artifacts.storage_policy({'mode':'delete'})
