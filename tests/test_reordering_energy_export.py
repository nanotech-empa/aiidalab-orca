"""Reordered-reference export construction and staging; no native execution."""

import hashlib
from pathlib import Path
import runpy

import pytest
from aiida import orm
from aiida.common import CodeRunMode, LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import common_orbitals, orbital_reordering
from aiida_empa_orca import orbital_reordering_job as reordering
from aiida_empa_orca.energy import EnergyExportWorkChain, EnergyHamiltonianCalculation
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401


@pytest.fixture
def reordered_reference(common_reference, tmp_path):
    uid, _, code_uid, source_root = common_reference
    source, code = orm.load_node(uid), orm.load_code(code_uid)
    original = source.get_dict()
    plan = orbital_reordering.selection_plan(original,
        {'electrons': 3, 'orbitals': [5, 7, 9]}, [2]*7+[1]+[0]*20,
        source_reference_uuid=uid,
        source_file_sha256=hashlib.sha256((source_root/'aiida.qro').read_bytes()).hexdigest())
    root = tmp_path/'reordered'; root.mkdir()
    data = b'synthetic reordered GBW bytes, never a native wavefunction'
    (root/'aiida.gbw').write_bytes(data)
    record = {'schema': orbital_reordering.SCHEMA, 'plan': plan,
        'source_file_sha256': plan['source_file_sha256'],
        'prepared_file_sha256': hashlib.sha256(data).hexdigest(),
        'prepared_size_bytes': len(data),
        'checks': {'array_checks_passed': True, 'native_readback_qualified': False,
                   'plan_sha256': plan['plan_sha256']}}
    native = orm.CalcJobNode(computer=code.computer, process_type=reordering.CALCULATION)
    for name, value in [('code', code), ('orbital_reference', source), ('plan', orm.Dict(dict=plan))]:
        if not value.is_stored:
            value.store()
        native.base.links.add_incoming(value, link_type=LinkType.INPUT_CALC, link_label=name)
    native.store()
    remote = orm.RemoteData(computer=code.computer, remote_path=str(root))
    reference = orm.Dict(dict=original | {'preparation': reordering.PREPARATION,
        'filename': 'aiida.gbw', 'orbital_mapping': record,
        'parent_orbital_reference_uuid': uid, 'reordered_active_space': plan['native_active_space']})
    for name, value in [('remote_folder', remote), ('orbital_reference', reference),
                         ('orbital_mapping', orm.Dict(dict=record))]:
        value.base.links.add_incoming(native, link_type=LinkType.CREATE, link_label=name)
        value.store()
    native.set_process_state(ProcessState.FINISHED); native.set_exit_status(0)
    return reference, remote, code, root


def export_builder(reference, remote, code):
    b = EnergyHamiltonianCalculation.get_builder()
    b.code = b.compact_code = code
    b.orbital_reference = reference
    b.structure = orm.load_node(reference.get_dict()['structure_uuid'])
    b.active_space = orm.Dict(dict=reference.get_dict()['reordered_active_space'])
    b.settings = orm.Dict(dict={'nroots': 1, 'multiplicity': 2, 'nprocs': 2,
                                'memory_mb': 2048, 'wallclock_seconds': 600})
    b.source_folder, b.source_filename = remote, orm.Str('aiida.gbw')
    b.native_output_policy = orm.Dict(dict={'mode': 'remote', 'maxsizeoutput': 5*1024**2})
    b.metadata.options = common_orbitals.options(b.settings.get_dict())
    return b


