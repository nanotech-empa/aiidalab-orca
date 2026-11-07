"""User-facing selection, invalid-state handling and natural-orbital semantics."""
import pytest

from aiida_empa_orca.scripts.orbital_character import character
from aiidalab_orca import pdos_services
from aiidalab_orca.pdos import PdosPanel
from test_pdos import model


def widget(monkeypatch, *, kind='SCF', callback=None, uks=False, multiple_atoms=False):
    raw = model(uks=uks)
    if multiple_atoms:
        m = raw['Molecule']
        m['Charge'] += 2
        m['Atoms'] += [{'Idx':i, 'ElementLabel':'H', 'ElementNumber':1, 'NuclearCharge':1,
                       'Coords':pos} for i,pos in [(1,[1.,0.,0.]),(2,[0.,1.,0.])]]
        m['MolecularOrbitals']['OrbitalLabels'] = ['0C 1s','1H 1s','2H 1s','0C 2s']
    meta, arrays = character(raw, kind)
    record = {'uuid': 'native-character-job', 'metadata_uuid': 'metadata', 'arrays_uuid': 'arrays',
              'metadata': meta, 'arrays': arrays}
    monkeypatch.setattr(pdos_services, 'context', lambda _: {'sets': {kind: 'aiida.gbw'}})
    monkeypatch.setattr(pdos_services, 'codes', lambda _: {'export': [], 'character': []})
    monkeypatch.setattr(pdos_services, 'latest', lambda *args: record)
    return PdosPanel('source', kind=kind, on_select=callback)


def test_click_selects_the_exact_orbital_and_sends_existing_preview_selection(monkeypatch):
    selected = []
    panel = widget(monkeypatch, callback=selected.append)
    row = panel._visible[0]
    panel.plot._receive(None, {'action': 'select', 'ids': [row]}, None)
    assert panel.levels.value == (row,)
    panel._send_selection()
    assert selected == [[(0, row)]]
    assert 'data-ids' in panel.plot.value
    panel.close()


def test_UNO_view_has_occupations_and_no_DOS_or_energy_controls(monkeypatch):
    panel = widget(monkeypatch, kind='UNO')
    assert panel.width.layout.display == 'none'
    assert panel.lower.description == 'First orbital'
    assert 'Natural orbital index' in panel.plot.value
    assert 'KS-energy' in panel.note.value
    panel.close()


def test_invalid_plane_is_reported_and_does_not_silently_reorient(monkeypatch):
    panel = widget(monkeypatch)
    panel.normal.value = '0 0 0'
    assert 'nonzero' in panel.error.value
    assert panel.normal.value == '0 0 0'
    assert panel.plot.value == ''
    assert panel.select.disabled
    panel.close()


def test_saved_character_reuse_needs_neither_remote_code_nor_submission(monkeypatch):
    panel = widget(monkeypatch)
    monkeypatch.setattr(pdos_services, 'submit', lambda *a: pytest.fail('Saved character must not be resubmitted'))
    panel._compute()
    assert 'Saved character' in panel.status.value
    panel.close()


def test_total_DOS_dash_colours_follow_the_spin_channels(monkeypatch):
    panel = widget(monkeypatch, uks=True)
    for name, colour in [('alpha','#2563b7'), ('beta','#c83e4d')]:
        assert f'stroke="{colour}" stroke-width="2" stroke-dasharray="5 4"><title>Total · {name}</title>' in panel.plot.value
    panel.close()


def test_standard_one_based_viewer_selection_and_element_filter_are_linked(monkeypatch):
    panel = widget(monkeypatch, multiple_atoms=True)
    view = panel.structure_viewer
    assert view.selection == [0]  # Initial carbon fragment.
    view._selected_atoms.value = '2..3'
    view.apply_displayed_selection()
    assert panel.atoms.value == (1,2) and panel.element.value == 'H'
    assert 'Angle:' not in view.selection_info.value
    assert 'Distance:' in view.selection_info.value
    assert panel.error.value == ''
    view._selected_atoms.value = '1 3'
    view.apply_displayed_selection()
    assert panel.atoms.value == (0,2) and panel.element.value == 'custom'
    panel.element.value = 'all'
    assert view.selection == [0,1,2]
    assert '1..3' in view._selected_atoms.value
    panel.close()
