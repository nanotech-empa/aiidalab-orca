"""KS previews inherit native retention, including reviewed reference recovery."""

import pytest
from aiida import orm
from aiida.engine.utils import instantiate_process

from aiida_empa_orca.reference import ArtifactUnavailable
from aiidalab_orca import property_services
from test_properties import TABLE
from test_reference import OUTPUT, electronic_source  # noqa: F401


def plan_for(uid):
    source = orm.load_node(uid)
    codes = {key: str(source.inputs.code.uuid) for key in ('python', 'plot', 'cubehandler')}
    return property_services.prepare_property(uid,
        {'orbitals': [[0, 1]], 'spin_density': True, 'grid_points': 40, 'retention': 'delete'},
        {'threshold_mb': 100, 'stash_directory': '/different/legacy/path'}, codes)


@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_property_inherits_recorded_retention_and_never_requests_retrieval(electronic_source, aiida_manager, mode):  # noqa: F811
    policy = {'mode': mode, **({'stash_directory': '/native/chosen/stash'} if mode == 'stash' else {})}
    uid, _ = electronic_source(output=OUTPUT + TABLE, native_policy=policy)
    plan = plan_for(uid)
    status = property_services.wavefunction_status(uid)
    assert status['retention'] == policy and status['inherited']
    assert plan['native_output_policy'] == policy
    assert plan['storage_policy']['threshold_mb'] == 0
    assert plan['storage_action'] == mode
    process = instantiate_process(aiida_manager.get_runner(), property_services.property_builder(plan))
    captured = []
    process.submit = lambda builder: captured.append(builder) or orm.CalcJobNode().store()
    try:
        assert process.setup() is None
        process.preserve()
        if mode == 'remote':
            assert not captured and process.inspect_storage() is None
        else:
            assert len(captured) == 1
            builder = captured[0]
            assert builder.policy.get_dict() == {'threshold_mb': 0, 'stash_directory': '/native/chosen/stash'}
            assert builder.metadata.options.stash['target_base'] == '/native/chosen/stash'
    finally:
        process.close()


@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_recovery_passes_configured_helper_and_original_retention(electronic_source, aiida_manager, mode):  # noqa: F811
    policy = {'mode': mode, **({'stash_directory': '/native/chosen/stash'} if mode == 'stash' else {})}
    uid, folder = electronic_source(output=OUTPUT + TABLE, native_policy=policy)
    (folder / 'aiida.gbw').unlink()
    plan = plan_for(uid)
    assert plan['regenerate_reference']
    process = instantiate_process(aiida_manager.get_runner(), property_services.property_builder(plan))
    captured = []
    process.submit = lambda builder: captured.append(builder) or orm.WorkChainNode().store()
    try:
        assert process.setup() is None and process.needs_reference()
        process.run_reference()
        source = orm.load_node(uid)
        assert captured[0].storage_code.uuid == source.inputs.code.uuid
        assert captured[0].native_output_policy.get_dict() == policy
        assert captured[0].bypass_cache.value
        assert captured[0].structure.uuid == source.outputs.structure.uuid
        assert captured[0].settings.get_dict() == source.inputs.settings.get_dict()
    finally:
        process.close()


def test_historical_defaults_stay_remote_and_unavailable_is_not_missing(electronic_source, monkeypatch):  # noqa: F811
    uid, _ = electronic_source(output=OUTPUT + TABLE)
    assert property_services.wavefunction_status(uid)['retention'] == {'mode': 'remote'}
    assert plan_for(uid)['storage_action'] == 'remote'
    def unavailable(*_):
        raise ArtifactUnavailable('temporarily inaccessible')
    monkeypatch.setattr(property_services, 'resolve_electronic', unavailable)
    assert property_services.wavefunction_status(uid)['state'] == 'unavailable'
    with pytest.raises(ArtifactUnavailable):
        plan_for(uid)


def test_hidden_helpers_do_not_make_runtime_selection_ambiguous(aiida_localhost, configured_orca_tools):
    hidden = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/old/orca-tools',
        default_calc_job_plugin='empa_orca.electronic_storage').store()
    hidden.is_hidden = True
    assert property_services.helper_code(aiida_localhost.uuid) == str(configured_orca_tools.uuid)


def test_property_panel_exposes_no_electronic_retrieval_threshold(monkeypatch):
    from types import SimpleNamespace
    from aiidalab_orca import orbitals as ui
    from aiidalab_orca.widget_lifecycle import close_widget_tree
    monkeypatch.setattr(ui.service, 'source_tools', lambda _: {'plot': [], 'cubehandler': []})
    monkeypatch.setattr(ui.service, 'property_runs', lambda _: [])
    monkeypatch.setattr(ui.service, 'wavefunction_status', lambda _: {
        'state': 'remote', 'inherited': True, 'retention': {'mode': 'remote'}})
    data = {'uuid': 'reference', 'symbols': ['H'], 'positions': [[0, 0, 0]],
            'levels': {'channels': [[{'spin': 0, 'index': 0, 'energy_ev': -5, 'occupation': 1}]],
                       'spin_polarized': False}}
    bounds = SimpleNamespace(lower=SimpleNamespace(value=-6), upper=SimpleNamespace(value=-4))
    panel = ui.OrbitalProperties(data, bounds)
    try:
        assert not hasattr(panel, 'threshold') and not hasattr(panel, 'wfn_policy')
        assert 'Inherited' in panel.wfn_info.value and 'Leave on the calculation computer' in panel.wfn_info.value
    finally:
        close_widget_tree(panel)
