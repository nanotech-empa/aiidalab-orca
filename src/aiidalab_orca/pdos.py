"""Linked molecular PDOS, orbital-character table and existing preview selection."""
import asyncio
import base64
import csv
import html
import io
import json

import ipywidgets as ipw
import numpy as np

from . import pdos_services as service
from .pdos_data import gaussian_dos, molecular_normal, p_perpendicular
from .interactive_svg import InteractiveSvg


class PdosPanel(ipw.VBox):
    def __init__(self, source_uuid, *, kind=None, on_select=None):
        self.source_uuid = str(source_uuid)
        self.on_select = on_select
        self.record = None
        self._task = None
        self._updating = False
        self._visible = []
        self._disposed = False
        self._syncing_atoms = False
        self.structure_viewer = None
        ctx, codes = service.context(self.source_uuid), service.codes(self.source_uuid)
        self.automatic_status = ctx.get('automatic_status', {})
        style = {'description_width': 'initial'}
        self.kind = ipw.Dropdown(options=list(ctx['sets']), description='Orbital set', style=style)
        if kind in ctx['sets']:
            self.kind.value = kind
        self.export = ipw.Dropdown(options=codes['export'], description='ORCA export', style=style)
        self.worker = ipw.Dropdown(options=codes['character'], description='Character worker', style=style)
        self.force = ipw.Checkbox(description='Recompute character', value=False, indent=False)
        self.memory = ipw.BoundedIntText(value=8, min=1, max=64, description='Analysis memory (GiB)', style=style)
        self.wallclock = ipw.BoundedIntText(value=30, min=1, max=10080,
            description='Analysis wall time (minutes)', style=style)
        setup = ipw.Accordion(children=[ipw.VBox([self.export, self.worker, self.memory, self.wallclock, self.force])], selected_index=None)
        setup.set_title(0, 'Codes and recomputation')
        self.compute = ipw.Button(description='Compute orbital character', icon='calculator', button_style='primary',
                                  layout=ipw.Layout(width='auto'))
        self.compute.on_click(self._compute)
        self.status, self.note, self.error = ipw.HTML(), ipw.HTML(), ipw.HTML()
        self.atoms = ipw.SelectMultiple(description='Atoms / fragment', style=style,
                                        layout=ipw.Layout(display='none'))
        self.geometry_box = ipw.VBox()
        self.element = ipw.Dropdown(description='Select element', style=style)
        self.mode = ipw.Dropdown(options=[('Atoms / fragment', 'atoms'), ('s / p / d character', 'angular'),
                                        ('Perpendicular p · π-like', 'pi')], description='Projection', style=style)
        self.lower = ipw.FloatText(description='Minimum (eV)', step=.01, style=style, layout=ipw.Layout(width='220px'))
        self.upper = ipw.FloatText(description='Maximum (eV)', step=.01, style=style, layout=ipw.Layout(width='220px'))
        self.width = ipw.BoundedFloatText(value=.15, min=.01, max=5, step=.01, description='FWHM (eV)',
                                         style=style, layout=ipw.Layout(width='205px'))
        self.reset = ipw.Button(description='HOMO − 1 to LUMO + 1 eV', icon='undo', layout=ipw.Layout(width='auto'))
        self.reset.on_click(self._reset)
        self.normal = ipw.Text(value='0 0 1', description='Plane normal', style=style)
        self.plane_note = ipw.HTML()
        self.plot = InteractiveSvg(on_action=self._picked, layout=ipw.Layout(width='100%'))
        self.levels = ipw.SelectMultiple(description='Orbital candidates', style=style,
                                         layout=ipw.Layout(width='98%', height='140px'))
        self.table, self.detail, self.download = ipw.HTML(), ipw.HTML(), ipw.HTML()
        self.select = ipw.Button(description='Inspect selected orbital shapes', icon='cube',
                                 disabled=on_select is None, layout=ipw.Layout(width='auto'))
        self.select.on_click(self._send_selection)
        self.energy_controls = ipw.HBox([self.lower, self.upper, self.width, self.reset],
                                        layout=ipw.Layout(flex_flow='row wrap'))
        self.content = ipw.VBox([ipw.HBox([self.element, self.mode], layout=ipw.Layout(flex_flow='row wrap')),
            self.geometry_box, self.atoms, self.energy_controls, self.normal, self.plane_note, self.plot, self.detail,
            self.levels, self.select, self.table, self.download], layout=ipw.Layout(display='none'))
        super().__init__([ipw.HTML('<h4>PDOS & orbital character</h4><p>Choose atoms or a fragment, inspect their '
            'orbital contributions, and click a level to identify its shape. Character is a basis-dependent '
            'Löwdin partition; it assists active-space selection without choosing the CAS for you.</p>'),
            ipw.HBox([self.kind, self.compute], layout=ipw.Layout(flex_flow='row wrap')), setup,
            self.status, self.error, self.note, self.content], layout=ipw.Layout(width='100%', min_width='0'))
        self.kind.observe(self._load, names='value')
        self.element.observe(self._element_changed, names='value')
        self.atoms.observe(self._atoms_changed, names='value')
        self.levels.observe(self._detail, names='value')
        for control in (self.atoms, self.mode, self.lower, self.upper, self.width, self.normal):
            control.observe(self._redraw, names='value')
        self._load()

    def select_kind(self, kind):
        if kind in self.kind.options:
            self.kind.value = kind

    def set_active(self, active):
        if self.structure_viewer:
            self.structure_viewer.set_active(active)

    def _load(self, _=None):
        self.record = service.latest(self.source_uuid, self.kind.value)
        self.content.layout.display = '' if self.record else 'none'
        self.note.value = ''
        self.compute.description = 'Refresh saved PDOS' if self.record else 'Compute / retry orbital character'
        if not self.record:
            self.status.value = ('<p>Compute the compact orbital weights once from the saved wavefunction. '
                'This submits a CalcJob and does not rerun SCF or change the orbitals.</p>')
            issue = self.automatic_status.get('sets', {}).get(self.kind.value, {})
            if issue.get('message') or self.automatic_status.get('message'):
                self.status.value += ('<p class="orca-notice">Automatic PDOS: ' +
                    html.escape(issue.get('message') or self.automatic_status['message']) +
                    ' Retry this analysis after resolving the issue; the SCF need not be repeated.</p>')
            return
        self._updating = True
        try:
            m = self.record['metadata']
            self.atoms.options = [(f"{i + 1}: {a['ElementLabel']}", i) for i, a in enumerate(m['atoms'])]
            elements = list(dict.fromkeys(a['ElementLabel'] for a in m['atoms']))
            self.element.options = [('All atoms', 'all')] + [(a, a) for a in elements] + [('Custom atoms', 'custom')]
            self.element.value = 'C' if 'C' in elements else 'all'
            self.atoms.value = tuple(i for i, a in enumerate(m['atoms'])
                                     if self.element.value == 'all' or a['ElementLabel'] == self.element.value)
            from .geometry_viewer import MolecularStructureViewer, metadata_atoms
            if self.structure_viewer is None:
                self.structure_viewer = MolecularStructureViewer(metadata_atoms(m))
                self.structure_viewer.observe(self._viewer_atoms_changed, names='selection')
                self.geometry_box.children = [ipw.HTML('<p>Select atoms in 3D or type ranges such as <b>1 3..5</b>, '
                    'then apply the selection. Atom numbers start at <b>1</b>; this selection updates the PDOS. '
                    'The same viewer measures distances, angles and dihedrals.</p>'), self.structure_viewer]
            self.structure_viewer.input_selection = list(self.atoms.value)
            normal, notice = molecular_normal([a['Coords'] for a in m['atoms']])
            self.normal.value = ' '.join(f'{v:.4f}' for v in normal)
            self.plane_note.value = ('<p>'+html.escape(notice)+' The π-like view is perpendicular '
                'p character only; metal d contributions are shown separately.</p>')
            self._reset()
            natural = m['energy_meaning'] == 'none'
            self.lower.description = 'First orbital' if natural else 'Minimum (eV)'
            self.upper.description = 'Last orbital' if natural else 'Maximum (eV)'
            self.lower.step = self.upper.step = 1 if natural else .01
            self.width.layout.display = 'none' if natural else ''
            self.reset.description = 'Fractional occupation range' if natural else 'HOMO − 1 to LUMO + 1 eV'
            text = (f'{self.kind.value} occupations and character: these are not KS-energy levels.' if natural else
                    'QRO energies are reference labels, not canonical KS eigenvalues.' if self.kind.value == 'QRO' else
                    'SCF orbital DOS; virtual and occupied orbitals both contribute.')
            self.note.value = ('<p>'+text+' Gaussian broadening is a display choice. DOS counts orbitals '
                'per displayed channel, without occupation weighting. <b>ORCA orbital indices start at 0.</b></p>')
            self.status.value = ('<p>Saved character · <code>'+self.record['uuid']+'</code> · CᵀSC error ≤ '
                f"{max(m['orthonormality_errors']):.1e}. Compact data are available without remote access.</p>")
        finally:
            self._updating = False
        self._redraw()

    def _element_changed(self, _=None):
        if not self.record or self._updating or self._syncing_atoms or self.element.value == 'custom':
            return
        self.atoms.value = tuple(i for i, a in enumerate(self.record['metadata']['atoms'])
                                 if self.element.value == 'all' or a['ElementLabel'] == self.element.value)

    def _atoms_changed(self, _=None):
        if self.structure_viewer and not self._updating and not self._syncing_atoms:
            self.structure_viewer.input_selection = list(self.atoms.value)

    def _viewer_atoms_changed(self, event):
        if self._updating or self._syncing_atoms or self._disposed:
            return
        self._syncing_atoms = True
        try:
            self.atoms.value = tuple(event['new'])
            selected = set(event['new'])
            elements = self.record['metadata']['atoms']
            choice = 'all' if selected == set(range(len(elements))) else 'custom'
            for label, key in self.element.options:
                if key not in ('all', 'custom') and selected == {i for i, a in enumerate(elements) if a['ElementLabel'] == key}:
                    choice = key
                    break
            self.element.value = choice
        finally:
            self._syncing_atoms = False

    def _reset(self, _=None):
        if not self.record:
            return
        a = self.record['arrays']
        if 'energies_ev' not in a:
            fractional = np.flatnonzero((a['occupations'] > .02) & (a['occupations'] < 1.98))
            if not len(fractional):
                fractional = [max(0, int(self.record['metadata']['n_electrons']) // 2 - 1)]
            self.lower.value = max(0, int(min(fractional)) - 3)
            self.upper.value = min(len(a['indices']) - 1, int(max(fractional)) + 3)
            return
        e, o = a['energies_ev'], a['occupations']
        homo = max(e[o > 1e-6], default=float(e.min()))
        lumo = min(e[o < 1e-6], default=float(e.max()))
        self.lower.value, self.upper.value = round(float(homo - 1), 2), round(float(max(lumo, homo) + 1), 2)

    def _redraw(self, _=None):
        if self._updating or not self.record:
            return
        try:
            for control in (self.lower, self.upper):
                digits = 0 if self.record['metadata']['energy_meaning'] == 'none' else 2
                if np.isfinite(control.value) and control.value != round(control.value, digits):
                    control.value = round(control.value, digits)
                    return
            self._draw()
            self.error.value = ''
        except (ValueError, IndexError) as exc:
            self.plot.value = ''
            self._visible = []
            self.levels.options = []
            self.table.value = self.detail.value = self.download.value = ''
            self.select.disabled = True
            self.error.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _draw(self):
        a, m = self.record['arrays'], self.record['metadata']
        atoms = list(self.atoms.value)
        if not atoms:
            raise ValueError('Select at least one atom')
        normal = [float(x) for x in self.normal.value.replace(',', ' ').split()]
        perp = p_perpendicular(a, atoms, normal)
        selected = a['weights'][:, atoms].sum(axis=1)
        natural = 'energies_ev' not in a
        lo, hi = self.lower.value, self.upper.value
        if not np.isfinite([lo, hi]).all() or hi <= lo:
            raise ValueError('Enter a finite maximum greater than the minimum')
        energies = np.arange(len(a['indices'])) if natural else a['energies_ev']
        self._visible = [i for i, e in enumerate(energies) if lo <= e <= hi]
        count = min(6000, max(600, int((hi - lo) / self.width.value * 10)))
        grid = np.linspace(lo, hi, count)
        curves = []
        palette = ['#2563b7', '#c83e4d']
        if not natural:
            for spin, channel in enumerate(m['channels']):
                mask = a['spin'] == spin
                total_color = palette[spin] if len(m['channels']) > 1 else '#a6afb9'
                curves.append(('Total · '+channel, total_color, '5 4', gaussian_dos(energies[mask], np.ones(mask.sum()), grid, self.width.value)))
                if self.mode.value == 'angular':
                    patterns = ['1 3', '', '8 3 1 3', '10 4', '8 3 1 3 1 3', '12 3 3 3', '12 3 3 3 3 3']
                    for angular, dash in zip(m['angular'], patterns):
                        if selected[:, m['angular'].index(angular)].max() < 1e-12:
                            continue
                        curves.append((angular+' · '+channel, palette[spin], dash,
                            gaussian_dos(energies[mask], selected[mask, m['angular'].index(angular)], grid, self.width.value)))
                else:
                    weight = perp if self.mode.value == 'pi' else selected.sum(axis=1)
                    label = 'Perpendicular p' if self.mode.value == 'pi' else 'Selected atoms'
                    curves.append((label+' · '+channel, palette[spin], '', gaussian_dos(energies[mask], weight[mask], grid, self.width.value)))
        ymax = max((float(c[3].max()) for c in curves), default=2.) * 1.12 or 1.
        xx = lambda e: 70 + (e - lo) / (hi - lo) * 780
        yy = lambda y: 250 - y / ymax * 205
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 900 370" role="img" aria-label="Projected orbital DOS and selectable levels">',
               '<rect width="900" height="370" fill="#fafcfd" rx="6"/>']
        ticks = [0, .5, 1, 1.5, 2] if natural else [ymax * j / 4 for j in range(5)]
        for val in ticks:
            svg.append(f'<path d="M70 {yy(val):.2f}H850" stroke="#e4e9ef"/><text x="60" y="{yy(val)+4:.2f}" text-anchor="end" font-size="12">{val:.1f}</text>')
        if natural:
            points = ' '.join(f'{xx(i):.2f},{yy(float(a["occupations"][i])):.2f}' for i in self._visible)
            svg.append(f'<polyline points="{points}" fill="none" stroke="#2563b7" stroke-width="2"/>')
            weight = perp if self.mode.value == 'pi' else selected.sum(axis=1)
            for i in self._visible:
                svg.append(f'<circle data-ids="[{i}]" role="button" tabindex="0" cx="{xx(i):.2f}" cy="{yy(float(a["occupations"][i])):.2f}" '
                    f'r="{3 + 4 * weight[i]:.2f}" fill="#2563b7" opacity="{.2 + .8 * weight[i]:.3f}" style="cursor:pointer">'
                    f'<title>UNO {int(a["indices"][i])}: occupation {a["occupations"][i]:.4f}, selected projection {weight[i]:.1%}</title></circle>')
        for label, color, dash, values in curves:
            points = ' '.join(f'{xx(e):.2f},{yy(v):.2f}' for e, v in zip(grid, values))
            svg.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}"><title>{html.escape(label)}</title></polyline>')
        legend = []
        for label, color, dash, _ in curves:
            # The SVG bridge makes all SVGs fluid; bound each sample with a fixed-size wrapper.
            legend.append(f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px">'
                '<span style="width:44px;height:12px;flex:0 0 44px">'
                f'<svg xmlns="http://www.w3.org/2000/svg" width="44" height="12" viewBox="0 0 44 12" aria-hidden="true">'
                f'<line x1="1" y1="6" x2="43" y2="6" stroke="{color}" stroke-width="2" '
                f'stroke-dasharray="{dash}"/></svg></span>{html.escape(label)}</span>')
        xticks = np.unique(np.linspace(lo, hi, min(7, int(hi-lo) + 1)).round()) if natural else np.linspace(lo, hi, 6)
        for e in xticks:
            text = str(int(e)) if natural else f'{e:.2f}'
            svg.append(f'<text x="{xx(e):.2f}" y="275" text-anchor="middle" font-size="12">{text}</text>')
        label = 'Natural orbital index' if natural else 'Orbital energy (eV)'
        svg.append(f'<text x="450" y="300" text-anchor="middle" font-size="13">{label}</text>')
        ylabel = 'Occupation' if natural else 'Orbitals / eV'
        svg.append(f'<text x="18" y="155" transform="rotate(-90 18 155)" text-anchor="middle" font-size="12">{ylabel}</text>')
        for i in self._visible:
            y = 323 + 16 * int(a['spin'][i])
            detail = f"{m['channels'][int(a['spin'][i])]} MO {a['indices'][i]} · occupation {a['occupations'][i]:.4f}"
            svg.append(f'<g data-ids="[{i}]" role="button" tabindex="0" aria-label="{html.escape(detail)}" style="cursor:pointer"><title>{html.escape(detail)}</title>'
                f'<line x1="{xx(energies[i]):.2f}" x2="{xx(energies[i]):.2f}" y1="{y}" y2="{y+11}" '
                f'stroke="{palette[int(a["spin"][i])]}" stroke-width="3"/>'
                f'<rect x="{xx(energies[i])-4:.2f}" y="{y-2}" width="8" height="16" fill="transparent"/></g>')
        svg.append('<text x="70" y="363" font-size="11" fill="#667085">Click an orbital mark to inspect its character; choose multiple candidates in the list below.</text></svg>')
        key = ('<p>Colour identifies spin; line pattern identifies orbital character.</p>'
               if self.mode.value == 'angular' and not natural else '')
        self.plot.value = key+'<div style="line-height:1.7">'+''.join(legend)+'</div>'+''.join(svg)
        self._selected_weights, self._perp = selected, perp
        previous = set(self.levels.value)
        self.levels.options = [(f"{m['channels'][int(a['spin'][i])]} MO {int(a['indices'][i])} · "
            + (f"{energies[i]:.2f} eV · " if not natural else '')
            + f"occ {a['occupations'][i]:.3f} · selected atoms {selected[i].sum():.1%} · p⊥ {perp[i]:.1%}", i)
            for i in self._visible]
        self.levels.value = tuple(i for i in self._visible if i in previous)
        if not self.levels.value and self._visible:
            self.levels.value = (min(self._visible, key=lambda i: abs(energies[i] - (lo + hi) / 2)),)
        self._detail()
        self.select.disabled = self.on_select is None or not bool(self.levels.value)
        view = {'calcjob_uuid': self.record['uuid'], 'metadata_uuid': self.record['metadata_uuid'],
                'arrays_uuid': self.record['arrays_uuid'], 'atoms_zero_based': atoms, 'normal': normal,
                'fwhm_ev': None if natural else self.width.value, 'display_range': [lo, hi],
                'energy_meaning': m['energy_meaning'], 'occupation_weighted_DOS': False}
        encoded = base64.b64encode(json.dumps(view, indent=2).encode()).decode()
        csv_stream = io.StringIO()
        writer = csv.writer(csv_stream)
        writer.writerow(['calcjob_uuid', 'spin', 'orbital_index', 'energy_ev', 'occupation', 'selected_atom_weight', *m['angular'], 'perpendicular_p'])
        for i in range(len(a['indices'])):
            writer.writerow([self.record['uuid'], m['channels'][int(a['spin'][i])], int(a['indices'][i]),
                '' if natural else float(energies[i]), float(a['occupations'][i]), float(selected[i].sum()),
                *[float(selected[i, m['angular'].index(l)]) for l in m['angular']], float(perp[i])])
        csv_data = base64.b64encode(csv_stream.getvalue().encode()).decode()
        self.download.value = f'<p><a download="pdos-view.json" href="data:application/json;base64,{encoded}">Download view and provenance</a> · '
        self.download.value += f'<a download="orbital-character.csv" href="data:text/csv;base64,{csv_data}">Download orbital character CSV</a></p>'

    def _picked(self, event):
        if event.get('action') == 'select' and event.get('ids') and event['ids'][0] in self._visible:
            self.levels.value = (event['ids'][0],)

    def _detail(self, _=None):
        if not self.record or not self.levels.value:
            self.detail.value, self.table.value = '', ''
            return
        i = self.levels.value[-1]
        a, m = self.record['arrays'], self.record['metadata']
        if not hasattr(self, '_selected_weights'):
            return
        weights = a['weights'][i]
        top = sorted(enumerate(weights.sum(axis=1)), key=lambda item: item[1], reverse=True)[:8]
        rows = ''.join(f"<tr><td>{atom + 1} · {html.escape(m['atoms'][atom]['ElementLabel'])}</td><td>{value:.1%}</td>"
                       + ''.join(f'<td>{weights[atom, m["angular"].index(l)]:.1%}</td>' for l in ('s', 'p', 'd')) + '</tr>' for atom, value in top)
        self.detail.value = f"<p><b>{html.escape(m['channels'][int(a['spin'][i])])} MO {int(a['indices'][i])}</b> · "
        self.detail.value += f"occupation {a['occupations'][i]:.4f} · selected atoms {self._selected_weights[i].sum():.1%} · perpendicular p {self._perp[i]:.1%}.</p>"
        self.table.value = '<details open><summary>Largest atomic contributions to this orbital</summary><table style="width:95%;text-align:left"><tr><th>Atom</th><th>Total</th><th>s</th><th>p</th><th>d</th></tr>'+rows+'</table></details>'

    def _send_selection(self, _=None):
        if self.on_select and self.record:
            a = self.record['arrays']
            try:
                self.on_select([(int(a['spin'][i]), int(a['indices'][i])) for i in self.levels.value])
            except Exception as exc:
                self.error.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _compute(self, _=None):
        try:
            if not self.force.value and service.latest(self.source_uuid, self.kind.value):
                self._load()
                return
            uuid = service.submit(self.source_uuid, self.kind.value, self.export.value, self.worker.value,
                                  self.force.value, self.memory.value, wallclock_seconds=self.wallclock.value * 60)
            self.compute.disabled = True
            self.status.value = '<p>Orbital-character CalcJob submitted: <code>'+uuid+'</code></p>'
            self._task = asyncio.get_running_loop().create_task(self._poll(uuid))
        except Exception as exc:
            self.error.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    async def _poll(self, uuid):
        from .casci_services import progress
        try:
            while not self._disposed:
                data = progress(uuid)
                if data['finished']:
                    if data['success']:
                        self._load()
                    else:
                        self.error.value = '<p style="color:#a02020">'+html.escape(data['message'])+'</p>'
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        finally:
            self.compute.disabled = False

    def close(self):
        if self._disposed:
            return
        self._disposed = True
        self.atoms.unobserve(self._atoms_changed, names='value')
        if self.structure_viewer:
            self.structure_viewer.unobserve(self._viewer_atoms_changed, names='selection')
        if self._task:
            self._task.cancel()
        from .widget_lifecycle import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()
