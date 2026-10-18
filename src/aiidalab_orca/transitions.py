"""Exact state endpoints and a linked, selectable Dyson transition diagram."""
import html
import json
import math

import ipywidgets as ipw

from aiida_empa_orca.dyson_data import HARTREE_EV, weighted_table
from aiida_empa_orca.levels import visible_groups
from .interactive_svg import InteractiveSvg


def intensity_color(weight, maximum):
    """Linear black-to-blue scale: zero is an opaque, visible black segment."""
    fraction = min(1., max(0., weight/maximum)) if maximum > 0 else 0.
    return '#%02x%02x%02x' % tuple(round(fraction*c) for c in (0, 135, 190))


def action_attributes(ids, title):
    return ('data-ids="'+html.escape(json.dumps(ids), quote=True)+'" tabindex="0" role="button" '
            'aria-label="'+html.escape(title, quote=True)+'" style="cursor:pointer"')


def state_key(uuid, root):
    return str(uuid)+':'+str(root)


def state_endpoints(states, table):
    """Resolve stored states by UUID/root and check their existing signed poles."""
    lookup = {state_key(r['state_uuid'], r['root']): r for r in states}
    initial_key = state_key(table['initial_state_uuid'], table['initial_state']['root'])
    if initial_key not in lookup:
        raise ValueError('The initial Dyson state is absent from the state diagram')
    initial = lookup[initial_key]
    endpoints = {}
    for row in table['transitions']:
        key = state_key(row['final_state_uuid'], row['final_root'])
        if key not in lookup:
            raise ValueError('A final Dyson state is absent from the state diagram')
        final = lookup[key]
        gap = (final['energy_hartree']-initial['energy_hartree'])*HARTREE_EV
        expected = -gap if row['side'] == 'removal' else gap
        if abs(expected-row['energy_ev']) > 1e-6:
            raise ValueError('State energies and stored Dyson transition energies do not agree')
        endpoints[row['id']] = key
    return initial_key, endpoints


def peak_groups(rows, lower, upper, pixels=850, hit_pixels=10):
    """Group unresolved click targets, preserving each transition's exact pole."""
    groups = []
    for row in sorted((r for r in rows if lower <= r['pole_ev'] <= upper), key=lambda r:r['pole_ev']):
        if not groups or (row['pole_ev']-groups[-1][-1]['pole_ev'])*pixels/(upper-lower) > hit_pixels:
            groups.append([])
        groups[-1].append(row)
    return groups


