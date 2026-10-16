"""Constant-height map controls using the existing shared slicing-plane viewer."""
import asyncio
import base64
import html
import json

import ipywidgets as ipw
import numpy as np
from ase.io.cube import read_cube
import io

from aiida_empa_orca.maps_data import default_plane, plane_basis
from . import map_services as service
from .property_services import preview_content


class DysonMaps(ipw.VBox):
    def __init__(self, cube_uuid, viewer, spectrum, code_uuid):
        self.cube_uuid, self.spectrum, self.code_uuid = str(cube_uuid), spectrum, code_uuid
        self.viewer, self.plan, self.map_uuid = None, None, None
        self._task, self._disposed, self._plane_controls = None, False, []
        self.source = service.source_data(cube_uuid)
        amplitudes = [c for c in self.source['manifest']['cubes'] if c['kind'] == 'dyson']
        first = amplitudes[0]
        cube = read_cube(io.StringIO(preview_content(cube_uuid, first['filename'])))
        span = (np.asarray(cube['data'].shape)-1) * np.linalg.norm(cube['spacing'], axis=1)
        self.defaults = default_plane(cube['atoms'].positions, .9*span[1], .9*span[0])
        style = {'description_width': '165px'}
        self.selection = ipw.SelectMultiple(description='Map transitions', style=style,
            options=[(c['transition_id'], c['transition_id']) for c in amplitudes],
            value=tuple(c['transition_id'] for c in amplitudes), layout=ipw.Layout(width='95%', height='120px'))
        self.kind = ipw.ToggleButtons(options=[('Individual transitions', 'individual'), ('Spectral blend', 'blend')])
        self.heights = ipw.Text(value='5, 7', description='Observation heights (Å)', style=style, layout=ipw.Layout(width='440px'))
        self.kappa = ipw.BoundedFloatText(value=1.15, min=.001, max=10, step=.01, description='Vacuum κ (Å⁻¹)', style=style)
        self.padding = ipw.BoundedIntText(value=0, min=0, max=512, description='FFT padding / edge', style=style)
        self.reset = ipw.Button(description='Reset: 1.5 Å above top atom (+z)', icon='undo', layout=ipw.Layout(width='auto'))
        self.reset.on_click(self._reset)
        self.plane_info, self.message = ipw.HTML(), ipw.HTML()
        self.review = ipw.Button(description='Review constant-height maps', icon='list', button_style='primary', layout=ipw.Layout(width='auto'))
        self.compute = ipw.Button(description='Compute numerical maps', icon='play', button_style='success', disabled=True, layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review)
        self.compute.on_click(self._submit)
        self.previous = ipw.Dropdown(description='Numerical maps', style=style, layout=ipw.Layout(width='95%'))
        self.previous.observe(self._open, names='value')
        self.load_settings = ipw.Button(description='Load selected map settings into viewer', icon='upload', layout=ipw.Layout(width='auto'))
        self.load_settings.on_click(self._load_settings)
        self.vmin = ipw.FloatText(value=0., description='Shared minimum', style=style)
        self.vmax = ipw.FloatText(value=1., description='Shared maximum', style=style)
        self.cmap = ipw.Dropdown(options=['bone', 'gray', 'viridis', 'magma'], description='Colour map', style=style)
        self.dpi = ipw.BoundedIntText(value=300, min=72, max=600, description='Figure DPI', style=style)
        self.bar = ipw.FloatText(value=5., description='Scale bar (Å)', style=style)
        self.rotation = ipw.Dropdown(options=[0, 90, 180, 270], description='Panel rotation (°)', style=style)
        self.range_button = ipw.Button(description='Use full map range (shared)', icon='arrows-v', layout=ipw.Layout(width='auto'))
        self.range_button.on_click(self._range)
        self.render = ipw.Button(description='Render shared-scale figure', icon='image', button_style='primary', layout=ipw.Layout(width='auto'))
        self.render.on_click(self._render)
        self.figures = ipw.Dropdown(description='Stored figures', style=style, layout=ipw.Layout(width='95%'))
        self.figures.observe(self._open_figure, names='value')
        self.image, self.download, self.details = ipw.Image(format='png'), ipw.HTML(), ipw.HTML()
        self.figure_box = ipw.VBox([ipw.HTML('<p><b>Shared intensity scale</b> · every panel uses the same explicit limits. '
            'Numerical intensities are preserved without normalization. Change the limits to reveal faint features; '
            'all panels change together.</p>'), ipw.HBox([self.vmin, self.vmax], layout=ipw.Layout(flex_flow='row wrap')),
            self.range_button, ipw.HBox([self.cmap, self.rotation], layout=ipw.Layout(flex_flow='row wrap')),
            ipw.HBox([self.dpi, self.bar], layout=ipw.Layout(flex_flow='row wrap')), self.render,
            self.figures, self.download, self.image, self.load_settings, self.details])
        self.figure_box.layout.display = 'none'
        super().__init__([ipw.HTML('<p>Adjust the <b>source slice in the 3D viewer above</b>. '
            'Its Center is the height-reference point; Offset is the source-slice height along Normal. '
            'Observation heights use that same reference and normal. Full-resolution amplitudes are extrapolated before squaring and combining; '
            'the displayed reduced cube only helps position the plane.</p>'), self.reset, self.plane_info,
            self.selection, self.kind, self.heights, ipw.HBox([self.kappa, self.padding], layout=ipw.Layout(flex_flow='row wrap')),
            ipw.HTML('<p>Blends use the energy/window, broadening and spin convention selected in the spectral viewer. '
                     'Individual maps use its spin convention. The model produces STM-like intensities, without absolute current calibration.</p>'),
            self.review, self.message, self.compute, self.previous, self.figure_box])
        for w in (self.selection, self.kind, self.heights, self.kappa, self.padding):
            w.observe(self.invalidate, names='value')
        self.bind_viewer(viewer, preserve=False)
        self._refresh()

    def bind_viewer(self, viewer, preserve=True):
        plane = self._plane() if self.viewer and preserve else self.defaults
        for w in self._plane_controls:
            w.unobserve(self.invalidate, names='value')
        self.viewer = viewer
        cut = viewer.slice2d
        self._plane_controls = [cut.center_txt, cut.normal_txt, cut.offset_txt, cut.width, cut.height, cut.res]
        self._apply_plane(plane)
        for w in self._plane_controls:
            w.observe(self.invalidate, names='value')
        self.invalidate()

    def _apply_plane(self, plane):
        cut = self.viewer.slice2d
        cut.center_txt.value = ' '.join(map(str, plane['center']))
        cut.normal_txt.value = ' '.join(map(str, plane['normal']))
        cut.offset_txt.value = str(plane['offset'])
        cut.width.value, cut.height.value, cut.res.value = plane['width'], plane['height'], plane['resolution']
        self.viewer.viewer3d.show_plane_checkbox.value = True

    def _plane(self):
        p = self.viewer.slice2d.return_settings()
        return {k: p[k] for k in ('center', 'normal', 'offset', 'width', 'height', 'resolution')}

    def _reset(self, _=None):
        self._apply_plane(self.defaults)
        self.invalidate()

    def invalidate(self, _=None):
        self.plan, self.compute.disabled = None, True
        if not self.viewer:
            return
        try:
            p = self._plane()
            n, _, _ = plane_basis(p['normal'])
            point = np.asarray(p['center']) + p['offset']*n
            self.plane_info.value = '<p>Reference point (Å): '+', '.join(f'{v:.3f}' for v in p['center'])+\
                ' · Source-plane centre (Å): '+', '.join(f'{v:.3f}' for v in point)+\
                f" · Source height: {p['offset']:.3f} Å. Plane controls override the initial default.</p>"
        except (ValueError, TypeError):
            self.plane_info.value = '<p>Enter a valid source plane in the slice viewer.</p>'

    def _parameters(self):
        p = dict(plane=self._plane(), heights_angstrom=[float(v) for v in self.heights.value.replace(',', ' ').split()],
                 kappa_inv_angstrom=self.kappa.value, padding=self.padding.value,
                 transition_ids=list(self.selection.value), kind=self.kind.value, spin_convention=self.spectrum.spin.value)
        if self.kind.value == 'blend':
            p['blend'] = self.spectrum.blend()
        return p

    def _error(self, exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review(self, _=None):
        self.invalidate()
        try:
            self.plan = service.prepare_maps(self.cube_uuid, self._parameters(), self.code_uuid)
            self.message.value = ('<p><b>Reuse stored numerical maps.</b></p>' if self.plan['action'] == 'reuse' else
                '<p><b>Submit numerical maps from full-resolution amplitude cubes.</b> No SCF, CASCI or Dyson coefficients are recomputed. '
                'The numerical arrays and complete settings will be stored in AiiDA.</p>')
            self.compute.disabled = self._task is not None
        except Exception as exc:
            self._error(exc)

    def _submit(self, _=None):
        if not self.plan or self.compute.disabled:
            return
        try:
            uuid = service.submit_maps(self.plan)
            self.invalidate()
            self._start(uuid, 'maps')
        except Exception as exc:
            self._error(exc)

    def _start(self, uuid, kind):
        self.compute.disabled = self.render.disabled = self.review.disabled = True
        if kind == 'figure':
            self.image.value, self.download.value = b'', ''
        self.message.value = '<p>Submitted '+kind+' · <code>'+str(uuid)+'</code></p>'
        self._task = asyncio.get_running_loop().create_task(self._poll(str(uuid), kind))

    async def _poll(self, uuid, kind):
        try:
            while True:
                data = service.progress(uuid)
                self.message.value = '<p>'+kind+': '+html.escape(data['state'])+' · <code>'+uuid+'</code></p>'
                if data['finished']:
                    if not data['success']:
                        raise ValueError(data['message']+'; '.join(data['reports']))
                    if kind == 'maps':
                        self._refresh(uuid)
                    else:
                        self._refresh_figures(uuid)
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._error(exc)
        finally:
            self._task = None
            self.render.disabled = self.review.disabled = False
            self.compute.disabled = self.plan is None

    def _refresh(self, selected=None):
        rows = service.map_history(self.cube_uuid)
        self.previous.options = [('Select numerical maps', None)]+rows
        if selected or rows:
            self.previous.value = selected or rows[0][1]

    def _open(self, change):
        if not change['new']:
            return
        try:
            data = service.progress(change['new'])
            if not data['finished']:
                if not self._task:
                    self._start(change['new'], 'maps')
                return
            self.map_uuid = str(change['new'])
            result = service.map_result(self.map_uuid)
            self.map_metadata = result['metadata']
            self._range()
            span = min(self.map_metadata['parameters']['plane'][k] for k in ('width', 'height'))
            self.bar.value = next((v for v in (5., 2., 1., .5, .2, .1) if v < .8*span), 0.)
            self.figure_box.layout.display = ''
            payload = base64.b64encode(json.dumps(self.map_metadata, indent=2).encode()).decode()
            self.details.value = '<p>Numerical map ArrayData: <code>'+result['maps_uuid']+'</code></p>'+\
                f'<a download="map-settings.json" href="data:application/json;base64,{payload}">Download map settings and source checksums</a>'
            self._refresh_figures()
        except Exception as exc:
            self._error(exc)

    def _range(self, _=None):
        if hasattr(self, 'map_metadata'):
            self.vmin.value = 0.
            self.vmax.value = self.map_metadata['maximum'] or 1.

    def _load_settings(self, _=None):
        if not hasattr(self, 'map_metadata'):
            return
        p = self.map_metadata['parameters']
        self._apply_plane(p['plane'])
        self.heights.value = ', '.join(map(str, p['heights_angstrom']))
        self.kappa.value, self.padding.value = p['kappa_inv_angstrom'], p['padding']
        self.selection.value, self.kind.value = tuple(p['transition_ids']), p['kind']
        self.spectrum.spin.value = p['spin_convention']
        if p['kind'] == 'blend':
            b = p['blend']
            self.spectrum.mode.value, self.spectrum.energy.value = b['mode'], b['energy_ev']
            self.spectrum.window_lower.value, self.spectrum.window_upper.value = b['lower_ev'], b['upper_ev']
            self.spectrum.eta.value, self.spectrum.shift.value = b['eta_ev'], b['shift_ev']
        self.invalidate()

    def _render(self, _=None):
        if not self.map_uuid or self._task:
            return
        try:
            settings = dict(vmin=self.vmin.value, vmax=self.vmax.value, cmap=self.cmap.value, dpi=self.dpi.value,
                            scale_bar_angstrom=self.bar.value, rotation=self.rotation.value)
            uuid = service.submit_figure(self.map_uuid, settings, self.code_uuid)
            self._start(uuid, 'figure')
        except Exception as exc:
            self._error(exc)

    def _refresh_figures(self, selected=None):
        result = service.map_result(self.map_uuid)
        self.figures.options = [('Select a stored figure', None)]+result['figures']
        self.image.value, self.download.value = b'', ''
        if selected or result['figures']:
            self.figures.value = selected or result['figures'][0][1]

    def _open_figure(self, change):
        if not change['new']:
            return
        try:
            data = service.progress(change['new'])
            if not data['finished']:
                if not self._task:
                    self._start(change['new'], 'figure')
                return
            result = service.figure_result(change['new'])
            self.image.value = result['images']['png']
            links = []
            for key, mime in (('png', 'image/png'), ('pdf', 'application/pdf')):
                encoded = base64.b64encode(result['images'][key]).decode()
                links.append(f'<a download="dyson-maps.{key}" href="data:{mime};base64,{encoded}">Download {key.upper()}</a>')
            self.download.value = ' · '.join(links)+'<p>Stored image nodes: <code>'+result['png_uuid']+'</code> / <code>'+result['pdf_uuid']+'</code>.</p>'
            for key in ('vmin', 'vmax', 'cmap', 'dpi', 'rotation'):
                getattr(self, key).value = result['settings'][key]
            self.bar.value = result['settings']['scale_bar_angstrom']
        except Exception as exc:
            self._error(exc)

    def close(self):
        if self._disposed:
            return
        self._disposed = True
        if self._task:
            self._task.cancel()
        for w in self._plane_controls:
            w.unobserve(self.invalidate, names='value')
        from .app import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()
