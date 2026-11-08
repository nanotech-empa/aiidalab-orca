"""Independent optical calculations with linked spectra, states and NTO pairs."""

import asyncio
import html
import json
import math

import ipywidgets as ipw
import numpy as np

from . import optical_services as service
from . import optical_data as display
from .casci_services import progress
from .interactive_svg import InteractiveSvg
from .orbitals import CubeDisplayMixin
from .presentation import ComputePanel
from .resources import MemoryInput
from .widget_lifecycle import close_widget_tree

STYLE = {'description_width': 'initial'}
WIDE = {'width': '95%'}


def state_label(row):
    prefix = {'singlet': 'S', 'triplet': 'T', 'uks': 'UKS root '}[row['family']]
    return f'{prefix}{row["root"]} · {row["energy_ev"]:.3f} eV · f={row["oscillator_strength"]:.5g}'


class OpticalSpectrum(ipw.VBox):
    def __init__(self, data, choose, previews=None):
        self.data, self.choose = data, choose
        self._availability = previews or {}
        self._disposed = False
        self.unit = ipw.ToggleButtons(options=[('Energy (eV)', 'eV'), ('Wavelength (nm)', 'nm')])
        self.width = ipw.BoundedFloatText(value=.15, min=.001, max=5, step=.01,
                                         description='FWHM (eV)', style=STYLE)
        self.lower = ipw.FloatText(description='Minimum', style=STYLE, step=.01)
        self.upper = ipw.FloatText(description='Maximum', style=STYLE, step=.01)
        self.reset = ipw.Button(description='Show all states', icon='arrows-v', layout=ipw.Layout(width='auto'))
        self.state = ipw.Dropdown(description='Excited state', style=STYLE,
            options=[(state_label(row), row['id']) for row in data['states']], layout=ipw.Layout(**WIDE))
        self.chart = InteractiveSvg(on_action=self._action)
        self.description = ipw.HTML()
        self.download = ipw.HTML()
        self._ready = False
        self.unit.observe(self._reset, names='value')
        self.reset.on_click(self._reset)
        for control in (self.width, self.lower, self.upper):
            control.observe(self._draw, names='value')
        self.state.observe(self._selected, names='value')
        super().__init__([ipw.HTML(f'<h4>{html.escape(data["method"])} · vertical optical excitations</h4>'
            '<p>Excited-state energies are relative to the continued DFT reference at this fixed geometry. '
            'Click a stick, marker or table row to inspect that state. Dark states remain selectable.</p>'),
            self.unit, ipw.HBox([self.lower, self.upper, self.width, self.reset], layout=ipw.Layout(flex_flow='row wrap')),
            self.chart, self.state, self.description, self.download])
        self._ready = True
        self._reset()
        self._selected()

    def _reset(self, _=None):
        values = [row['energy_ev'] if self.unit.value == 'eV' else row['wavelength_nm'] for row in self.data['states']]
        margin = max(.1 if self.unit.value == 'eV' else 2, (max(values)-min(values))*.1)
        self._ready = False
        self.lower.value, self.upper.value = max(.01, round(min(values)-margin, 2)), round(max(values)+margin, 2)
        self._ready = True
        self._draw()

    def set_availability(self, values):
        self._availability = values
        self._draw()

    def _downloads(self, svg=None, spectrum=None):
        links = [display.download_link('optical-states.csv', 'States CSV', display.states_csv(self.data, self._availability), 'text/csv'),
                 display.download_link('optical-excitations.json', 'Full data JSON', json.dumps(self.data, indent=2), 'application/json')]
        if svg is not None:
            links += [display.download_link('optical-spectrum.csv', 'Spectrum CSV', spectrum, 'text/csv'),
                      display.download_link('optical-spectrum.svg', 'Spectrum SVG', svg, 'image/svg+xml')]
        self.download.value = '<p>Downloads: ' + ' · '.join(links) + '</p>'

    def _action(self, action):
        ids = action.get('ids', [])
        if action.get('action') == 'select' and isinstance(ids, list) and len(ids) == 1:
            if ids[0] in {row['id'] for row in self.data['states']}:
                self.state.value = ids[0]

    def _selected(self, _=None):
        row = next(r for r in self.data['states'] if r['id'] == self.state.value)
        spin = f' ⟨S²⟩ = {row["spin_squared"]:.5f}.' if row['spin_squared'] is not None else ''
        self.description.value = ('<p><b>' + html.escape(state_label(row)) + '</b> · ' + f'{row["wavelength_nm"]:.1f} nm.' + spin +
            (' UKS spin labels are approximate; this is not a spin-pure multiplicity assignment.' if row['family'] == 'uks' else '') +
            '</p><details><summary>Native orbital contributions · ORCA indices start at 0</summary><p>' + ('; '.join(
                f'{c["hole"]}{c["hole_spin"]} → {c["particle"]}{c["particle_spin"]}: {c["native_weight"]:.4f}'
                for c in row['contributions']) or 'none above the native print threshold') +
            '. These are truncated native response contributions, not NTO weights.</p></details>')
        self.choose(row['id'])
        self._draw()

    def _draw(self, _=None):
        if not self._ready:
            return
        lo, hi = self.lower.value, self.upper.value
        if not math.isfinite(lo+hi) or hi <= lo or lo <= 0:
            self.chart.value = '<p>Choose positive, increasing plot limits.</p>'
            self._downloads()
            return
        from aiida_empa_orca.optical import HC_EV_NM
        rows = self.data['states']
        x = np.linspace(lo, hi, 900)
        energies = x if self.unit.value == 'eV' else HC_EV_NM/x
        sigma = self.width.value / (2*np.sqrt(2*np.log(2)))
        curve = sum(r['oscillator_strength']*np.exp(-.5*((energies-r['energy_ev'])/sigma)**2)/(sigma*np.sqrt(2*np.pi)) for r in rows)
        ymax = max(float(curve.max()), max(r['oscillator_strength']/(sigma*np.sqrt(2*np.pi)) for r in rows), .001)*1.1
        sx = lambda value: 90 + 825*(value-lo)/(hi-lo)
        sy = lambda value: 280 - 225*value/ymax
        view = {'axis_unit': self.unit.value, 'minimum': lo, 'maximum': hi, 'fwhm_ev': self.width.value,
                'broadening': 'Gaussian in energy; ordinate per eV; no intensity normalization'}
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="950" height="350" viewBox="0 0 950 350" font-family="Arial, sans-serif" role="img" aria-label="Vertical absorption spectrum">',
               '<title>' + html.escape(self.data['method'] + ' · vertical optical excitations') + '</title>',
               '<metadata>' + html.escape(json.dumps(display.metadata(self.data) | view)) + '</metadata>',
               '<rect x="0" y="0" width="950" height="350" fill="#f8fafc" rx="8"/>']
        for i in range(5):
            value = ymax*i/4
            y = sy(value)
            svg.append(f'<path d="M90 {y} H915" stroke="#dce4ec"/><text x="80" y="{y+4}" text-anchor="end" font-size="12">{value:.3g}</text>')
            value = lo+(hi-lo)*i/4
            svg.append(f'<text x="{sx(value)}" y="310" text-anchor="middle" font-size="12">{value:.2f}</text>')
        path = ' '.join(('M' if i == 0 else 'L') + f'{sx(v):.2f},{sy(c):.2f}' for i, (v, c) in enumerate(zip(x, curve)))
        svg.append(f'<path d="{path}" stroke="#247b91" fill="none" stroke-width="2"/>')
        table = ['<table style="width:100%;border-collapse:collapse"><tr><th>State</th><th>Energy (eV)</th><th>λ (nm)</th><th>Oscillator strength</th><th>NTO analysis</th><th>Cube preview pairs</th></tr>']
        for row in rows:
            value = row['energy_ev'] if self.unit.value == 'eV' else row['wavelength_nm']
            attributes = 'data-ids="' + html.escape(json.dumps([row['id']]), quote=True) + '" tabindex="0" role="button"'
            color = '#d44953' if row['family'] == 'triplet' else '#2463b7'
            selected = row['id'] == self.state.value
            if lo <= value <= hi:
                position = sx(value)
                height = row['oscillator_strength']/(sigma*np.sqrt(2*np.pi))
                svg.append(f'<g {attributes} style="cursor:pointer"><title>{html.escape(state_label(row))}</title>'
                    f'<path d="M{position} 280 V{sy(height)}" stroke="{color}" stroke-width="{4 if selected else 2}"/>'
                    f'<circle cx="{position}" cy="288" r="{5 if selected else 3}" fill="{color}"/>'
                    f'<rect x="{position-6}" y="{min(sy(height),280)-6}" width="12" height="{max(20,abs(280-sy(height))+22)}" fill="transparent"/></g>')
            table.append(f'<tr {attributes} style="cursor:pointer;background:{"#e5effa" if selected else "transparent"}">'
                f'<td style="padding:7px">{html.escape(row["id"])}</td><td>{row["energy_ev"]:.4f}</td>'
                f'<td>{row["wavelength_nm"]:.1f}</td><td>{row["oscillator_strength"]:.7g}</td>'
                f'<td>{"Available" if row["nto"] else "Not qualified" if row["family"] == "triplet" else "Not requested"}</td>'
                f'<td>{html.escape(display.preview_label(self._availability.get(row["id"], {}))) if row["nto"] else "—"}</td></tr>')
        svg.append(f'<text x="490" y="340" text-anchor="middle" font-size="14">{"Excitation energy (eV)" if self.unit.value == "eV" else "Wavelength (nm)"}</text>'
                   '<text x="17" y="175" transform="rotate(-90 17 175)" text-anchor="middle" font-size="13">Broadened oscillator strength / eV</text></svg>')
        table.append('</table><p>Gaussian display broadening is defined in energy, also in the wavelength view; the ordinate stays per eV. No intensity normalization or absolute extinction coefficient is applied.</p>')
        self.chart.value = ''.join(svg+table)
        self._downloads(''.join(svg), display.spectrum_csv(self.data, x, energies, curve, view))

    def close(self):
        if self._disposed:
            return
        self._disposed = True
        self.chart.close()
        super().close()


