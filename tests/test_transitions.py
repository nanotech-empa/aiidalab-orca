"""Exact level/peak identities, visible dark transitions and linked selections."""
from copy import deepcopy
import json
import xml.etree.ElementTree as ET

import pytest

from aiida_empa_orca.dyson_data import HARTREE_EV
from aiidalab_orca.transitions import state_endpoints, peak_groups, intensity_color
from aiidalab_orca.spectra import SpectralViewer


def example():
    initial = dict(charge=0, multiplicity=2, root=0, energy_hartree=-100.)
    states = [dict(initial, state_uuid='neutral')]
    transitions = []
    for name, charge, mult, root, gap, weight in [
        ('rem0', 1, 1, 0, 10.813, .99),
        ('rem_dark', 1, 3, 0, 17.195, 0.),
        ('rem1', 1, 3, 1, 17.300, .9),
        ('add0', -1, 3, 0, 3.161, .9),
        ('add_dark', -1, 3, 1, 11.644, 0.),
        ('add1', -1, 1, 0, 4.395132, .6),
        ('add2', -1, 1, 1, 4.398341, .5)]:
        uuid = f'q{charge}m{mult}'
        states.append(dict(state_uuid=uuid, root=root, charge=charge, multiplicity=mult,
                           energy_hartree=-100.+gap/HARTREE_EV))
        transitions.append(dict(id=name, final_state_uuid=uuid, final_root=root, final_charge=charge,
            final_multiplicity=mult, side='removal' if charge == 1 else 'addition',
            energy_ev=-gap if charge == 1 else gap, strength=weight, final_ci_norm=1.))
    return states, dict(initial_state_uuid='neutral', initial_state=initial, transitions=transitions)


def svg(widget):
    return ET.fromstring(widget.value)


def test_endpoints_use_exact_state_uuid_and_root_and_check_energy_signs():
    states, table = example()
    initial, final = state_endpoints(states, table)
    assert initial == 'neutral:0' and final['rem1'] == 'q1m3:1'
    wrong = deepcopy(table)
    wrong['transitions'][0]['energy_ev'] *= -1
    with pytest.raises(ValueError, match='do not agree'):
        state_endpoints(states, wrong)
    wrong = deepcopy(table)
    wrong['transitions'][0]['final_state_uuid'] = 'another-calculation'
    with pytest.raises(ValueError, match='absent'):
        state_endpoints(states, wrong)


def test_unresolved_peak_targets_keep_both_poles_and_separate_when_zoomed():
    rows = [dict(id='a', pole_ev=4.395132), dict(id='b', pole_ev=4.398341)]
    groups = peak_groups(rows, -20., 12.)
    assert [r['id'] for r in groups[0]] == ['a', 'b']
    assert [r['pole_ev'] for r in groups[0]] == [4.395132, 4.398341]
    assert len(peak_groups(rows, 4.394, 4.4)) == 2


def test_dark_connector_is_black_and_remains_a_click_target():
    states, table = example()
    widget = SpectralViewer(table, states=states)
    try:
        widget._action(dict(action='select', ids=['add_dark']))
        group = next(e for e in svg(widget.diagram.plot).iter() if e.get('data-transition-id') == 'add_dark')
        assert json.loads(group.get('data-ids')) == ['add_dark']
        assert any(p.get('stroke') == '#000000' for p in group)
        assert intensity_color(0., 1.35) == '#000000'
        assert intensity_color(0., 0.) == '#000000'
        assert '0.00000' in widget.selection_info.value
    finally:
        widget.close()


def test_nearby_state_bars_keep_exact_energies_and_get_separate_horizontal_slots():
    states, table = example()
    widget = SpectralViewer(table, states=states)
    try:
        nodes = {e.get('data-state-key'):e for e in svg(widget.diagram.plot).iter() if e.get('data-state-key')}
        a, b = nodes['q-1m1:0'], nodes['q-1m1:1']
        assert float(a.get('data-energy')) == pytest.approx(4.395132)
        assert float(b.get('data-energy')) == pytest.approx(4.398341)
        assert list(a)[1].get('d') != list(b)[1].get('d')
        original = {key:node.get('data-energy') for key,node in nodes.items()}
        widget.shift.value = 2.
        shifted = {e.get('data-state-key'):e.get('data-energy') for e in svg(widget.diagram.plot).iter() if e.get('data-state-key')}
        assert shifted == original  # Spectral offset never moves a many-electron level.
    finally:
        widget.close()


