"""Analysis choices retain their reference and never submit prerequisites."""

import ipywidgets as ipw
import pytest

from test_result_navigation import reference_data
from test_reuse import source  # noqa: F401 -- isolated finished-run fixture


@pytest.mark.parametrize('task', ['casci', 'dyson', 'kondo'])
def test_missing_states_keep_requested_view_and_offer_explicit_preparation(monkeypatch, task):
    from aiidalab_orca import casci, viewer
    from aiidalab_orca.app import close_widget_tree
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))
    monkeypatch.setattr(casci.service, 'reference_runs', lambda uuid: [])

    def unwanted(*args, **kwargs):
        raise AssertionError('Navigation must not submit a prerequisite')

    monkeypatch.setattr(casci.service, 'prepare_common', unwanted)
    result = viewer.show_result(reference_data())
    try:
        result.navigation.value = task
        panel = result.tabs.panels['states']
        assert panel.source_uuid == 'reference'
        if task != 'casci':
            assert result.navigation.value == task
            assert result.prerequisites.layout.display == '' and panel.layout.display == 'none'
            assert 'CASCI states first' in result.prerequisites.children[0].value
            result.prerequisites.children[1].click()
            assert result.navigation.value == 'casci'
        assert panel.layout.display != 'none'
        assert panel.analysis.value == 'states' and panel.calculation.toggle.value
        assert panel.analysis.layout.display == 'none'
        assert panel.plan is None and panel._dyson is None
        assert (panel.electrons.value, panel.norb.value, panel.charge.value, panel.mult.value) == (2, 2, 0, 1)
        assert panel.common_submit.disabled and panel.submit.disabled
    finally:
        close_widget_tree(result)


def test_analysis_switches_reuse_the_same_state_workspace(monkeypatch):
    from aiidalab_orca import viewer, casci
    from aiidalab_orca.app import close_widget_tree
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))

    class SavedStates(ipw.VBox):
        def __init__(self, data, **kwargs):
            self.reference = ipw.Dropdown(options=[('Saved common orbitals', 'common')])
            self.analysis = ipw.ToggleButtons(options=[('States','states'), ('Dyson','spectrum'), ('Kondo','kondo')])
            self._datasets = [{'workflow_uuid': 'saved-states'}]
            self._dyson = None
            self.selected_root = 3
            super().__init__([self.reference, self.analysis])

    monkeypatch.setattr(casci, 'CasciStates', SavedStates)
    result = viewer.show_result(reference_data())
    try:
        first = result.open_analysis('kondo')
        assert first.analysis.value == 'kondo'
        assert result.open_analysis('dyson') is first
        assert first.analysis.value == 'spectrum'
        assert first.reference.value == 'common' and first.selected_root == 3
    finally:
        close_widget_tree(result)


def test_new_goal_stays_in_setup_and_existing_reference_is_explicit(source, monkeypatch):
    from aiidalab_orca import app as app_module, casci, services, viewer
    monkeypatch.setattr(services, 'codes', lambda: [('Test ORCA', source.inputs.code.uuid)])
    monkeypatch.setattr(casci.service, 'reference_runs', lambda uuid: [])
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))
    data = reference_data() | {'uuid': str(source.uuid), 'label': 'Saved reference',
        'finished': True, 'successful': True, 'scientific_success': True}
    monkeypatch.setattr(services, 'result', lambda uuid: dict(data, uuid=str(uuid)))

    def unwanted(*args, **kwargs):
        raise AssertionError('Opening the analysis must not submit a calculation')

    monkeypatch.setattr(services, 'submit_plan', unwanted)
    app = app_module.OrcaApp()
    try:
        before = app._settings()
        app.analysis_chooser.choice.value = 'kondo'
        assert app.pages.selected_index == 0 and app._requested_analysis == 'kondo'
        assert app._settings() == before and app.process_uuid is None
        assert 'First step' in app.analysis_hint.value
        app.open_existing.click()
        assert app.pages.selected_index == 1
        app.history.select(source.uuid)
        assert not app.history.view.disabled
        app.history.view.click()
        assert not app.error.value
        assert app.pages.selected_index == 2 and app.process_uuid == source.uuid
        result = app.result_box.children[0]
        panel = result.tabs.panels['states']
        assert panel.source_uuid == source.uuid
        assert 'Kondo' in result.analysis_hint.value
        assert result.navigation.value == 'kondo' and result.goal == 'kondo'
        assert result.tabs._view_name == 'StackView'
        assert result.prerequisites.layout.display == ''
        result.prerequisites.children[1].click()
        assert result.navigation.value == 'casci' and panel.calculation.toggle.value
        assert result.goal == 'kondo' and result.continue_goal.layout.display == ''
        assert app._requested_analysis is None
    finally:
        app.close()


def test_new_submission_opens_its_goal_after_reference_completes(source, monkeypatch):
    from aiidalab_orca import app as app_module, casci, services, viewer
    monkeypatch.setattr(services, 'codes', lambda: [('Test ORCA', source.inputs.code.uuid)])
    monkeypatch.setattr(casci.service, 'reference_runs', lambda uuid: [])
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))
    data = reference_data() | {'uuid': str(source.uuid), 'label': 'Completed reference',
        'finished': True, 'successful': True, 'scientific_success': True}
    monkeypatch.setattr(services, 'result', lambda uuid: dict(data, uuid=str(uuid)))
    submitted = []

    def submit(plan, label):
        submitted.append(plan)
        return str(source.uuid)

    monkeypatch.setattr(services, 'submit_plan', submit)
    app = app_module.OrcaApp()
    try:
        app.analysis_chooser.choice.value = 'dyson'
        app.structure.example.click()
        app._confirm_structure()
        app._confirm_settings()
        app._review()
        assert app.review is not None
        app._submit()
        assert len(submitted) == 1 and app.pages.selected_index == 2
        result = app.result_box.children[0]
        assert result.goal == 'dyson' and result.navigation.value == 'dyson'
        assert result.prerequisites.layout.display == ''
        assert result.tabs.panels['states'].plan is None
    finally:
        app.close()
