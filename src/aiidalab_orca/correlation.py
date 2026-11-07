"""Compact, separate energy-only routes with reviewed scientific prerequisites."""
import asyncio
import base64
import html
import json

import ipywidgets as ipw

from . import correlation_services as service
from .casci_services import progress
from .resources import MemoryInput, memory_label


class CorrelationResults(ipw.VBox):
    def __init__(self, data):
        self.data = data  # Plain values only; no ORM objects.
        method = data['method']
        cells = ' style="padding: .25em 1em .25em 0; text-align: right"'
        rows = ''.join(f'<tr><td{cells}>{r["multiplicity"]}</td><td{cells}>{r["root"]}</td>'
            f'<td{cells}>{r["reference_energy_hartree"]:.10f}</td><td{cells}>{r["correction_hartree"]:.10f}</td>'
            f'<td{cells}>{r["energy_hartree"]:.10f}</td></tr>' for r in data['states'])
        table = ('<table style="border-collapse: collapse"><tr>' + ''.join(f'<th{cells}>{label}</th>' for label in
            ('Multiplicity', 'Root', data['reference_method'] + ' energy (Ha)', 'Correction (Ha)', method + ' energy (Ha)')) +
            '</tr>' + rows + '</table>')
        self.plot = ipw.HTML()
        self.energy_kind = ipw.ToggleButtons(options=[(method, 'energy_hartree'),
            (data['reference_method'] + ' reference', 'reference_energy_hartree')],
            layout=ipw.Layout(display='' if len(data['states']) > 1 else 'none'))
        self.energy_kind.observe(self._redraw, names='value')
        check = data['checks']
        diagnostics = '<p>Energy-sum check: ' + f'{check["energy_sum_max_error_hartree"]:.2e} Ha.'
        if 'reference_readback_max_error_hartree' in check:
            diagnostics += f' Reference readback: {check["reference_readback_max_error_hartree"]:.2e} Ha.'
        spin_note = ''
        if check.get('hf_reference') == 'UHF':
            spin_note = (f'<p><b>Unrestricted HF reference:</b> ⟨S²⟩ = {check["hf_spin_squared"]:.6f}; '
                f'pure-spin target = {check["hf_target_spin_squared"]:.6f}. '
                'Assess the reference spin contamination when interpreting MP2 energies.</p>')
        diagnostics += '</p>'
        encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
        download = f'<a download="correlation-energies.json" href="data:application/json;base64,{encoded}">Download energies and provenance</a>'
        super().__init__([ipw.HTML(f'<h4>{html.escape(method)} · validated energy results</h4>' + table + spin_note),
            self.energy_kind, self.plot, ipw.HTML('<details><summary>Model and automatic checks</summary><p>'
                f'Frozen core: {data["model"]["frozen_core_electrons"]} electrons. '
                f'Basis: {html.escape(data["model"]["basis"])}; auxiliary: {html.escape(data["model"]["auxiliary_basis"])}.'
                '</p>' + diagnostics + '</details>'), ipw.HTML(download),
            ipw.HTML('<p>These corrected energies do not supply transition amplitudes. '
                'Use the separate shared-orbital CASCI route for current Dyson/Kondo calculations.</p>')])
        self._redraw()

    def _redraw(self, _=None):
        if len(self.data['states']) < 2:
            self.plot.value = ''
            return
        key = self.energy_kind.value
        states = self.data['states']
        minimum = min(r[key] for r in states)
        maximum = max((r[key] - minimum) * 27.211386245988 for r in states)
        span = max(.1, maximum * 1.1)
        multiplicities = sorted({r['multiplicity'] for r in states})
        width = max(600, len(multiplicities) * 180 + 130)
        svg = [f'<svg width="100%" viewBox="0 0 {width} 350" role="img" aria-label="Method-specific excitation energies">']
        for i in range(5):
            value = span * i / 4
            y = 290 - 240 * value / span
            svg.append(f'<path d="M65 {y} H{width - 20}" stroke="#dce2e8"/>'
                       f'<text x="55" y="{y + 4}" text-anchor="end" font-size="12">{value:.2f}</text>')
        for row in states:
            i = multiplicities.index(row['multiplicity'])
            x = 100 + i * (width - 140) / len(multiplicities)
            y = 290 - 240 * (row[key] - minimum) * 27.211386245988 / span
            color = ['#2563b7', '#d7473f', '#19855b', '#8844aa'][i % 4]
            label = f'M={row["multiplicity"]}, root {row["root"]}: {(row[key] - minimum) * 27.211386245988:.6f} eV'
            svg.append(f'<path d="M{x} {y} h100" stroke="{color}" stroke-width="3"><title>{label}</title></path>')
        for i, mult in enumerate(multiplicities):
            x = 150 + i * (width - 140) / len(multiplicities)
            svg.append(f'<text x="{x}" y="320" text-anchor="middle" font-size="13">Multiplicity {mult}</text>')
        svg.append('<text x="15" y="185" transform="rotate(-90 15 185)" font-size="12">Energy above lowest displayed state (eV)</text></svg>')
        self.plot.value = ''.join(svg)

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        self.energy_kind.unobserve(self._redraw, names='value')
        super().close()


