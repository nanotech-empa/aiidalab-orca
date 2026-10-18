"""Molecular adapter for the existing AiiDAlab QE IR/Raman viewer.

No phonopy cell, periodic NAC correction or Born-charge conversion is applied
to ORCA molecular data. Models retain only serialized arrays and node UUIDs.
"""

import numpy as np
import ipywidgets as ipw
import traitlets as tl
from ase import Atoms
from aiidalab_qe_vibroscopy.app.widgets.ramanmodel import RamanModel
from aiidalab_qe_vibroscopy.app.widgets.ramanwidget import RamanWidget
from aiidalab_qe_vibroscopy.utils.mode_projection import atom_participation
from aiida_vibroscopy.utils.spectra import raman_prefactor


class MolecularResponse:
    """Plain-data implementation of the optical interface used by the viewer."""

    def __init__(self, record, activity=False):
        arrays = record['arrays']
        indices = np.asarray(arrays['mode_indices'], dtype=int)
        frequencies = np.asarray(arrays['frequencies'])
        self.indices = indices[frequencies[indices] > 0]
        self.frequencies = frequencies[self.indices]
        self.arrays = {key: np.asarray(value) for key, value in arrays.items()}
        self.activity = activity

    def prefactor(self, frequency_laser, temperature):
        if self.activity:
            return np.ones_like(self.frequencies)
        if not np.isfinite(temperature) or temperature < 0:
            raise ValueError('Temperature must be finite and nonnegative')
        if not np.isfinite(frequency_laser) or frequency_laser <= 0:
            raise ValueError('Laser wavelength must be finite and positive')
        if np.any(1e7/frequency_laser <= self.frequencies):
            raise ValueError('For this Stokes spectrum the laser energy must exceed all displayed vibrational energies')
        return raman_prefactor(frequency=self.frequencies, frequency_laser=frequency_laser,
                              temperature=temperature, absolute=False)

    def run_powder_raman_intensities(self, *, frequency_laser, temperature, **kwargs):
        activity = self.arrays['raman_activities'][self.indices] * self.prefactor(frequency_laser, temperature)
        rho = self.arrays['depolarizations'][self.indices]
        parallel = activity/(1+rho)
        return parallel, parallel*rho, self.frequencies, None

    def run_powder_ir_intensities(self, **kwargs):
        return self.arrays['ir_intensities'][self.indices], self.frequencies, None

    @staticmethod
    def polarization(value):
        vector = np.asarray(value, dtype=float)
        if vector.shape != (3,) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
            raise ValueError('Polarization requires a finite nonzero three-component vector')
        return vector/np.linalg.norm(vector)

    def run_single_crystal_raman_intensities(self, *, pol_incoming, pol_outgoing, frequency_laser, temperature, **kwargs):
        incoming, outgoing = self.polarization(pol_incoming), self.polarization(pol_outgoing)
        tensors = self.arrays['raman_tensors'][self.indices]
        intensity = 45*np.einsum('i,mij,j->m', outgoing, tensors, incoming)**2
        return intensity*self.prefactor(frequency_laser, temperature), self.frequencies, None

    def run_single_crystal_ir_intensities(self, *, pol_incoming, **kwargs):
        incoming = self.polarization(pol_incoming)
        dipoles = self.arrays['transition_dipoles'][self.indices]
        norm = np.sum(dipoles**2, axis=1)
        fraction = np.divide((dipoles@incoming)**2, norm, out=np.zeros_like(norm), where=norm > 0)
        return self.arrays['ir_intensities'][self.indices]*fraction, self.frequencies, None


