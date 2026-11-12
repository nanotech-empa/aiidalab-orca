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
from .helper_budget import HelperBudget
from .kondo_guidance import chemical_potential_help
from .presentation import data_table


class KondoChannels(CubeDisplayMixin, ipw.VBox):
    def __init__(self, transitions_uuid, code_uuid, cubehandler_uuid):
        self.transitions_uuid, self.code_uuid = str(transitions_uuid), code_uuid
        self.cubehandler_uuid = cubehandler_uuid
        self.plan, self.cube_plan, self.record = None, None, None
        self._task, self._cube_view, self.render_panel, self.map_panel = None, None, None, None
        self.process_uuid = None
        style = {'description_width': '170px'}
        wide = ipw.Layout(width='95%')
        self.mu = ipw.FloatText(value=0., description='Chemical potential μ (eV)', style=style)
        self.channel_budget,self.reference_budget,self.cube_budget=HelperBudget(),HelperBudget(),HelperBudget()
        self.channel_resources=ipw.Accordion(children=[self.channel_budget],selected_index=None)
        self.channel_resources.set_title(0,'Kondo channel resources · serial')
        self.cube_resources=ipw.Accordion(children=[self.reference_budget,self.cube_budget],selected_index=None)
        self.cube_resources.set_title(0,'Native reference cubes · serial')
        self.cube_resources.set_title(1,'Channel cubes and reduction · serial')
        self.mu_help = ipw.HTML()
        self._mu_context, self._mu_context_error = None, ''
        try:
            self._mu_context = service.chemical_potential_context(self.transitions_uuid)
        except Exception as exc:
            self._mu_context_error = str(exc)
        self.mu.observe(self._update_mu_help, names='value')
        self._update_mu_help()
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
        self.stash = ipw.Text(value=default_stash_directory(), description='Cube stash directory', style=style, layout=ipw.Layout(width='95%'))
        self.stash.layout.display = 'none'
        self.retention.observe(lambda _: setattr(self.stash.layout, 'display', '' if self.retention.value == 'stash' else 'none'), names='value')
        self.cube_review=ipw.Button(description='Review Kondo cubes',icon='list',layout=ipw.Layout(width='auto'))
        self.cube_review.on_click(self._review_cubes)
        self.cube_message=ipw.HTML()
        self.generate = ipw.Button(description='Generate selected channel cubes', icon='cube',disabled=True, layout=ipw.Layout(width='auto'))
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
            self.retention, self.stash, self.cube_resources,self.cube_review,self.cube_message,self.generate])
        self.result_box = ipw.VBox([self.summary, self.cube_previous, self.cube_controls, self.map_box, self.view])
        self.result_box.layout.display = 'none'
        self.guide = kondo_preparation_guide()
        super().__init__([ipw.HTML('<h3>Kondo orbitals and channel maps · draft</h3><p>'
            'Spin-pure local moment, S &gt; 0; equal coupling of active orbitals to the substrate. '
            'The exchange matrix uses signed Dyson amplitudes, charged-state energies and Clebsch–Gordan factors.</p>'
            '<p>μ follows ε = E + (N−N₀)μ: increasing μ lowers the removal cost and raises the addition cost. '
            'Both costs must stay positive. No substrate alignment is inferred automatically.</p>'),
            self.guide, self.previous, self.mu, self.mu_help,self.channel_resources, ipw.HBox([self.review, self.submit]), self.message, self.result_box])
        self.channel_budget.observe(self._invalidate,names='revision')
        for budget in (self.reference_budget,self.cube_budget):budget.observe(self._invalidate_cubes,names='revision')
        for control in (self.channels,self.grid,self.retention,self.stash):control.observe(self._invalidate_cubes,names='value')
        self._refresh()

    def _update_mu_help(self, _=None):
        self.mu_help.value = chemical_potential_help(self._mu_context, self.mu.value, self._mu_context_error)

    def _invalidate(self, _=None):
        self.plan, self.submit.disabled = None, True
        self.message.value = ''

    def _error(self, exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review(self, _=None):
        if self._task:return
        self._invalidate()
        try:
            self.plan = service.prepare(self.transitions_uuid, self.mu.value, self.code_uuid,resources=self.channel_budget.values())
            lo, hi = self.plan['stability_interval_ev']
            self.message.value = f'<p>Selected roots require {lo:.3f} &lt; μ &lt; {hi:.3f} eV. '
            self.message.value += 'Submit an independent exchange CalcJob; no SCF, CASCI or Dyson calculation is repeated.</p>'
            self.message.value += '<p>'+self.channel_budget.summary()+'.</p>'
            self.message.value += ''.join('<p>'+html.escape(w)+'</p>' for w in self.plan['warnings'])
            self.submit.disabled = self._task is not None
        except Exception as exc:
            self._error(exc)

    def _submit(self, _=None):
        if self.plan and not self.submit.disabled and not self._task:
            plan=self.plan
            self._invalidate()
            try:
                self._start(service.submit_channels(plan), 'channels')
            except Exception as exc:
                self._error(exc)

    def _start(self, uuid, kind):
        self.submit.disabled = self.generate.disabled = self.review.disabled = self.cube_review.disabled = True
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
            self.review.disabled = self.cube_review.disabled = False
            self.generate.disabled = self.cube_plan is None
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
            self._invalidate_cubes()
            data = self.record['data']
            self.mu.value = data['parameters']['chemical_potential_ev']
            rows = data['channels']
            text = f"<p>Selected result: <b>μ={self.mu.value:.2f} eV</b>.</p>"
            text += data_table(['Channel','j/V² (eV⁻¹)','Coupling'],
                [[r['id'], f"{r['exchange_over_v2_inv_ev']:.5f}", r['coupling']] for r in rows],
                numeric_columns=(1,),label='Kondo eigenchannels')
            text += '<p>Individual unit-normalized channel maps; couplings are not map brightness weights. '
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

    def _invalidate_cubes(self,_=None):
        self.cube_plan,self.generate.disabled=None,True
        self.cube_message.value=''

    def _review_cubes(self,_=None):
        if self._task:return
        self._invalidate_cubes()
        try:
            if not self.record or not self.channels.value:
                raise ValueError('Select Kondo channels')
            p = dict(orbitals=[[0, i] for i in self.channels.value], spin_density=False,
                     grid_points=self.grid.value, retention=self.retention.value, stash_directory=self.stash.value)
            self.cube_plan=service.prepare_cubes(self.record['channels_uuid'],p,self.code_uuid,self.cubehandler_uuid,
                resources=self.cube_budget.values(),reference_resources=self.reference_budget.values())
            indices=', '.join(map(str,self.cube_plan['reference_orbitals']))
            self.cube_message.value=('<p><b>At most two CalcJobs, strictly one after the other.</b> '
                'Native initial-CASCI reference cubes (orbitals '+indices+'): '+self.reference_budget.summary()+'. '
                'Matching reference grids may be reused; full reference grids stay in their calculation directory.</p>'
                '<p>Then '+str(len(p['orbitals']))+' selected channel cube(s) and cubehandler reduction: '+self.cube_budget.summary()+'. '
                'Grid '+str(p['grid_points'])+' points/axis; full channel cubes: '+html.escape(self.retention.label)+'. '
                'Only reduced previews and compact manifests/logs are retrieved.</p>')
            self.generate.disabled=False
        except Exception as exc:
            self.cube_message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _generate(self, _=None):
        if not self.cube_plan or self.generate.disabled or self._task:return
        plan=self.cube_plan
        self._invalidate_cubes()
        try:
            self._start(service.submit_reviewed_cubes(plan),'cubes')
        except Exception as exc:
            self.cube_message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

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
        from .widget_lifecycle import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()
