"""A peak request prepares the full map without manual cube picking or submission."""
from copy import deepcopy
from types import SimpleNamespace

import ipywidgets as ipw
import pytest

from aiidalab_orca import dyson as frontend
from aiidalab_orca.presentation import ComputePanel


def transition_table():
    return dict(initial_state=dict(multiplicity=2), transitions=[
        dict(id='t'+str(i),energy_ev=pole,strength=.4,side='addition' if pole>0 else 'removal',
             final_multiplicity=1,final_charge=-1 if pole>0 else 1,final_root=i,final_ci_norm=1.)
        for i,pole in enumerate((-2.,1.,1.04))])


def map_panel(ids, table_uuid='table', retention='stash', complete=True):
    controls=dict(source=dict(table_uuid=table_uuid,
        manifest=dict(retention=retention,cubes=[dict(kind='dyson',transition_id=i) for i in ids])),
        kind=ipw.ToggleButtons(options=['individual','blend']),
        selection=ipw.SelectMultiple(options=[(i,i) for i in ids],value=tuple(ids)),
        review=ipw.Button(), compute=ipw.Button(disabled=True),
        calculation=ComputePanel('Map setup',[]), plan=None)
    panel=ipw.VBox(children=[value for value in controls.values() if isinstance(value,ipw.Widget)])
    for name,value in controls.items():
        setattr(panel,name,value)
    if complete:
        panel.complete=ipw.Checkbox(value=False)
    panel.invalidate=lambda: (setattr(panel,'plan',None),setattr(panel.compute,'disabled',True))
    return panel


@pytest.fixture
def peak_panel(monkeypatch):
    rows=[dict(state_uuid='initial',root=0,charge=0,multiplicity=2,energy_hartree=-10.)]
    monkeypatch.setattr(frontend.service,'states',lambda _:rows)
    monkeypatch.setattr(frontend.service,'codes',lambda _:dict(export=[],dyson=[('Dyson','code')],cubehandler=[('Cubes','cubes')]))
    monkeypatch.setattr(frontend.service,'runs',lambda *_:[])
    monkeypatch.setattr(frontend.service,'cube_runs',lambda _:[])
    monkeypatch.setattr(frontend.service,'progress',lambda _:dict(finished=True,success=True))
    monkeypatch.setattr(frontend.service,'result',lambda _:dict(data=deepcopy(transition_table()),transitions_uuid='table'))
    monkeypatch.setattr(frontend.service,'diagram_states',lambda *_:[])
    monkeypatch.setattr(frontend.service,'map_cube_inventory',lambda _:dict(cube_uuid=None,running_uuid=None,available_count=0))
    submitted=[]
    monkeypatch.setattr(frontend.service,'submit_cubes',lambda **_:submitted.append('cubes'))
    monkeypatch.setattr(frontend.service,'submit_dyson',lambda *_:submitted.append('dyson'))
    opened=[]
    widget=frontend.DysonStates('common',[dict(reference_charge=0)],on_show_maps=lambda:opened.append('maps'))
    widget._open_previous({'new':'dyson-result'})
    widget.cube_states.value=(1,)
    widget.spectrum.selected.value=('t1',)
    yield widget,submitted,opened
    widget.map_panel=None
    widget.close()


def use_positive_peak(widget):
    peak=next(row['energy_ev'] for row in widget.spectrum.peak_rows if row['energy_ev']>0)
    widget.spectrum.peak_choices.value=peak
    widget.spectrum.use_peak.click()
    return peak


def test_peak_selects_every_amplitude_and_opens_review_without_a_job(peak_panel):
    widget,submitted,opened=peak_panel
    peak=use_positive_peak(widget)
    assert widget.cube_states.value==(0,1,2) and widget.cube_states.disabled
    assert widget.spectrum.selected.value==('t1',)
    assert widget.cube_calculation.toggle.value and widget._view=='maps'
    assert 'Step 1 of 2' in widget.peak_map_status.value
    assert '0 of 3' in widget.peak_map_status.value
    assert widget.spectrum.blend()['energy_ev']==peak
    widget._review_cubes()
    assert len(widget.cube_plan['parameters']['orbitals'])==3
    assert widget.cube_plan['blend'] is None  # A 3D intensity cube is not required for maps.
    assert submitted==[] and opened==['maps']
    widget.retention.value='delete'
    widget._review_cubes()
    assert widget.cube_plan is None and widget.cube_submit.disabled
    assert 'Select Stash or Leave' in widget.cube_message.value


