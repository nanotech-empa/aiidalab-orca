"""QRO/UNO helper budgets, sequential scheduling, and reviewed browser actions."""
from pathlib import Path

import pytest
from aiida import engine, orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.common.datastructures import CodeRunMode
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import orbital_inspection as backend, common_orbitals
from aiida_empa_orca.pdos import OrbitalCharacterCalculation, OrbitalCharacterParser
from aiidalab_orca import inspection_services as service, casci_services
from aiidalab_orca.inspection import OrbitalInspection
from test_pdos_workflow import CharacterHarness, seed  # noqa: F401
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401
from test_orbital_inspection import catalog_node

BUDGET = {'memory_mb': 2048, 'wallclock_seconds': 600}


class PreparedHarness(CharacterHarness):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('prepared', valid_type=orm.Dict)
        spec.output('orbital_reference', valid_type=orm.Dict)
        spec.outline(cls.seed, cls.run_orbital_character,
                     engine.while_(cls.has_pending_orbital_character)(
                         cls.inspect_serial_orbital_character, cls.run_next_orbital_character),
                     cls.inspect_orbital_character)

    def seed(self):
        super().seed()
        self.out('orbital_reference', self.inputs.prepared)


def test_two_pdos_children_are_serial_even_after_first_failure(seed, aiida_localhost, entry_points):
    root = Path(seed['retrieved'].creator.outputs.remote_folder.get_remote_path())
    (root/'aiida.qro').write_bytes(b'test QRO')
    (root/'aiida.uno').write_bytes(b'test UNO')
    entry_points.add(OrbitalCharacterCalculation, 'aiida.calculations:empa_orca.orbital_character')
    entry_points.add(OrbitalCharacterParser, 'aiida.parsers:empa_orca.orbital_character')
    export = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/false').store()
    helper = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    # Intentional non-scientific failures exercise the real engine's wait boundaries.
    outputs, parent = engine.run_get_node(PreparedHarness, **seed,
        prepared=orm.Dict(dict={'filename':'aiida.qro','charge':0,'source_multiplicity':1}),
        character_export_code=export, character_helper_code=helper,
        character_memory_gib=orm.Int(2), character_wallclock_seconds=orm.Int(600))
    assert parent.is_finished_ok
    children = sorted(parent.called_descendants, key=lambda node: node.ctime)
    assert len(children) == 2 and all(node.is_failed for node in children)
    assert [node.inputs.identity['kind'] for node in children] == ['QRO','UNO']
    assert children[0].mtime <= children[1].ctime
    for child in children:
        assert child.get_option('max_wallclock_seconds') == 600
        assert child.get_option('max_memory_kb') == 2097152
        assert child.get_option('resources')['num_mpiprocs_per_machine'] == 1
    assert outputs['pdos_status'].get_dict()['state'] == 'incomplete'
    assert outputs['retrieved'].uuid == seed['retrieved'].uuid


@pytest.fixture
def completed_common(common_reference):
    ref_uid, remote_uid, code_uid, root = common_reference
    ref, remote, code = orm.load_node(ref_uid), orm.load_node(remote_uid), orm.load_code(code_uid)
    native = ref.creator
    source_retrieved = native.inputs.source_retrieved
    source = source_retrieved.base.links.get_incoming(link_type=LinkType.RETURN).first().node
    inputs = {'structure':native.inputs.structure, 'settings':native.inputs.settings, 'code':code,
              'source_retrieved':source_retrieved, 'source_remote':source_retrieved.creator.outputs.remote_folder,
              'storage_code':code, 'storage_policy':orm.Dict(dict={'threshold_mb':0,'stash_directory':'/chosen/stash'})}
    w = orm.WorkChainNode(process_type=common_orbitals.PROCESS_TYPE)
    for key,value in inputs.items():
        value.store(); w.base.links.add_incoming(value,link_type=LinkType.INPUT_WORK,link_label=key)
    w.store()
    ref.base.links.add_incoming(w,link_type=LinkType.RETURN,link_label='orbital_reference')
    remote.base.links.add_incoming(w,link_type=LinkType.RETURN,link_label='remote_folder')
    w.set_process_state(ProcessState.FINISHED);w.set_exit_status(0)
    (root/'aiida.uno').write_bytes(b'test UNO')
    return str(w.uuid),str(source.uuid),common_reference


def test_common_review_controls_forward_pdos_budget_and_invalidate(completed_common, monkeypatch):
    from aiidalab_orca.casci import CasciStates
    from test_result_navigation import reference_data
    uid, source_uid, parts = completed_common
    data = reference_data(); data['uuid'] = source_uid
    monkeypatch.setattr(casci_services, 'helper_code', lambda _: parts[2])
    monkeypatch.setattr(casci_services, 'reference_runs', lambda _: [])
    panel = CasciStates(data)
    try:
        panel.common_force.value = True
        panel._review_common()
        assert panel.plan is not None,panel.message.value
        assert panel.plan['pdos']['memory_gib'] == 2
        assert panel.plan['pdos']['wallclock_seconds'] == 600
        assert 'QRO, then UNO' in panel.message.value and 'one serial CalcJob at a time' in panel.message.value
        assert '2 GiB, up to 10 minutes' in panel.message.value
        b = casci_services.common_builder(source_uid, True, panel.plan['pdos'])
        assert b.character_memory_gib.value == 2 and b.character_wallclock_seconds.value == 600
        panel.common_pdos_memory.value = 3
        assert panel.plan is None and panel.common_submit.disabled
        panel._review_common()
        panel.common_pdos_wallclock.value = 11
        assert panel.plan is None and panel.common_submit.disabled
    finally: panel.close()


