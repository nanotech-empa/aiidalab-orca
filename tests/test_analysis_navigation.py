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
        assert result.navigation.value == task
        assert result.prerequisites.layout.display == '' and panel.layout.display == 'none'
        assert 'prepare an orbital reference' in result.prerequisites.children[0].value
        result.prerequisites.children[1].click()
        assert result.navigation.value == 'prepare'
        assert panel.layout.display != 'none'
        assert panel.analysis.value == 'states' and panel.calculation.toggle.value
        assert panel.analysis.layout.display == 'none'
        assert panel.common_preparation.layout.display == '' and panel.sector_preparation.layout.display == 'none'
        assert panel.preparation_actions.children[1].disabled
        assert panel.guide.layout.display == 'none'
        assert panel.plan is None and panel._dyson is None
        assert (panel.electrons.value, panel.norb.value, panel.charge.value, panel.mult.value) == (2, 2, '0', '1')
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
        assert result.navigation.value == 'prepare' and result.goal == 'kondo'
        assert result.tabs._view_name == 'StackView'
        assert result.prerequisites.layout.display == 'none'
        assert panel.preparation_actions.children[1].disabled
        assert panel.calculation.toggle.value and panel.sector_preparation.layout.display == 'none'
        assert result.goal == 'kondo' and result.continue_goal.layout.display == ''
        assert app._requested_analysis is None
    finally:
        app.close()


def test_new_submission_opens_its_goal_after_reference_completes(source, monkeypatch, configured_orca_tools):
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
        assert result.goal == 'dyson' and result.navigation.value == 'prepare'
        assert result.tabs.panels['states'].preparation_actions.children[1].disabled
        assert result.tabs.panels['states'].plan is None
    finally:
        app.close()


def test_preparation_then_explicit_active_selection_precedes_state_requests(monkeypatch):
    from aiidalab_orca import casci, viewer, active_space_step
    from aiidalab_orca.app import close_widget_tree
    from aiidalab_orca.presentation import ComputePanel
    references = []
    ref = {'kind':'restricted','n_electrons':10,'n_orbitals':20,'charge':0,'source_multiplicity':1}
    monkeypatch.setattr(viewer,'molecule',lambda *args:ipw.Label('Geometry'))
    monkeypatch.setattr(casci.service,'reference_runs',lambda uuid:list(references))
    monkeypatch.setattr(casci.service,'reference_data',lambda uuid:dict(ref))
    monkeypatch.setattr(casci.service,'runs',lambda uuid:[])
    monkeypatch.setattr(casci.service,'results',lambda *args:[])

    class Inspection(ipw.VBox):
        def __init__(self, uuid, *, active_indices, apply_window, allow_reordering=False):
            self.apply_window = apply_window
            self.allow_reordering = allow_reordering
            self.export_code = ipw.Dropdown(options=[])
            self.orbitals = ipw.SelectMultiple(options=list(range(20)), value=tuple(active_indices))
            self.kind = ipw.Dropdown(options=['restricted'])
            self._job_uuid = None
            from aiidalab_orca.orbital_selection import OrbitalIndexInput
            self.selection_input = OrbitalIndexInput(self.orbitals)
            self.catalog_record = None
            self.calculation = ComputePanel('Read orbital information',[])
            super().__init__([self.calculation])

        def set_active(self, active):
            pass

    monkeypatch.setattr(active_space_step,'OrbitalInspection',Inspection)

    def unwanted(*args, **kwargs):
        raise AssertionError('Moving between stages must not submit a calculation')

    monkeypatch.setattr(casci.service,'prepare_common',unwanted)
    result = viewer.show_result(reference_data() | {'requested_analysis':'kondo'})
    try:
        result.open_goal('kondo')
        panel = result.tabs.panels['states']
        assert result.navigation.value == 'prepare' and result.confirmed_space is None
        references.append({'uuid':'common','kind':'restricted','reference_uuid':'prepared-orbitals'})
        panel._refresh()
        assert not panel.preparation_actions.children[1].disabled
        panel.preparation_actions.children[1].click()
        selection = result.tabs.panels['active']
        assert result.navigation.value == 'active' and not selection.inspection.calculation.toggle.value
        result.open_analysis('casci')
        assert panel.layout.display == 'none' and 'confirm the active space' in result.prerequisites.children[0].value
        result.prerequisites.children[1].click()
        selection.electrons.value,selection.norb.value = 4,4
        assert (panel.electrons.value,panel.norb.value) == (2,2)
        selection.confirm.click()
        assert result.navigation.value == 'energy'
        route = result.tabs.panels['energy']
        assert 'quantum' not in dict(route.choice.options).values()
        route.continue_button.click()
        assert result.navigation.value == 'casci'
        assert result.confirmed_space == ('common',4,4)
        assert panel.sector_preparation.layout.display == '' and panel.common_preparation.layout.display == 'none'
        assert not panel.calculation.toggle.value or panel.submit.disabled
        assert panel.plan is None
        result.open_analysis('active')
        assert result.tabs.panels['active'] is selection
        selection.inspection.apply_window([2,3,4,5,6])
        assert result.confirmed_space == ('common',6,5)
        assert result.navigation.value == 'energy' and result.goal == 'kondo'
        result.open_analysis('prepare')
        panel.reference.options = [('New reference','another-common')]
        result.open_analysis('casci')
        assert panel.layout.display == 'none' and result.prerequisites.layout.display == ''
        selection.confirm.click()
        assert 'reference changed' in selection.summary.value
        assert result.confirmed_space is None
    finally:
        close_widget_tree(result)
