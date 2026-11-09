"""Draft CASCI property panel: common orbitals, independent sectors, energy diagram."""

import asyncio
import html

import ipywidgets as ipw

from . import casci_services as service
from .state_levels import StateEnergyLevels
from .guidance import kondo_preparation_guide
from . import casci_batch
from .presentation import data_table
from .resources import MemoryInput, memory_label


class CasciStates(ipw.VBox):
    def __init__(self, data, on_inspect=None):
        self.source_uuid = str(data['uuid'])
        self.process_uuid = None
        self.plan = None
        self._poll_task = None
        self._batch_task = None
        self._batch_jobs = []
        self._batch_uuid = None
        self._execution_context = None
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
        self.common_pdos_memory = ipw.BoundedIntText(value=2, min=1, max=64,
            description='PDOS memory (GiB)', style={'description_width': 'initial'})
        self.common_pdos_wallclock = ipw.BoundedIntText(value=10, min=1, max=10080,
            description='PDOS wall time (minutes)', style={'description_width': 'initial'})
        self.common_pdos_resources = ipw.Accordion(children=[ipw.VBox([
            self.common_pdos_memory, self.common_pdos_wallclock,
            ipw.HTML('<p>Prepared orbital sets are analysed one at a time: QRO, then UNO. '
                     'Any separate orbital-file preservation uses the same helper budget.</p>')])], selected_index=None)
        self.common_pdos_resources.set_title(0, 'Prepared-orbital PDOS resources')
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
        self.charge = ipw.Text(value=str(s['charge']),description='Charges',style=style,layout=wide,
                               placeholder='e.g. 0 +1 -1 +2 -2')
        self.mult = ipw.Text(value=str(s['multiplicity']),description='Multiplicities (2S+1)',style=style,
                             layout=wide,placeholder='e.g. 1 2 3 4')
        self.roots = ipw.BoundedIntText(value=1,min=1,max=100,description='Electronic states',style=style)
        self.roots.tooltip = 'Number of CASCI states (roots) in this charge/spin sector: 1 requests its lowest-energy state; 2 also requests the next state.'
        basis = s['basis']
        self.aux = ipw.Combobox(value=basis+'/C' if basis in ('def2-SVP','def2-TZVP','def2-TZVPP') else 'AutoAux',
                options=['def2-SVP/C','def2-TZVP/C','def2-TZVPP/C','AutoAux'],ensure_option=False,
                description='Correlation auxiliary',style=style,layout=wide)
        self.nprocs = ipw.BoundedIntText(value=s['nprocs'],min=1,max=128,description='Processes',style=style)
        self.memory = MemoryInput(value=s['memory_mb'],min=256,max=1048576,style=style)
        self.walltime = ipw.BoundedIntText(value=s['wallclock_seconds']//60,min=1,max=10080,description='Wall time (minutes)',style=style)
        self.threshold = ipw.FloatText(value=1e-6,description='CI print threshold',style=style)
        self.force = ipw.Checkbox(value=False,description='Recompute requested CASCI sectors',layout=ipw.Layout(width='auto'))
        self.space_info = ipw.HTML()
        from .retention import FullFileRetention
        self.full_files = FullFileRetention()
        self.common_full_files = FullFileRetention()
        advanced = ipw.Accordion(children=[ipw.VBox([self.aux,self.threshold,self.nprocs,self.memory,self.walltime,self.force])],selected_index=None)
        advanced.set_title(0,'CASCI resources and advanced settings')
        self.review = ipw.Button(description='Review charge / spin combinations',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review_casci)
        self.submit = ipw.Button(description='Submit reviewed calculations',icon='play',button_style='success',disabled=True,
                                 layout=ipw.Layout(width='auto'))
        self.submit.on_click(self._submit_casci)
        self.message, self.status = ipw.HTML(), ipw.HTML()
        self.batch_review, self.batch_status = ipw.HTML(), ipw.HTML()
        self.execution_info, self.history_status = ipw.HTML(), ipw.HTML()
        self.result_charge = ipw.Dropdown(options=[('All available charges',None)],
            description='Available charge',style=style,layout=wide)
        self.result_charge.observe(self._filter_runs,names='value')
        self.previous = ipw.Dropdown(description='Calculation to inspect',style=style,layout=wide)
        self.previous.observe(self._open_previous,names='value')
        self.history = ipw.Accordion(children=[ipw.VBox([
            ipw.HTML('<p>Inspect the status of individual saved calculations here. '
                'The energy diagram above always includes all compatible completed charge/spin sectors. '
                'This selection does not filter the diagram or change submission settings.</p>'),
            self.result_charge,self.previous,self.history_status])],selected_index=None)
        self.history.set_title(0,'Calculation history and status')
        self.diagram_box = ipw.VBox()
        self.empty = ipw.HTML()
        self.analysis = ipw.ToggleButtons(options=[('Many-electron states', 'states'),
            ('Dyson spectrum', 'spectrum'), ('Dyson orbitals & maps', 'maps'), ('Kondo orbitals & maps', 'kondo')],
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
        self.preparation_actions = ipw.VBox()
        self.common_preparation = ipw.VBox([
            ipw.HTML('<h4>Common spatial-orbital reference</h4><p>One shared set of spatial orbitals is used for all CASCI states and charge/spin sectors. '
                'Preparing it reads the saved wavefunction without running a new SCF calculation.</p>'),
            self.execution_info,self.common_full_files,self.common_pdos_resources,self.prepare,self.common_submit,self.preparation_actions,common_options])
        self.active_controls = ipw.HBox([self.electrons,self.norb],layout=ipw.Layout(flex_flow='row wrap'))
        self.sector_preparation = ipw.VBox([
            ipw.HTML('<h4>Add charge / spin sectors</h4>'),
            ipw.HTML('<p>Request one combination or a list of charges and multiplicities. Review all pairs '
                'below before submitting. Each allowed pair is an independent AiiDA calculation; '
                'incompatible pairs are listed with reasons and skipped. Compatible saved sectors '
                'appear together in the energy diagram.</p>'),
            ipw.HTML('<p><b>Choose the active space explicitly.</b> The small initial values are a starting example, not a validated '
            'choice for your molecule. All charge sectors use the same spatial orbitals; their active electron counts adjust with charge.</p>'),
            self.charge,ipw.HTML('<p><b>Charges are absolute molecular charges</b>, not changes relative '
                'to the reference. Use spaces or commas: <code>0 +1 -1 +2 -2</code>. '
                'Charge +1 means one electron fewer than the neutral molecule; −1 means one more. '
                'For reference charge q₀, active electrons = reference active electrons − (q − q₀).</p>'),
            self.mult,ipw.HTML('<p>Enter multiplicities separated by spaces or commas, e.g. '
                '<code>1 2 3 4</code>: singlet, doublet, triplet, quartet. '
                'Even electron counts allow odd multiplicities; odd counts allow even multiplicities. '
                'The active-space size also limits the highest possible spin. '
                'The app tests every requested charge/multiplicity pair and never substitutes a different spin.</p>'),self.roots,
            ipw.HTML('<p><b>Electronic states (also called roots):</b> '
                '<b>1</b> requests the lowest-energy CASCI state in the chosen charge/spin sector; '
                '<b>2</b> also requests the next state, and so on. '
                'This count applies to each allowed sector and is separate from the number of active orbitals. '
                'If fewer states exist, the review table explicitly shows the available count.</p>'),
            self.full_files,advanced,self.review,self.batch_review,self.submit,self.batch_status])
        self.calculation = ComputePanel('Prepare orbitals / add CASCI states…',
                                        [self.common_preparation,self.sector_preparation])
        self.states_view = ipw.VBox([self.status,self.empty,self.diagram_box,self.history,
            self.inspect if on_inspect else self.inspection_box, self.calculation,self.message])
        self.guide = kondo_preparation_guide()
        self.reference_controls = ipw.HBox([self.reference,self.refresh],layout=ipw.Layout(flex_flow='row wrap'))
        super().__init__([ipw.HTML('<p>Shared spatial orbitals at this fixed geometry. '
            'Use CASCI states on their own, or explore optional Dyson transitions and maps.</p>'), self.guide,
            self.reference_controls, self.space_info, self.active_controls,
            self.analysis,self.states_view,self.dyson_box])
        for control in (self.electrons,self.norb,self.charge,self.mult,self.roots,self.aux,self.threshold,
                        self.nprocs,self.memory,self.walltime,self.force,self.common_force,
                        self.common_pdos_memory,self.common_pdos_wallclock):
            control.observe(self._invalidate,names='value')
        self.full_files.observe(self._invalidate, names='revision')
        self.common_full_files.observe(self._invalidate, names='revision')
        self.electrons.observe(self._refresh_diagram,names='value')
        self.norb.observe(self._refresh_diagram,names='value')
        self.aux.observe(self._refresh_diagram,names='value')
        self._refresh()

    def set_stage(self, stage):
        """Expose preparation and state requests as separate UI stages."""
        preparing = stage == 'prepare'
        legacy = stage == 'legacy'
        self.guide.layout.display = 'none' if preparing else ''
        self.common_preparation.layout.display = '' if preparing or legacy else 'none'
        self.sector_preparation.layout.display = 'none' if preparing else ''
        self.reference_controls.layout.display = '' if preparing or legacy else 'none'
        self.active_controls.layout.display = '' if legacy else 'none'
        self.space_info.layout.display = 'none' if preparing else ''
        for widget in (self.history,self.empty, self.inspect, self.inspection_box, self.diagram_box):
            widget.layout.display = 'none' if preparing else ''
        self.calculation.toggle.description = 'Prepare orbital reference' if preparing else 'Add / extend CASCI states'
        if preparing:
            self.analysis.value = 'states'
            self.calculation.show()

    def _invalidate(self, _=None):
        self.plan = None
        self.submit.disabled = True
        self.common_submit.disabled = True
        self.message.value = ''
        self.batch_review.value = ''
        self._space_text()

    def _space_text(self):
        self.inspect.disabled = not self.reference.value
        if not self.reference.value:
            self.space_info.value = '<p>Prepare common orbitals before reviewing CASCI.</p>'
            return
        try:
            ref = service.reference_data(self.reference.value)
            start = (ref['n_electrons']-self.electrons.value)//2
            sector = f'Reference active space: <b>CAS({self.electrons.value},{self.norb.value})</b> at charge {ref["charge"]:+d}.'
            self.space_info.value = (f'<p>ORCA orbital indices <b>{start}–{start+self.norb.value-1}</b> (start at 0). '
                f'{sector} Orbitals are held fixed; orbital reordering is not yet available.</p>')
            if self._inspection:
                self._inspection.set_active_indices(list(range(start,start+self.norb.value)))
        except Exception as exc:
            self.space_info.value = '<p>'+html.escape(str(exc))+'</p>'

    def _reference_changed(self, _=None):
        if self._inspection:
            self._inspection.close()
            self._inspection = None
            self.inspection_box.children = (ipw.HTML("Open orbital inspection to read this reference."),)
        self._invalidate()
        self._execution_text()
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
        self._execution_text()

    def _execution_text(self):
        explanation = ('<p><b>Computer and resources:</b> orbital preparation inherits the SCF '
            'calculation’s ORCA code, computer, process count, memory and wall-time limit. '
            'Saved remote or stashed wavefunctions are read on that computer. '
            'CASCI keeps the orbital reference’s computer; its processes, memory and wall time '
            'can be edited under <b>CASCI resources and advanced settings</b>.</p>')
        try:
            context = service.execution_details(self.reference.value or self.source_uuid)
            self._execution_context = context
            if not self.full_files.directory.value:
                self.full_files.directory.value = context.get('stash_directory', '')
            if not self.common_full_files.directory.value:
                self.common_full_files.directory.value = context.get('stash_directory', '')
            self.execution_info.value = (explanation+f'<p><b>Inherited preparation settings:</b> '
                f'{html.escape(context["code"])}@{html.escape(context["computer"])}; '
                f'{context["nprocs"]} processes, {memory_label(context["memory_mb"])} total memory, '
                f'{context["wallclock_seconds"]//60} minutes wall-time limit.</p>')
        except Exception as exc:
            self._execution_context = None
            self.execution_info.value = explanation+'<p>Execution details unavailable: '+html.escape(str(exc))+'</p>'

    def _refresh_runs(self):
        rows = service.runs(self.reference.value) if self.reference.value else []
        self._runs = {r['uuid']:r for r in rows}
        keep_charge = self.result_charge.value
        charges = sorted({r['settings']['charge'] for r in rows})
        self.result_charge.unobserve(self._filter_runs,names='value')
        try:
            self.result_charge.options = [('All available charges',None)]+[(f'Charge {q:+d}',q) for q in charges]
            self.result_charge.value = keep_charge if keep_charge in charges else None
        finally:
            self.result_charge.observe(self._filter_runs,names='value')
        self._filter_runs()

    def _filter_runs(self, _=None):
        rows = [r for r in self._runs.values() if self.result_charge.value is None or
                r['settings']['charge'] == self.result_charge.value]
        available = {row['uuid'] for row in rows}
        keep = self.previous.value
        self.previous.options = [('Select a CASCI calculation',None)]+[(f"{r['date'][:16]} · {r['state']} · {r['label']}",r['uuid']) for r in rows]
        if self.process_uuid in available:
            self.previous.value = self.process_uuid
        elif keep in available:
            self.previous.value = keep
        elif rows:
            self.previous.value = rows[0]['uuid']

    def _open_previous(self, change):
        if not change['new']:
            return
        row = self._runs[change['new']]
        s = row['settings']
        data = service.progress(row['uuid'])
        self.history_status.value = (f'<p>Saved calculation: charge {s["charge"]:+d}, multiplicity {s["multiplicity"]}, '
            f'{s["nroots"]} states · '+html.escape(data['state']+' · '+data['message'])+'</p>')
        if not data['finished'] and not self._running:
            self.process_uuid = row['uuid']
            try:
                if self._poll_task:
                    self._poll_task.cancel()
                self._running = True
                self._poll_task = asyncio.get_running_loop().create_task(self._poll())
            except RuntimeError:
                pass

    def _review_common(self, _=None):
        self._invalidate()
        self._execution_text()
        try:
            self.plan = service.prepare_common(self.source_uuid,self.common_force.value,
                                               native_output_policy=self.common_full_files.values(),
                                               pdos_memory_gib=self.common_pdos_memory.value,
                                               pdos_wallclock_seconds=self.common_pdos_wallclock.value * 60)
            text = ('Reuse preserved common orbitals.' if self.plan['action']=='reuse' else
                    'Read the saved SCF orbitals without SCF iterations; prepare '+self.plan['kind']+' spatial orbitals.')
            if self.plan['action'] != 'reuse':
                policy = self.plan['native_output_policy']
                destination = ('stashed at '+policy['stash_directory'] if policy['mode']=='stash'
                               else 'left on the calculation computer')
                text += ' Full native logs and orbital files are '+destination+'; only compact results are retrieved.'
                pdos = self.plan['pdos']
                order = 'QRO, then UNO' if self.plan['kind'] == 'QRO' else 'restricted orbitals'
                text += (f" Orbital-character postprocessing: {order}; one serial CalcJob at a time, "
                         f"{pdos['memory_gib']} GiB, up to {pdos['wallclock_seconds'] / 60:g} minutes per job. "
                         'Any separate orbital-file preservation uses the same helper budget.')
                if not self.plan.get('pdos', {}).get('ready'):
                    text += ' Its exporter or analysis worker is not configured; PDOS will be reported as unavailable.'
            if self.plan['unavailable']:
                text += ' Earlier common-orbital files are missing: preparation will run again, creating a new reference. Old CASCI states remain attached to their original reference.'
            self.message.value = '<p>'+html.escape(text)+'</p>'
            self.common_submit.description = 'Use common orbitals' if self.plan['action']=='reuse' else 'Prepare common orbitals'
            self.common_submit.disabled = self._running
        except Exception as exc:
            self._error(exc)

    def _review_casci(self, _=None):
        if self._running:
            return
        self._invalidate()
        try:
            if not self.reference.value:
                raise ValueError('Prepare or select common orbitals first')
            values = {'nroots':self.roots.value,
                'auxiliary_basis':self.aux.value.strip(),'tprintwf':self.threshold.value,
                'nprocs':self.nprocs.value,'memory_mb':self.memory.value,'wallclock_seconds':self.walltime.value*60}
            charges = casci_batch.parse_integer_list(self.charge.value,'charges')
            multiplicities = casci_batch.parse_integer_list(self.mult.value,'multiplicities',positive=True)
            self.plan = casci_batch.prepare_batch(self.reference.value,self.electrons.value,self.norb.value,
                charges,multiplicities,values,self.force.value,native_output_policy=self.full_files.values())
            self.batch_review.value = casci_batch.review_html(self.plan,self._execution_context)
            self.submit.disabled = self._running or not self.plan['ready']
            if self.plan.get('active_batch_uuid'):
                self._watch_batch(self.plan['active_batch_uuid'])
        except Exception as exc:
            self._error(exc)

    def _error(self, exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _submit_common(self, _=None):
        if self.plan and not self.common_submit.disabled:
            self._launch(service.submit_common)

    def _submit_casci(self, _=None):
        if self._running or not self.plan or self.plan.get('kind') != 'casci-batch' or self.submit.disabled:
            return
        plan,self.plan = self.plan,None
        self.submit.disabled,self.common_submit.disabled,self._running = True,True,True
        try:
            self._watch_batch(service.submit_casci_batch(plan))
        except Exception as exc:
            self._running = False
            self._error(exc)

    def _watch_batch(self, uuid):
        self._batch_uuid = str(uuid)
        self._running = True
        self.submit.disabled,self.common_submit.disabled = True,True
        try:
            info = service.casci_batch_progress(self._batch_uuid)
        except Exception as exc:
            info = {'finished':False, 'sectors':[]}
            self.message.value = '<p>Status unavailable; serial batch continues in AiiDA: '+html.escape(str(exc))+'</p>'
        self._batch_jobs = info['sectors']
        self._batch_status()
        if self._batch_task:
            self._batch_task.cancel()
        if info['finished']:
            self._running = False
            self._refresh()
        else:
            try:
                self._batch_task = asyncio.get_running_loop().create_task(self._poll_batch())
            except RuntimeError:
                # The queue belongs to the daemon and continues without this view.
                pass

    def _batch_status(self):
        rows = data_table(['Charge','Multiplicity','Status','Calculation UUID','Details'],[
            [f'{row["charge"]:+d}',row['multiplicity'],row['state'],row['uuid'] or '—',row['message']]
            for row in self._batch_jobs],numeric_columns=(0,1),label='Batch calculation status')
        self.batch_status.value = ('<h4>Reviewed serial batch</h4><p>Batch <code>'+
            html.escape(self._batch_uuid or '')+'</code>. Sectors run one at a time in AiiDA, including '
            'after this page closes. Failed sectors retain their diagnostics; the next sector waits for '
            'termination. A submission error stops the remaining queue without automatic retries.</p>'+rows)

    async def _poll_batch(self):
        try:
            while self._batch_uuid:
                try:
                    info = service.casci_batch_progress(self._batch_uuid)
                    changed = info['sectors'] != self._batch_jobs
                    self._batch_jobs = info['sectors']
                    self._batch_status()
                    if changed:
                        self._refresh_runs()
                        self._refresh_diagram()
                    if info['finished']:
                        self._running = False
                        self._refresh_runs()
                        self._refresh_diagram()
                        return
                except Exception as exc:
                    # Keep submission locked while the daemon's queue may be active.
                    self.message.value = '<p>Status unavailable; serial batch continues in AiiDA: '+html.escape(str(exc))+'</p>'
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass

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
        if getattr(self,'_batch_task',None):
            self._batch_task.cancel()
        if getattr(self,'_diagram',None):
            self._diagram.close()
            self._diagram = None
        from .widget_lifecycle import close_widget_tree
        if self.on_inspect:
            close_widget_tree(self.inspection_box)
        for child in self.children:
            close_widget_tree(child)
        super().close()
