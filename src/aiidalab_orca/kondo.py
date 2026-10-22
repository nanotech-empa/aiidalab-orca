"""Kondo eigenchannels, reduced previews and shared-scale constant-height maps."""
import asyncio
import base64
import html
import json

import ipywidgets as ipw

from . import kondo_services as service
from .guidance import kondo_preparation_guide
from .orbitals import CubeDisplayMixin
from .property_services import property_result, default_stash_directory


class KondoChannels(CubeDisplayMixin, ipw.VBox):
    def __init__(self, transitions_uuid, code_uuid, cubehandler_uuid):
        self.transitions_uuid, self.code_uuid = str(transitions_uuid), code_uuid
        self.cubehandler_uuid = cubehandler_uuid
        self.plan, self.record = None, None
        self._task, self._cube_view, self.render_panel, self.map_panel = None, None, None, None
        self.process_uuid = None
        style = {'description_width': '170px'}
        wide = ipw.Layout(width='95%')
        self.mu = ipw.FloatText(value=0., description='Chemical potential μ (eV)', style=style)
        self.review = ipw.Button(description='Review Kondo orbitals', icon='list', button_style='primary', layout=ipw.Layout(width='auto'))
        self.submit = ipw.Button(description='Compute Kondo orbitals', icon='play', button_style='success', disabled=True, layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        self.mu.observe(self._invalidate, names='value')
        self.message, self.summary = ipw.HTML(), ipw.HTML()
        self.previous = ipw.Dropdown(description='Kondo results', style=style, layout=wide)
        self.previous.observe(self._open, names='value')
        self.channels = ipw.SelectMultiple(description='Cube channels', style=style, layout=ipw.Layout(width='95%', height='110px'))
        self.grid = ipw.BoundedIntText(value=80, min=40, max=256, description='Grid points/axis', style=style)
        self.retention = ipw.Dropdown(options=[('Leave full cubes in calculation directory', 'leave'),
            ('Stash full-resolution cubes', 'stash'), ('Delete full cubes after preview validation', 'delete')],
            value='leave', description='Full cubes', style=style, layout=wide)
        self.stash = ipw.Text(value=default_stash_directory(), description='Cube stash directory', style=style, layout=wide)
        self.stash.layout.display = 'none'
        self.retention.observe(lambda _: setattr(self.stash.layout, 'display', '' if self.retention.value == 'stash' else 'none'), names='value')
        self.generate = ipw.Button(description='Generate selected channel cubes', icon='cube', layout=ipw.Layout(width='auto'))
        self.generate.on_click(self._generate)
        self.cube_previous = ipw.Dropdown(description='Cube results', style=style, layout=wide)
        self.cube_previous.observe(self._open_cubes, names='value')
        self.cube = ipw.Dropdown(description='Preview channel', style=style, layout=wide)
        self.cube.observe(self._show_cube, names='value')
        self.download, self.cube_box, self.map_box = ipw.HTML(), ipw.VBox(), ipw.VBox()
        self.view = ipw.Accordion(children=[ipw.VBox([self.cube, self.download, self.cube_box])], selected_index=None)
        self.view.set_title(0, '3D Kondo orbitals and slicing plane')
        self.view.observe(lambda _: self.set_active(self.view.selected_index == 0), names='selected_index')
        from .presentation import ComputePanel
        self.cube_controls = ComputePanel('Generate Kondo orbital previews…', [self.channels, self.grid,
            ipw.HTML('<p>Use signed native ORCA orbital grids from the exact initial CASCI wavefunction. '
                     'Reference grids are retained for reuse across chemical potentials; cubehandler reduces the previews.</p>'),
            self.retention, self.stash, self.generate])
        self.result_box = ipw.VBox([self.summary, self.cube_previous, self.cube_controls, self.map_box, self.view])
        self.result_box.layout.display = 'none'
        self.guide = kondo_preparation_guide()
        super().__init__([ipw.HTML('<h3>Kondo orbitals and channel maps · draft</h3><p>'
            'Spin-pure local moment, S &gt; 0; equal coupling of active orbitals to the substrate. '
            'The exchange matrix uses signed Dyson amplitudes, charged-state energies and Clebsch–Gordan factors.</p>'
            '<p>μ follows ε = E + (N−N₀)μ: increasing μ lowers the removal cost and raises the addition cost. '
            'Both costs must stay positive. No substrate alignment is inferred automatically.</p>'),
            self.guide, self.previous, self.mu, ipw.HBox([self.review, self.submit]), self.message, self.result_box])
        self._refresh()

    def _invalidate(self, _=None):
        self.plan, self.submit.disabled = None, True
        self.message.value = ''

    def _error(self, exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review(self, _=None):
        self._invalidate()
        try:
            self.plan = service.prepare(self.transitions_uuid, self.mu.value, self.code_uuid)
            lo, hi = self.plan['stability_interval_ev']
            self.message.value = f'<p>Selected roots require {lo:.3f} &lt; μ &lt; {hi:.3f} eV. '
            self.message.value += 'Submit an independent exchange CalcJob; no SCF, CASCI or Dyson calculation is repeated.</p>'
            self.message.value += ''.join('<p>'+html.escape(w)+'</p>' for w in self.plan['warnings'])
            self.submit.disabled = self._task is not None
        except Exception as exc:
            self._error(exc)

    def _submit(self, _=None):
        if self.plan and not self.submit.disabled:
            try:
                self._start(service.submit_channels(self.plan), 'channels')
            except Exception as exc:
                self._error(exc)

    def _start(self, uuid, kind):
        self.submit.disabled = self.generate.disabled = True
        self.message.value = '<p>Submitted '+kind+' · <code>'+str(uuid)+'</code></p>'
        if self._task:
            self._task.cancel()
        self._task = asyncio.get_running_loop().create_task(self._poll(str(uuid), kind))

    async def _poll(self, uuid, kind):
        try:
            while True:
                data = service.progress(uuid)
                self.message.value = '<p>'+kind+': '+html.escape(data['state'])+' · <code>'+uuid+'</code></p>'
                if data['finished']:
                    if not data['success']:
                        raise ValueError(data['message']+'; '.join(data['reports']))
                    (self._refresh if kind == 'channels' else self._refresh_cubes)(uuid)
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._error(exc)
        finally:
            self._task = None
            self.generate.disabled = False
            self.submit.disabled = self.plan is None

    def _refresh(self, selected=None):
        rows = service.history(self.transitions_uuid)
        self.previous.options = [('Select Kondo results', None)]+rows
        if selected or rows:
            self.previous.value = selected or rows[0][1]

    def _open(self, change):
        if not change['new']:
            return
        try:
            status = service.progress(change['new'])
            if not status['finished']:
                self._start(change['new'], 'channels')
                return
            self.record = service.result(change['new'])
            data = self.record['data']
            self.mu.value = data['parameters']['chemical_potential_ev']
            rows = data['channels']
            text = f"<p>Selected result: <b>μ={self.mu.value:.2f} eV</b>.</p>"
            text += '<table><tr><th>Channel</th><th>j/V² (eV⁻¹)</th><th>Coupling</th></tr>'
            text += ''.join(f"<tr><td>{r['id']}</td><td>{r['exchange_over_v2_inv_ev']:.5f}</td><td>{r['coupling']}</td></tr>" for r in rows)
            text += '</table><p>Individual unit-normalized channel maps; couplings are not map brightness weights. '
            text += 'A combined experimental Kondo map and resonance width require further modelling.</p>'
            text += ''.join('<p>'+html.escape(w)+'</p>' for w in data['warnings'])
            payload = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
            self.summary.value = text+f'<a download="kondo-channels.json" href="data:application/json;base64,{payload}">Download exchange matrix, channels and settings</a>'
            self.channels.options = [(r['id']+' · '+r['coupling'], r['index']) for r in rows]
            self.channels.value = tuple(r['index'] for r in rows if r['coupling'] == 'AFM')
            self.result_box.layout.display = ''
            self._refresh_cubes()
        except Exception as exc:
            self._error(exc)

    def _generate(self, _=None):
        try:
            if not self.record or not self.channels.value:
                raise ValueError('Select Kondo channels')
            p = dict(orbitals=[[0, i] for i in self.channels.value], spin_density=False,
                     grid_points=self.grid.value, retention=self.retention.value, stash_directory=self.stash.value)
            self._start(service.submit_cubes(self.record['channels_uuid'], p, self.code_uuid, self.cubehandler_uuid), 'cubes')
        except Exception as exc:
            self._error(exc)

    def _refresh_cubes(self, selected=None):
        rows = service.cube_history(self.record['channels_uuid'])
        self.cube_previous.options = [('Select channel cubes', None)]+rows
        if selected or rows:
            self.cube_previous.value = selected or rows[0][1]

    def _open_cubes(self, change):
        if not change['new']:
            return
        try:
            data = property_result(change['new'])
            if not data['finished']:
                self._start(change['new'], 'cubes')
            elif data['successful']:
                self.process_uuid = str(change['new'])
                self.cube.unobserve(self._show_cube, names='value')
                try:
                    self.cube.options = [(c['filename'], c['filename']) for c in data['manifest']['cubes']]
                    self.cube.value = self.cube.options[0][1]
                finally:
                    self.cube.observe(self._show_cube, names='value')
                self._show_cube()
            else:
                raise ValueError(data['message'])
        except Exception as exc:
            self._error(exc)

    def _show_cube(self, _=None):
        super()._show_cube()
        if not self._cube_view:
            return
        from .maps import DysonMaps
        if self.map_panel and self.map_panel.cube_uuid == self.process_uuid:
            self.map_panel.bind_viewer(self._cube_view)
        else:
            if self.map_panel:
                self.map_panel.close()
            self.map_panel = DysonMaps(self.process_uuid, self._cube_view, None, self.code_uuid)
            self.map_box.children = (self.map_panel,)

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        if self._task:
            self._task.cancel()
        from .app import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()
