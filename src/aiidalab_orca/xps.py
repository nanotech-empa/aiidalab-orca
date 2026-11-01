"""Optional XPS workspace: atom selection, per-site results and comparison."""

import asyncio
import base64
import csv
import html
import io
import json

import ipywidgets as ipw
import numpy as np
import plotly.graph_objects as go

from . import xps_services as service
from .casci_services import progress
from .presentation import ComputePanel


class XpsSpectrum(ipw.VBox):
    def __init__(self, record, comparisons=()):
        self.record, self.comparisons = record, list(comparisons)
        symbols = sorted({s['symbol'] for s in record['sites']})
        self.edge = ipw.Dropdown(options=[(s+' 1s', s) for s in symbols], description='Edge')
        self.axis = ipw.Dropdown(options=[('Binding energy', 'absolute'), ('Chemical shift', 'relative')], description='Energy axis',
                                 style={'description_width': 'initial'}, layout=ipw.Layout(width='260px'))
        self.width = ipw.BoundedFloatText(value=.4, min=.01, max=10, step=.01, description='Gaussian FWHM (eV)',
                                          style={'description_width': 'initial'}, layout=ipw.Layout(width='260px'))
        self.spin_view = ipw.Dropdown(options=[('Triplet + estimated singlet', 'projected'), ('Raw UKS branches (HS / BS)', 'raw')],
            description='Spin treatment', style={'description_width': 'initial'}, layout=ipw.Layout(width='480px', display='' if record.get('multiplets') else 'none'))
        self.qe = ipw.Dropdown(options=[('No QE overlay', -1)]+[(r['label']+' · '+r['uuid'][:8], i) for i, r in enumerate(comparisons)],
                              value=-1, description='Compare', layout=ipw.Layout(width='95%', display='' if comparisons else 'none'))
        self.figure = go.FigureWidget()
        self.figure.update_layout(template='plotly_white', height=390, margin=dict(l=60, r=20, t=25, b=55),
                                   yaxis_title='Schematic intensity (equal area per component)')
        self.table, self.download = ipw.HTML(), ipw.HTML()
        super().__init__([ipw.HBox([self.edge, self.axis, self.width], layout=ipw.Layout(flex_flow='row wrap')),
                          self.spin_view, self.qe, self.figure, self.table, self.download,
                          ipw.HTML('<p>Each displayed component contributes equal integrated area. These schematic line shapes do not include photoionization cross sections, spin statistical weights or satellite intensities. '
                                   'Chemical shifts use the lowest binding energy within each displayed edge and method. QE absolute energies include its pseudopotential corrections.</p>')])
        for control in (self.edge, self.axis, self.width, self.qe, self.spin_view):
            control.observe(self._update, names='value')
        self._update()

    def _update(self, event=None):
        sites = [s for s in self.record['sites'] if s['symbol'] == self.edge.value]
        if self.record.get('multiplets') and self.spin_view.value == 'projected':
            projected=[]
            for pair in self.record['multiplets']:
                hs=next((s for s in sites if s['atom_index']==pair['atom_index'] and s.get('spin_assignment')=='triplet_ms1'),None)
                if hs:
                    projected += [hs, hs | {'label': f"{hs['symbol']}{hs['atom_index']+1} · 1s · estimated singlet",
                        'binding_energy_ev':pair['singlet_estimate_binding_energy_ev'], 'spin_squared':None,
                        'data_uuid':pair['data_uuid'], 'spin_assignment':'singlet_energy_estimate'}]
            sites=projected
        if not sites:
            return
        relative = self.axis.value == 'relative'
        zero = min(s['binding_energy_ev'] for s in sites) if relative else 0
        selected = {s['atom_index'] for s in sites}
        compare = []
        if self.qe.value >= 0:
            for s in self.comparisons[self.qe.value]['sites']:
                members = set(s.get('equivalent_atom_indices', [s['atom_index']])) & selected
                if s['symbol'] == self.edge.value and members:
                    compare.append(s | {'weight': len(members)})
        qzero = min(s['binding_energy_ev'] for s in compare) if relative and compare else 0
        centres = [s['binding_energy_ev']-zero for s in sites] + [s['binding_energy_ev']-qzero for s in compare]
        sigma = self.width.value / np.sqrt(8*np.log(2))
        x = np.linspace(min(centres)-max(1, 4*sigma), max(centres)+max(1, 4*sigma), 1600)
        self.figure.data = ()
        total = np.zeros_like(x)
        for site in sites:
            y = np.exp(-.5*((x-(site['binding_energy_ev']-zero))/sigma)**2)/(sigma*np.sqrt(2*np.pi))
            total += y
            self.figure.add_scatter(x=x, y=y, name=site['label'], mode='lines')
        self.figure.add_scatter(x=x, y=total, name='ORCA total', line=dict(color='#1f2937', width=2, dash='dot'))
        if compare:
            qe_y = sum(s.get('weight', 1)*np.exp(-.5*((x-(s['binding_energy_ev']-qzero))/sigma)**2)/(sigma*np.sqrt(2*np.pi)) for s in compare)
            self.figure.add_scatter(x=x, y=qe_y, name='QE total', line=dict(color='#777777', dash='dash', width=3))
        self.figure.update_xaxes(title='Chemical shift (eV)' if relative else 'Vertical binding energy (eV)', autorange='reversed')
        rows = []
        for s in sites:
            match = next((q for q in compare if s['atom_index'] in q.get('equivalent_atom_indices', [q['atom_index']])), None)
            qvalue = f"{match['binding_energy_ev']-qzero:.2f}" if match else '—'
            spin = f"{s['spin_squared']:.4f}" if s['spin_squared'] is not None else 'energy estimate'
            population = f"{100*s['hole_population']:.1f}%" if s.get('spin_assignment') != 'singlet_energy_estimate' else '—'
            rows.append(f"<tr><td>{s['label']}</td><td>{s['binding_energy_ev']-zero:.2f}</td><td>{qvalue}</td><td>{spin}</td><td>{population}</td></tr>")
        self.table.value = '<table class="table"><thead><tr><th>Site</th><th>ORCA (eV)</th><th>QE (eV)</th><th>Final ⟨S²⟩</th><th>Core MO on target atom (Mulliken)</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['atom_number', 'element', 'shell', 'component', 'binding_energy_eV', 'spin_squared', 'hole_population', 'site_data_uuid'])
        writer.writerows([s['atom_index']+1, s['symbol'], s['shell'], s.get('spin_assignment','doublet'), s['binding_energy_ev'], s['spin_squared'],
            '' if s.get('spin_assignment')=='singlet_energy_estimate' else s['hole_population'], s['data_uuid']] for s in sites)
        encoded = base64.b64encode(stream.getvalue().encode()).decode()
        snapshot = self.record | {'view': {'edge': self.edge.value, 'energy_axis': self.axis.value,
            'spin_treatment':self.spin_view.value, 'gaussian_fwhm_ev': self.width.value, 'qe_uuid': None if self.qe.value < 0 else self.comparisons[self.qe.value]['uuid']}}
        config = base64.b64encode(json.dumps(snapshot, indent=2, allow_nan=False).encode()).decode()
        self.download.value = f'<a download="xps-sites.csv" href="data:text/csv;base64,{encoded}">Download site energies</a> · <a download="xps-view.json" href="data:application/json;base64,{config}">Download view and provenance</a>'


