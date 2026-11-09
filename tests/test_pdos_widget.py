"""User-facing selection, invalid-state handling and natural-orbital semantics."""
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from aiida_empa_orca.scripts.orbital_character import character
from aiidalab_orca import pdos_services
from aiidalab_orca.pdos import PdosPanel
from test_pdos import model


def widget(monkeypatch, *, kind='SCF', callback=None, uks=False, multiple_atoms=False, angular_shells=False):
    raw = model(uks=uks)
    if multiple_atoms:
        m = raw['Molecule']
        m['Charge'] += 2
        m['Atoms'] += [{'Idx':i, 'ElementLabel':'H', 'ElementNumber':1, 'NuclearCharge':1,
                       'Coords':pos} for i,pos in [(1,[1.,0.,0.]),(2,[0.,1.,0.])]]
        m['MolecularOrbitals']['OrbitalLabels'] = ['0C 1s','1H 1s','2H 1s','0C 2s']
    if angular_shells:
        table = raw['Molecule']['MolecularOrbitals']
        labels = table['OrbitalLabels'] + [f'0C {i+3}{l}0' for i, l in enumerate('dfghi')]
        nbf = len(labels)
        original = table['MOs']
        raw['Molecule']['S-Matrix'] = np.eye(nbf).tolist()
        table['OrbitalLabels'] = labels
        table['MOs'] = [dict(Occupancy=original[spin*4+i]['Occupancy'] if i < 4 else 0,
                            OrbitalEnergy=i*.1, MOCoefficients=np.eye(nbf)[:, i].tolist())
                        for spin in range(2 if uks else 1) for i in range(nbf)]
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


@pytest.mark.parametrize('mode', ['atoms', 'angular', 'pi'])
def test_all_projected_curves_and_legend_preserve_spin_colours(monkeypatch, mode):
    monkeypatch.setattr(pdos_services, 'submit', lambda *a, **kw: pytest.fail('Viewing must not submit'))
    panel = widget(monkeypatch, uks=True, angular_shells=True)
    saved = {name: values.copy() for name, values in panel.record['arrays'].items()}
    try:
        panel.mode.value = mode
        assert not panel.error.value
        root = ET.fromstring('<root>'+panel.plot.value+'</root>')
        ns = '{http://www.w3.org/2000/svg}'
        curves = {line.find(ns+'title').text: line for line in root.iter(ns+'polyline')
                  if line.find(ns+'title') is not None}
        legends = {}
        for span in root.iter('span'):
            box = span.find('span')
            if box is not None and box.find(ns+'svg') is not None:
                assert 'width:44px' in box.attrib['style'] and 'flex:0 0 44px' in box.attrib['style']
                legends[box.tail] = box.find(ns+'svg').find(ns+'line')
        expected = ['Total'] + (list('spdfghi') if mode == 'angular' else
                               ['Perpendicular p' if mode == 'pi' else 'Selected atoms'])
        assert set(curves) == {f'{name} · {spin}' for name in expected for spin in ('alpha', 'beta')}
        for label, curve in curves.items():
            assert curve.attrib['stroke'] == ('#2563b7' if label.endswith('alpha') else '#c83e4d')
        assert set(legends) == set(curves)
        for label, curve in curves.items():
            assert legends[label].attrib['stroke'] == curve.attrib['stroke']
            assert legends[label].attrib['stroke-dasharray'] == curve.attrib['stroke-dasharray']
        if mode == 'angular':
            patterns = {curves[f'{name} · alpha'].attrib['stroke-dasharray'] for name in expected}
            assert len(patterns) == len(expected)  # Total and each angular component are distinguishable.
            assert 'Colour identifies spin' in panel.plot.value
            for name in expected:
                assert curves[f'{name} · alpha'].attrib['stroke-dasharray'] == curves[f'{name} · beta'].attrib['stroke-dasharray']
        for name, values in saved.items():
            np.testing.assert_array_equal(panel.record['arrays'][name], values)
    finally:
        panel.close()
