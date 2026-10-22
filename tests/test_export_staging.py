"""Use the provenance-linked native log without a server/client round trip."""
import hashlib
import io
import json

import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import dyson
from aiida_empa_orca.artifacts import stash_options
from aiida_empa_orca.reference import ArtifactUnavailable
from aiida_empa_orca.scripts import export_dyson
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401


@pytest.mark.parametrize('available', [True, False])
def test_export_stages_remote_log_or_falls_back_to_immutable_repository(
        common_reference, aiida_manager, monkeypatch, available):
    ref_uuid, _, code_uuid, _ = common_reference
    code = orm.load_code(code_uuid)
    structure = orm.load_node(orm.load_node(ref_uuid).get_dict()['structure_uuid'])
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.casci', computer=code.computer)
    calc.base.links.add_incoming(structure, link_type=LinkType.INPUT_CALC, link_label='structure')
    calc.store()
    state = orm.Dict(dict={'states':[]})
    retrieved = orm.FolderData()
    native_bytes = b'An immutable native CI output with signed coefficients\n'
    retrieved.base.repository.put_object_from_filelike(io.BytesIO(native_bytes), 'aiida.out')
    remote = orm.RemoteData(computer=code.computer, remote_path='/native/casci')
    for label, node in [('state_energies',state), ('retrieved',retrieved), ('remote_folder',remote)]:
        node.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label=label)
        node.store()
    calc.set_process_state(ProcessState.FINISHED); calc.set_exit_status(0)

    def probe(computer, base, names):
        assert computer.uuid == code.computer.uuid and base == '/native/casci'
        assert names == ['aiida.out']
        if not available:
            raise FileNotFoundError('scratch was cleaned')
        return [{'name':'aiida.out', 'size_bytes':len(native_bytes)}]

    monkeypatch.setattr(dyson, 'remote_files', probe)
    b = dyson.StateExportCalculation.get_builder()
    b.code = b.helper_code = code
    b.state_energies, b.source = state, remote
    b.location = orm.Dict(dict={'kind':'remote', 'uuid':str(remote.uuid),
                               'files':[{'name':'aiida.gbw','size_bytes':5}]})
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/test/stash'})
    b.metadata.options.resources = {'num_machines':1,'num_mpiprocs_per_machine':1}
    b.metadata.options.stash = stash_options('/test/stash','exports')
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            request = json.loads(open(folder.get_abs_path('request.json')).read())
            assert request['source_output_sha256'] == hashlib.sha256(native_bytes).hexdigest()
            assert request['state_uuid'] == str(state.uuid)
            if available:
                assert info.local_copy_list == []
                assert (code.computer.uuid, '/native/casci/aiida.out', 'aiida.out') in info.remote_copy_list
            else:
                assert info.local_copy_list == [(retrieved.uuid, 'aiida.out', 'aiida.out')]
                assert not any(row[2]=='aiida.out' for row in info.remote_copy_list)
            assert (code.computer.uuid, '/native/casci/aiida.gbw', 'aiida.gbw') in info.remote_copy_list
    finally:
        process.close()


def test_staging_does_not_treat_unavailable_transport_as_deleted_scratch(monkeypatch):
    from types import SimpleNamespace
    retrieved = SimpleNamespace(base=SimpleNamespace(repository=SimpleNamespace(
        open=lambda *a,**k:io.BytesIO(b'native output'))))
    remote = SimpleNamespace(computer=object(), get_remote_path=lambda:'/native')
    class Outputs(dict):
        __getattr__ = dict.__getitem__
    calc = SimpleNamespace(outputs=Outputs(retrieved=retrieved, remote_folder=remote))
    def unavailable(*args,**kwargs):
        raise ArtifactUnavailable('SSH authentication unavailable')
    monkeypatch.setattr(dyson, 'remote_files', unavailable)
    with pytest.raises(ArtifactUnavailable, match='SSH authentication'):
        dyson.stage_native_output(SimpleNamespace(local_copy_list=[],remote_copy_list=[]), calc)


def test_staged_log_checksum_checked_before_any_wavefunction_or_ci_interpretation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    expected = hashlib.sha256(b'correct output').hexdigest()
    (tmp_path/'aiida.out').write_bytes(b'corrupt output')  # Same length.
    (tmp_path/'request.json').write_text(json.dumps({'source_output_sha256':expected}))
    with pytest.raises(ValueError, match='output checksum'):
        export_dyson.main()
    (tmp_path/'aiida.out').write_bytes(b'correct output')
    assert export_dyson.checked_source_output(tmp_path/'aiida.out', expected) == expected
    assert export_dyson.checked_source_output(tmp_path/'missing', None) is None