class XpsSpectroscopy(ipw.VBox):
    def __init__(self, source_uuid):
        self.source_uuid = str(source_uuid)
        self.plan, self._poll_task, self._running_uuid, self._shown_uuid = None, None, None, None
        self.message, self.status, self.empty, self.details = (ipw.HTML() for _ in range(4))
        self.viewer = ipw.VBox()
        self.previous = ipw.Dropdown(description='XPS calculations', style={'description_width': 'initial'}, layout=ipw.Layout(width='95%'))
        self.refresh = ipw.Button(description='Refresh calculations', icon='refresh', layout=ipw.Layout(width='auto'))
        self.atoms = ipw.SelectMultiple(description='Ionize atoms', style={'description_width': 'initial'}, rows=5,
                                         layout=ipw.Layout(width='95%'))
        self.force = ipw.Checkbox(description='Recompute selected sites even if results are available', indent=False, layout=ipw.Layout(width='auto'))
        self.review = ipw.Button(description='Review XPS calculation', icon='list', button_style='primary', layout=ipw.Layout(width='auto'))
        self.submit = ipw.Button(description='Compute XPS', icon='play', button_style='success', disabled=True, layout=ipw.Layout(width='auto'))
        self.calculation = ComputePanel('Compute / extend XPS…', [
            ipw.HTML('<p>Select atoms for 1s ionization (Ctrl/Cmd selects several). Atom numbers match the geometry viewer. '
                     'The geometry, functional and basis remain those of the selected reference. A singlet reference gives a doublet core hole; '
                     'a doublet reference gives high-spin and spin-mixed branches, with an approximate singlet-energy estimate. '
                     'Core orbitals are assigned to atoms before ionization and localized within the occupied 1s subspace only when necessary.</p>'),
            ipw.HTML('<details><summary>How validation works</summary><p>For a doublet reference, each branch is optimized, '
                     'refined and checked by reading its saved wavefunction. Geometry, core-hole location, shell, electron count, '
                     'spin and normalization are checked automatically. Failed checks show an explanation before any energy is accepted. '
                     'Raw UKS branches can be spin mixed; the singlet energy estimate requires additional spin checks.</p></details>'),
            self.atoms, self.force, self.review, self.submit])
        super().__init__([ipw.HTML('<h3>X-ray photoelectron spectroscopy</h3><p>Site-resolved vertical ΔSCF binding energies at this geometry.</p>'),
                          self.previous, self.refresh, self.empty, self.status, self.calculation, self.message, self.details, self.viewer])
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        self.refresh.on_click(self._refresh)
        self.previous.observe(self._open, names='value')
        for control in (self.atoms, self.force):
            control.observe(self._invalidate, names='value')
        info={}
        try:
            info = service.reference_info(source_uuid)
            self.atoms.options = [(f"{a['symbol']}{a['index']+1} · 1s · ({', '.join(f'{x:.2f}' for x in a['position'])}) Å", a['index']) for a in info['atoms']]
        except Exception as exc:
            self.review.disabled = True
            self._error(exc)
        self._refresh()
        if any(a['symbol']=='Co' for a in info.get('atoms', [])):
            from .cobalt_view import CobaltXpsPanel
            one_s=ipw.VBox(self.children[1:])
            methods=ipw.Tab(children=[one_s,CobaltXpsPanel(self.source_uuid)])
            methods.set_title(0,'1s · ΔSCF');methods.set_title(1,'Co 2p · multiplets')
            self.children=(ipw.HTML('<h3>X-ray photoelectron spectroscopy</h3><p>Independent methods at the same frozen geometry.</p>'),methods)

    def _error(self, exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _invalidate(self, event=None):
        self.plan = None
        self.submit.disabled = True
        self.message.value = ''

    def _review(self, event=None):
        self._invalidate()
        try:
            self.plan = service.prepare(self.source_uuid, self.atoms.value, force_recompute=self.force.value)
            count = len(self.plan['missing'])
            reused = len(self.plan['reuse'])
            self.message.value = f'<p><b>{count} new site calculation(s), {reused} verified site result(s) reused.</b> Calculations run sequentially. '
            self.message.value += ('Missing wavefunction: repeat the fixed-geometry SCF first. ' if self.plan['regenerate_reference'] else '') + '</p>'
            if self.plan.get('open_shell'):
                reused_branches=sum(len(v) for v in self.plan['branch_reuse'].values())
                self.message.value += f'<p>{2*len(self.plan["atom_indices"])-reused_branches} new spin-branch CalcJob(s); {reused_branches} branch result(s) reused.</p>'
            self.message.value += ''.join('<p>'+html.escape(w)+'</p>' for w in self.plan['warnings'])
            if self.plan.get('validation'):
                self.message.value += '<p class="orca-notice">'+html.escape(self.plan['validation'])+'</p>'
            self.message.value += '<p>Final core-hole location, electron count and spin are checked before a binding energy is accepted.</p>'
            policy = self.plan['storage_policy']
            if policy.get('mode') == 'remote':
                self.message.value += '<p>Wavefunctions remain in their original calculation directories. Only file manifests and scientific results are retrieved.</p>'
            else:
                self.message.value += f"<p>Wavefunctions follow the reference storage policy: retrieve bundles up to {policy['threshold_mb']:g} MiB; stash larger bundles in <code>{html.escape(policy['stash_directory'])}</code>.</p>"
            self.submit.disabled = self._running_uuid is not None
        except Exception as exc:
            self._error(exc)

    def _submit(self, event=None):
        if self.plan is None or self.submit.disabled:
            return
        try:
            uuid = service.submit_plan(self.plan)
            self._invalidate()
            self._start(uuid)
        except Exception as exc:
            self._error(exc)

    def _start(self, uuid):
        self._running_uuid = str(uuid)
        self.review.disabled, self.submit.disabled = True, True
        self.status.value = '<p>Submitted XPS · <code>'+str(uuid)+'</code></p>'
        if self._poll_task:
            self._poll_task.cancel()
        self._poll_task = asyncio.get_running_loop().create_task(self._poll())

    async def _poll(self):
        try:
            while self._running_uuid:
                state = progress(self._running_uuid)
                self.status.value = '<p><b>'+html.escape(state['state'])+'</b> · <code>'+self._running_uuid+'</code></p>'
                if state['finished']:
                    uuid, self._running_uuid = self._running_uuid, None
                    self.review.disabled = False
                    self._refresh(preferred=uuid)
                    if not state['success']:
                        self._error(state['message']+'; '.join(state['reports']))
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._running_uuid = None
            self.review.disabled = False
            self._error(exc)

    def _refresh(self, event=None, *, preferred=None):
        try:
            rows = service.runs(self.source_uuid)
            self.empty.value = '' if rows else '<p class="orca-notice">No XPS results for this reference. Select the atoms you need under Compute / extend XPS.</p>'
            selected = preferred or self.previous.value
            self.previous.options = [('Select an XPS calculation', None)] + [(f"{r['date'][:16]} · {r['state']} · {r['label']}", r['uuid']) for r in rows]
            self.previous.value = selected if any(r['uuid'] == selected for r in rows) else rows[0]['uuid'] if rows else None
        except Exception as exc:
            self._error(exc)

    def _open(self, event):
        uuid = event['new']
        if not uuid or uuid == self._shown_uuid:
            return
        try:
            state = progress(uuid)
            if not state['finished']:
                if not self._running_uuid:
                    self._start(uuid)
                return
            record = service.result(uuid)
            if not state['success']:
                self._error(state['message']+'; '.join(state['reports']))
            from .app import close_widget_tree
            for child in self.viewer.children:
                close_widget_tree(child)
            self.viewer.children = (XpsSpectrum(record, service.qe_comparisons(self.source_uuid)),) if record['sites'] else ()
            self._shown_uuid = uuid
            self.details.value = '<p>'+('Complete' if record['complete'] else 'Partial results · inspect the failed site before interpretation') + '</p><details><summary>Provenance and validation</summary>'
            self.details.value += ''.join(f"<p>{s['label']} · initial multiplicity {s['initial_multiplicity']} · {s.get('spin_assignment', 'doublet')} · {s['localization']}<br>Site data: <code>{s['data_uuid']}</code><br>CalcJob: <code>{s['calculation_uuid']}</code></p>" for s in record['sites'])+'</details>'
            self.details.value += ''.join('<p style="color:#a02020">'+html.escape(w)+'</p>' for s in record['sites'] for w in s['warnings'])
            self.details.value += ''.join('<p style="color:#a02020"><b>No energy accepted:</b> '
                +html.escape(d['reason'])+'<br>'+html.escape(d['guidance'])+'</p>'
                for d in record.get('diagnostics', []))
            if record.get('multiplets'):
                self.details.value += '<p class="orca-notice">The estimated singlet energies use approximate two-state Yamaguchi spin projection. Raw UKS branches remain available in the spin-treatment selector. No spin-pure singlet wavefunction or physical relative intensities are implied.</p>'
        except Exception as exc:
            self._error(exc)

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        if self._poll_task:
            self._poll_task.cancel()
        super().close()
