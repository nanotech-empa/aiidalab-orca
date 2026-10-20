"""State-pair selection, spectra and independently requested Dyson cubes."""
import asyncio
import html

import ipywidgets as ipw

from . import dyson_services as service
from .orbitals import CubeDisplayMixin
from .property_services import default_stash_directory,property_result
from .spectra import SpectralViewer


class DysonStates(CubeDisplayMixin,ipw.VBox):
    def __init__(self,common_uuid,datasets,on_show_maps=None):
        self.on_show_maps = on_show_maps
        self.common_uuid = str(common_uuid)
        self.state_rows = service.states(datasets)
        self.reference_charge = datasets[0]['reference_charge']
        self.plan,self.cube_plan,self.record = None,None,None
        self.process_uuid,self._cube_view,self.render_panel = None,None,None
        self._job_uuid,self._job_kind,self._poll_task = None,None,None
        self.spectrum = None
        self.map_panel = None
        self.kondo_panel = None
        self.kondo_box = ipw.VBox()
        self.map_box = ipw.Accordion(children=[],selected_index=None)
        choices = service.codes(self.common_uuid)
        style,wide = {'description_width':'155px'},ipw.Layout(width='95%')
        self.initial = ipw.Dropdown(description='Initial CASCI state',style=style,layout=wide,
            options=[(self._label(row),(row['state_uuid'],row['root'])) for row in self.state_rows])
        neutral = [r for r in self.state_rows if r['charge'] == self.reference_charge]
        first = min(neutral or self.state_rows,key=lambda r:r['energy_hartree'])
        self.initial.value = (first['state_uuid'],first['root'])
        self.side = ipw.Dropdown(options=[('Removal and addition','both'),('Removal','removal'),('Addition','addition')],
                                 description='Transitions',style=style,layout=ipw.Layout(width='400px'))
        self.finals = ipw.SelectMultiple(description='Final CASCI states',style=style,layout=ipw.Layout(width='95%',height='180px'))
        self.refresh = ipw.Button(description='Select all compatible final states',icon='check',layout=ipw.Layout(width='auto'))
        self.refresh.on_click(lambda _:setattr(self.finals,'value',tuple(value for _,value in self.finals.options)))
        self.export_code = ipw.Dropdown(options=choices['export'],description='ORCA export',style=style,layout=wide)
        self.dyson_code = ipw.Dropdown(options=choices['dyson'],description='Dyson tools',style=style,layout=wide)
        self.cubehandler_code = ipw.Dropdown(options=choices['cubehandler'],description='Cubehandler',style=style,layout=wide)
        self.loss = ipw.BoundedFloatText(value=1e-5,min=0,max=.01,description='Max. missing CI norm',style=style)
        self.force = ipw.Checkbox(value=False,description='Recompute Dyson coefficients',layout=ipw.Layout(width='auto'))
        advanced = ipw.Accordion(children=[ipw.VBox([self.loss,self.force,self.export_code,self.dyson_code,self.cubehandler_code])],selected_index=None)
        advanced.set_title(0,'Dyson validation and codes')
        self.review = ipw.Button(description='Review Dyson calculation',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review)
        self.submit = ipw.Button(description='Compute Dyson transitions',icon='play',button_style='success',disabled=True,layout=ipw.Layout(width='auto'))
        self.submit.on_click(self._submit)
        self.message,self.status = ipw.HTML(),ipw.HTML()
        self.previous = ipw.Dropdown(description='Dyson results',style=style,layout=wide)
        self.previous.observe(self._open_previous,names='value')
        self.spectrum_box = ipw.VBox()
        self.cube_states = ipw.SelectMultiple(description='Cubes / blend states',style=style,layout=ipw.Layout(width='95%',height='150px'))
        self.blend = ipw.Checkbox(value=False,description='Include spectral intensity blend of selected transitions',layout=ipw.Layout(width='auto'))
        self.grid = ipw.BoundedIntText(value=80,min=40,max=256,description='Grid points/axis',style=style)
        self.retention = ipw.Dropdown(options=[('Stash full-resolution cubes','stash'),('Leave full cubes in calculation directory','leave'),
            ('Delete full cubes after preview validation','delete')],value='stash',description='Full cubes',style=style,layout=wide)
        self.stash = ipw.Text(value=choices.get('storage_policy',{}).get('stash_directory',default_stash_directory()),description='Cube stash directory',style=style,layout=wide)
        self.retention.observe(lambda _:setattr(self.stash.layout,'display','' if self.retention.value == 'stash' else 'none'),names='value')
        self.cube_review = ipw.Button(description='Review Dyson cubes / blend',icon='list',layout=ipw.Layout(width='auto'))
        self.cube_review.on_click(self._review_cubes)
        self.cube_submit = ipw.Button(description='Generate cubes / blend',icon='play',button_style='success',disabled=True,layout=ipw.Layout(width='auto'))
        self.cube_submit.on_click(self._submit_cubes)
        self.cube_message = ipw.HTML()
        self.cube_previous = ipw.Dropdown(description='Cube results',style=style,layout=wide)
        self.cube_previous.observe(self._open_cubes,names='value')
        self.cube = ipw.Dropdown(description='Preview cube',style=style,layout=wide)
        self.cube.observe(self._show_cube,names='value')
        self.download,self.cube_box = ipw.HTML(),ipw.VBox()
        from .presentation import ComputePanel
        self.cube_calculation = ComputePanel('Generate Dyson cubes / intensity blends…', [ipw.HTML('<p>Generate only the requested Dyson amplitudes and optional incoherent intensity blend. Full cubes pass through cubehandler before previews are retrieved. Blends are spectral intensities, without an STM tip or vacuum-decay model.</p>'),
            self.cube_states,self.blend,self.grid,self.retention,self.stash,self.cube_review,self.cube_message,self.cube_submit,
            ])
        self.orbital_view = ipw.Accordion(children=[ipw.VBox([self.cube,self.download,self.cube_box])], selected_index=None)
        self.orbital_view.set_title(0, '3D orbitals and slicing plane')
        self.orbital_view.observe(self._resize_cube, names='selected_index')
        self.cube_empty = ipw.HTML()
        self.cube_controls = ipw.VBox([self.cube_previous,self.cube_empty,self.cube_calculation,self.map_box,self.orbital_view])
        self.cube_controls.layout.display = 'none'
        self.calculation = ComputePanel('Compute / extend Dyson transitions…', [
            ipw.HTML('<p>Select an initial many-electron state and compatible N±1 final states at this fixed geometry. '
            'Missing sectors can be added in the Many-electron states view. No SCF or CASCI is silently repeated.</p>'),
            self.side,self.finals,self.refresh,advanced,self.review,self.submit])
        self.empty = ipw.HTML()
        self._view = 'spectrum'
        super().__init__([self.initial,self.previous,self.status,self.empty,self.calculation,self.message,
                          self.spectrum_box,self.cube_controls,self.kondo_box])
        self.initial.observe(self._initial_changed,names='value')
        self.side.observe(self._initial_changed,names='value')
        for w in (self.finals,self.loss,self.force,self.export_code,self.dyson_code):
            w.observe(self._invalidate,names='value')
        for w in (self.cube_states,self.blend,self.grid,self.retention,self.stash,self.cubehandler_code,self.dyson_code):
            w.observe(self._invalidate_cubes,names='value')
        self._initial_changed()
        self.set_view(self._view)

    def set_view(self, view):
        self._view = view
        self.spectrum_box.layout.display = '' if view == 'spectrum' else 'none'
        self.cube_controls.layout.display = '' if view == 'maps' and self.record else 'none'
        self.kondo_box.layout.display = '' if view == 'kondo' else 'none'
        if view == 'kondo' and self.record and self.kondo_panel is None:
            from .kondo import KondoChannels
            self.kondo_panel = KondoChannels(self.record['transitions_uuid'], self.dyson_code.value, self.cubehandler_code.value)
            self.kondo_box.children = (self.kondo_panel,)
        self.empty.value = ('' if self.record else '<p class="orca-notice">No Dyson result is available for this initial state. '
            'CASCI results remain usable on their own. Compute transitions here only if you need spectra or tunnelling maps.</p>')
        if view == 'maps':
            self._resize_cube()

    def _resize_cube(self, event=None):
        if self._cube_view and self.orbital_view.selected_index == 0:
            self._cube_view.viewer3d.viewer._remote_call('handleResize', target='Widget')

    @staticmethod
    def _label(row):
        return f"q={row['charge']:+d} · multiplicity {row['multiplicity']} · root {row['root']} · {row['energy_hartree']:.8f} Ha"

    def _initial_changed(self,_=None):
        self._invalidate()
        self._invalidate_cubes()
        if self.spectrum:
            from .app import close_widget_tree
            close_widget_tree(self.spectrum)
            self.spectrum = None
        self.record = None
        if self.kondo_panel:
            self.kondo_panel.close()
            self.kondo_panel = None
        self.kondo_box.children = ()
        if self.map_panel:
            self.map_panel.close()
            self.map_panel = None
        self.map_box.children = ()
        self.spectrum_box.children = ()
        self.cube_controls.layout.display = 'none'
        initial = next(r for r in self.state_rows if (r['state_uuid'],r['root']) == self.initial.value)
        choices = []
        for row in self.state_rows:
            delta = row['charge']-initial['charge']
            side = 'removal' if delta == 1 else 'addition'
            if abs(delta) == 1 and abs(row['multiplicity']-initial['multiplicity']) == 1 and self.side.value in ('both',side):
                choices.append((side+' · '+self._label(row),(row['state_uuid'],row['root'])))
        self.finals.options = choices
        self.finals.value = tuple(value for _,value in choices)
        self._refresh_runs()

    def _invalidate(self,_=None):
        self.plan,self.submit.disabled = None,True
        self.message.value = ''

    def _invalidate_cubes(self,_=None):
        self.cube_plan,self.cube_submit.disabled = None,True
        self.cube_message.value = ''
        if self.map_panel:
            self.map_panel.code_uuid = self.dyson_code.value
            self.map_panel.invalidate()

    def _error(self,exc,cubes=False):
        (self.cube_message if cubes else self.message).value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review(self,_=None):
        self._invalidate()
        try:
            self.plan = service.review(self.common_uuid,self.initial.value,self.finals.value,
                {'export':self.export_code.value,'dyson':self.dyson_code.value},self.loss.value,self.force.value)
            text = '<p><b>'+('Reuse stored Dyson coefficients and transition energies.' if self.plan['action'] == 'reuse' else 'Compute selected Dyson transitions from existing CASCI wavefunctions.')+'</b></p>'
            text += ''.join('<p>'+html.escape(r['label']+' · '+r['action'])+'</p>' for r in self.plan['exports'])
            text += '<p>Exports follow the reference wavefunction preservation policy: a size-limited retrieved copy and a native stash. CI coefficients are checked and retained without renormalization.</p>'
            self.message.value = text
            self.submit.disabled = self._job_uuid is not None
        except Exception as exc:
            self._error(exc)

    def _submit(self,_=None):
        if self.plan and not self.submit.disabled:
            try:
                uuid = service.submit_dyson(self.plan)
                self._invalidate()
                self._start(uuid,'dyson')
            except Exception as exc:
                self._error(exc)

    def _start(self,uuid,kind):
        self._job_uuid,self._job_kind = str(uuid),kind
        self.submit.disabled = self.cube_submit.disabled = True
        self.status.value = '<p>Submitted '+kind+' · <code>'+str(uuid)+'</code></p>'
        if self._poll_task:
            self._poll_task.cancel()
        self._poll_task = asyncio.get_running_loop().create_task(self._poll())

    async def _poll(self):
        try:
            while self._job_uuid:
                data = service.progress(self._job_uuid)
                self.status.value = '<p><b>'+self._job_kind+': '+html.escape(data['state'])+'</b> · <code>'+self._job_uuid+'</code></p>'
                if data['finished']:
                    uuid,kind = self._job_uuid,self._job_kind
                    self._job_uuid = None
                    if data['success']:
                        if kind == 'dyson':
                            self._refresh_runs(uuid)
                        else:
                            self._refresh_cubes(uuid)
                    else:
                        self._error(data['message']+'; '.join(data['reports']),kind == 'cubes')
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._job_uuid = None
            self._error(exc)

    def _refresh_runs(self,selected=None):
        rows = service.runs(*self.initial.value)
        self.previous.options = [('Select a Dyson calculation',None)]+rows
        values = [value for _,value in rows]
        if selected in values:
            self.previous.value = selected
        elif rows:
            self.previous.value = rows[0][1]
        else:
            self.record = None
            self.spectrum_box.children = ()
            self.cube_controls.layout.display = 'none'
        self.set_view(self._view)

    def _open_previous(self,change):
        uuid = change['new']
        if not uuid:
            return
        data = service.progress(uuid)
        if not data['finished']:
            self._start(uuid,'dyson')
            return
        if not data['success']:
            self._error(data['message'])
            return
        self.record = service.result(uuid)
        if self.kondo_panel:
            self.kondo_panel.close()
            self.kondo_panel = None
        self.kondo_box.children = ()
        if self.map_panel:
            self.map_panel.close()
            self.map_panel = None
        self.map_box.children = ()
        if self.spectrum:
            from .app import close_widget_tree
            close_widget_tree(self.spectrum)
        diagram_states = service.diagram_states(self.record['data'],self.state_rows)
        self.spectrum = SpectralViewer(self.record['data'],self._invalidate_cubes,states=diagram_states,
                                      on_selection=self._preview_selection,on_use=self._use_transition_selection)
        self.spectrum_box.children = (self.spectrum,)
        options = []
        for i,r in enumerate(self.record['data']['transitions']):
            options.append((f"{r['side']} · q={r['final_charge']:+d} · mult {r['final_multiplicity']} · root {r['final_root']} · {r['energy_ev']:.3f} eV · component strength {r['strength']:.4f}",i))
        self.cube_states.options = options
        self.cube_states.value = tuple(i for i,r in enumerate(self.record['data']['transitions']) if r['strength'] > 1e-8)
        self.cube_controls.layout.display = ''
        self._refresh_cubes()
        self.set_view(self._view)

    def _preview_selection(self,identifiers):
        """Show an already retrieved amplitude, without requesting new cubes."""
        if len(identifiers) == 1:
            filename = 'dyson_'+identifiers[0]+'.cube'
            if filename in [value for _,value in self.cube.options]:
                if self.cube.value != filename:
                    self.cube.value = filename
                self.spectrum.preview_info.value = '<p>Stored orbital preview selected: <b>'+html.escape(filename)+'</b>. Use the selection to open Dyson orbitals &amp; maps.</p>'
            else:
                self.spectrum.preview_info.value = '<p>No stored amplitude cube for this transition. Use the cube controls to generate it; selecting a transition does not submit a calculation.</p>'
        else:
            self.spectrum.preview_info.value = '<p>Select one transition to inspect its stored orbital, or use this selection for an intensity blend.</p>'

    def _use_transition_selection(self,identifiers):
        if not self.record:
            return
        self.cube_states.value = tuple(i for i,row in enumerate(self.record['data']['transitions']) if row['id'] in identifiers)
        if self.map_panel:
            available = {value for _,value in self.map_panel.selection.options}
            self.map_panel.selection.value = tuple(i for i in identifiers if i in available)
            if not set(identifiers) <= available:
                self.cube_message.value = '<p>Some selected amplitude cubes have not been generated. Use the cube controls to generate them before computing their maps.</p>'
        self._preview_selection(identifiers)
        if self.on_show_maps:
            self.on_show_maps()

    def _review_cubes(self,_=None):
        self._invalidate_cubes()
        try:
            from aiida_empa_orca.dyson_data import blend_options
            from aiida_empa_orca.orbitals import cube_parameters
            if not self.record or not self.cube_states.value:
                raise ValueError('Select computed Dyson transitions')
            if not self.dyson_code.value or not self.cubehandler_code.value:
                raise ValueError('Configure Dyson tools and cubehandler')
            p = cube_parameters({'orbitals':[[0,i] for i in self.cube_states.value],'spin_density':False,
                'grid_points':self.grid.value,'retention':self.retention.value,'stash_directory':self.stash.value.strip()})
            blend = blend_options(self.spectrum.blend()) if self.blend.value else None
            self.cube_plan = {'transitions_uuid':self.record['transitions_uuid'],'parameters':p,
                'code_uuid':self.dyson_code.value,'cubehandler_uuid':self.cubehandler_code.value,'blend':blend}
            self.cube_message.value = '<p>Generate '+str(len(p['orbitals']))+' Dyson amplitudes'+(' and their spectral intensity blend' if blend else '')+'. Only reduced previews are retrieved; full cubes: '+html.escape(self.retention.label)+'.</p>'
            self.cube_submit.disabled = self._job_uuid is not None
        except Exception as exc:
            self._error(exc,True)

    def _submit_cubes(self,_=None):
        if self.cube_plan and not self.cube_submit.disabled:
            try:
                uuid = service.submit_cubes(**self.cube_plan)
                self._invalidate_cubes()
                self._start(uuid,'cubes')
            except Exception as exc:
                self._error(exc,True)

    def _refresh_cubes(self,selected=None):
        rows = service.cube_runs(self.record['transitions_uuid']) if self.record else []
        self.cube_empty.value = '' if rows else '<p class="orca-notice">No Dyson cube results are available. Generate the selected amplitudes if you want orbital previews or constant-height maps.</p>'
        self.cube_previous.options = [('Select Dyson cube results',None)]+rows
        if selected in [value for _,value in rows]:
            self.cube_previous.value = selected
        elif rows:
            self.cube_previous.value = rows[0][1]

    def _open_cubes(self,change):
        if not change['new']:
            return
        data = property_result(change['new'])
        if data['successful']:
            self.process_uuid = change['new']
            self.cube.unobserve(self._show_cube,names='value')
            try:
                self.cube.options = [(c['filename'],c['filename']) for c in data['manifest']['cubes']]
                self.cube.value = self.cube.options[0][1]
            finally:
                self.cube.observe(self._show_cube,names='value')
            self._show_cube()
        elif not data['finished']:
            self._start(change['new'],'cubes')
        else:
            self._error(data['message'],True)

    def _show_cube(self,_=None):
        super()._show_cube()
        if not self.process_uuid or not self._cube_view or not self.spectrum:
            return
        from .maps import DysonMaps
        if self.map_panel and self.map_panel.cube_uuid == self.process_uuid:
            self.map_panel.bind_viewer(self._cube_view)
        else:
            if self.map_panel:
                self.map_panel.close()
            self.map_panel = DysonMaps(self.process_uuid,self._cube_view,self.spectrum,self.dyson_code.value)
            self.map_box.children = (self.map_panel,)
            self.map_box.set_title(0,'STM-like constant-height maps (draft)')
            self.map_box.selected_index = 0

    def close(self):
        if getattr(self,'_disposed',False):
            return
        self._disposed = True
        if self._poll_task:
            self._poll_task.cancel()
        from .app import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()