@pytest.mark.parametrize('complete_control',[False,True])
def test_saved_complete_set_opens_full_spectral_map_without_generating_cubes(peak_panel,monkeypatch,complete_control):
    widget,submitted,_=peak_panel
    monkeypatch.setattr(frontend.service,'map_cube_inventory',lambda _:dict(cube_uuid='saved',running_uuid=None,available_count=3))
    selected=[]
    def refresh(uuid):
        selected.append(uuid)
        widget.map_panel=map_panel(['t0','t1','t2'],complete=complete_control)
        widget.map_box.children=(widget.map_panel,)
    monkeypatch.setattr(widget,'_refresh_cubes',refresh)
    peak=use_positive_peak(widget)
    assert selected==['saved'] and submitted==[]
    assert widget.map_panel.kind.value=='blend' and widget.map_panel.kind.disabled
    assert widget.map_panel.selection.value==('t0','t1','t2')
    assert widget.map_panel.calculation.toggle.value
    assert not widget.cube_calculation.toggle.value and widget.map_box.selected_index==0
    assert 'Step 2 of 2' in widget.peak_map_status.value and 'no new cubes' in widget.peak_map_status.value
    assert widget.spectrum.blend()['energy_ev']==peak
    widget.spectrum.eta.value=.2
    assert widget._peak_map_request is None and not widget.cube_states.disabled
    assert not widget.map_panel.kind.disabled and 'Spectral settings changed' in widget.peak_map_status.value


def test_pending_peak_survives_cube_generation_and_enables_map_step(peak_panel):
    widget,submitted,_=peak_panel
    peak=use_positive_peak(widget)
    widget.map_panel=map_panel(['t0','t1'])
    widget._sync_peak_map()
    assert widget.map_panel.review.disabled and widget.cube_calculation.toggle.value
    widget.map_panel=map_panel(['t0','t1','t2'])
    widget.map_box.children=(widget.map_panel,)
    widget._sync_peak_map()
    assert widget.map_panel.kind.value=='blend' and widget.map_panel.complete.value
    assert not widget.map_panel.review.disabled and 'Step 2 of 2' in widget.peak_map_status.value
    assert widget._peak_map_request['blend']['energy_ev']==peak and submitted==[]
    widget._use_transition_selection(['t1'])
    assert widget._peak_map_request is None and not widget.cube_states.disabled
    assert widget.cube_states.value==(1,) and widget.map_panel.kind.value=='individual'
    assert not widget.map_panel.complete.value and widget.map_panel.selection.value==('t1',)


def test_existing_running_set_is_opened_without_duplicate_submission(peak_panel,monkeypatch):
    widget,submitted,_=peak_panel
    monkeypatch.setattr(frontend.service,'map_cube_inventory',lambda _:dict(cube_uuid=None,running_uuid='running',available_count=1))
    selected=[]
    monkeypatch.setattr(widget,'_refresh_cubes',lambda uuid:selected.append(uuid))
    use_positive_peak(widget)
    assert selected==['running'] and submitted==[]
    assert 'already running' in widget.peak_map_status.value and not widget.cube_calculation.toggle.value


def test_inventory_rejects_deleted_sets_and_combining_partial_runs(monkeypatch):
    from aiidalab_orca import dyson_services as service
    def saved(ids,retention='stash'):
        return SimpleNamespace(is_finished_ok=True,is_terminated=True,
            outputs=SimpleNamespace(manifest=SimpleNamespace(get_dict=lambda:dict(retention=retention,
                cubes=[dict(kind='dyson',transition_id=i) for i in ids]))))
    def running(indices,retention='stash'):
        return SimpleNamespace(is_finished_ok=False,is_terminated=False,
            inputs=SimpleNamespace(parameters=SimpleNamespace(get_dict=lambda:dict(retention=retention,orbitals=[[0,i] for i in indices]))))
    nodes={'table':SimpleNamespace(get_dict=transition_table),'a':saved(['t0','t1']),
        'b':saved(['t2']),'deleted':saved(['t0','t1','t2'],'delete'),
        'partial-running':running([0,1]),'running':running([0,1,2])}
    monkeypatch.setattr(service.orm,'load_node',lambda uuid:nodes[uuid])
    monkeypatch.setattr(service,'cube_runs',lambda _:[(key,key) for key in nodes if key!='table'])
    result=service.map_cube_inventory('table')
    assert result==dict(cube_uuid=None,running_uuid='running',available_count=2)
    nodes['saved']=saved(['t0','t1','t2'])
    assert service.map_cube_inventory('table')==dict(cube_uuid='saved',running_uuid='running',available_count=3)
