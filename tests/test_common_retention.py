"""Common-orbital preparation/inspection never retrieves full electronic files."""

import io
import logging
from types import SimpleNamespace

import pytest
from aiida import orm
from aiida.common import AttributeDict
from aiida.common.folders import SandboxFolder
from aiida.engine import ExitCode
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import common_orbitals, native_logs, orbital_inspection
from aiida_empa_orca.scripts import compact_orbitals
from aiidalab_orca import casci_services
from test_reference import electronic_source  # noqa: F401
from test_casci import common_reference  # noqa: F401
from test_orbital_inspection import catalog_builder, catalog_node

NATIVE = '''MaxIter==0 has been chosen - skipping the SCF
Guess MOs are being read from file: reference.gbw
Input Geometry matches current geometry
Input basis set matches current basis set
Number of basis functions ... 28
Number of Electrons NEL ... 15
Quasi-Restricted Orbitals were saved in aiida.qro
ORCA TERMINATED NORMALLY
'''


@pytest.mark.parametrize('late', ['', 'SCF CONVERGED AFTER 2 CYCLES\n'])
def test_full_and_compact_logs_obey_the_same_native_parser(electronic_source, tmp_path, late):  # noqa: F811
    uid, path = electronic_source()
    source = orm.load_node(uid)
    (path / 'aiida.qro').write_bytes(b'preserved QRO')
    raw = tmp_path / 'native_output'
    raw.mkdir()
    text = NATIVE + 'irrelevant native output\n' * 100000 + late
    (raw / 'aiida.out').write_text(text)
    native_logs.collect_output({'protocol':'common-orbitals-v1','policy':{'mode':'remote','maxsizeoutput':0}}, tmp_path)
    compact = (tmp_path / 'aiida_summary.out').read_text()
    assert len(compact) < 2000
    results = []
    for content in (text, compact):
        retrieved = orm.FolderData()
        retrieved.base.repository.put_object_from_filelike(io.StringIO(content), 'aiida.out')
        out = {}
        fake = SimpleNamespace(retrieved=retrieved, logger=logging.getLogger(__name__),
            exit_codes=SimpleNamespace(ERROR_REFERENCE=ExitCode(310)), out=lambda k,v:out.update({k:v}),
            node=SimpleNamespace(inputs=AttributeDict({'settings':source.inputs.settings,
                'structure':source.inputs.structure, 'source_retrieved':source.outputs.retrieved}),
                outputs=AttributeDict({'remote_folder':source.outputs.remote_folder}), computer=source.inputs.code.computer))
        status = common_orbitals.CommonOrbitalsParser.parse(fake)
        results.append((status.status if status else 0, out.get('orbital_reference').get_dict() if out else None))
    assert results[0] == results[1]
    assert results[0][0] == (310 if late else 0)


@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_preparation_uses_the_reviewed_retention(electronic_source, monkeypatch, aiida_manager, mode):  # noqa: F811
    uid, _ = electronic_source()
    source = orm.load_node(uid)
    monkeypatch.setattr(casci_services, 'helper_code', lambda _:str(source.inputs.code.uuid))
    policy = {'mode':mode,'stash_directory':'/chosen/stash'}
    b = casci_services.common_builder(uid, force=True, native_output_policy=policy)
    parent = instantiate_process(aiida_manager.get_runner(), b)
    captured = []
    parent.submit = lambda child:captured.append(child) or orm.CalcJobNode().store()
    try:
        assert parent.setup() is None
        assert parent.should_stash() == (mode == 'stash')
        parent.prepare()
        child = instantiate_process(aiida_manager.get_runner(), captured[0])
        try:
            with SandboxFolder() as folder:
                info = child.prepare_for_submission(folder)
                assert info.codes_info[0].cmdline_params == ['aiida.inp']
                assert info.codes_info[0].stdout_name == 'native_output/aiida.out'
                assert info.codes_info[1].cmdline_params == ['compact_output.py']
                assert 'native_output.json' in info.retrieve_list
                assert not any(name.endswith(('.gbw','.qro','.uno','.property.txt')) for name in info.retrieve_list)
                with folder.open('aiida.inp') as h:
                    text = h.read()
                assert 'NoIter' in text and '%moinp "reference.gbw"' in text and 'MaxIter 0' in text
        finally:
            child.close()
    finally:
        parent.close()


@pytest.mark.parametrize('mode', ['remote','stash'])
def test_catalog_cannot_apply_a_legacy_retrieval_threshold(common_reference, aiida_manager, mode):  # noqa: F811
    b = catalog_builder(common_reference)
    b.retention_policy = orm.Dict(dict={'mode':mode,'stash_directory':'/chosen/stash'})
    process = instantiate_process(aiida_manager.get_runner(), b)
    captured = []
    process.submit = lambda child:captured.append(child) or orm.CalcJobNode().store()
    try:
        assert process.setup() is None
        process.preserve()
        assert len(captured) == (1 if mode == 'stash' else 0)
        if captured:
            assert captured[0].policy.get_dict() == {'threshold_mb':0,'stash_directory':'/chosen/stash'}
    finally:
        process.close()


def test_metadata_budget_preserves_source_instead_of_writing_a_large_document(monkeypatch):
    monkeypatch.setattr(compact_orbitals, 'METADATA_LIMIT', 100)
    with pytest.raises(ValueError, match='budget'):
        compact_orbitals.compact_json(io.StringIO('{"large retained field":"' + 'X'*200 + '"}'))


@pytest.mark.parametrize('mode', ['remote','stash'])
def test_cube_previews_do_not_override_the_orbital_retention(common_reference, aiida_manager, mode):  # noqa: F811
    ref, remote, code, _ = common_reference
    b = orbital_inspection.CommonOrbitalCubesWorkChain.get_builder()
    b.orbital_reference, b.source_remote = orm.load_node(ref), orm.load_node(remote)
    b.catalog, b.orbital_kind = catalog_node(common_reference), orm.Str('QRO')
    b.storage_code = b.plot_code = b.cubehandler_code = orm.load_code(code)
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/legacy'})
    b.orbital_retention_policy = orm.Dict(dict={'mode':mode,'stash_directory':'/chosen/stash'})
    b.parameters = orm.Dict(dict={'orbitals':[[0,7]],'retention':'leave'})
    p = instantiate_process(aiida_manager.get_runner(), b)
    captured = []
    p.submit = lambda child:captured.append(child) or orm.CalcJobNode().store()
    try:
        assert p.setup() is None
        p.preserve()
        assert len(captured) == (1 if mode == 'stash' else 0)
        if captured:
            assert captured[0].policy.get_dict()['threshold_mb'] == 0
    finally:
        p.close()


def test_preparation_retention_edits_require_a_new_review(monkeypatch):
    from aiidalab_orca.casci import CasciStates
    from test_result_navigation import reference_data
    monkeypatch.setattr(casci_services, 'reference_runs', lambda _:[])
    monkeypatch.setattr(casci_services, 'prepare_common', lambda uid, force, **kw:{
        'action':'prepare','kind':'QRO','unavailable':[],'pdos':{'ready':True},**kw})
    panel = CasciStates(reference_data())
    try:
        panel.prepare.click()
        assert panel.plan is not None and not panel.common_submit.disabled
        panel.common_full_files.mode.value = 'stash'
        assert panel.plan is None and panel.common_submit.disabled
    finally:
        panel.close()
