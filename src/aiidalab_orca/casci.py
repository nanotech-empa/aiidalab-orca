"""Draft CASCI property panel: common orbitals, independent sectors, energy diagram."""

import asyncio
import html

import ipywidgets as ipw

from . import casci_services as service
from .state_levels import StateEnergyLevels


class CasciStates(ipw.VBox):
    def __init__(self, data, on_inspect=None):
        self.source_uuid = str(data['uuid'])
        self.process_uuid = None
        self.plan = None
        self._poll_task = None
        self._diagram = None
        self._inspection = None
        self._dyson = None
        self._dyson_key = None
        self._datasets = []
        self._running = False
        self._runs = {}
        self.on_inspect = on_inspect
        s = data['settings']
        style = {'description_width':'155px'}
        wide = ipw.Layout(width='95%')
        self.prepare = ipw.Button(description='Review common orbitals', icon='list', layout=ipw.Layout(width='auto'))
        self.prepare.on_click(self._review_common)
        self.common_submit = ipw.Button(description='Prepare common orbitals', icon='play', button_style='success', disabled=True,
                                        layout=ipw.Layout(width='auto'))
        self.common_submit.on_click(self._submit_common)
        self.common_force = ipw.Checkbox(value=False,description='Prepare a new common-orbital reference',layout=ipw.Layout(width='auto'))
        common_options = ipw.Accordion(children=[ipw.VBox([self.common_force,ipw.HTML(
            '<p>Regenerate from the saved SCF wavefunction without SCF iterations. Existing CASCI states remain linked to their original reference.</p>')])],selected_index=None)
        common_options.set_title(0,'Common-orbital regeneration')
        self.reference = ipw.Dropdown(description='Common orbitals',style=style,layout=wide)
        self.reference.layout = ipw.Layout(width='auto', flex='1 1 auto', min_width='280px')
        self.reference.observe(self._reference_changed,names='value')
        self.refresh = ipw.Button(description='Refresh states',icon='refresh',layout=ipw.Layout(width='auto'))
        self.refresh.on_click(self._refresh)
        # An explicit small starting space, clearly requiring scientific review.
        self.electrons = ipw.BoundedIntText(value=3 if s['multiplicity']%2==0 else 2,min=0,max=100,
                                           description='Active electrons (N)',style=style)
        self.norb = ipw.BoundedIntText(value=2,min=1,max=50,description='Active orbitals',style=style)
        self.charge = ipw.Dropdown(options=[(f"N−1 electrons · charge {s['charge']+1:+d}",s['charge']+1),
                (f"N electrons · charge {s['charge']:+d}",s['charge']),
                (f"N+1 electrons · charge {s['charge']-1:+d}",s['charge']-1)],value=s['charge'],
                description='Charge sector',style=style,layout=wide)
        self.mult = ipw.BoundedIntText(value=s['multiplicity'],min=1,max=99,description='Multiplicity (2S+1)',style=style)
        self.roots = ipw.BoundedIntText(value=1,min=1,max=100,description='Number of roots',style=style)
        basis = s['basis']
        self.aux = ipw.Combobox(value=basis+'/C' if basis in ('def2-SVP','def2-TZVP','def2-TZVPP') else 'AutoAux',
                options=['def2-SVP/C','def2-TZVP/C','def2-TZVPP/C','AutoAux'],ensure_option=False,
                description='Correlation auxiliary',style=style,layout=wide)
        self.nprocs = ipw.BoundedIntText(value=s['nprocs'],min=1,max=128,description='Processes',style=style)
        self.memory = ipw.BoundedIntText(value=s['memory_mb'],min=256,max=1048576,description='Total memory (MiB)',style=style)
        self.walltime = ipw.BoundedIntText(value=s['wallclock_seconds']//60,min=1,max=10080,description='Wall time (minutes)',style=style)
        self.threshold = ipw.FloatText(value=1e-6,description='CI print threshold',style=style)
        self.force = ipw.Checkbox(value=False,description='Recompute this CASCI sector',layout=ipw.Layout(width='auto'))
        self.space_info = ipw.HTML()
        advanced = ipw.Accordion(children=[ipw.VBox([self.aux,self.threshold,self.nprocs,self.memory,self.walltime,self.force])],selected_index=None)
        advanced.set_title(0,'CASCI resources and advanced settings')
        self.review = ipw.Button(description='Review CASCI calculation',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review_casci)
        self.submit = ipw.Button(description='Compute states',icon='play',button_style='success',disabled=True)
        self.submit.on_click(self._submit_casci)
        self.message, self.status = ipw.HTML(), ipw.HTML()
        self.previous = ipw.Dropdown(description='CASCI calculations',style=style,layout=wide)
        self.previous.observe(self._open_previous,names='value')
        self.diagram_box = ipw.VBox()
        self.empty = ipw.HTML()
        self.analysis = ipw.ToggleButtons(options=[('Many-electron states', 'states'),
            ('Dyson spectrum', 'spectrum'), ('Dyson orbitals & maps', 'maps')],
            style={'button_width': 'auto'}, layout=ipw.Layout(width='100%'))
        self.analysis.observe(self._analysis_changed, names='value')
        self.inspection_box = ipw.Accordion(children=[ipw.HTML("Select common orbitals to inspect.")],selected_index=None)
        self.inspection_box.set_title(0,"Inspect QRO / UNO orbitals")
        self.inspection_box.observe(self._open_inspection,names="selected_index")
        self.inspect = ipw.Button(description='Inspect active orbitals', icon='search', layout=ipw.Layout(width='auto'))
        self.inspect.on_click(self._inspect_window)
        self.dyson_box = ipw.VBox([ipw.HTML('Compute compatible CASCI states to prepare optional Dyson transitions.')],
                                 layout=ipw.Layout(display='none'))
        from .presentation import ComputePanel
        self.calculation = ComputePanel('Prepare orbitals / add CASCI states…', [
            ipw.HTML('<h4>Common spatial-orbital reference</h4>'), self.prepare,self.common_submit,common_options,
            ipw.HTML('<h4>Add a charge / spin sector</h4>'),
            ipw.HTML('<p><b>Choose the active space explicitly.</b> The small initial values are a starting example, not a validated '
            'choice for your molecule. The same spatial orbitals are used for N and N±1; their active electron counts adjust with charge.</p>'),
            ipw.HBox([self.electrons,self.norb],layout=ipw.Layout(flex_flow='row wrap')),
            self.charge,self.mult,self.roots,advanced,self.review,self.submit])
        self.states_view = ipw.VBox([self.previous,self.status,self.empty,
            self.inspect if on_inspect else self.inspection_box, self.calculation,self.message,self.diagram_box])
        super().__init__([ipw.HTML('<p>Shared spatial orbitals at this fixed geometry. '
            'Use CASCI states on their own, or explore optional Dyson transitions and maps.</p>'),
            ipw.HBox([self.reference,self.refresh],layout=ipw.Layout(flex_flow='row wrap')), self.space_info,
            self.analysis,self.states_view,self.dyson_box])
        for control in (self.electrons,self.norb,self.charge,self.mult,self.roots,self.aux,self.threshold,
                        self.nprocs,self.memory,self.walltime,self.force,self.common_force):
            control.observe(self._invalidate,names='value')
        self.electrons.observe(self._refresh_diagram,names='value')
        self.norb.observe(self._refresh_diagram,names='value')
        self.aux.observe(self._refresh_diagram,names='value')
        self.charge.observe(self._charge_changed,names='value')
        self._refresh()

    def _invalidate(self, _=None):
        self.plan = None
        self.submit.disabled = True
        self.common_submit.disabled = True
        self.message.value = ''
        self._space_text()

    def _space_text(self):
        self.inspect.disabled = not self.reference.value
        if not self.reference.value:
            self.space_info.value = '<p>Prepare common orbitals before reviewing CASCI.</p>'
            return
        try:
            ref = service.reference_data(self.reference.value)
            start = (ref['n_electrons']-self.electrons.value)//2
            count = self.electrons.value-self.charge.value+ref['charge']
            sector = (f'This charge sector: <b>CAS({count},{self.norb.value})</b>.' if self.analysis.value == 'states' else
                      f'Reference active space: <b>CAS({self.electrons.value},{self.norb.value})</b>.')
            self.space_info.value = (f'<p>ORCA orbital indices <b>{start}–{start+self.norb.value-1}</b> (start at 0). '
                f'{sector} Orbitals are held fixed; orbital reordering is not yet available.</p>')
            if self._inspection:
                self._inspection.set_active_indices(list(range(start,start+self.norb.value)))
        except Exception as exc:
            self.space_info.value = '<p>'+html.escape(str(exc))+'</p>'

    def _charge_changed(self, _=None):
        if self.reference.value:
            ref = service.reference_data(self.reference.value)
            count = ref['n_electrons']-self.charge.value+ref['charge']
            self.mult.value = 1 if count%2==0 else 2

    def _reference_changed(self, _=None):
        if self._inspection:
            self._inspection.close()
            self._inspection = None
            self.inspection_box.children = (ipw.HTML("Open orbital inspection to read this reference."),)
        self._invalidate()
        self._refresh_runs()
        self._refresh_diagram()
        if self.inspection_box.selected_index == 0:
            self._open_inspection()

    def _open_inspection(self, _=None):
        if self.inspection_box.selected_index == 0 and self.reference.value and not self._inspection:
            from .inspection import OrbitalInspection
            ref = service.reference_data(self.reference.value)
            start = (ref["n_electrons"]-self.electrons.value)//2
            self._inspection = OrbitalInspection(self.reference.value,active_indices=range(start,start+self.norb.value),
                                                apply_window=self._apply_orbital_window)
            self.inspection_box.children = (self._inspection,)

    def _inspect_window(self, event=None):
        if self.reference.value and self.on_inspect:
            ref = service.reference_data(self.reference.value)
            start = (ref['n_electrons']-self.electrons.value)//2
            self.on_inspect(self.reference.value, list(range(start, start+self.norb.value)))

    def _analysis_changed(self, event=None):
        self._space_text()
        states = self.analysis.value == 'states'
        self.states_view.layout.display = '' if states else 'none'
        self.dyson_box.layout.display = 'none' if states else ''
        if not states:
            self._open_dyson()

    def set_active(self, active):
        if active and self._dyson and self.analysis.value != 'states':
            self._dyson.set_view(self.analysis.value)

    def _open_dyson(self,_=None):
        key = (self.reference.value,tuple(sorted(data['workflow_uuid'] for data in self._datasets)))
        if self._dyson_key != key:
            if self._dyson:
                self._dyson.close()
            self._dyson,self._dyson_key = None,key
            self.dyson_box.children = (ipw.HTML('Compute compatible CASCI states to prepare Dyson transitions.'),)
        if self.analysis.value != 'states' and self._datasets and not self._dyson:
            from .dyson import DysonStates
            self._dyson = DysonStates(self.reference.value,self._datasets,
                on_show_maps=lambda: setattr(self.analysis, 'value', 'maps'))
            self.dyson_box.children = (self._dyson,)
        if self._dyson and self.analysis.value != 'states':
            self._dyson.set_view(self.analysis.value)

    def _apply_orbital_window(self, indices):
        from aiida_empa_orca.casci import active_space
        ref = service.reference_data(self.reference.value)
        nel = ref["n_electrons"]-2*indices[0]
        if not self.electrons.min <= nel <= self.electrons.max or len(indices) > self.norb.max:
            raise ValueError("The selected window exceeds the active-space controls; choose a smaller window")
        space = active_space({"electrons":nel,"orbitals":indices},ref)
        self.electrons.value = space["electrons"]
        self.norb.value = len(indices)

    def _refresh(self, _=None):
        previous = self.reference.value
        rows = service.reference_runs(self.source_uuid)
        self.reference.options = [('Prepare or select common orbitals',None)]+[(f"{r['kind']} · {r['reference_uuid'][:8]}",r['uuid']) for r in rows]
        if previous in [r['uuid'] for r in rows]:
            self.reference.value = previous
        elif rows:
            self.reference.value = rows[0]['uuid']
        self._refresh_runs()
        self._refresh_diagram()

    def _refresh_runs(self):
        rows = service.runs(self.reference.value) if self.reference.value else []
        self._runs = {r['uuid']:r for r in rows}
        keep = self.previous.value
        self.previous.options = [('Select a CASCI calculation',None)]+[(f"{r['date'][:16]} · {r['state']} · {r['label']}",r['uuid']) for r in rows]
        if self.process_uuid in self._runs:
            self.previous.value = self.process_uuid
        elif keep in self._runs:
            self.previous.value = keep
        elif rows:
            self.previous.value = rows[0]['uuid']

    def _open_previous(self, change):
        if not change['new']:
            return
        row = self._runs[change['new']]
        self.electrons.value = row['space']['electrons']
        self.norb.value = len(row['space']['orbitals'])
        s = row['settings']
        self.charge.value = s['charge']
        self.mult.value = s['multiplicity']
        self.roots.value = s['nroots']
        self.aux.value = s['auxiliary_basis']
        self.threshold.value = s['tprintwf']
        self.nprocs.value = s['nprocs']
        self.memory.value = s['memory_mb']
        self.walltime.value = s['wallclock_seconds']//60
        self.process_uuid = row['uuid']
        data = service.progress(self.process_uuid)
        self.status.value = '<p>'+html.escape(data['state']+' · '+data['message'])+'</p>'
        if not data['finished']:
            try:
                if self._poll_task:
                    self._poll_task.cancel()
                self._running = True
                self._poll_task = asyncio.get_running_loop().create_task(self._poll())
            except RuntimeError:
                pass
        self._refresh_diagram()

    def _review_common(self, _=None):
        self._invalidate()
        try:
            self.plan = service.prepare_common(self.source_uuid,self.common_force.value)
            text = ('Reuse preserved common orbitals.' if self.plan['action']=='reuse' else
                    'Read the saved SCF orbitals without SCF iterations; prepare '+self.plan['kind']+' spatial orbitals and preserve them using the SCF wavefunction storage policy.')
            if self.plan['unavailable']:
                text += ' Earlier common-orbital files are missing: preparation will run again, creating a new reference. Old CASCI states remain attached to their original reference.'
            self.message.value = '<p>'+html.escape(text)+'</p>'
            self.common_submit.description = 'Use common orbitals' if self.plan['action']=='reuse' else 'Prepare common orbitals'
            self.common_submit.disabled = self._running
        except Exception as exc:
            self._error(exc)

    def _review_casci(self, _=None):
        self._invalidate()
        try:
            if not self.reference.value:
                raise ValueError('Prepare or select common orbitals first')
            values = {'charge':self.charge.value,'multiplicity':self.mult.value,'nroots':self.roots.value,
                'auxiliary_basis':self.aux.value.strip(),'tprintwf':self.threshold.value,
                'nprocs':self.nprocs.value,'memory_mb':self.memory.value,'wallclock_seconds':self.walltime.value*60}
            self.plan = service.prepare_casci(self.reference.value,self.electrons.value,self.norb.value,values,self.force.value)
            text = 'Reuse the available CASCI states.' if self.plan['action']=='reuse' else 'Run one fixed-geometry, fixed-orbital CASCI calculation.'
            self.message.value = '<p><b>'+text+'</b></p><details><summary>ORCA input preview</summary><pre>'+html.escape(self.plan['input'])+'</pre></details>'
            self.submit.disabled = self._running
        except Exception as exc:
            self._error(exc)

    def _error(self, exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _submit_common(self, _=None):
        if self.plan and not self.common_submit.disabled:
            self._launch(service.submit_common)

    def _submit_casci(self, _=None):
        if self.plan and not self.submit.disabled:
            self._launch(service.submit_casci)

    def _launch(self, function):
        try:
            self.process_uuid = function(self.plan)
            self._invalidate()
            self._running = True
            if self._poll_task:
                self._poll_task.cancel()
            self._poll_task = asyncio.get_running_loop().create_task(self._poll())
        except Exception as exc:
            self._error(exc)

    async def _poll(self):
        try:
            while True:
                data = service.progress(self.process_uuid)
                self.status.value = '<p><b>'+html.escape(data['state'])+'</b> · '+self.process_uuid[:8]+'</p>'
                if data['finished']:
                    self._running = False
                    self._refresh()
                    if data['success'] and data.get('process_type') == 'aiida.workflows:empa_orca.common_orbitals':
                        self.reference.value = self.process_uuid
                        self.common_force.value = False
                    if not data['success']:
                        self._error(data['message']+' '+ '; '.join(data['reports']))
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._running = False
            self._error(exc)

    def _refresh_diagram(self, _=None):
        if self._diagram:
            self._diagram.close()
            self._diagram = None
        self.diagram_box.children = ()
        if not self.reference.value:
            self._datasets = []
            self.empty.value = '<p class="orca-notice">No common orbitals or CASCI states are available. Prepare a common reference if you want this optional analysis.</p>'
            self._open_dyson()
            return
        try:
            datasets = service.results(self.reference.value,self.electrons.value,self.norb.value,self.aux.value.strip())
            self._datasets = datasets
            self.empty.value = '' if datasets else '<p class="orca-notice">No completed CASCI states match this reference and active space. Add the charge/spin sectors you need; Dyson calculations are optional.</p>'
            self._open_dyson()
            if datasets:
                self._diagram = StateEnergyLevels(datasets)
                self.diagram_box.children = (self._diagram,)
            self._space_text()
        except Exception as exc:
            self._error(exc)

    def close(self):
        if getattr(self,'_disposed',False):
            return
        self._disposed = True
        if getattr(self,'_poll_task',None):
            self._poll_task.cancel()
        if getattr(self,'_diagram',None):
            self._diagram.close()
            self._diagram = None
        from .app import close_widget_tree
        if self.on_inspect:
            close_widget_tree(self.inspection_box)
        for child in self.children:
            close_widget_tree(child)
        super().close()