class NtoPreviews(CubeDisplayMixin, ipw.VBox):
    def __init__(self, optical_uuid):
        self.optical_uuid = str(optical_uuid)
        self.data = service.result(optical_uuid)
        self.plan, self.process_uuid, self._poll_task = None, None, None
        self._job_uuid = None
        self._cube_view, self.render_panel = None, None
        self._disposed = False
        initial = service.cube_defaults(optical_uuid)
        self.state_id = None
        self.on_availability = None
        self._inventory = []
        self._updating_members = False
        self._view_context = None
        self.pairs = ipw.SelectMultiple(description='NTO pairs', style=STYLE, layout=ipw.Layout(width='95%', height='110px'))
        self.note, self.message = ipw.HTML(), ipw.HTML()
        self.grid = ipw.BoundedIntText(value=80, min=40, max=256, description='Grid points/axis', style=STYLE)
        self.retention = ipw.Dropdown(description='Full cubes', style=STYLE, layout=ipw.Layout(**WIDE),
            options=[('Leave in calculation directory', 'leave'), ('Stash full cubes', 'stash'), ('Delete after preview validation', 'delete')])
        self.stash = ipw.Text(value=initial['storage_policy']['stash_directory'], description='Stash directory', style=STYLE, layout=ipw.Layout(**WIDE))
        self.threshold = ipw.BoundedFloatText(value=initial['storage_policy']['threshold_mb'], min=0, max=10000,
                                             description='NTO retrieval limit (MiB)', style=STYLE)
        self.codes = {key: ipw.Dropdown(description=label, style=STYLE, options=initial['codes'][key], layout=ipw.Layout(**WIDE))
                      for key, label in [('plot', 'ORCA plot'), ('cubehandler', 'Cubehandler')]}
        advanced = ipw.Accordion(children=[ipw.VBox([self.grid, self.threshold, *self.codes.values(),
            ipw.HTML('<p>Selected native NTO files use size-aware electronic preservation: below this limit they are retrieved; larger files are stashed in the directory above. Full cube retention is a separate choice. Only cubehandler-reduced cube previews are retrieved.</p>')])], selected_index=None)
        advanced.set_title(0, 'Grid, electronic storage and codes')
        self.review = ipw.Button(description='Review NTO previews', icon='list', layout=ipw.Layout(width='auto'))
        self.submit = ipw.Button(description='Generate hole/particle previews', icon='play', disabled=True, layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        self.previous = ipw.Dropdown(description='Saved NTO previews', style=STYLE, layout=ipw.Layout(**WIDE))
        self.previous.observe(self._open_previous, names='value')
        self.refresh = ipw.Button(description='Refresh NTO previews', icon='refresh', layout=ipw.Layout(width='auto'))
        self.refresh.on_click(lambda _: self._refresh())
        self.availability_note = ipw.HTML()
        self.display_pair = ipw.Dropdown(description='Inspect pair', style=STYLE, layout=ipw.Layout(**WIDE))
        self.member = ipw.ToggleButtons(options=[('Hole', 'hole'), ('Particle', 'particle')])
        self.display_pair.observe(self._choose_member, names='value')
        self.member.observe(self._choose_member, names='value')
        self.cube = ipw.Dropdown(description='NTO to display', style=STYLE, layout=ipw.Layout(**WIDE))
        self.cube.observe(self._show_cube, names='value')
        self.cube.layout.display = 'none'  # Kept for the shared saved-view/render interface.
        self.member_controls = ipw.VBox([self.display_pair, self.member, ipw.HTML('<p>Hole/particle switching keeps the camera, isovalues and slice settings. Blue/gold indicate amplitude signs, not hole versus particle.</p>')])
        self.download, self.cube_box = ipw.HTML(), ipw.VBox()
        self.compute = ComputePanel('Compute NTO hole/particle previews…', [self.pairs, self.retention, self.stash, advanced,
            ipw.HBox([self.review, self.submit], layout=ipw.Layout(flex_flow='row wrap'))])
        super().__init__([ipw.HTML('<h4>Natural transition orbitals</h4>'), self.note,
                          ipw.HBox([self.previous, self.refresh], layout=ipw.Layout(flex_flow='row wrap')), self.availability_note,
                          self.compute, self.message, self.member_controls, self.cube, self.download, self.cube_box])
        for control in (self.pairs, self.grid, self.retention, self.stash, self.threshold, *self.codes.values()):
            control.observe(self._invalidate, names='value')
        self._refresh()

    def choose(self, state_id):
        self.state_id = state_id
        state = next(r for r in self.data['states'] if r['id'] == state_id)
        pairs = state['nto']['pairs'] if state['nto'] else []
        self.pairs.options = [(f'Pair {i+1}: {p["hole"]}{p["hole_spin"]} → {p["particle"]}{p["particle_spin"]} · native weight {p["weight"]:.6f}', i+1)
                              for i, p in enumerate(pairs)]
        self.pairs.value = (1,) if pairs else ()
        self.compute.layout.display = '' if pairs else 'none'
        self.note.value = ('<p>Both members of each pair are generated together. Weights are native response-pseudodensity eigenvalues, not MO occupations or necessarily probabilities; full-TDDFT weights may exceed one. Only pairs above the print threshold are listed.</p>'
                          if pairs else '<p>No qualified NTO file is available for this state in this result. Triplet energies are supported; triplet NTO generation is not yet qualified. Choose a state with NTO analysis, or review a new optical calculation requesting NTOs.</p>')
        self._invalidate()
        self._refresh()

    def _invalidate(self, _=None):
        self.plan = None
        self.submit.disabled = True
        self.message.value = ''

    def _review(self, _=None):
        self._invalidate()
        try:
            self.plan = service.review_cubes(self.optical_uuid, {'state_id': self.state_id, 'pairs': list(self.pairs.value)},
                {'grid_points': self.grid.value, 'retention': self.retention.value, 'stash_directory': self.stash.value.strip()},
                {'threshold_mb': self.threshold.value, 'stash_directory': self.stash.value.strip()},
                {key: control.value for key, control in self.codes.items()})
            self.message.value = f'<p><b>{"Reuse saved previews" if self.plan["reuse_uuid"] else "Generate and reduce both NTO pair members"}</b> · {len(self.pairs.value)} pairs · {self.grid.value} grid points/axis · full cubes: {self.retention.value}.</p>'
            self.submit.disabled = False
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'

    def _submit(self, _=None):
        try:
            self._job_uuid = service.submit_cubes(self.plan)
            self._invalidate()
            self._start_poll()
            self._refresh()
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'

    def _start_poll(self):
        if self._poll_task:
            self._poll_task.cancel()
        try:
            self._poll_task = asyncio.get_running_loop().create_task(self._poll())
        except RuntimeError:
            pass

    async def _poll(self):
        while self._job_uuid:
            status = progress(self._job_uuid)
            self.message.value = '<p>' + html.escape(status['state'] + ' · ' + status.get('message', '')) + '</p>'
            if status['finished']:
                self._refresh()
                return
            await asyncio.sleep(3)

    def availability(self):
        return display.availability(self.data, self._inventory)

    def _refresh(self):
        self._inventory = service.preview_inventory(self.optical_uuid)
        rows = [(r['date'][:16] + ' · ' + r['state_id'] + ' · pairs ' + ', '.join(map(str, r['ready_pairs'])), r['uuid'])
                for r in self._inventory if r['ready_pairs'] and r['state_id'] == self.state_id]
        old = self.previous.value
        self.previous.options = [('Select saved previews' if rows else 'No saved pair previews for this state', None)] + rows
        valid = {uid for label, uid in rows}
        self.previous.value = self._job_uuid if self._job_uuid in valid else old if old in valid else rows[0][1] if rows else None
        values = self.availability()
        state = next((r for r in self.data['states'] if r['id'] == self.state_id), None)
        summary = display.preview_label(values.get(self.state_id, {}))
        self.availability_note.value = ('<p><b>Cube preview pairs:</b> ' + html.escape(summary) +
            ('. Use <b>Compute NTO hole/particle previews…</b> to generate the pairs you need.' if not rows and state and state['nto'] else '.') + '</p>')
        self.member_controls.layout.display = '' if rows else 'none'
        if not rows:
            self.cube.options = []
            self.download.value = ''
            if self._cube_view:
                close_widget_tree(self._cube_view)
                self._cube_view = None
            if self.render_panel:
                close_widget_tree(self.render_panel)
                self.render_panel = None
            self._view_context = None
            self.cube_box.children = []
        if self.on_availability:
            self.on_availability(values)

    def _open_previous(self, _=None):
        if not self.previous.value:
            return
        record = next(r for r in self._inventory if r['uuid'] == self.previous.value)
        self.process_uuid = record['uuid']
        state = next(r for r in self.data['states'] if r['id'] == record['state_id'])
        old_pair = self.display_pair.value
        self._updating_members = True
        try:
            self.cube.options = [(f'{state["id"]} · pair {i} · {role}', name)
                for i in record['ready_pairs'] for role, name in record['members'][str(i)].items()]
            self.display_pair.options = [(f'Pair {i} · {state["nto"]["pairs"][i-1]["hole_spin"]} · native weight {state["nto"]["pairs"][i-1]["weight"]:.6f}', i)
                                         for i in record['ready_pairs']]
            self.display_pair.value = old_pair if old_pair in record['ready_pairs'] else record['ready_pairs'][0]
        finally:
            self._updating_members = False
        self._choose_member()

    def _choose_member(self, _=None):
        if self._updating_members or not self.previous.value or not self.display_pair.value:
            return
        record = next(r for r in self._inventory if r['uuid'] == self.previous.value)
        filename = record['members'][str(self.display_pair.value)][self.member.value]
        if self.cube.value != filename:
            self.cube.value = filename
        elif self._cube_view is None:
            self._show_cube()

    def _show_cube(self, _=None):
        if self._updating_members or not self.cube.value:
            return
        # A view is presentation state only; native cube values are never rescaled.
        snapshot = None
        context = (self.process_uuid, self.state_id)
        if self._cube_view is not None and self._view_context == context:
            try:
                snapshot = self._cube_view.view_settings()
            except ValueError:  # No camera has reached the browser yet.
                pass
        if self._cube_view is not None and self._view_context == context:
            from .property_services import preview_content
            content = preview_content(self.process_uuid, self.cube.value)
            self._cube_view.set_content(content)
            self.render_panel.filename = self.cube.value
            self.download.value = display.download_link(self.cube.value, 'Download reduced cube', content, 'text/plain')
        else:
            CubeDisplayMixin._show_cube(self)
        self._view_context = context
        if snapshot:
            iso = self._cube_view.viewer3d.isovalues
            values = [value for value, _ in snapshot['render']['iso']]
            # An isovalue outside the new data range correctly shows no surface.
            # Widen only the input-control limits so it is not silently clamped.
            if values:
                data_range_label = iso.info.value
                iso.set_range(vmin=min(iso.iso_min, *values), vmax=max(iso.iso_max, *values))
                iso.info.value = data_range_label
            self._cube_view.apply_view_settings(snapshot)
        record = next(r for r in self._inventory if r['uuid'] == self.process_uuid)
        self._updating_members = True
        try:
            for number, members in record['members'].items():
                for role, name in members.items():
                    if name == self.cube.value:
                        self.display_pair.value, self.member.value = int(number), role
        finally:
            self._updating_members = False

    def close(self):
        if self._disposed:
            return
        self._disposed = True
        if self._poll_task:
            self._poll_task.cancel()
        self.on_availability = None
        if self._cube_view:
            close_widget_tree(self._cube_view)
        if self.render_panel:
            close_widget_tree(self.render_panel)
        super().close()


class OpticalExcitations(ipw.VBox):
    def __init__(self, source_uuid):
        self.source_uuid = str(source_uuid)
        self.plan, self.process_uuid, self._poll_task = None, None, None
        self._disposed = False
        self.saved = ipw.Dropdown(description='Optical calculations', style=STYLE, layout=ipw.Layout(**WIDE))
        self.refresh = ipw.Button(description='Refresh optical results', icon='refresh', layout=ipw.Layout(width='auto'))
        self.message, self.review_text, self.output = ipw.HTML(), ipw.HTML(), ipw.VBox()
        self.method = ipw.Dropdown(description='Response method', options=[('TDA-DFT', 'TDA'), ('Full TDDFT', 'TDDFT')], style=STYLE)
        self.roots = ipw.BoundedIntText(value=5, min=1, max=100, description='Excited roots per family', style=STYLE)
        self.triplets = ipw.Checkbox(description='Also compute spin-adapted triplets (RKS singlet only)', value=False, indent=False, layout=ipw.Layout(width='auto'))
        self.nto = ipw.Checkbox(description='Compute native NTO analysis', value=True, indent=False)
        self.nto_states = ipw.Text(description='NTO states (optional)', placeholder='Blank: all; e.g. 1 2 3', style=STYLE)
        self.nprocs = ipw.BoundedIntText(value=1, min=1, max=4096, description='Processes', style=STYLE)
        self.memory = MemoryInput(value=1024, style=STYLE)
        self.wall = ipw.BoundedIntText(value=10, min=1, max=100000, description='Wall time (minutes)', style=STYLE)
        self.iterations = ipw.BoundedIntText(value=100, min=1, max=1000, description='Maximum response iterations', style=STYLE)
        self.force = ipw.Checkbox(description='Run again even if a matching result exists', value=False, indent=False, layout=ipw.Layout(width='auto'))
        self.review = ipw.Button(description='Review optical calculation', icon='list', button_style='primary', layout=ipw.Layout(width='auto'))
        self.submit = ipw.Button(description='Submit reviewed calculation', icon='play', disabled=True, layout=ipw.Layout(width='auto'))
        advanced = ipw.Accordion(children=[ipw.VBox([self.nto_states, self.nprocs, self.memory, self.wall, self.iterations, self.force])], selected_index=None)
        advanced.set_title(0, 'Resources and advanced settings')
        self.compute = ComputePanel('Compute / extend optical excitations…', [self.method, self.roots, self.triplets, self.nto, advanced,
            ipw.HBox([self.review, self.submit], layout=ipw.Layout(flex_flow='row wrap')), self.review_text])
        super().__init__([ipw.HTML('<h3>Optical excitations · UV–Vis</h3><p>Continue the selected DFT reference at this fixed geometry. '
            'TDA and full TDDFT are explicit choices. These optical states do not supply the current CASCI/Dyson/Kondo vectors.</p>'),
            ipw.HBox([self.saved, self.refresh], layout=ipw.Layout(flex_flow='row wrap')),
            self.message, self.output, self.compute])
        self.saved.observe(self._selected, names='value')
        self.refresh.on_click(self._refresh)
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        for control in (self.method, self.roots, self.triplets, self.nto, self.nto_states, self.nprocs, self.memory, self.wall, self.iterations, self.force):
            control.observe(self._invalidate, names='value')
        try:
            default = service.defaults(source_uuid)
            self.nprocs.value, self.memory.value, self.wall.value = default['nprocs'], default['memory_mb'], max(1, default['wallclock_seconds']//60)
            self.triplets.disabled = default.get('reference_type') == 'UKS'
        except ValueError as exc:
            self.compute.layout.display = 'none'
            self.message.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'
        self._refresh()

    def _invalidate(self, _=None):
        self.plan = None
        self.submit.disabled = True
        self.review_text.value = ''

    def _review(self, _=None):
        self._invalidate()
        try:
            roots = [int(i) for i in self.nto_states.value.replace(',', ' ').split()]
            self.plan = service.review(self.source_uuid, {'method': self.method.value, 'nroots': self.roots.value,
                'triplets': self.triplets.value, 'nto': self.nto.value, 'nto_states': roots,
                'maxiter': self.iterations.value, 'nprocs': self.nprocs.value, 'memory_mb': self.memory.value,
                'wallclock_seconds': self.wall.value*60}, self.force.value)
            self.review_text.value = ('<p><b>' + ('Reuse matching optical calculation' if self.plan['reuse_uuid'] else 'Compute vertical optical excitations') +
                '</b> · ' + html.escape(self.plan['execution']) + '</p><p>Geometry, charge, DFT functional, basis and grids follow this reference. '
                'SCF is continued from its saved orbitals and its energy must agree within 10⁻⁷ Hartree. No excited-state geometry optimization, SOC, spin flip or automatic scientific remedy is added.</p>'
                '<details><summary>Native ORCA input</summary><pre>' + html.escape(self.plan['input']) + '</pre></details>')
            self.submit.disabled = False
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'

    def _submit(self, _=None):
        try:
            self.process_uuid = service.submit(self.plan)
            self._invalidate()
            self._refresh()
            if self._poll_task:
                self._poll_task.cancel()
            self._poll_task = asyncio.get_running_loop().create_task(self._poll())
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'

    async def _poll(self):
        while not self._disposed:
            status = progress(self.process_uuid)
            self.message.value = '<p>' + html.escape(status['state'] + ' · ' + status.get('message', '')) + '</p>'
            if status['finished']:
                self._refresh()
                if status['success']:
                    self.saved.value = self.process_uuid
                return
            await asyncio.sleep(3)

    def _refresh(self, _=None):
        rows = service.runs(self.source_uuid)
        old = self.saved.value
        self.saved.options = [('Select an optical calculation', None)] + [(r['date'][:16]+' · '+r['label']+' · '+r['state'], r['uuid']) for r in rows]
        valid = {r['uuid'] for r in rows}
        self.saved.value = self.process_uuid if self.process_uuid in valid else old if old in valid else rows[0]['uuid'] if rows else None
        if not rows:
            self.compute.show()

    def _selected(self, _=None):
        for child in self.output.children:
            child.close()
        self.output.children = []
        if not self.saved.value:
            return
        try:
            status = progress(self.saved.value)
            if not status['success']:
                self.message.value = ('<p>' + html.escape(status['state'] + ' · ' + status['message']) + '</p>'
                    '<details><summary>Calculation diagnostics</summary><pre>' + html.escape('\n'.join(status['reports'][-8:])) + '</pre></details>')
                return
            self.message.value = ''
            data = service.result(self.saved.value)
            ntos = NtoPreviews(self.saved.value)
            spectrum = OpticalSpectrum(data, ntos.choose, ntos.availability())
            ntos.on_availability = spectrum.set_availability
            self.output.children = [spectrum, ntos]
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.message.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'

    def close(self):
        self._disposed = True
        if self._poll_task:
            self._poll_task.cancel()
        for child in self.output.children:
            child.close()
        super().close()