class MolecularRamanModel(RamanModel):
    activity = tl.Bool(False)

    def __init__(self, record, **kwargs):
        self.record = record  # Serialized data only; never an ORM node.
        super().__init__(**kwargs)

    def get_raman_data(self):
        return MolecularResponse(self.record, self.activity)

    def _refresh_modes(self):
        response = self.get_raman_data()
        if not len(response.indices):
            raise ValueError('No positive vibrational modes are available for a harmonic spectrum')
        self.eigenvectors = response.arrays['displacements'][response.indices]
        self._atom_participation = atom_participation(self.eigenvectors,
            response.arrays['masses'], response.frequencies)
        self._mode_frequencies = response.frequencies
        self.raw_frequencies = response.frequencies
        self.labels = [f'ORCA mode {index}' for index in response.indices]
        self.rounded_frequencies = np.round(response.frequencies, 2).tolist()
        self.active_modes_options = self._get_active_modes_options()
        self.active_mode = min(self.active_mode, len(response.indices)-1)

    def _update_spectrum_options(self):
        self.plot_type_options = [('Orientation average', 'powder'), ('Fixed orientation', 'single_crystal')]

    def update_data(self):
        if not np.isfinite(self.broadening) or self.broadening <= 0:
            raise ValueError('Broadening must be finite and positive')
        super().update_data()

    def _update_powder_data(self):
        super()._update_powder_data()
        if self._has_separate_polarizations():
            # Preserve the depolarization ratio in the displayed spectrum.
            # Independent peak normalization of the two channels loses it.
            _, parallel = self.generate_plot_data(self.raw_frequencies, self.raw_pol_intensities,
                self.broadening, x_range=self.frequencies, normalize=False)
            _, crossed = self.generate_plot_data(self.raw_frequencies, self.raw_depol_intensities,
                self.broadening, x_range=self.frequencies, normalize=False)
            scale = np.max(parallel+crossed, initial=0)
            self.intensities = parallel/scale if scale > 0 else parallel
            self.intensities_depolarized = crossed/scale if scale > 0 else crossed

    def _project_spectrum(self, intensities):
        total = (np.asarray(self.raw_pol_intensities)+np.asarray(self.raw_depol_intensities)
                 if self._has_separate_polarizations() else np.asarray(self.raw_intensities))
        _, full = self.generate_plot_data(self.raw_frequencies, total, self.broadening,
            x_range=self.frequencies, normalize=False)
        _, selected = self.generate_plot_data(self.raw_frequencies,
            np.asarray(intensities)*self.projection_weights, self.broadening,
            x_range=self.frequencies, normalize=False)
        scale = np.max(full, initial=0)
        return selected/scale if scale > 0 else selected

    def download_data(self, event=None):
        import base64
        import json
        exported = {'source_workflow_uuid': self.record['uuid'], 'vibrational_data_uuid': self.record['data_uuid'],
            'summary': self.record['summary'], 'symbols': self.record['symbols'], 'positions_angstrom': self.record['positions'],
            'raw_arrays': self.record['arrays'], 'view': {'spectrum': self.spectrum_type,
            'orientation': self.plot_type, 'polarization_in': self.pol_incoming, 'polarization_out': self.pol_outgoing,
            'raman_activity': self.activity, 'temperature_kelvin': self.temperature, 'laser_wavelength_nm': self.frequency_laser,
            'broadening_cm-1': self.broadening, 'selected_atoms': self.selected_atoms,
            'normalization': 'common maximum for total and polarization/participation channels'},
            'wavenumber_cm-1': np.asarray(self.frequencies).tolist(), 'display_curve': np.asarray(self.intensities).tolist(),
            'display_depolarized_curve': np.asarray(self.intensities_depolarized).tolist()}
        self._download(base64.b64encode(json.dumps(exported, indent=2).encode()).decode(), 'molecular-spectrum.json')

    def update_plot(self, plot):
        super().update_plot(plot)
        plot.layout.title.text = ('Orientation averaged' if self.plot_type == 'powder' else 'Fixed orientation') + f' {self.spectrum_type} spectrum'
        plot.layout.yaxis.title.text = ('Raman activity' if self.activity and self.spectrum_type == 'Raman' else 'Intensity') + ' (relative scale)'

    def mode_animation_state(self, playing=True):
        from weas_widget.phonon import generate_phonon_trajectory
        from weas_widget.utils import ASEAdapter
        eigenvector = self.eigenvectors[self.active_mode]
        trajectory = generate_phonon_trajectory(self.input_structure,
            np.stack((eigenvector, np.zeros_like(eigenvector)), axis=-1),
            kpoint=[0, 0, 0], amplitude=self.amplitude, nframes=20)
        return {'version': 'weas_state_v1', 'atoms': ASEAdapter.to_weas(trajectory),
            'state': {'animation': {'isPlaying': playing, 'frameDuration': 100, 'currentFrame': 0},
                'plugins': {'vectorField': {'settings': {'mode': {'origins': 'positions', 'vectors': 'movement',
                    'factor': self.amplitude * .6, 'color': 'black', 'radius': .1}}}}}}


