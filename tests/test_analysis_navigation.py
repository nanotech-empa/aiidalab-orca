"""Analysis choices retain their reference and never submit prerequisites."""

import ipywidgets as ipw
import pytest

from test_result_navigation import reference_data
from test_reuse import source  # noqa: F401 -- isolated finished-run fixture


@pytest.mark.parametrize('task', ['casci', 'dyson', 'kondo'])
def test_missing_states_open_preparation_without_changing_the_model(monkeypatch, task):
    from aiidalab_orca import casci, viewer
    from aiidalab_orca.app import close_widget_tree
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))
    monkeypatch.setattr(casci.service, 'reference_runs', lambda uuid: [])

    def unwanted(*args, **kwargs):
        raise AssertionError('Navigation must not submit a prerequisite')

    monkeypatch.setattr(casci.service, 'prepare_common', unwanted)
    result = viewer.show_result(reference_data())
    try:
        result.analysis_chooser.buttons[task].click()
        panel = result.tabs.panels['states']
        assert panel.source_uuid == 'reference'
        assert panel.analysis.value == 'states' and panel.calculation.toggle.value
        assert panel.plan is None and panel._dyson is None
        assert (panel.electrons.value, panel.norb.value, panel.charge.value, panel.mult.value) == (2, 2, 0, 1)
        assert panel.common_submit.disabled and panel.submit.disabled
        if task != 'casci':
            assert 'First prepare the CASCI states' in result.analysis_hint.value
    finally:
        close_widget_tree(result)


def test_analysis_switches_reuse_the_same_state_workspace(monkeypatch):
    from aiidalab_orca import viewer, casci
    from aiidalab_orca.app import close_widget_tree
    monkeypatch.setattr(viewer, 'molecule', lambda *args: ipw.Label('Geometry'))

    class SavedStates(ipw.VBox):
        def __init__(self, data, **kwargs):
            self.reference = ipw.Dropdown(options=[('Saved common orbitals', 'common')])
            self.analysis = ipw.ToggleButtons(options=['states', 'spectrum', 'kondo'])
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


def test_start_page_choice_opens_selected_reference_in_requested_workspace(source, monkeypatch):
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
        assert app.analysis_chooser in app.draft_panel.children
        app.analysis_chooser.buttons['kondo'].click()
        assert app.pages.selected_index == 1 and app._requested_analysis == 'kondo'
        assert 'View results' in app.analysis_hint.value
        app.history.select(source.uuid)
        assert not app.history.view.disabled
        app.history.view.click()
        assert not app.error.value
        assert app.pages.selected_index == 2 and app.process_uuid == source.uuid
        result = app.result_box.children[0]
        panel = result.tabs.panels['states']
        assert panel.source_uuid == source.uuid and panel.calculation.toggle.value
        assert 'Kondo' in result.analysis_hint.value
        assert 'First prepare the CASCI states' in result.analysis_hint.value
        assert app._requested_analysis is None and app.analysis_hint.layout.display == 'none'
    finally:
        app.close()
