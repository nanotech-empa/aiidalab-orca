"""Reviewed helper budgets and explicit render confirmation without native execution."""
from copy import deepcopy
import io
from types import SimpleNamespace

import ipywidgets as ipw
import pytest
import traitlets as tl
from aiida import orm
from aiida.common import LinkType
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process

from aiida_empa_orca.rendering import helper_resources
from aiidalab_orca import orbitals as ui, property_services, render_services
from aiidalab_orca.rendering import RenderPanel
from test_properties import TABLE
from test_reference import OUTPUT, electronic_source  # noqa: F401
from test_rendering import SETTINGS, PLANE

BUDGET = {'memory_mb': 2048, 'wallclock_seconds': 600}


@pytest.mark.parametrize('bad', [
    {'memory_mb': True}, {'memory_mb': 0}, {'memory_mb': 1048577}, {'memory_mb': 2048.0},
    {'wallclock_seconds': True}, {'wallclock_seconds': 59}, {'wallclock_seconds': 604801},
    {'wallclock_seconds': '600'}, {'nprocs': 2},
])
def test_invalid_helper_budgets_are_rejected(bad):
    with pytest.raises(ValueError):
        helper_resources(bad)


def assert_budget(node):
    assert node.get_option('max_wallclock_seconds') == 600
    assert node.get_option('max_memory_kb') == 2097152
    assert node.get_option('resources') == {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    assert node.get_option('withmpi') is False


def test_cube_gui_review_reaches_parent_and_actual_child_options(electronic_source, aiida_manager, monkeypatch):
    uid, _ = electronic_source(output=OUTPUT+TABLE, native_policy={'mode': 'remote'})
    source = orm.load_node(uid)
    code = str(source.inputs.code.uuid)
    monkeypatch.setattr(property_services, 'helper_code', lambda _: code)
    monkeypatch.setattr(property_services, 'source_tools', lambda _: {
        'plot': [('Test plot', code)], 'cubehandler': [('Test reduction', code)]})
    from aiida_empa_orca.levels import orbital_levels
    levels = orbital_levels(OUTPUT+TABLE)
    panel = ui.OrbitalProperties({'uuid': uid, 'symbols': ['N','O'], 'positions': [[0,0,0],[0,0,1.3]],
                                 'levels': levels}, SimpleNamespace(lower=SimpleNamespace(value=-6),
                                                                   upper=SimpleNamespace(value=-3)))
    children = []
    try:
        panel.retention.value = 'leave'
        panel.memory.value = 2048
        panel.wallclock.value = 10
        panel._review()
        assert panel.plan is not None, panel.message.value
        assert panel.plan['resources'] == BUDGET
        assert '1 process, 2 GiB, up to 10 minutes' in panel.message.value
        builder = property_services.property_builder(panel.plan)
        assert builder.cube_resources.get_dict() == BUDGET
        process = instantiate_process(aiida_manager.get_runner(), builder)
        try:
            assert process.setup() is None
            assert process.preserve() is None
            def capture(child_builder):
                child = instantiate_process(aiida_manager.get_runner(), child_builder)
                children.append(child)
                return child.node
            process.submit = capture
            process.run_cubes()
            assert len(children) == 1
            assert_budget(children[0].node)
            assert children[0].inputs.parameters.get_dict()['retention'] == 'leave'
        finally:
            for child in children:
                child.close()
            process.close()
        panel.memory.value = 1024
        assert panel.plan is None and panel.submit_button.disabled
        panel.memory.value = 2048
        panel._review()
        panel.wallclock.value = 11
        assert panel.plan is None and panel.submit_button.disabled
        panel._review()
        assert panel.plan['resources']['wallclock_seconds'] == 660
        assert 'up to 11 minutes' in panel.message.value
    finally:
        panel.close()


def test_optional_preservation_uses_the_same_reviewed_budget(electronic_source, aiida_manager):
    uid, _ = electronic_source(output=OUTPUT+TABLE, native_policy={'mode': 'stash', 'stash_directory': '/chosen/stash'})
    source = orm.load_node(uid)
    codes = {key: str(source.inputs.code.uuid) for key in ('python','plot','cubehandler')}
    plan = property_services.prepare_property(uid,
        {'orbitals': [[0,1]], 'retention': 'leave'}, {'threshold_mb': 0, 'stash_directory': '/chosen/stash'},
        codes, resources=BUDGET)
    process = instantiate_process(aiida_manager.get_runner(), property_services.property_builder(plan))
    builders = []
    process.submit = lambda b: builders.append(b) or orm.CalcJobNode().store()
    try:
        assert process.setup() is None
        process.preserve()
        assert len(builders) == 1
        assert builders[0].metadata.options.max_wallclock_seconds == 600
        assert builders[0].metadata.options.max_memory_kb == 2097152
        assert builders[0].metadata.options.stash['target_base'] == '/chosen/stash'
    finally:
        process.close()


@pytest.fixture
def cube_result(aiida_profile_clean, aiida_localhost, tmp_path):
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true',
        default_calc_job_plugin='empa_orca.cube_render').store()
    root = tmp_path/'cube-source'
    (root/'full_cubes').mkdir(parents=True)
    (root/'full_cubes/a.cube').write_bytes(b'full cube\n')
    job = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.orbital_cubes').store()
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.BytesIO(b'reduced cube\n'), 'previews/a.cube')
    outputs = {'retrieved': retrieved, 'remote_folder': orm.RemoteData(computer=aiida_localhost, remote_path=str(root)),
               'manifest': orm.Dict(dict={'retention': 'leave', 'cubes': [{'filename': 'a.cube', 'full': {'size_bytes': 10}}]})}
    for label, node in outputs.items():
        node.base.links.add_incoming(job, link_type=LinkType.CREATE, link_label=label)
        node.store()
    job.set_process_state(ProcessState.FINISHED)
    job.set_exit_status(0)
    return str(job.uuid)