def test_selection_links_spectrum_states_and_cg_readout_without_using_or_submitting():
    states, table = example()
    selected, used = [], []
    widget = SpectralViewer(table, states=states, on_selection=selected.append, on_use=used.append)
    try:
        widget._action(dict(action='select', ids=['add0']))
        assert widget.selected.value == ('add0',) and selected[-1] == ['add0']
        assert len(selected) == 1
        assert not used
        assert '1.35000' in widget.selection_info.value and '1.5' in widget.selection_info.value
        assert '3.161000' in widget.selection_info.value
        widget.spin.value = 'highest_ms_component'
        assert '0.90000' in widget.selection_info.value
        assert '3.161000' in widget.selection_info.value
        widget.use_selection.click()
        assert used == [['add0']]
        widget._action(dict(action='select', ids=['unknown']))
        assert widget.selected.value == ('add0',)
    finally:
        widget.close()


def test_drag_uses_outward_rounded_window_and_keeps_unresolved_contributors():
    states, table = example()
    widget = SpectralViewer(table, states=states)
    try:
        widget._action(dict(action='window', lower=4.395, upper=4.399))
        assert widget.mode.value == 'window'
        assert (widget.window_lower.value, widget.window_upper.value) == (4.39, 4.4)
        assert set(widget.selected.value) == {'add1', 'add2'}
        widget._action(dict(action='window', lower=5, upper=3))
        assert (widget.window_lower.value, widget.window_upper.value) == (4.39, 4.4)
    finally:
        widget.close()


def test_intensity_scale_does_not_rescale_when_filtering_branches_or_connections():
    states, table = example()
    widget = SpectralViewer(table, states=states)
    try:
        widget._action(dict(action='select', ids=['add1']))
        def colour():
            group = next(e for e in svg(widget.diagram.plot).iter() if e.get('data-transition-id') == 'add1')
            return [p.get('stroke') for p in group if p.get('stroke') not in ('#fbbf24','transparent',None)][0]
        first = colour()
        widget.side.value = 'addition'
        widget.diagram.mode.value = 'all'
        assert colour() == first
        assert '1.35' in widget.diagram.legend.value
    finally:
        widget.close()


def test_explicit_selection_reveals_hidden_pole_and_both_state_endpoints():
    states, table = example()
    widget = SpectralViewer(table, states=states)
    try:
        widget.side.value = 'addition'
        widget.lower.value,widget.upper.value = 3.,6.
        widget.diagram.lower.value,widget.diagram.upper.value = 0.,6.
        widget._action(dict(action='select',ids=['rem1']))
        assert widget.side.value == 'both'
        assert widget.lower.value < -17.3 and widget.diagram.upper.value > 17.3
        assert 'data-transition-id="rem1"' in widget.diagram.plot.value
    finally:
        widget.close()


def test_historical_dyson_uses_original_state_sectors_after_a_casci_rerun(aiida_profile):
    from aiida import orm
    from aiidalab_orca.dyson_services import diagram_states
    initial = dict(charge=0,multiplicity=2,root=0,energy_hartree=-100.)
    old = dict(charge=1,multiplicity=1,root=0,energy_hartree=-99.)
    neutral = orm.Dict(dict={'states':[initial]}).store()
    original = orm.Dict(dict={'states':[old]}).store()
    newer = dict(old,energy_hartree=-98.9,state_uuid='new-casci')
    context = [dict(initial,state_uuid=str(neutral.uuid)),newer,
               dict(charge=0,multiplicity=4,root=0,energy_hartree=-99.8,state_uuid='quartet')]
    table = dict(initial_state_uuid=str(neutral.uuid),initial_state=initial,
                 transitions=[dict(id='rem',final_state_uuid=str(original.uuid),final_root=0,side='removal',energy_ev=-HARTREE_EV)])
    rows = diagram_states(table,context)
    assert len(rows) == 3
    assert not any(r['state_uuid']=='new-casci' for r in rows)
    assert any(r['state_uuid']=='quartet' for r in rows)
    assert state_endpoints(rows,table)[1]['rem'] == str(original.uuid)+':0'
