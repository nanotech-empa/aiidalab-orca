"""NTO helper budgets, durable serialization and safe reviewed submission."""
from copy import deepcopy

import pytest
from aiida import common, engine, orm
from aiida.common import LinkType
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process
from aiida.parsers import Parser

from aiida_empa_orca import optical as backend
from aiidalab_orca import optical as ui, optical_services as service
from test_optical import result

BUDGET = {'memory_mb': 2048, 'wallclock_seconds': 600}


def output(producer, name, node):
    node.base.links.add_incoming(producer, link_type=LinkType.CREATE, link_label=name)
    return node.store()


@pytest.fixture
def source(aiida_profile_clean, aiida_localhost, tmp_path, monkeypatch):
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    node = orm.CalcJobNode(computer=aiida_localhost, process_type=backend.PROCESS_TYPE)
    policy = orm.Dict(dict={'mode': 'stash', 'stash_directory': str(tmp_path/'stash'),
                            'maxsizeoutput': 5*1024**2}).store()
    node.base.links.add_incoming(policy, link_type=LinkType.INPUT_CALC, link_label='native_output_policy')
    node.store()
    table = result() | {'structure_uuid': 'unchanged-geometry'}
    output(node, 'excitations', orm.Dict(dict=table))
    output(node, 'remote_folder', orm.RemoteData(computer=aiida_localhost, remote_path=str(tmp_path)))
    node.set_process_state(ProcessState.FINISHED)
    node.set_exit_status(0)
    state = table['states'][0]
    (tmp_path/state['nto']['filename']).write_bytes(b'unchanged native NTO test bytes')
    monkeypatch.setattr(service, 'result', lambda _: deepcopy(table))
    monkeypatch.setattr(service, 'helper_code', lambda _: str(code.uuid))
    return str(node.uuid), str(code.uuid)


def plan(source, resources=BUDGET):
    uid, code = source
    return service.review_cubes(uid, {'state_id': 'singlet:1', 'pairs': [1]},
        {'grid_points': 80, 'retention': 'leave', 'stash_directory': '/tmp/unused'},
        {'threshold_mb': 0, 'stash_directory': '/tmp/unused'},
        {'plot': code, 'cubehandler': code}, resources=resources)