@pytest.mark.parametrize('quality', ['preview','full'])
def test_render_review_and_child_options_without_submission(cube_result, aiida_manager, monkeypatch, quality):
    monkeypatch.setattr(render_services, 'submit', lambda *a: pytest.fail('Review must not submit'))
    count = orm.QueryBuilder().append(orm.ProcessNode).count()
    plan = render_services.prepare_render(cube_result, 'a.cube', quality,
        {**SETTINGS, 'slice_plane': PLANE}, resources=BUDGET)
    assert orm.QueryBuilder().append(orm.ProcessNode).count() == count
    assert plan['resources'] == BUDGET
    child = instantiate_process(aiida_manager.get_runner(), render_services.render_builder(plan))
    try:
        assert_budget(child.node)
        assert child.inputs.settings.get_dict()['slice_plane'] == PLANE
        assert ('source_folder' in child.inputs) == (quality == 'full')
    finally:
        child.close()


def fake_viewer():
    class Camera(tl.HasTraits):
        _camera_orientation = tl.List(default_value=list(SETTINGS['orientation']))
    viewer = ipw.VBox()
    viewer.width = ipw.IntText(value=640)
    viewer.render_button, viewer.render_message = ipw.Button(), ipw.HTML()
    viewer.tabs = ipw.Tab(children=[ipw.VBox(), ipw.VBox(), ipw.VBox([
        viewer.width, viewer.render_button, viewer.render_message])])
    viewer.viewer3d = SimpleNamespace(viewer=Camera())
    viewer.render_settings = lambda: {**deepcopy(SETTINGS), 'width': viewer.width.value}
    viewer.children = (viewer.tabs,)
    return viewer


def test_render_gui_requires_review_invalidates_edits_and_submits_once(cube_result, monkeypatch):
    panel = RenderPanel(cube_result, 'a.cube')
    viewer = fake_viewer()
    panel.bind_viewer(viewer, lambda _: None)
    submitted = []
    monkeypatch.setattr(render_services, 'submit_reviewed_render', lambda plan: submitted.append(deepcopy(plan)) or 'test-render')
    monkeypatch.setattr(panel, '_start_poll', lambda: None)
    try:
        assert viewer.render_button.description == 'Review current view'
        assert panel.saved.render_button.description == 'Review selected views'
        panel.submit(viewer.render_settings())
        assert not submitted
        assert '1 CalcJob(s), each: 1 process, 2 GiB, up to 10 minutes' in panel.review_html.value
        panel.memory.value = 1024
        assert panel.plan is None and panel.submit_button.disabled
        panel.memory.value = 2048
        panel.submit(viewer.render_settings())
        panel.wallclock.value = 11
        assert panel.plan is None and panel.submit_button.disabled
        panel.wallclock.value = 10
        panel.submit(viewer.render_settings())
        viewer.width.value = 800
        assert panel.plan is None and panel.submit_button.disabled
        panel.submit(viewer.render_settings())
        panel.submit_button.click()
        panel.submit_button.click()
        assert len(submitted) == 1
        assert submitted[0]['resources'] == BUDGET
        assert submitted[0]['settings']['width'] == 800
    finally:
        panel.close()
        panel.close()  # Result replacement and parent disposal may both reach the controller.
        viewer.close()


def test_saved_render_review_keeps_snapshot_and_rejects_later_changes(cube_result):
    state = {'version': 1, 'render': deepcopy(SETTINGS), 'plane': PLANE, 'show_plane': True}
    identifier = render_services.save_view(cube_result, 'a.cube', 'full', 'With plane', state)
    panel = RenderPanel(cube_result, 'a.cube')
    try:
        panel._render_saved([identifier])
        assert not panel.submit_button.disabled
        assert 'With plane' in panel.review_html.value and 'slicing plane: included' in panel.review_html.value
        assert panel.plan[0]['resources'] == BUDGET
        assert panel.plan[0]['settings']['slice_plane'] == PLANE
        render_services.save_view(cube_result, 'a.cube', 'full', 'Changed name', state, identifier)
        with pytest.raises(ValueError, match='visualization changed'):
            render_services.render_builder(panel.plan[0])
    finally:
        panel.close()