def setup_codes(monkeypatch, code):
    monkeypatch.setattr(service, 'helper_code', lambda _: code)
    monkeypatch.setattr(service, 'codes', lambda _: {key:[('Test '+key,code)] for key in ('export','plot','cubehandler')})


def test_catalog_review_reaches_export_with_serial_native_codes(completed_common, aiida_manager, monkeypatch):
    uid, _, parts = completed_common
    setup_codes(monkeypatch, parts[2])
    before = orm.QueryBuilder().append(orm.ProcessNode).count()
    plan = service.review_catalog(uid, parts[2], resources=BUDGET)
    assert plan['sets'] == ['QRO','UNO'] and plan['resources'] == BUDGET
    assert orm.QueryBuilder().append(orm.ProcessNode).count() == before
    b = service.catalog_builder(uid,parts[2],resources=plan['resources'])
    assert b.catalog_resources.get_dict() == BUDGET
    parent = instantiate_process(aiida_manager.get_runner(),b)
    builders=[]; parent.submit=lambda b:builders.append(b) or orm.CalcJobNode().store()
    try:
        assert parent.setup() is None
        parent.preserve();assert not builders  # Leave remains Leave.
        parent.export();assert len(builders)==1
        child=instantiate_process(aiida_manager.get_runner(),builders[0])
        try:
            assert child.node.get_option('max_wallclock_seconds')==600
            assert child.node.get_option('max_memory_kb')==2097152
            with SandboxFolder() as folder:info=child.prepare_for_submission(folder)
            assert info.codes_run_mode==CodeRunMode.SERIAL
            assert len(info.codes_info)==3  # QRO export, UNO export, compact collector.
            assert not any(name.endswith(('.qro','.uno','.gbw')) for name in info.retrieve_list)
        finally:child.close()
    finally:parent.close()


def test_preview_review_passes_budget_to_actual_child(completed_common, aiida_manager, monkeypatch):
    uid,_,parts=completed_common
    setup_codes(monkeypatch,parts[2])
    catalog=catalog_node(parts)
    plan=service.review_cubes(uid,str(catalog.uuid),'QRO',
        {'orbitals':[[0,6],[0,7]],'grid_points':80,'retention':'leave'},
        {'plot':parts[2],'cubehandler':parts[2]},resources=BUDGET)
    b=service.cubes_builder(plan)
    assert b.preview_resources.get_dict()==BUDGET
    parent=instantiate_process(aiida_manager.get_runner(),b)
    children=[]
    def capture(b):
        child=instantiate_process(aiida_manager.get_runner(),b);children.append(child);return child.node
    parent.submit=capture
    try:
        assert parent.setup() is None
        parent.preserve();assert not children
        parent.generate();assert len(children)==1
        assert children[0].node.get_option('max_wallclock_seconds')==600
        assert children[0].node.get_option('max_memory_kb')==2097152
        assert children[0].node.get_option('resources')['num_mpiprocs_per_machine']==1
        assert children[0].inputs.parameters.get_dict()['retention']=='leave'
    finally:
        for child in children:child.close()
        parent.close()


def test_inspection_reviews_invalidate_and_block_overlapping_submits(completed_common, monkeypatch):
    uid,_,parts=completed_common
    setup_codes(monkeypatch,parts[2])
    stored_catalog = catalog_node(parts)
    record={'uuid':str(stored_catalog.uuid),'data':stored_catalog.get_dict()}
    monkeypatch.setattr(service,'catalog',lambda _:record)
    widget=OrbitalInspection(uid)
    submitted=[]
    monkeypatch.setattr(service,'submit_catalog_plan',lambda plan:submitted.append(plan) or 'catalog-job')
    def start(uuid,kind): widget._job_uuid=uuid;widget._job_kind=kind
    monkeypatch.setattr(widget,'_start',start)
    try:
        widget.catalog_review.click()
        assert widget.catalog_plan is not None,widget.catalog_message.value
        assert '1 process, 2 GiB, up to 10 minutes' in widget.catalog_message.value
        widget.catalog_memory.value=1024
        assert widget.catalog_plan is None and widget.read.disabled
        widget.catalog_memory.value=2048;widget.catalog_review.click()
        widget.catalog_wallclock.value=11
        assert widget.catalog_plan is None and widget.read.disabled
        widget.catalog_wallclock.value=10;widget.catalog_review.click()
        widget.read.click();widget.read.click()
        assert len(submitted)==1 and submitted[0]['resources']==BUDGET
        widget.catalog_review.click();assert widget.catalog_plan is None
        widget._job_uuid=None
        widget.orbitals.value=(6,7)
        widget.retention.value='leave';widget.review.click()
        assert widget.plan is not None,widget.message.value
        assert widget.plan['resources']==BUDGET
        widget.preview_memory.value=1024
        assert widget.plan is None and widget.submit.disabled
        widget.preview_memory.value=2048;widget.review.click()
        widget.preview_wallclock.value=11
        assert widget.plan is None and widget.submit.disabled
    finally:widget.close()
