"""Optional orbital optimization, followed by explicit inspection and reuse."""

import asyncio
import html
import re

import ipywidgets as ipw

from . import casscf_services as service
from .casci_services import progress, reference_data
from .resources import MemoryInput, memory_label
from .retention import FullFileRetention


class CasscfOrbitals(ipw.VBox):
    def __init__(self, reference_uuid, space, use_reference):
        self.reference_uuid, self.space = str(reference_uuid), dict(space)
        self.use_reference = use_reference
        self.plan, self.process_uuid, self._poll_task = None, None, None
        self._disposed = False
        self._blocks = []
        ref = reference_data(reference_uuid)
        settings = ref['settings']
        style = {'description_width': 'initial'}
        self.mode = ipw.ToggleButtons(options=[('One selected state', 'state_specific'),
                                                ('State average (SA)', 'state_average')])
        self.mult = ipw.BoundedIntText(value=ref['source_multiplicity'], min=1, max=99,
                                       description='Multiplicity (2S+1)', style=style)
        self.root = ipw.BoundedIntText(value=0, min=0, max=999, description='Root to optimize', style=style)
        self.root.tooltip = 'State numbering starts at 0: the lowest state in the chosen charge and multiplicity.'
        self.single = ipw.HBox([self.mult, self.root], layout=ipw.Layout(flex_flow='row wrap'))
        self.intent = ipw.HTML()
        self.blocks = ipw.VBox()
        self.add = ipw.Button(description='Add multiplicity', icon='plus', layout=ipw.Layout(width='auto'))
        self.add.on_click(lambda _: self._add_block())
        self.average = ipw.VBox([ipw.HTML('<p>Each row has one multiplicity, its number of roots and optional '
            'weights in root order (0, 1, …). Blank weights give equal weights to individual states '
            'across all rows. All states have the same charge.</p>'), self.blocks, self.add])
        self._add_block(ref['source_multiplicity'], 2)
        self.nprocs = ipw.BoundedIntText(value=settings['nprocs'], min=1, max=4096, description='Processes', style=style)
        self.memory = MemoryInput(value=settings['memory_mb'], style=style)
        self.wall = ipw.BoundedIntText(value=max(1, settings['wallclock_seconds'] // 60), min=1,
                                       max=100000, description='Wall time (minutes)', style=style)
        self.steps = ipw.BoundedIntText(value=75, min=2, max=10000, description='Max macro-iterations', style=style)
        self.aux = ipw.Text(description='Correlation auxiliary basis', style=style)
        self.force = ipw.Checkbox(description='Run again even if a matching result exists', value=False, indent=False,
                                  layout=ipw.Layout(width='auto'))
        self.force.tooltip = 'Normally reuse a matching running or successful calculation. Changed inputs already define a new request.'
        self.full_files = FullFileRetention()
        resources = ipw.Accordion(children=[ipw.VBox([self.nprocs, self.memory, self.wall, self.steps, self.aux, self.force])], selected_index=None)
        resources.set_title(0, 'Resources and convergence')
        self.pdos_memory=ipw.BoundedIntText(value=2,min=1,max=64,description='PDOS memory (GiB)',style=style)
        self.pdos_wall=ipw.BoundedIntText(value=10,min=1,max=10080,description='PDOS wall time (minutes)',style=style)
        self.pdos_resources=ipw.Accordion(children=[ipw.VBox([self.pdos_memory,self.pdos_wall,
            ipw.HTML('<p>After optimization and readback pass, one serial CalcJob computes compact orbital character and PDOS.</p>')])],selected_index=None)
        self.pdos_resources.set_title(0,'PDOS resources · serial')
        self.review = ipw.Button(description='Review CASSCF', icon='list', button_style='primary')
        self.submit = ipw.Button(description='Submit reviewed CASSCF', icon='play', disabled=True,
                                  layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        self.review_text, self.status, self.message = ipw.HTML(), ipw.HTML(), ipw.HTML()
        self.saved = ipw.Dropdown(description='CASSCF calculations', options=[('No calculations yet', None)], style=style,
                                 layout=ipw.Layout(width='95%'))
        self.saved.observe(self._selected, names='value')
        self.refresh = ipw.Button(description='Refresh status', icon='refresh')
        self.refresh.on_click(self._refresh)
        self.levels = ipw.VBox()
        self.inspect = ipw.Button(description='Inspect optimized orbitals', icon='eye', disabled=True,
                                   layout=ipw.Layout(width='auto'))
        self.inspect.on_click(lambda _: self.use_reference(self.saved.value))
        super().__init__([ipw.HTML('<h3>Optimize the shared orbitals · CASSCF</h3>'
            f'<p><b>Fixed geometry · charge {ref["charge"]:+d} · CAS({space["electrons"]},{len(space["orbitals"])})</b>. '
            'CASSCF optimizes orbitals as well as CI coefficients. State averaging finds one compromise '
            'orbital set for the states you select; their individual energies remain separate.</p>'
            '<p>These are <b>orbital-optimization weights</b>, not thermal populations, '
            'Clebsch–Gordan factors or spectral intensities. Existing results retain their original orbitals.</p>'),
            self.mode, self.single, self.average, self.intent, self.full_files, resources,self.pdos_resources,
            ipw.HBox([self.review, self.submit], layout=ipw.Layout(flex_flow='row wrap')),
            self.review_text, self.message, self.saved, self.refresh, self.status, self.levels, self.inspect,
            ipw.HTML('<p>After successful optimization and saved-orbital readback, inspect and confirm the '
                'new reference. Use it for fixed-orbital CASCI in all required charge/spin sectors before '
                'Dyson/Kondo, or export its Hamiltonian for quantum-assisted energies. '
                'Independently optimized charge states cannot be mixed in the shared-orbital Dyson route.</p>')])
        for control in (self.mode, self.mult, self.root, self.nprocs, self.memory, self.wall, self.steps, self.aux, self.force,self.pdos_memory,self.pdos_wall):
            control.observe(self._invalidate, names='value')
        self.mode.observe(self._mode_changed, names='value')
        self.full_files.observe(self._invalidate, names='revision')
        self._mode_changed()
        self._refresh()

    def _add_block(self, mult=1, roots=1):
        style = {'description_width': 'initial'}
        row = (ipw.BoundedIntText(value=mult, min=1, max=99, description='Multiplicity', style=style),
               ipw.BoundedIntText(value=roots, min=1, max=1000, description='Roots', style=style),
               ipw.Text(placeholder='Equal weights', description='Root weights', style=style))
        remove = ipw.Button(icon='trash', tooltip='Remove multiplicity', layout=ipw.Layout(width='40px'))
        box = ipw.HBox([*row, remove], layout=ipw.Layout(flex_flow='row wrap'))
        entry = (row, box)
        self._blocks.append(entry)
        for control in row:
            control.observe(self._invalidate, names='value')
        def delete(_):
            self._blocks.remove(entry)
            self.blocks.children = [b for _, b in self._blocks]
            self._invalidate()
        remove.on_click(delete)
        self.blocks.children = [b for _, b in self._blocks]
        if hasattr(self, 'submit'):
            self._invalidate()

    def _mode_changed(self, _=None):
        single = self.mode.value == 'state_specific'
        self.single.layout.display = '' if single else 'none'
        self.average.layout.display = 'none' if single else ''
        self._explain_objective()

    def _explain_objective(self):
        if self.mode.value == 'state_average':
            text = 'Optimize one shared orbital set for the listed states. Each state retains its own energy.'
        elif self.root.value == 0:
            text = (f'Optimize one state: root 0, the lowest state with multiplicity {self.mult.value}. '
                    'For more energy levels with these optimized orbitals, inspect them and continue with CASCI.')
        else:
            text = (f'Compute roots 0–{self.root.value}; only root {self.root.value} drives orbital optimization. '
                    'Inspect the state character when following an excited root.')
        self.intent.value = '<p>' + text + '</p>'

    def _invalidate(self, _=None):
        self.plan = None
        if hasattr(self, 'intent'):
            self._explain_objective()
        if hasattr(self, 'submit'):
            self.submit.disabled = True
            self.review_text.value = ''

    def _values(self):
        if self.mode.value == 'state_specific':
            blocks = [{'multiplicity': self.mult.value, 'weights': [0.0] * self.root.value + [1.0]}]
        else:
            blocks = []
            for (mult, roots, weights), _ in self._blocks:
                values = [float(v) for v in re.split(r'[\s,]+', weights.value.strip())] if weights.value.strip() else [1.0] * roots.value
                if len(values) != roots.value:
                    raise ValueError('Provide one weight for every requested root, or leave the weights blank')
                blocks.append({'multiplicity': mult.value, 'weights': values})
        values = {'mode': self.mode.value, 'states': blocks, 'nprocs': self.nprocs.value,
                  'memory_mb': self.memory.value, 'wallclock_seconds': self.wall.value * 60, 'maxiter': self.steps.value}
        if self.aux.value.strip():
            values['auxiliary_basis'] = self.aux.value.strip()
        return values

    def _review(self, _=None):
        self._invalidate()
        try:
            self.plan = service.review(self.reference_uuid, self.space, self._values(), force=self.force.value,
                                       native_output_policy=self.full_files.values(),
                                       pdos_resources={'memory_gib':self.pdos_memory.value,'wallclock_seconds':self.pdos_wall.value*60})
            p = self.plan
            cell = ' style="padding: 0.25em 1.5em 0.25em 0; text-align: left"'
            rows = ''.join(f'<tr><td{cell}>{b["multiplicity"]}</td><td{cell}>{r}</td><td{cell}>{w:.6g}</td></tr>'
                           for b in p['settings']['states'] for r, w in enumerate(b['weights']))
            processes = 'process' if p['settings']['nprocs'] == 1 else 'processes'
            retention = self.full_files.values()
            destination = ('stashed at ' + html.escape(retention['stash_directory'])
                           if retention['mode'] == 'stash' else 'left on the calculation computer')
            self.review_text.value = (f'<p><b>{html.escape(p["action"].capitalize())}</b> · '
                f'{html.escape(p["execution"])} · {p["settings"]["nprocs"]} {processes} · '
                f'{memory_label(p["settings"]["memory_mb"])} · {p["settings"]["wallclock_seconds"] // 60} minutes. '
                'One job runs orbital optimization followed by independent frozen-orbital verification; '
                f'large artifacts are {destination}. Native outputs up to '
                f'{retention.get("maxsizeoutput", 5 * 1024**2) / 1024**2:g} MiB are retrieved unchanged; '
                'larger files use a separate extract and explicit notice. Reused/running results keep their recorded retention.</p>'
                f'<table style="border-collapse: collapse"><tr><th{cell}>Multiplicity</th><th{cell}>Root</th>'
                f'<th{cell}>Normalized optimization weight</th></tr>' + rows + '</table>'
                '<details><summary>Review ORCA optimization and readback inputs</summary><pre>' +
                html.escape(p['input']) + '</pre><pre>' + html.escape(p['readback_input']) + '</pre></details>')
            pdos=p['pdos']
            if p['action']=='compute':
                self.review_text.value += (f'<p><b>Then automatic PDOS: 1 process, {pdos["memory_gib"]} GiB, '
                    f'up to {pdos["wallclock_seconds"]/60:g} minutes.</b> It starts after the optimization/readback '
                    'CalcJob finishes; only compact PDOS data and logs are retrieved.</p>')
                if not pdos['ready']:
                    self.review_text.value += '<p>PDOS helpers are unavailable; the electronic reference is retained if analysis cannot run.</p>'
            self.message.value = ''
            self.submit.disabled = False
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p>' + html.escape(str(exc)) + '</p>'

    def _submit(self, _=None):
        if not self.plan or self.submit.disabled:
            return
        plan=self.plan
        self._invalidate()
        try:
            self.process_uuid = service.submit(plan)
            self._refresh()
            self.saved.value = self.process_uuid
            try:
                self._poll_task = asyncio.get_running_loop().create_task(self._poll())
            except RuntimeError:
                pass  # Script-driven widgets have an explicit Refresh status action.
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p>' + html.escape(str(exc)) + '</p>'

    def _refresh(self, _=None):
        previous = self.saved.value
        rows = service.history(self.reference_uuid, self.space)
        self.saved.options = [('Select a CASSCF calculation', None), *rows]
        if previous in [v for _, v in rows]:
            self.saved.value = previous
        elif rows:
            self.saved.value = rows[0][1]
        self._selected()

    def _selected(self, _=None):
        for widget in self.levels.children:
            widget.close()
        self.levels.children = ()
        self.inspect.disabled = True
        if not self.saved.value:
            self.status.value = ''
            return
        state = progress(self.saved.value)
        self.status.value = '<p><b>' + html.escape(state['state']) + '</b> · <code>' + self.saved.value + '</code> ' + html.escape(state['message']) + '</p>'
        if state['finished'] and not state['success']:
            details = '\n'.join(service.diagnostics(self.saved.value))
            self.status.value += ('<details open><summary>Why the candidate was rejected</summary><pre>' +
                html.escape(details or state['message']) + '</pre></details><p>Edit the inputs above and review again. '
                'Maximum macro-iterations is under Resources and convergence; a failed orbital/readback check '
                'also requires inspecting the active space and state choices, rather than automatically loosening tolerances.</p>')
        if state['success']:
            from .state_levels import StateEnergyLevels
            data = service.results(self.saved.value)
            explanation = ('<p>One state was requested. To compute additional energy levels using these orbitals, '
                           'choose <b>Inspect optimized orbitals</b>, confirm the active space, then request '
                           'several roots in CASCI.</p>') if len(data['states']) == 1 else ''
            self.levels.children = [ipw.HTML(explanation + '<p>Saved-orbital readback passed: largest state-energy difference '
                f'{data["readback_max_error_hartree"]:.2e} Hartree.</p>'), StateEnergyLevels([data])]
            self.inspect.disabled = False

    async def _poll(self):
        try:
            while not self._disposed and self.process_uuid:
                state = progress(self.process_uuid)
                self._refresh()
                if state['finished']:
                    break
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    def close(self):
        if self._disposed:
            return
        self._disposed = True
        if self._poll_task:
            self._poll_task.cancel()
        for widget in self.levels.children:
            widget.close()
        super().close()