@pytest.mark.parametrize('budget', [BUDGET, {'memory_mb': 3072, 'wallclock_seconds': 900}])
def test_both_native_helpers_receive_reviewed_budget_without_changing_pairs(source, aiida_manager, monkeypatch, budget):
    reviewed = plan(source, budget)
    assert reviewed['resources'] == budget and reviewed['preserve_nto']
    base = plan(source)
    for key in ('selection', 'parameters', 'policy', 'codes'):
        assert reviewed[key] == base[key]
    builder = service.cube_builder(reviewed)
    assert builder.preview_resources.get_dict() == budget
    process = instantiate_process(aiida_manager.get_runner(), builder)
    captured = []
    monkeypatch.setattr(process, 'submit', lambda b: captured.append(b) or orm.CalcJobNode())
    try:
        assert process.setup() is None
        assert process.needs_storage()
        process.store()
        process.cubes()
        assert len(captured) == 2
        for b in captured:
            assert b.metadata.options.resources == {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
            assert b.metadata.options.max_memory_kb == budget['memory_mb']*1024
            assert b.metadata.options.max_wallclock_seconds == budget['wallclock_seconds']
            assert not b.metadata.options.withmpi
        assert captured[0].policy.get_dict()['threshold_mb'] == 0
        assert captured[1].parameters.get_dict() == reviewed['parameters']
        assert captured[1].orbital_identity.get_dict()['state_id'] == 'singlet:1'
        assert captured[1].orbital_identity.get_dict()['pairs'] == [1]
    finally:
        process.close()


def test_budget_validation_and_stale_review(source):
    reviewed = plan(source)
    changed = deepcopy(reviewed)
    changed['resources']['wallclock_seconds'] = 540
    with pytest.raises(ValueError, match='changed'):
        service.cube_builder(changed)
    for invalid in ({'memory_mb': 0}, {'wallclock_seconds': 1}, {'nprocs': 2}):
        with pytest.raises(ValueError):
            plan(source, invalid)


def test_another_state_preview_blocks_review_and_workchain_before_native_jobs(source, aiida_manager):
    reviewed = plan(source)
    builder = service.cube_builder(reviewed)
    source_node = orm.load_node(source[0])
    active = orm.WorkChainNode(process_type=backend.NTO_PROCESS)
    active.base.links.add_incoming(source_node.outputs.excitations,
        link_type=LinkType.INPUT_WORK, link_label='excitations')
    active.store()
    active.set_process_state(ProcessState.WAITING)
    with pytest.raises(ValueError, match='still active'):
        plan(source)
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        assert process.setup().status == 400
        assert not process.node.called
    finally:
        process.close()


def test_finished_historical_preview_can_be_reused_without_new_resource_input(source, monkeypatch):
    p = plan(source)
    old = orm.WorkChainNode(process_type=backend.NTO_PROCESS)
    original = orm.load_node(source[0])
    for key, node in {'excitations': original.outputs.excitations,
                      'selection': orm.Dict(dict=p['selection']).store(),
                      'parameters': orm.Dict(dict=p['parameters']).store(),
                      'storage_policy': orm.Dict(dict=p['policy']).store(),
                      **{k: orm.load_code(source[1]) for k in ('code', 'plot_code', 'cubehandler_code')}}.items():
        old.base.links.add_incoming(node, link_type=LinkType.INPUT_WORK, link_label=key)
    old.store()
    old.set_process_state(ProcessState.FINISHED)
    old.set_exit_status(0)
    monkeypatch.setattr(service, 'validate_cube_outputs', lambda _: None)
    reused = plan(source, {'memory_mb': 4096, 'wallclock_seconds': 1200})
    assert reused['reuse_uuid'] == str(old.uuid) and reused['action'] == 'reuse'


@pytest.fixture
def widget(monkeypatch):
    monkeypatch.setattr(service, 'result', lambda _: result())
    monkeypatch.setattr(service, 'cube_defaults', lambda _: {
        'storage_policy': {'threshold_mb': 0, 'stash_directory': '/tmp/nto'},
        'codes': {'plot': [('plot', 'plot')], 'cubehandler': [('cubehandler', 'cubehandler')]}})
    inventory = []
    monkeypatch.setattr(service, 'preview_inventory', lambda _: deepcopy(inventory))
    monkeypatch.setattr(ui.NtoPreviews, '_show_cube', lambda *a: None)
    calls = []
    def review(uid, selection, parameters, policy, codes, *, resources):
        calls.append(deepcopy(resources))
        return {'resources': resources, 'reuse_uuid': None, 'preserve_nto': False}
    monkeypatch.setattr(service, 'review_cubes', review)
    viewer = ui.NtoPreviews('optical-source')
    viewer.choose('singlet:1')
    yield viewer, inventory, calls
    viewer.close()


def test_widget_reviews_invalidates_and_consumes_before_uncertain_submission(widget, monkeypatch):
    viewer, _, calls = widget
    for field, value in ((viewer.preview_budget.walltime, 9), (viewer.preview_budget.memory, 3072)):
        viewer._review()
        assert calls[-1] == viewer.preview_budget.values()
        assert '1 process' in viewer.message.value and 'minutes' in viewer.message.value
        field.value = value
        assert viewer.plan is None and viewer.submit.disabled
        field.value = 10 if field is viewer.preview_budget.walltime else 2048
        assert viewer.plan is None and viewer.submit.disabled
    viewer._review()
    submitted = []
    def uncertain(plan):
        assert viewer.plan is None and viewer.submit.disabled and viewer.review.disabled
        viewer._submit()  # A second queued event cannot reach the service.
        submitted.append(plan)
        raise RuntimeError('Submission response lost; review status before retrying')
    monkeypatch.setattr(service, 'submit_cubes', uncertain)
    viewer._submit()
    viewer._submit()
    assert len(submitted) == 1 and viewer.plan is None and viewer.submit.disabled
    assert 'response lost' in viewer.message.value


def test_widget_adopts_active_preview_and_unlocks_on_failure(widget):
    viewer, inventory, _ = widget
    inventory.append({'uuid': 'running', 'date': '2026-11-10', 'state_id': 'singlet:2',
                      'pairs': [1], 'finished': False, 'success': False, 'ready_pairs': [], 'members': {}})
    viewer._refresh()
    assert viewer._job_uuid == 'running' and viewer.review.disabled and viewer.submit.disabled
    viewer.choose('singlet:3')
    viewer._review()
    assert viewer.plan is None and viewer.submit.disabled
    inventory[0]['finished'] = True
    viewer._refresh()
    assert viewer._job_uuid is None and not viewer.review.disabled and viewer.submit.disabled


def test_successful_submission_locks_controls_until_inventory_finishes(widget, monkeypatch):
    viewer, inventory, _ = widget
    submitted = []
    def submit(plan):
        submitted.append(plan)
        inventory.append({'uuid': 'new-cubes', 'date': '2026-11-10', 'state_id': 'singlet:1',
            'pairs': [1], 'finished': False, 'success': False, 'ready_pairs': [], 'members': {}})
        return 'new-cubes'
    monkeypatch.setattr(service, 'submit_cubes', submit)
    viewer._review()
    viewer._submit()
    viewer._submit()
    assert len(submitted) == 1 and viewer.review.disabled and viewer.submit.disabled
    inventory[0].update(finished=True, success=True, ready_pairs=[1],
                        members={'1': {'hole': 'hole.cube', 'particle': 'particle.cube'}})
    viewer._refresh()
    assert viewer._job_uuid is None and not viewer.review.disabled
    assert viewer.previous.value == 'new-cubes' and viewer.cube.value == 'hole.cube'
    viewer.member.value = 'particle'
    assert viewer.cube.value == 'particle.cube'
    assert viewer.plan is None and viewer.submit.disabled


class ProbeCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('fail', valid_type=orm.Bool)
        spec.input('metadata.options.parser_name', default='test.nto_resources')
        spec.output('manifest', valid_type=orm.Dict)
        spec.exit_code(400, 'ERROR_PROBE', message='Intentional dummy failure')
    def prepare_for_submission(self, folder):
        code = common.CodeInfo()
        code.code_uuid = self.inputs.code.uuid
        info = common.CalcInfo()
        info.codes_info = [code]
        return info


class ProbeParser(Parser):
    def parse(self, **kwargs):
        if self.node.inputs.fail.value:
            return self.exit_codes.ERROR_PROBE
        self.out('manifest', orm.Dict(dict={'dummy': True}))


class SerialNtoHarness(backend.NtoCubesWorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('fail_storage', valid_type=orm.Bool)
    def setup(self):
        state, _ = backend.nto_selection(self.inputs.excitations.get_dict(), self.inputs.selection.get_dict())
        self.ctx.filename = state['nto']['filename']
    def needs_storage(self):
        return True
    def _probe(self, fail, label):
        b = ProbeCalculation.get_builder()
        b.code, b.fail = self.inputs.code, fail
        b.metadata.options = self._preview_options()
        b.metadata.call_link_label = label
        return self.submit(b)
    def store(self):
        return engine.ToContext(storage=self._probe(self.inputs.fail_storage, 'preserve_nto'))
    def cubes(self):
        return engine.ToContext(calculation=self._probe(orm.Bool(False), 'nto_cubes'))


@pytest.mark.parametrize('fail', [False, True])
def test_real_outline_waits_for_storage_and_stops_after_failure(source, entry_points, fail):
    entry_points.add(ProbeCalculation, 'aiida.calculations:test.nto_resources')
    entry_points.add(ProbeParser, 'aiida.parsers:test.nto_resources')
    entry_points.add(SerialNtoHarness, 'aiida.workflows:test.nto_serial')
    reviewed = plan(source)
    base = service.cube_builder(reviewed)
    b = SerialNtoHarness.get_builder()
    for key, value in base.items():
        if key != 'metadata':
            b[key] = value
    b.fail_storage = orm.Bool(fail)
    _, run = engine.run_get_node(b)
    assert run.exit_status == (401 if fail else 0)
    children = sorted(run.called, key=lambda n: n.ctime)
    assert len(children) == (1 if fail else 2)
    for job in children:
        assert job.get_option('max_memory_kb') == 2*1024**2
        assert job.get_option('max_wallclock_seconds') == 600
        assert job.get_option('resources')['num_mpiprocs_per_machine'] == 1
    if not fail:
        assert children[0].mtime <= children[1].ctime