@pytest.mark.parametrize('location', ['remote', 'repository'])
def test_reordered_export_inherits_single_hash_guard_before_native(
        reordered_reference, aiida_manager, tmp_path, monkeypatch, location):
    reference, remote, code, root = reordered_reference
    b = export_builder(reference, remote, code)
    if location == 'repository':
        repository = orm.FolderData()
        repository.base.repository.put_object_from_file(str(root/'aiida.gbw'), 'electronic/aiida.gbw')
        b.source_repository = repository
        del b['source_folder']
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            assert info.codes_run_mode == CodeRunMode.SERIAL
            assert [c.cmdline_params for c in info.codes_info] == [
                ['verify_reordering.py'], ['aiida.inp'], ['compact_output.py']]
            assert all(not c.withmpi for c in info.codes_info)
            copies = info.remote_copy_list if location == 'remote' else info.local_copy_list
            assert len(copies) == 1 and copies[0][2] == 'unchecked_reference.gbw'
            assert 'verify_reordering.log' in info.retrieve_list
            assert not any(name.endswith(('.gbw', '.fcidump')) for name in info.retrieve_list)
            text = Path(folder.abspath, 'aiida.inp').read_text()
            assert 'DumpActInts true' in text and '{2 1 0}' in text and 'nroots 1' in text
            assert 'MOREAD NoIter' in text and 'maxiter 1' in text
            assert all(f'{space}Orbs unchanged' in text for space in ('Act', 'Int', 'Ext'))
            assert process.node.get_option('max_memory_kb') == 2097152
            assert process.node.get_option('max_wallclock_seconds') == 600
            assert process.node.get_option('resources')['num_mpiprocs_per_machine'] == 2
            # A failed helper launcher must leave ORCA's moinp unavailable.
            work = tmp_path/'staged'; work.mkdir(); monkeypatch.chdir(work)
            Path('unchecked_reference.gbw').write_bytes((root/'aiida.gbw').read_bytes())
            assert not Path('reference.gbw').exists()  # No helper has started.
            script = Path(folder.abspath, 'verify_reordering.py')
            Path('unchecked_reference.gbw').write_bytes(b'wrong source bytes')
            with pytest.raises(ValueError, match='checksum changed'):
                runpy.run_path(str(script))
            assert not Path('reference.gbw').exists()
            Path('unchecked_reference.gbw').write_bytes((root/'aiida.gbw').read_bytes())
            runpy.run_path(str(script))
            assert hashlib.sha256(Path('reference.gbw').read_bytes()).hexdigest() == (
                reference.get_dict()['orbital_mapping']['prepared_file_sha256'])
    finally:
        process.close()


@pytest.mark.parametrize('failure', ['wrong_code', 'unfinished_producer'])
def test_reordered_export_rejects_wrong_code_or_unfinished_source(
        reordered_reference, aiida_manager, failure):
    reference, remote, code, _ = reordered_reference
    b = export_builder(reference, remote, code)
    if failure == 'wrong_code':
        b.code = orm.InstalledCode(computer=code.computer, filepath_executable='/not/run/wrong-orca').store()
    else:
        reference.creator.set_process_state(ProcessState.RUNNING)
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder, pytest.raises(ValueError):
            process.prepare_for_submission(folder)
    finally:
        process.close()


def test_export_parent_preserves_reordered_identity_and_reviewed_allocation(
        reordered_reference, aiida_manager, entry_points, monkeypatch):
    entry_points.add(EnergyHamiltonianCalculation, 'aiida.calculations:empa_orca.energy_hamiltonian')
    reference, remote, code, _ = reordered_reference
    code.base.extras.set('quantum_energy_tools', {'protocol': 'quantum-energy/v1',
        'commands': ['validate'], 'source_sha256': '0'*64, 'versions': {}})
    b = EnergyExportWorkChain.get_builder()
    b.orbital_reference, b.source_remote = reference, remote
    b.orca_code = b.worker_code = b.compact_code = code
    b.active_space = orm.Dict(dict=reference.get_dict()['reordered_active_space'])
    b.settings = orm.Dict(dict={'nroots': 1, 'multiplicity': 2, 'nprocs': 2,
                                'memory_mb': 2048, 'wallclock_seconds': 600})
    b.native_output_policy = orm.Dict(dict={'mode': 'remote', 'maxsizeoutput': 5*1024**2})
    process = instantiate_process(aiida_manager.get_runner(), b)
    captured = []
    monkeypatch.setattr(process, 'submit', lambda child: captured.append(child) or orm.CalcJobNode().store())
    try:
        process.export()
        assert len(captured) == 1
        child = captured[0]
        assert child.orbital_reference.uuid == reference.uuid
        assert child.source_folder.uuid == remote.uuid
        assert child.code.uuid == code.uuid
        assert child.active_space.get_dict() == reference.get_dict()['reordered_active_space']
        assert child.metadata.options.max_memory_kb == 2097152
        assert child.metadata.options.max_wallclock_seconds == 600
        assert child.metadata.options.resources['num_mpiprocs_per_machine'] == 2
        assert child.metadata.disable_cache
        assert child.native_output_policy.get_dict() == b.native_output_policy.get_dict()
    finally:
        process.close()