class TransitionDiagram(ipw.VBox):
    def __init__(self, states, table, on_action):
        self.states, self.table = states, table
        self.initial_key, self.endpoints = state_endpoints(states, table)
        self.selection, self.convention, self.side = [], 'unpolarized', 'both'
        self.spectrum_range, self.shift = None, 0.
        self.mode = ipw.ToggleButtons(options=[('Selected connections', 'selected'), ('All in spectrum', 'all'), ('No connections', 'none')],
                                      value='selected', layout=ipw.Layout(width='100%'))
        self.minimum = ipw.FloatText(value=0., description='Min. weight (All)', style={'description_width':'120px'}, layout=ipw.Layout(width='240px'))
        initial = table['initial_state']['energy_hartree']
        values = [(r['energy_hartree']-initial)*HARTREE_EV for r in states]
        self.lower = ipw.FloatText(value=math.floor((min(values)-.25)*100)/100, description='State min. (eV)',
                                  style={'description_width':'100px'}, layout=ipw.Layout(width='210px'))
        self.upper = ipw.FloatText(value=math.ceil((max(values)+.25)*100)/100, description='State max. (eV)',
                                  style={'description_width':'100px'}, layout=ipw.Layout(width='210px'))
        self.plot = InteractiveSvg(on_action=on_action)
        self.legend, self.message = ipw.HTML(), ipw.HTML()
        advanced = ipw.Accordion(children=[ipw.HBox([self.minimum,self.lower,self.upper],layout=ipw.Layout(flex_flow='row wrap'))],selected_index=None)
        advanced.set_title(0,'State range and connection filter')
        super().__init__([ipw.HTML('<b>Many-electron states and Dyson connections</b>'), self.mode,
            self.message, self.plot, self.legend,advanced])
        for control in (self.mode, self.minimum, self.lower, self.upper):
            control.observe(self._draw, names='value')
        self._draw()

    def update(self, selected, convention, side, lower, upper, shift):
        self.selection, self.convention, self.side = list(selected), convention, side
        self.spectrum_range, self.shift = (lower, upper), shift
        self._draw()

    def reveal(self, identifiers):
        """An explicit selection reveals its exact endpoints without moving them."""
        keys = {self.initial_key} | {self.endpoints[i] for i in identifiers if i in self.endpoints}
        if len(keys) <= 1:
            return
        initial = self.table['initial_state']['energy_hartree']
        values = [(r['energy_hartree']-initial)*HARTREE_EV for r in self.states if state_key(r['state_uuid'],r['root']) in keys]
        self.lower.value = min(self.lower.value,math.floor((min(values)-.25)*100)/100)
        self.upper.value = max(self.upper.value,math.ceil((max(values)+.25)*100)/100)

    def _draw(self, _=None):
        lo, hi = self.lower.value, self.upper.value
        if not all(math.isfinite(v) for v in (lo, hi, self.minimum.value)) or lo >= hi or self.minimum.value < 0:
            self.message.value = '<p>Choose an increasing state-energy range and a nonnegative minimum weight.</p>'
            return
        self.message.value = ''
        table = weighted_table(self.table, self.convention)
        maximum = max((r['strength'] for r in table['transitions']), default=0.)
        sectors = sorted({(r['charge'], r['multiplicity']) for r in self.states}, key=lambda s:(-s[0], s[1]))
        width, height, left, right = 680, 425, 65, 665
        span = (right-left)/len(sectors)
        y = lambda energy: 45+(hi-energy)/(hi-lo)*270
        initial_energy = self.table['initial_state']['energy_hartree']
        initial_charge = self.table['initial_state']['charge']
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Linked many-electron state transitions">',
               f'<rect width="{width}" height="{height}" rx="10" fill="#f8fafc"/>']
        for tick in range(6):
            value = lo+(hi-lo)*tick/5
            yy = y(value)
            svg.append(f'<path d="M{left} {yy}H{right}" stroke="#e2e8f0"/><text x="{left-10}" y="{yy+4}" text-anchor="end" font-size="15" fill="#475569">{value:.2f}</text>')
        svg.append('<text x="18" y="190" transform="rotate(-90 18 190)" text-anchor="middle" font-size="13">Energy relative to initial state (eV)</text>')
        positions = {}
        for index, sector in enumerate(sectors):
            x = left+(index+.5)*span
            rows = [dict(r, energy_ev=(r['energy_hartree']-initial_energy)*HARTREE_EV) for r in self.states
                    if (r['charge'], r['multiplicity']) == sector]
            for group in visible_groups(rows, lo, hi, height=270, linewidth=5):
                slot = min(58., span*.85/len(group))
                for j, row in enumerate(group):
                    xx = x+(j-(len(group)-1)/2)*slot
                    key = state_key(row['state_uuid'], row['root'])
                    row['_show_label'] = slot >= 20
                    positions[key] = (xx, y(row['energy_ev']), max(3.,min(46., slot-5)), row)
            svg.append(f'<text x="{x}" y="360" text-anchor="middle" font-size="14">M={sector[1]}</text>')
        # One heading per charge group makes charge/electron-count direction explicit.
        for charge in sorted({q for q, _ in sectors}, reverse=True):
            indexes = [i for i, (q, _) in enumerate(sectors) if q == charge]
            x = left+(sum(indexes)/len(indexes)+.5)*span
            delta = charge-initial_charge
            label = {1:'Removal · N−1', 0:'Initial sector · N', -1:'Addition · N+1'}.get(delta, 'Other charge')
            color = {1:'#2563b7', 0:'#334155', -1:'#ed642d'}.get(delta, '#64748b')
            svg.append(f'<text x="{x}" y="22" text-anchor="middle" font-size="14" font-weight="600" fill="{color}">{label}</text>'
                       f'<text x="{x}" y="387" text-anchor="middle" font-size="15">Charge {charge:+d}</text>')
        if lo <= 0 <= hi:
            svg.append(f'<path d="M{left} {y(0)}H{right}" stroke="#475569" stroke-dasharray="4 4"/>')
        eligible = []
        for row in table['transitions']:
            pole = row['energy_ev']+self.shift
            if self.side not in ('both', row['side']):
                continue
            if self.spectrum_range and not self.spectrum_range[0] <= pole <= self.spectrum_range[1]:
                continue
            selected = row['id'] in self.selection
            if self.mode.value == 'none' or (self.mode.value == 'selected' and not selected):
                continue
            if self.mode.value == 'all' and row['strength'] < self.minimum.value and not selected:
                continue
            if self.initial_key in positions and self.endpoints[row['id']] in positions:
                eligible.append(row)
        # Selection is drawn last; every connector retains its intensity colour.
        for row in sorted(eligible, key=lambda r:r['id'] in self.selection):
            a, b = positions[self.initial_key], positions[self.endpoints[row['id']]]
            selected = row['id'] in self.selection
            color = intensity_color(row['strength'], maximum)
            title = f"{row['id']}: {row['side']}, pole {row['energy_ev']+self.shift:.6f} eV; weight {row['strength']:.6g}; applied spin factor {row['spin_factor']:g}"
            attrs = action_attributes([row['id']], title)
            path = f'M{a[0]} {a[1]}L{b[0]} {b[1]}'
            svg.append(f'<g {attrs} data-transition-id="{html.escape(row["id"], quote=True)}"><title>{html.escape(title)}</title>')
            if selected:
                svg.append(f'<path d="{path}" stroke="#fbbf24" stroke-width="7" opacity=".65"/>')
            svg.append(f'<path d="{path}" stroke="{color}" stroke-width="2.5" fill="none"/>'
                       f'<path d="{path}" stroke="transparent" stroke-width="12" fill="none"/></g>')
        for key, (x, yy, length, row) in positions.items():
            ids = [r['id'] for r in table['transitions'] if self.endpoints[r['id']] == key]
            initial = key == self.initial_key
            selected = initial or any(i in self.selection for i in ids)
            title = f"q={row['charge']:+d}, multiplicity {row['multiplicity']}, root {row['root']}: {row['energy_ev']:.6f} eV relative to initial state"
            attrs = action_attributes(ids, title) if ids else ''
            color = '#0f172a' if selected else '#94a3b8'
            svg.append(f'<g {attrs} data-state-key="{html.escape(key, quote=True)}" data-energy="{row["energy_ev"]:.12g}"><title>{html.escape(title)}</title>'
                       f'<path d="M{x-length/2} {yy}h{length}" stroke="{color}" stroke-width="{4 if selected else 2}"/>')
            if selected or row['_show_label']:
                svg.append(f'<text x="{x}" y="{yy-9}" text-anchor="middle" font-size="14" fill="{color}">r{row["root"]}</text>')
            if selected:
                svg.append(f'<circle cx="{x}" cy="{yy}" r="5" fill="{ "#fbbf24" if initial else "#ffffff"}" stroke="#0f172a" stroke-width="2"/>')
            if initial:
                svg.append(f'<text x="{x}" y="{yy+20}" text-anchor="middle" font-size="12" font-weight="600">Initial · 0 eV</text>')
            if ids:
                svg.append(f'<rect x="{x-length/2-3}" y="{yy-5}" width="{length+6}" height="10" fill="transparent"/>')
            svg.append('</g>')
        svg.append('</svg>')
        self.plot.value = ''.join(svg)
        self.legend.value = ('<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12px">'
            '<span>Dyson weight</span><span>0 (black)</span><span style="width:140px;height:10px;background:linear-gradient(to right,#000000,#0087be)"></span>'
            f'<span>{maximum:.4g}</span><span>Gold outline: selected. Same scale for all transitions.</span></div>'
            '<p style="font-size:12px;color:#475569">M = multiplicity. Each bar stays at its exact energy; nearby roots occupy separate horizontal slots. Click a connector or final-state bar to select its transition.</p>')

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        for control in (self.mode, self.minimum, self.lower, self.upper):
            control.unobserve(self._draw, names='value')
        self.plot.close()
        super().close()
