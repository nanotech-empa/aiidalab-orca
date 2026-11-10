"""Job construction, source guards and review semantics; no scientific jobs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import ipywidgets as ipw
import pytest
from aiida import orm
from aiida.common import CodeRunMode
from aiida.common import LinkType
from aiida.engine import ProcessState
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import casci, common_orbitals
from aiida_empa_orca import orbital_reordering as reorder
from aiida_empa_orca import orbital_reordering_job as backend
from aiidalab_orca.reordering import OrbitalReordering
from aiidalab_orca import reordering_services as service
from test_orbital_reordering import spatial_source, plan_for, SOURCE  # noqa: F401
from test_casci import common_reference, reference_data  # noqa: F401
from test_reference import electronic_source  # noqa: F401
from test_l06_resources import completed_common  # noqa: F401
from test_reference_navigation import reference_switch  # noqa: F401

BUDGET = {'memory_mb': 2048, 'wallclock_seconds': 600}


def bound_catalog(ref, remote, root):
    native = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.orbital_catalog')
    native.base.links.add_incoming(ref, link_type=LinkType.INPUT_CALC, link_label='orbital_reference')
    native.store()
    selected = {'filename': 'aiida.qro', 'sha256': hashlib.sha256((root/'aiida.qro').read_bytes()).hexdigest(),
                'levels': [{'index': i, 'occupation': value} for i, value in enumerate([2]*7+[1]+[0]*20)]}
    catalog = orm.Dict(dict={'orbital_reference_uuid': str(ref.uuid), 'source_remote_uuid': str(remote.uuid),
                             'sets': {'QRO': selected}})
    catalog.base.links.add_incoming(native, link_type=LinkType.CREATE, link_label='catalog')
    catalog.store()
    native.set_process_state(ProcessState.FINISHED); native.set_exit_status(0)
    return catalog


def test_submitted_prepare_check_scripts_preserve_source_and_remove_only_temporary_json(spatial_source, tmp_path, monkeypatch):
    ref, doc = spatial_source
    monkeypatch.chdir(tmp_path)
    source = b'synthetic source bytes'
    Path('source.gbw').write_bytes(source)
    Path('source.json').write_text(json.dumps(doc))
    plan = reorder.selection_plan(ref, {'electrons': 3, 'orbitals': [1, 3, 5]},
        [r['Occupancy'] for r in doc['Molecule']['MolecularOrbitals']['MOs']],
        source_reference_uuid=SOURCE, source_file_sha256=hashlib.sha256(source).hexdigest())
    Path('reordering_request.json').write_text(json.dumps({'reference': ref, 'plan': plan}))
    Path('orbital_reordering.py').write_text(Path(reorder.__file__).read_text())
    for stage in ('prepare', 'check'):
        Path(stage+'.py').write_text(backend._script(stage))
    runpy.run_path('prepare.py', run_name='__main__')
    # Simulate the native format roundtrip; this is not native qualification.
    Path('prepared_copy.json').write_bytes(Path('prepared.json').read_bytes())
    Path('prepared_copy.gbw').write_bytes(b'synthetic converted bytes')
    runpy.run_path('check.py', run_name='__main__')
    record = json.loads(Path('reordering.json').read_text())
    assert record['checks']['full_signed_overlap_error'] < 1e-12
    assert record['checks']['native_readback_qualified'] is False
    assert Path('source.gbw').read_bytes() == source
    assert not any(Path(name).exists() for name in ('source.json', 'prepared.json', 'prepared_copy.json'))
    assert hashlib.sha256(Path('aiida.gbw').read_bytes()).hexdigest() == record['prepared_file_sha256']


@pytest.mark.parametrize('failure', ['source_digest', 'unknown_scientific_field'])
def test_failed_prepare_cannot_publish_reference_when_serial_shell_continues(
        spatial_source, tmp_path, monkeypatch, failure):
    ref, doc = deepcopy(spatial_source)
    monkeypatch.chdir(tmp_path)
    source = b'synthetic source bytes'
    Path('source.gbw').write_bytes(source)
    plan = reorder.selection_plan(ref, {'electrons': 3, 'orbitals': [1, 3, 5]},
        [r['Occupancy'] for r in doc['Molecule']['MolecularOrbitals']['MOs']],
        source_reference_uuid=SOURCE, source_file_sha256=hashlib.sha256(source).hexdigest())
    if failure == 'source_digest': Path('source.gbw').write_bytes(b'changed source bytes')
    if failure == 'unknown_scientific_field': doc['Unknown-MO-Density'] = [[1]]
    Path('source.json').write_text(json.dumps(doc))
    Path('reordering_request.json').write_text(json.dumps({'reference': ref, 'plan': plan}))
    Path('orbital_reordering.py').write_text(Path(reorder.__file__).read_text())
    for stage in ('prepare', 'check'):
        Path(stage+'.py').write_text(backend._script(stage))
    with pytest.raises(ValueError):
        runpy.run_path('prepare.py', run_name='__main__')
    assert not Path('prepared.json').exists()
    # The scheduler's SERIAL shell may continue after a helper fails. Without
    # prepared.json the converters cannot produce a GBW/JSON; no native
    # executable is invoked in this synthetic regression.
    with pytest.raises((ValueError, FileNotFoundError)):
        runpy.run_path('check.py', run_name='__main__')
    assert not Path('aiida.gbw').exists()
    assert not Path('reordering.json').exists()
    errors, accepted = [], []
    parser = SimpleNamespace(retrieved=SimpleNamespace(base=SimpleNamespace(repository=SimpleNamespace(
        get_object_content=lambda *a, **kw: Path('reordering.json').read_bytes()))),
        logger=SimpleNamespace(error=errors.append), out=lambda *args: accepted.append(args),
        exit_codes=SimpleNamespace(ERROR_REORDERING='rejected'))
    assert backend.OrbitalReorderingParser.parse(parser) == 'rejected'
    assert errors and accepted == []


def test_native_job_is_serial_bounded_and_keeps_all_electronic_arrays_external(common_reference, aiida_manager, entry_points):
    entry_points.add(backend.OrbitalReorderingCalculation, 'aiida.calculations:empa_orca.orbital_reordering')
    entry_points.add(backend.OrbitalReorderingParser, 'aiida.parsers:empa_orca.orbital_reordering')
    uid, remote_uid, code_uid, root = common_reference
    ref_node, remote, code = orm.load_node(uid), orm.load_node(remote_uid), orm.load_code(code_uid)
    # Existing fixture has 15 electrons / 28 spatial orbitals.
    ref = ref_node.get_dict() | {'kind': 'QRO'}
    bound_ref = ref_node
    plan = reorder.selection_plan(ref, {'electrons': 3, 'orbitals': [5, 7, 9]},
        [2]*7+[1]+[0]*20, source_reference_uuid=str(bound_ref.uuid),
        source_file_sha256=hashlib.sha256((root/'aiida.qro').read_bytes()).hexdigest())
    b = backend.OrbitalReorderingCalculation.get_builder()
    b.code = b.export_code = b.compact_code = code
    b.structure, b.orbital_reference, b.plan = orm.load_node(ref['structure_uuid']), bound_ref, orm.Dict(dict=plan)
    b.source_remote = remote
    b.catalog = bound_catalog(bound_ref, remote, root)
    common_orbitals.attach_orbital(b, {'kind': 'remote', 'uuid': remote_uid}, 'aiida.qro')
    b.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    b.metadata.options.max_memory_kb, b.metadata.options.max_wallclock_seconds = 2097152, 600
    process = instantiate_process(aiida_manager.get_runner(), b)
    with SandboxFolder() as folder:
        info = process.prepare_for_submission(folder)
        assert info.codes_run_mode == CodeRunMode.SERIAL
        assert [c.cmdline_params for c in info.codes_info] == [
            ['source.gbw', '-json'], ['prepare_reordering.py'], ['prepared.json', '-gbw'],
            ['prepared_copy.gbw', '-json'], ['check_reordering.py'], ['compact_output.py']]
        assert all(not c.withmpi for c in info.codes_info)
        assert info.remote_copy_list[0][2] == 'source.gbw'
        assert 'reordering.json' in info.retrieve_list
        assert not any(name.endswith(('.gbw', '.qro')) or name in ('source.json', 'prepared.json', 'prepared_copy.json')
                       for name in info.retrieve_list)
        assert 'NoIter' not in Path(folder.abspath, 'reordering_request.json').read_text()
    assert process.node.get_option('max_memory_kb') == 2097152
    assert process.node.get_option('max_wallclock_seconds') == 600
    process.close()


@pytest.mark.parametrize('producer_type', ['aiida.calculations:empa_orca.common_orbitals',
    'aiida.calculations:empa_orca.casscf', backend.CALCULATION, 'import-calculation'])
def test_unfinished_producers_are_rejected_for_every_reference_type(monkeypatch, producer_type):
    monkeypatch.setattr(casci, 'imported_reference_contract', lambda: SimpleNamespace(
        CALCULATION='import-calculation', PREPARATION='verified-import', PROCESS='import-workchain'))
    producer = SimpleNamespace(process_type=producer_type, is_finished_ok=False,
                               outputs=SimpleNamespace(remote_folder=SimpleNamespace(uuid='folder')))
    ref = SimpleNamespace(creator=producer, get_dict=lambda: {'preparation': 'verified-import'})
    with pytest.raises(ValueError, match='share their preparation'):
        casci.validate_reference(ref, SimpleNamespace(uuid='folder'))


def test_verified_import_keeps_its_marker_and_declared_orca_parent(monkeypatch):
    contract = SimpleNamespace(CALCULATION='import-calculation', PREPARATION='verified-import', PROCESS='import-workchain')
    monkeypatch.setattr(casci, 'imported_reference_contract', lambda: contract)
    remote = SimpleNamespace(uuid='folder')
    producer = SimpleNamespace(process_type=contract.CALCULATION, is_finished_ok=True,
        outputs=SimpleNamespace(remote_folder=remote), inputs=SimpleNamespace(code=SimpleNamespace(uuid='validation-helper')))
    parent = SimpleNamespace(process_type=contract.PROCESS, is_finished_ok=True,
        outputs=SimpleNamespace(remote_folder=remote), inputs=SimpleNamespace(code=SimpleNamespace(uuid='declared-orca')))
    record = {'preparation': contract.PREPARATION}
    ref = SimpleNamespace(creator=producer, get_dict=lambda: record,
        base=SimpleNamespace(links=SimpleNamespace(get_incoming=lambda **kw: SimpleNamespace(
            all=lambda: [SimpleNamespace(node=parent)]))))
    assert casci.validate_reference(ref, remote) == record
    assert casci.reference_orca_code(ref) == 'declared-orca'
    record['preparation'] = 'not-verified'
    with pytest.raises(ValueError, match='frozen-CASCI import'):
        casci.validate_reference(ref, remote)
    parent.is_finished_ok = False
    with pytest.raises(ValueError, match='successful preparation'):
        casci.reference_orca_code(ref)


def test_downstream_staged_file_is_unavailable_on_digest_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    good = b'verified reordered file'
    expected = hashlib.sha256(good).hexdigest()
    inputs = SimpleNamespace(orbital_reference=SimpleNamespace(get_dict=lambda: {
        'preparation': backend.PREPARATION, 'orbital_mapping': {'prepared_file_sha256': expected}}),
        compact_code=SimpleNamespace(uuid='helper'))
    # AttributeDict is the real input access convention.
    from aiida.common import AttributeDict
    inputs = AttributeDict(vars(inputs))
    with SandboxFolder() as folder:
        info = SimpleNamespace(codes_info=[], retrieve_list=[],
                               local_copy_list=[('source', 'aiida.gbw', 'reference.gbw')])
        backend.protect_reordered_input(info, inputs, folder)
        script = Path(folder.abspath, 'verify_reordering.py')
        assert info.local_copy_list[0][2] == 'unchecked_reference.gbw'
        # No helper launched: staging alone must not expose the native moinp.
        Path(info.local_copy_list[0][2]).write_bytes(b'changed file')
        assert not Path('reference.gbw').exists()
        with pytest.raises(ValueError, match='checksum changed'):
            runpy.run_path(str(script))
        assert not Path('reference.gbw').exists()
        Path('unchecked_reference.gbw').write_bytes(good)
        runpy.run_path(str(script))
        assert Path('reference.gbw').read_bytes() == good


@pytest.mark.parametrize('kind', ['local_copy_list', 'remote_copy_list'])
def test_helper_never_executed_cannot_expose_unchecked_staged_gbw(tmp_path, monkeypatch, kind):
    from aiida.common import AttributeDict
    monkeypatch.chdir(tmp_path)
    inputs = AttributeDict({'orbital_reference': SimpleNamespace(get_dict=lambda: {
        'preparation': backend.PREPARATION, 'orbital_mapping': {'prepared_file_sha256': 'a'*64}}),
        'compact_code': SimpleNamespace(uuid='helper')})
    info = SimpleNamespace(codes_info=[], retrieve_list=[], **{kind: [('source', 'aiida.gbw', 'reference.gbw')]})
    with SandboxFolder() as folder:
        backend.protect_reordered_input(info, inputs, folder)
        target = getattr(info, kind)[0][2]
        Path(target).write_bytes(b'unchecked scientific data')
        # Simulate launcher failure by deliberately never running the helper.
        assert target == 'unchecked_reference.gbw'
        assert not Path('reference.gbw').exists()


@pytest.fixture
def review_card(monkeypatch, spatial_source):
    ref, doc = spatial_source
    selected = {'electrons': 3, 'orbitals': [1, 3, 5]}
    plan = {'action': 'prepare', 'space': deepcopy(selected), 'plan': plan_for(ref, doc),
            'reuse_uuid': None, 'reused_resources': None, 'reused_policy': None}
    monkeypatch.setattr(service, 'review', lambda *args, **kwargs: deepcopy(plan))
    submitted = []
    monkeypatch.setattr(service, 'submit', lambda p: submitted.append(p) or 'new-workflow')
    card = OrbitalReordering('original', lambda: deepcopy(selected),
        ipw.Dropdown(options=[('export', 'export')]), lambda *args: None)
    yield card, selected, plan, submitted
    card.close()


@pytest.mark.parametrize('change', ['indices', 'electrons', 'walltime', 'memory', 'policy', 'export'])
def test_review_cannot_submit_stale_visible_selection_or_execution(review_card, change):
    card, selected, _, submitted = review_card
    card._review()
    assert not card.submit.disabled
    if change == 'indices': selected['orbitals'] = [0, 3, 5]  # Deliberately bypass observers.
    if change == 'electrons': selected['electrons'] = 5
    if change == 'walltime': card.walltime.value = 9
    if change == 'memory': card.memory.value = 1024
    if change == 'policy': card.retention.maxsizeoutput.value = 0
    if change == 'export': card.export_code.value = None
    card._submit()
    assert submitted == []
    assert card.submit.disabled


def test_reuse_review_reports_original_budget_and_retention(review_card):
    card, _, plan, submitted = review_card
    plan.update(action='reuse', reuse_uuid='already-saved',
                reused_resources={'memory_mb': 1024, 'wallclock_seconds': 300},
                reused_policy={'mode': 'remote', 'maxsizeoutput': 1024**2})
    card._review()
    text = card.message.value
    assert 'No new CalcJob' in text and 'already-saved' in text
    assert '1 GiB' in text and '5 minutes' in text and 'up to 1 MiB' in text
    assert 'One serial preparation CalcJob' not in text
    assert submitted == []


def test_native_route_rejects_unqualified_source_kinds_and_identity_permutations(spatial_source):
    ref, doc = spatial_source
    plan = plan_for(ref, doc)
    ref['preparation'] = 'moread_noiter_v1'
    # Rebuild with the exact source metadata used for the native request.
    plan = plan_for(ref, doc)
    backend.validate_request(ref, plan)
    for kind, preparation in [('CASSCF', 'casscf_verified_v1'), ('fixed', 'external'),
                              ('QRO', backend.PREPARATION)]:
        with pytest.raises(ValueError, match='qualification'):
            backend.validate_request(ref | {'kind': kind, 'preparation': preparation}, plan)


def test_review_builder_and_real_child_propagate_serial_budget(completed_common, monkeypatch, entry_points, aiida_manager):
    from aiidalab_orca import inspection_services, property_services
    entry_points.add(backend.OrbitalReorderingWorkChain, 'aiida.workflows:empa_orca.orbital_reordering')
    entry_points.add(backend.OrbitalReorderingCalculation, 'aiida.calculations:empa_orca.orbital_reordering')
    uid, _, (ref_uid, _, code_uid, root) = completed_common
    ref = orm.load_node(ref_uid)
    catalog = bound_catalog(ref, orm.load_node(completed_common[2][1]), root)
    monkeypatch.setattr(inspection_services, 'catalog', lambda _: {
        'uuid': str(catalog.uuid), 'reference_uuid': ref_uid, 'data': catalog.get_dict()})
    monkeypatch.setattr(property_services, 'helper_code', lambda _: code_uid)
    plan = service.review(uid, {'electrons': 3, 'orbitals': [5, 7, 9]}, code_uid,
                          resources=BUDGET, native_output_policy={'mode': 'remote', 'maxsizeoutput': 5*1024**2})
    b = service.builder(plan)
    assert b.storage_policy.get_dict() == {'threshold_mb': 0, 'stash_directory': ''}
    assert b.storage_policy.uuid != orm.load_node(uid).inputs.storage_policy.uuid
    stashed = service.review(uid, plan['space'], code_uid, resources=BUDGET,
        native_output_policy={'mode': 'stash', 'stash_directory': '/new/chosen/stash', 'maxsizeoutput': 5*1024**2})
    assert service.builder(stashed).storage_policy.get_dict() == {
        'threshold_mb': 0, 'stash_directory': '/new/chosen/stash'}
    process = instantiate_process(aiida_manager.get_runner(), b)
    assert process.setup() is None
    captured = []
    monkeypatch.setattr(process, 'submit', lambda child: captured.append(child) or orm.CalcJobNode().store())
    process.prepare()
    child = captured[0]
    assert child.metadata.options.max_memory_kb == 2097152
    assert child.metadata.options.max_wallclock_seconds == 600
    assert child.metadata.options.resources['num_mpiprocs_per_machine'] == 1
    assert child.metadata.options.environment_variables == {
        'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    assert child.source_remote.uuid == process.inputs.source_remote.uuid
    assert child.orbital_reference.uuid == ref.uuid
    assert child.metadata.disable_cache
    changed = deepcopy(plan)
    changed['resources']['wallclock_seconds'] = 540
    # A modified, freshly recalculated allocation is valid, but changing only
    # the recorded mapping can never sneak past the fresh review.
    changed['plan']['native_to_source'].reverse()
    with pytest.raises(ValueError, match='changed'):
        service.builder(changed)
    process.close()


def test_visible_selection_blocks_legacy_confirmation_and_contiguous_route_stays_unchanged(reference_switch):
    result, panel, _ = reference_switch
    panel.reference.value = 'original'
    active = result.open_analysis('active')
    active._use_selected([10, 11, 12])
    assert result.confirmed_space is not None
    active = result.open_analysis('active')
    active._use_selected([9, 11, 13])
    assert result.confirmed_space is None
    assert active.confirm.disabled
    assert active.reordering_box.layout.display != 'none'
    active.electrons.value = 5
    active._confirm()
    assert result.confirmed_space is None
    active.electrons.value = 3
    active._use_selected([10, 11, 12])
    assert result.confirmed_space is not None
    assert result.open_analysis('energy') is not None


def test_duplicate_submit_keeps_a_single_pending_workflow(review_card):
    card, _, _, submitted = review_card
    card._review()
    card._submit()
    card._submit()
    assert len(submitted) == 1
    assert card._job_uuid == 'new-workflow'
    assert card.review.disabled and card.submit.disabled


def test_downstream_keeps_old_contiguous_guard_and_reference_identity(spatial_source):
    from aiida_empa_orca import casscf, energy, dyson_data
    from aiida_empa_orca.protocols import protocol_settings
    from aiida_empa_orca.reference import reference_settings
    ref, doc = spatial_source
    ref = ref | {'settings': reference_settings(protocol_settings())}
    plan = plan_for(ref, doc)
    native = plan['native_active_space']
    with pytest.raises(ValueError, match='contiguous'):
        casci.active_space(plan['source_active_space'], ref)
    for charge, multiplicity, nel in [(0, 2, 3), (-1, 1, 4), (-1, 3, 4), (1, 1, 2), (1, 3, 2)]:
        text = casci.casci_input(ref, native, {'charge': charge, 'multiplicity': multiplicity})
        assert f'nel {nel}\n' in text and 'ActOrbs unchanged' in text
        assert '%scf\n rotate' not in text
    assert 'ActOrbs NatOrbs' in casscf.casscf_input(ref, native, {})
    assert 'DumpActInts true' in energy.export_input(ref, native, {})
    old = {'orbital_reference_uuid': 'original', 'structure_uuid': 'same', 'active_space': native,
           'model': {}, 'method': 'CASCI', 'geometry_mode': 'fixed',
           'states': [{'charge': 0, 'multiplicity': 2}]}
    new = old | {'orbital_reference_uuid': 'reordered', 'states': [{'charge': 1, 'multiplicity': 1}]}
    with pytest.raises(ValueError, match='share geometry, orbital reference'):
        dyson_data.compatible(old, new)


def test_large_full_json_is_blocked_before_submission():
    assert backend.checked_resources({'n_orbitals': 67}, BUDGET) == BUDGET
    with pytest.raises(ValueError, match='memory allowance'):
        backend.checked_resources({'n_orbitals': 6000}, BUDGET)
    with pytest.raises(ValueError, match='explicit'):
        backend.checked_resources({'n_orbitals': 67}, {})


def test_real_import_component_remains_compatible_when_present(monkeypatch):
    imported = pytest.importorskip('aiida_empa_orca.fixed_orbitals_data',
        reason='Verified-import component is present in the research assembly, not this standard-app base')
    # Unlike the portable import regression above, this loads the actual
    # component and its existing marker/process identifiers in composed tests.
    folder = SimpleNamespace(uuid='same-folder')
    producer = SimpleNamespace(process_type=imported.CALCULATION, is_finished_ok=True,
        outputs=SimpleNamespace(remote_folder=folder))
    ref = SimpleNamespace(creator=producer, get_dict=lambda: {'preparation': imported.PREPARATION})
    assert casci.validate_reference(ref, folder)['preparation'] == imported.PREPARATION
    producer.is_finished_ok = False
    with pytest.raises(ValueError):
        casci.validate_reference(ref, folder)


def test_converter_logs_keep_the_existing_size_threshold_contract(tmp_path):
    from aiida_empa_orca import native_logs
    root = tmp_path/'native_output'; root.mkdir()
    for name in native_logs.PROTOCOLS[backend.PROTOCOL]:
        (root/name).write_text('Synthetic converter diagnostic\n')
    record = native_logs.collect_output({'protocol': backend.PROTOCOL,
        'policy': {'mode': 'remote', 'maxsizeoutput': 0}}, tmp_path)
    assert record['status'] == 'complete'
    assert len(record['additional_summaries']) == 4
    assert len(record['retrieved_outputs']) == 5
    for row in record['retrieved_outputs']:
        assert b'original' in (tmp_path/row['name']).read_bytes().lower()