class CorrelationEnergies(ipw.VBox):
    def __init__(self, entry_uuid, prepare_casscf):
        self.entry_uuid = str(entry_uuid)
        self.plan, self.process_uuid, self._poll_task = None, None, None
        self._disposed = False
        style = {'description_width': 'initial'}
        self.method = ipw.ToggleButtons(options=[('HF → RI-MP2', 'RI-MP2'), ('CASSCF → SC-NEVPT2', 'SC-NEVPT2')],
            style={'button_width': 'auto'})
        self.reference = ipw.Dropdown(description='Verified CASSCF', options=[('Select a reference', None)], style=style,
                                       layout=ipw.Layout(width='95%'))
        self.prepare = ipw.Button(description='Prepare / inspect a CASSCF reference', icon='arrow-right',
                                     layout=ipw.Layout(width='auto'))
        self.prepare.on_click(lambda _: prepare_casscf())
        self.notice, self.message = ipw.HTML(), ipw.HTML()
        self.frozen = ipw.Checkbox(description='Freeze chemical core in the correlation step', value=True, indent=False,
                                    layout=ipw.Layout(width='auto'))
        self.nprocs = ipw.BoundedIntText(value=1, min=1, max=4096, description='Processes', style=style)
        self.memory = MemoryInput(value=1024, style=style)
        self.wall = ipw.BoundedIntText(value=10, min=1, max=100000, description='Wall time (minutes)', style=style)
        self.aux = ipw.Text(description='Correlation auxiliary basis', style=style)
        self.force = ipw.Checkbox(description='Run again even if a matching result exists', value=False, indent=False,
                                   layout=ipw.Layout(width='auto'))
        advanced = ipw.Accordion(children=[ipw.VBox([self.nprocs, self.memory, self.wall, self.aux, self.force])], selected_index=None)
        advanced.set_title(0, 'Resources and advanced settings')
        self.review = ipw.Button(description='Review correlation energies', icon='list', button_style='primary',
            layout=ipw.Layout(width='auto'))
        self.submit = ipw.Button(description='Submit reviewed calculation', icon='play', disabled=True,
            layout=ipw.Layout(width='auto'))
        self.review_text = ipw.HTML()
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        self.saved = ipw.Dropdown(description='Stored calculations', options=[('No calculations yet', None)], style=style,
                                   layout=ipw.Layout(width='95%'))
        self.saved.observe(self._selected, names='value')
        self.refresh = ipw.Button(description='Refresh results and references', icon='refresh', layout=ipw.Layout(width='auto'))
        self.refresh.on_click(self._refresh)
        self.output = ipw.VBox()
        self.form = ipw.VBox([self.frozen, advanced, ipw.HBox([self.review, self.submit],
            layout=ipw.Layout(flex_flow='row wrap')), self.review_text])
        super().__init__([ipw.HTML('<h3>Correlation energies</h3><p>Choose the route matching your reference. '
            'Each calculation keeps this geometry fixed and stores its reference energy, correlation correction '
            'and total energy separately.</p>'), self.method, self.reference, self.prepare, self.notice,
            self.form, self.message, self.refresh, self.saved, self.output])
        self.method.observe(self._source_changed, names='value')
        self.reference.observe(self._source_changed, names='value')
        for control in (self.frozen, self.nprocs, self.memory, self.wall, self.aux, self.force):
            control.observe(self._invalidate, names='value')
        self._refresh()
        self._source_changed()

    def _source(self):
        return self.entry_uuid if self.method.value == 'RI-MP2' else self.reference.value

    def _source_changed(self, _=None):
        self._invalidate()
        nevpt = self.method.value == 'SC-NEVPT2'
        self.reference.layout.display = '' if nevpt else 'none'
        self.prepare.layout.display = '' if nevpt else 'none'
        self.aux.disabled = nevpt
        try:
            if not self._source():
                raise ValueError('First prepare CASSCF, inspect its optimized orbitals, then select that verified reference here.')
            effective = service.defaults(self._source(), self.method.value)
            self.nprocs.value, self.memory.value = effective['nprocs'], effective['memory_mb']
            self.wall.value, self.aux.value = max(1, effective['wallclock_seconds'] // 60), effective['auxiliary_basis']
            self.form.layout.display = ''
            self.notice.value = ('<p><b>Fixed CASSCF reference.</b> The active space, spin/root families and weights '
                'are inherited. Standard per-state canonicalization is used for the correction; there is no new '
                'orbital optimization. Its auxiliary basis must match the CASSCF integral model.</p>') if nevpt else (
                '<p><b>Fresh HF reference.</b> Converge RHF for a singlet or UHF for an open shell, then compute RI-MP2. '
                'The selected geometry, charge and basis are retained. Existing DFT/CAS orbitals are not read as a frozen MP2 reference.</p>')
            self.notice.value += '<p>Small energy/log outputs are retrieved; full electronic files stay on the calculation computer.</p>'
        except (ValueError, KeyError, OSError) as exc:
            self.form.layout.display = 'none'
            self.notice.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'
        self._history()

    def _invalidate(self, _=None):
        self.plan = None
        if hasattr(self, 'submit'):
            self.submit.disabled = True
            self.review_text.value = ''

    def _values(self):
        return {'frozen_core': self.frozen.value, 'nprocs': self.nprocs.value,
                'memory_mb': self.memory.value, 'wallclock_seconds': self.wall.value * 60,
                'auxiliary_basis': self.aux.value.strip()}

    def _review(self, _=None):
        self._invalidate()
        try:
            self.plan = service.review(self._source(), self.method.value, self._values(), self.force.value)
            p = self.plan
            reference = p['reference_summary']
            if p['method'] == 'SC-NEVPT2':
                space = reference['active_space']
                source = f'CAS({space["electrons"]},{len(space["orbitals"])}) · ' + '; '.join(
                    f'multiplicity {r["multiplicity"]}, root {r["root"]}, weight {r["averaging_weight"]:.4g}'
                    for r in reference['states'])
            else:
                source = f'Fresh HF · charge {reference["charge"]:+d} · multiplicity {reference["multiplicity"]}'
            self.review_text.value = (f'<p><b>{p["action"].capitalize()} {p["method"]}</b> · {html.escape(p["execution"])} · '
                f'{p["settings"]["nprocs"]} process(es) · {memory_label(p["settings"]["memory_mb"])} · '
                f'{p["settings"]["wallclock_seconds"] // 60} minutes.</p>'
                f'<p>{html.escape(source)}. Frozen core: {"chemical core" if p["settings"]["frozen_core"] else "none"}.</p>'
                '<details><summary>Review native input</summary><pre>' + html.escape(p['input']) + '</pre></details>')
            self.message.value = ''
            self.submit.disabled = False
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p>' + html.escape(str(exc)) + '</p>'

    def _submit(self, _=None):
        if self.plan is None:
            return
        try:
            self.process_uuid = service.submit(self.plan)
            self._invalidate()
            self._history()
            self.saved.value = self.process_uuid
            try:
                self._poll_task = asyncio.get_running_loop().create_task(self._poll())
            except RuntimeError:
                pass
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p>' + html.escape(str(exc)) + '</p>'

    def _refresh(self, _=None):
        previous = self.reference.value
        rows = service.casscf_sources(self.entry_uuid)
        self.reference.options = [('Select a verified CASSCF reference', None), *rows]
        if previous in [uid for _, uid in rows]:
            self.reference.value = previous
        self._history()

    def _history(self):
        previous = self.saved.value
        rows = service.history(self._source(), self.method.value) if self._source() else []
        self.saved.options = [('Select a calculation', None), *rows]
        self.saved.value = previous if previous in [uid for _, uid in rows] else rows[0][1] if rows else None
        self._selected()

    def _selected(self, _=None):
        for widget in self.output.children:
            widget.close()
        self.output.children = ()
        if not self.saved.value:
            return
        state = progress(self.saved.value)
        if state['success']:
            self.output.children = [CorrelationResults(service.result(self.saved.value))]
        else:
            self.output.children = [ipw.HTML('<p>' + html.escape(state['state'] + ' · ' + state['message']) + '</p>')]

    async def _poll(self):
        try:
            while not self._disposed and self.process_uuid:
                state = progress(self.process_uuid)
                self._history()
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
        for widget in self.output.children:
            widget.close()
        super().close()
