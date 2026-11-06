"""Shared structure inspection with one-based atom selection and lazy playback."""

import ipywidgets as ipw
import numpy as np
from aiidalab_widgets_base.utils import list_to_string_range, string_range_to_list
from aiidalab_widgets_base.viewers import StructureDataViewer
from ase import Atoms

from .presentation import LazyTabs


class MolecularStructureViewer(StructureDataViewer):
    """Keep the standard viewer, measurement tools and selection expressions."""

    def __init__(self, structure=None, **kwargs):
        kwargs.setdefault('configuration_tabs', ['Selection', 'Appearance', 'Download'])
        super().__init__(structure=structure.copy() if structure is not None else None, **kwargs)
        self._closed = False
        self.observe(self._selection_text, names='selection')
        self._selected_atoms.placeholder = 'Atom numbers, e.g. 1 3..5'
        self._viewer.layout = ipw.Layout(width='100%', height='350px')
        self.layout.width = '100%'
        self.layout.min_width = '0'

    def _selection_text(self, event):
        self._selected_atoms.value = list_to_string_range(event['new'], shift=1)

    def apply_displayed_selection(self, _=None):
        selected, valid = string_range_to_list(self._selected_atoms.value, shift=-1)
        if valid and any(i < 0 or i >= self.natoms for i in selected):
            self.wrong_syntax.value = f'<p>Use atom numbers from 1 to {self.natoms}.</p>'
            self.wrong_syntax.layout.visibility = 'visible'
            return
        self.wrong_syntax.value = '<p>Invalid selection syntax.</p>'
        super().apply_displayed_selection(_)

    def set_active(self, active):
        if active and not self._closed:
            self._viewer._remote_call('handleResize', target='Widget')

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        self.unobserve(self._selection_text, names='selection')
        from .app import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()


def metadata_atoms(metadata):
    """Display the parser-validated native geometry in Angstrom, without mutation."""
    positions = np.array([row['Coords'] for row in metadata['atoms']], dtype=float)
    if metadata['coordinate_units'] == 'Bohr':
        positions *= .5291772105638411  # Same conversion as OrbitalCharacterParser.
    elif metadata['coordinate_units'] not in ('Angs', 'Angstrom'):
        raise ValueError('Unknown native geometry units')
    return Atoms(numbers=[row['ElementNumber'] for row in metadata['atoms']], positions=positions)


class GeometryInspection(ipw.VBox):
    """Measure final or selected-frame coordinates; retain separate trajectory controls."""

    def __init__(self, symbols, frames, final_positions, playback):
        self.symbols = list(symbols)
        self.frames = np.array(frames, dtype=float, copy=True)
        self.final_positions = np.array(final_positions, dtype=float, copy=True)
        self.viewer = MolecularStructureViewer(Atoms(self.symbols, positions=self.final_positions))
        self._playback_factory = playback
        self.playback_view = None
        self._active, self._closed = True, False
        self.frame = ipw.Dropdown(description='Inspect geometry', value=-1,
            options=[('Final geometry', -1)] + [(f'Optimization frame {i + 1}', i) for i in range(len(self.frames))],
            style={'description_width': 'initial'}, layout=ipw.Layout(width='auto'))
        self.frame.observe(self._frame_changed, names='value')
        geometry = ipw.VBox([self.frame, ipw.HTML('<p>Atom numbers start at <b>1</b>. Select two atoms for a distance, '
            'three for an angle, or four for a dihedral. Frame selection changes only the displayed geometry.</p>'), self.viewer])
        if len(self.frames) > 1:
            self.tabs = LazyTabs([('geometry', 'Geometry & measurements', lambda: geometry),
                                  ('trajectory', 'Optimization trajectory', self._playback)])
            self.tabs.observe(self._tab_changed, names='selected_index')
            children = [self.tabs]
        else:
            self.tabs = None
            self.frame.layout.display = 'none'
            children = [geometry]
        super().__init__(children, layout=ipw.Layout(width='100%', min_width='0'))

    def _frame_changed(self, event):
        selection = list(self.viewer.selection)
        positions = self.final_positions if event['new'] == -1 else self.frames[event['new']]
        self.viewer.structure = Atoms(self.symbols, positions=positions)
        self.viewer.input_selection = None
        self.viewer.input_selection = selection

    def _playback(self):
        self.playback_view = self._playback_factory(self.symbols, self.frames)
        # NGL renders its player itself; a second view of that Play model
        # interferes with the native controller's animation callbacks.
        return self.playback_view

    def _tab_changed(self, _=None):
        self.set_active(self._active)

    def set_active(self, active):
        self._active = active
        inspecting = self.tabs is None or self.tabs.selected_index == 0
        self.viewer.set_active(active and inspecting)
        if self.playback_view is not None and not (active and not inspecting):
            self.playback_view.player.widget_player.playing = False

    def close(self):
        if getattr(self, '_closed', False):
            return
        self.set_active(False)
        self._closed = True
        self.frame.unobserve(self._frame_changed, names='value')
        if self.tabs:
            self.tabs.unobserve(self._tab_changed, names='selected_index')
        from .app import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()


class GeometryOverview(ipw.VBox):
    """Forward result-section visibility to its geometry/trajectory controls."""

    def set_active(self, active):
        for child in self.children:
            if hasattr(child, 'set_active'):
                child.set_active(active)
