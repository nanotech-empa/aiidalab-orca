"""Shared measurement tools, final coordinates and independent trajectory playback."""
import ipywidgets as ipw
import numpy as np
import pytest
from ase import Atoms
from aiidalab_widgets_base.viewers import StructureDataViewer

from aiidalab_orca.geometry_viewer import GeometryInspection, MolecularStructureViewer, metadata_atoms


def test_shared_viewer_supports_one_based_measurements_without_editing_input():
    atoms = Atoms('OH2', positions=[[0,0,0],[1,0,0],[0,1,0]])
    original = atoms.positions.copy()
    view = MolecularStructureViewer(atoms)
    try:
        assert isinstance(view, StructureDataViewer)
        assert view.structure_node is None
        view._selected_atoms.value = '1 2'
        view.apply_displayed_selection()
        assert view.selection == [0,1]
        assert 'Distance: 1.00' in view.selection_info.value
        view._selected_atoms.value = '2 1 3'
        view.apply_displayed_selection()
        assert 'Angle: 90.0' in view.selection_info.value
        np.testing.assert_array_equal(atoms.positions, original)
    finally:
        view.close()


@pytest.mark.parametrize('text', ['0', '4', '1..4'])
def test_bad_atom_numbers_cannot_wrap_to_an_existing_atom(text):
    view = MolecularStructureViewer(Atoms('OH2', positions=[[0,0,0],[1,0,0],[0,1,0]]))
    try:
        view.input_selection = [0,1]
        view._selected_atoms.value = text
        view.apply_displayed_selection()
        assert view.selection == [0,1]
        assert view.wrong_syntax.layout.visibility == 'visible'
    finally:
        view.close()


def test_frame_inspection_preserves_selection_and_uses_exact_final_coordinates():
    frames = np.array([[[0,0,0],[0,0,1]], [[0,0,0],[0,0,1.2]]])
    final = [[0,0,0],[0,0,1.23456789]]
    calls = []

    class Playback(ipw.VBox):
        def __init__(self):
            from types import SimpleNamespace
            self.play = ipw.Play()
            self.player = SimpleNamespace(widget_player=self.play)
            super().__init__([self.play])

    def factory(symbols, data):
        calls.append((symbols, data.copy()))
        return Playback()

    view = GeometryInspection(['C','O'], frames, final, factory)
    try:
        assert not calls  # Playback is constructed only on request.
        np.testing.assert_array_equal(view.viewer.structure.positions, final)
        view.viewer.input_selection = [0,1]
        view.frame.value = 0
        assert view.viewer.selection == [0,1]
        assert 'Distance: 1.00' in view.viewer.selection_info.value
        view.frame.value = -1
        assert 'Distance: 1.23' in view.viewer.selection_info.value
        np.testing.assert_array_equal(view.viewer.structure.positions, final)
        view.tabs.show_section('trajectory')
        assert len(calls) == 1
        assert view.tabs.panels['trajectory'] is view.playback_view
        view.playback_view.player.widget_player.playing = True
        view.set_active(False)
        assert not view.playback_view.player.widget_player.playing
        view.tabs.show_section('geometry')
        assert view.viewer.selection == [0,1]
        np.testing.assert_array_equal(frames[0], [[0,0,0],[0,0,1]])
    finally:
        view.close()


def test_native_geometry_display_converts_units_without_mutating_metadata():
    metadata = {'coordinate_units':'Bohr', 'atoms':[{'ElementNumber':1,'Coords':[0.,0.,2.]}]}
    atoms = metadata_atoms(metadata)
    assert atoms.positions[0,2] == pytest.approx(1.0583544211276822)
    assert metadata['atoms'][0]['Coords'][2] == 2.