class MolecularSpectrum(RamanWidget):
    def __init__(self, record, spectrum_type):
        atoms = Atoms(record['symbols'], positions=record['positions'], pbc=False)
        model = MolecularRamanModel(record)
        super().__init__(model, record['data_uuid'], atoms, spectrum_type)

    def _initial_view(self):
        # Keep widget views attached once. Re-displaying WEAS inside an Output
        # on every mode change races classic-notebook widget attachment.
        self._model.update_data()
        self._model._update_spectrum_options()
        for widget in (self.nac_direction, self.help_nac_direction, self.plane_type):
            widget.layout.display = 'none'
        if self._model.spectrum_type == 'IR':
            for widget in (self.temperature, self.frequency_laser, self.pol_outgoing, self.separate_polarizations):
                widget.layout.display = 'none'
        self._model.update_plot(self.spectrum)
        from weas_widget import WeasWidget
        state = self._model.mode_animation_state()
        old_weas = self.weas
        # Supply all frames at creation: WEAS reads phonon/viewerStyle only on
        # mount, and a delayed static-atoms update can replace a new trajectory.
        self.weas = WeasWidget(atoms=state['atoms'], animationState=state['state']['animation'],
            vectorField=state['state']['plugins']['vectorField']['settings'],
            viewerStyle={'width': '100%', 'height': '420px'}, guiConfig=self.guiConfig,
            modelStyle=1, colorType='JMOL', cameraSetting={'direction': [1, 1, 1]})
        self.weas.layout = ipw.Layout(width='100%', min_width='0')
        self.weas._widget.layout = ipw.Layout(width='100%', min_width='0', flex='1 1 auto')
        old_table, old_animation = self.modes_table, self.animation
        self.modes_table = ipw.HTML(self._model.modes_table(), layout=ipw.Layout(max_height='250px', overflow='auto', min_width='240px'))
        modes_box = self.children[-2].children[0]
        modes_box.children = (ipw.HTML('<b>Normal modes</b>'), self.modes_table)
        self.animation = ipw.VBox([self.weas], layout=ipw.Layout(width='100%', min_width='0'))
        self.children = self.children[:-1] + (self.animation,)
        old_table.close()
        old_animation.close()
        old_weas._widget.close()
        old_weas.close()

    def render(self):
        if self.rendered:
            return
        super().render()
        self.use_nac_direction.layout.display = 'none'
        self.supercell_selector.layout.display = 'none'
        self._model._update_spectrum_options()
        self._model.update_plot(self.spectrum)
        self.spectrum.layout.width = None
        self.spectrum.layout.autosize = True
        self.play_animation = ipw.ToggleButton(value=True, description='Pause animation', icon='pause',
            layout=ipw.Layout(width='auto'))
        self.play_animation.observe(self._playback_changed, names='value')
        self.weas._widget.observe(self._playback_state_changed, names='animationState')
        mode_controls = self.children[-2].children[1]
        mode_controls.children = (*mode_controls.children, self.play_animation)
        self.measure = ipw.ToggleButtons(options=[('Intensity', False), ('Activity', True)],
            description='Show', layout=ipw.Layout(display='' if self._model.spectrum_type == 'Raman' else 'none'))
        ipw.link((self.measure, 'value'), (self._model, 'activity'))
        self.measure.observe(self._measure_changed, names='value')
        self.lower = ipw.FloatText(value=max(0., float(min(self._model.raw_frequencies))-200), description='Minimum (cm⁻¹)')
        self.upper = ipw.FloatText(value=float(max(self._model.raw_frequencies))+200, description='Maximum (cm⁻¹)')
        self.range_button = ipw.Button(description='Apply range', icon='arrows-h', layout=ipw.Layout(width='auto'))
        self.range_button.on_click(self._range_changed)
        self.children = (self.children[0], ipw.HTML('<p>Isolated molecule · harmonic frequencies · no empirical frequency scaling. '
            'Click a mode marker to animate it. Atom selection shows mode participation, not an additive decomposition of optical intensity.</p>'),
            self.measure, *self.children[2:]) + (ipw.HBox([self.lower, self.upper, self.range_button]),)
        self._add_mode_markers()

    def _add_mode_markers(self):
        import plotly.graph_objects as go
        from aiida_vibroscopy.utils.broadenings import multilorentz
        intensities = np.asarray(self._model.raw_intensities)
        if self._model._has_separate_polarizations():
            intensities = np.asarray(self._model.raw_pol_intensities)+np.asarray(self._model.raw_depol_intensities)
        heights = multilorentz(self._model.raw_frequencies, self._model.raw_frequencies, intensities, self._model.broadening)
        curve = multilorentz(self._model.frequencies, self._model.raw_frequencies, intensities, self._model.broadening)
        scale = np.max(curve, initial=0)
        self.spectrum.add_trace(go.Scatter(x=self._model.raw_frequencies, y=heights/scale if scale > 0 else heights,
            mode='markers', marker={'size': 7, 'color': '#237b98'}, name='Modes',
            text=self._model.labels, hovertemplate='%{text}: %{x:.2f} cm⁻¹<extra></extra>'))
        self.spectrum.data[-1].on_click(self._mode_clicked)

    def _mode_clicked(self, trace, points, state):
        if points.point_inds:
            self.active_modes.value = int(points.point_inds[0])

    def _on_plot_button_click(self, event):
        from html import escape
        self._model.selected_atoms = self.atom_controls.selection.value
        self._model.selected_only = self.atom_controls.selected_only.value
        try:
            self._model.update_data()
            self._model.update_plot(self.spectrum)
            self.modes_table.value = self._model.modes_table()
            self._select_active_mode(None)
            self.atom_controls.message.value = (f'{len(self._model.selected_indices)} atoms selected.'
                                                if self._model.selected_indices else '')
            self._add_mode_markers()
        except (ValueError, TypeError) as exc:
            self.atom_controls.message.value = '<div class="alert alert-danger">'+escape(str(exc))+'</div>'

    def _measure_changed(self, change):
        for widget in (self.temperature, self.frequency_laser):
            widget.layout.display = 'none' if change['new'] else ''
        self._on_plot_button_click(None)

    def _range_changed(self, event):
        if np.isfinite([self.lower.value, self.upper.value]).all() and self.upper.value > self.lower.value:
            self.spectrum.layout.xaxis.range = [self.lower.value, self.upper.value]
        else:
            self.atom_controls.message.value = '<div class="alert alert-danger">Choose a finite range with maximum greater than minimum.</div>'

    def _select_active_mode(self, event):
        if hasattr(self, 'play_animation'):
            # Unlike the initial-only phonon trait, the supported state importer
            # replaces an attached trajectory when mode or amplitude changes.
            self.weas.import_state(self._model.mode_animation_state(self.play_animation.value))

    def _playback_changed(self, change):
        self.play_animation.description = 'Pause animation' if change['new'] else 'Play animation'
        self.play_animation.icon = 'pause' if change['new'] else 'play'
        self.weas._widget.animationState = {'isPlaying': change['new'], 'frameDuration': 100}

    def _playback_state_changed(self, change):
        playing = change['new'].get('isPlaying')
        if playing is not None and playing != self.play_animation.value:
            self.play_animation.value = playing


def spectra_view(record):
    kinds = ['IR', 'Raman'] if record['summary']['raman'] else ['IR']
    widgets = [MolecularSpectrum(record, kind) for kind in kinds]
    tabs = ipw.Tab(children=widgets)
    for index, kind in enumerate(kinds):
        tabs.set_title(index, kind)
    def render(change=None):
        widgets[tabs.selected_index or 0].render()
    tabs.observe(render, names='selected_index')
    render()
    return tabs
