"""A common total-energy scale for fixed-geometry many-electron states."""

import base64
import html
import json
import math

import ipywidgets as ipw

from aiida_empa_orca.casci import energy_diagram
from aiida_empa_orca.levels import visible_groups


def state_label(row):
    return f"q={row['charge']:+d}, multiplicity {row['multiplicity']}, root {row['root']}"


class StateEnergyLevels(ipw.VBox):
    def __init__(self, datasets):
        self.datasets = datasets  # Only plain data, never live ORM objects.
        diagram = energy_diagram(datasets)
        self.zero = ipw.Dropdown(options=[(state_label(r),r['id']) for r in diagram['states']],
                                value=diagram['reference_state'], description='Energy zero',
                                layout=ipw.Layout(width='95%'))
        self.lower = ipw.FloatText(description='Minimum (eV)', step=.01, style={'description_width':'105px'},layout=ipw.Layout(width='240px'))
        self.upper = ipw.FloatText(description='Maximum (eV)', step=.01, style={'description_width':'105px'},layout=ipw.Layout(width='240px'))
        self.reset = ipw.Button(description='Show all states', icon='arrows-v', layout=ipw.Layout(width='auto'))
        self.plot, self.table, self.message, self.download = (ipw.HTML() for _ in range(4))
        self.reset.on_click(self._reset)
        super().__init__([ipw.HTML('<h4>Many-electron state energies</h4><p>Fixed geometry · shared spatial orbitals. '
            'All charge and spin sectors use the selected common energy zero. These are total state energies, '
            'not orbital energies or signed addition/removal spectral peaks. Nearby states may share an averaged overview bar; '
            'hover or open the table for exact values. After computing Dyson transitions, switch to Dyson spectrum for the linked diagram and clickable spectrum.</p>'), self.zero,
            ipw.HBox([self.lower,self.upper,self.reset],layout=ipw.Layout(flex_flow='row wrap')),
            self.message,self.plot,self.table,self.download])
        self.zero.observe(self._reset,names='value')
        self.lower.observe(self._redraw,names='value')
        self.upper.observe(self._redraw,names='value')
        self._reset()

    def _reset(self, _=None):
        data = energy_diagram(self.datasets, self.zero.value)
        values = [r['relative_energy_ev'] for r in data['states']]
        self.lower.value = math.floor((min(values)-.25)*100)/100
        self.upper.value = math.ceil((max(values)+.25)*100)/100
        self._redraw()

    def _redraw(self, _=None):
        lo, hi = self.lower.value, self.upper.value
        if not all(math.isfinite(x) for x in (lo,hi)) or lo >= hi:
            self.message.value = '<p>Enter a finite maximum greater than the minimum.</p>'
            return
        self.message.value = ''
        data = energy_diagram(self.datasets,self.zero.value)
        sectors = sorted({(r['charge'],r['multiplicity']) for r in data['states']})
        width = max(680, 110+150*len(sectors))
        span = (width-110)/len(sectors)
        y = lambda energy: 30+(hi-energy)/(hi-lo)*320
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="440" viewBox="0 0 {width} 440" '
               'role="img" aria-label="Many-electron state energies">', f'<rect width="{width}" height="440" fill="#fafbfd"/>']
        for tick in range(6):
            energy = lo+(hi-lo)*tick/5
            yy = y(energy)
            svg.append(f'<path d="M75 {yy} H{width-15}" stroke="#dce2e8"/><text x="65" y="{yy+4}" text-anchor="end" font-size="12">{energy:.2f}</text>')
        svg.append('<text x="16" y="190" transform="rotate(-90 16 190)" font-size="13">E − selected state (eV)</text>')
        colors = ['#2563b7','#d7473f','#19855b','#8844aa','#aa6c00']
        multiplicities = sorted({m for _,m in sectors})
        for index,(charge,mult) in enumerate(sectors):
            x = 90+index*span
            color = colors[multiplicities.index(mult)%len(colors)]
            rows = [dict(r,energy_ev=r['relative_energy_ev']) for r in data['states'] if (r['charge'],r['multiplicity']) == (charge,mult)]
            for group in visible_groups(sorted(rows,key=lambda r:r['energy_ev']),lo,hi):
                yy = y(sum(r['energy_ev'] for r in group)/len(group))
                title = '; '.join(f"{state_label(r)}: {r['energy_ev']:.6f} eV" for r in group)
                label = f"r{group[0]['root']}" if len(group)==1 else f'{len(group)} states'
                svg.append(f'<g><title>{html.escape(title)}</title><path d="M{x} {yy} h{span*.58}" stroke="{color}" stroke-width="3"/>'
                           f'<text x="{x+span*.62}" y="{yy+4}" font-size="11">{label}</text></g>')
            svg.append(f'<text x="{x+span*.4}" y="385" text-anchor="middle" font-size="14">Charge {charge:+d}</text>'
                       f'<text x="{x+span*.4}" y="407" text-anchor="middle" fill="{color}" font-size="13">Multiplicity {mult}</text>')
        svg.append('</svg>')
        self.plot.value = ''.join(svg)
        rows = ''.join(f"<tr><td>{r['charge']:+d}</td><td>{r['multiplicity']}</td><td>{r['root']}</td>"
                       f"<td>{r['energy_hartree']:.10f}</td><td>{r['relative_energy_ev']:.6f}</td></tr>"
                       for r in sorted(data['states'],key=lambda r:(r['charge'],r['multiplicity'],r['root'])))
        self.table.value = '<details><summary>State energies and identifiers</summary><table><tr><th>Charge</th><th>Multiplicity</th><th>Root</th><th>Total energy (Hartree)</th><th>Relative energy (eV)</th></tr>'+rows+'</table></details>'
        payload = base64.b64encode(json.dumps({'diagram':data,'calculations':self.datasets},indent=2).encode()).decode()
        self.download.value = f'<a download="casci_states.json" href="data:application/json;base64,{payload}">Download state energies and provenance</a>'

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        if hasattr(self, 'zero'):
            self.zero.unobserve(self._reset, names='value')
            self.lower.unobserve(self._redraw, names='value')
            self.upper.unobserve(self._redraw, names='value')
            self.reset.on_click(self._reset, remove=True)
            from .app import close_widget_tree
            for child in self.children:
                close_widget_tree(child)
        super().close()
