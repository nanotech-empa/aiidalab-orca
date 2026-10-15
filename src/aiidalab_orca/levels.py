"""Interactive energy limits and a fixed-height, spin-resolved level diagram."""

import html
import math

import ipywidgets as ipw

from aiida_empa_orca.levels import visible_groups


class EnergyLevels(ipw.VBox):
    def __init__(self, levels):
        self.levels = levels
        lower, upper = levels['default_range_ev']
        self.lower = ipw.FloatText(value=lower, description='Minimum (eV)', layout=ipw.Layout(width='230px'))
        self.upper = ipw.FloatText(value=upper, description='Maximum (eV)', layout=ipw.Layout(width='230px'))
        reset = ipw.Button(description='HOMO − 1 / LUMO + 1', icon='undo', layout=ipw.Layout(width='auto'))
        reset.on_click(self.reset)
        self.plot = ipw.HTML()
        self.error = ipw.HTML()
        self.details = ipw.HTML()
        note = ('Restricted orbitals share one spatial level for both spins.' if not levels['spin_polarized'] else
                'Blue: α / spin up. Red: β / spin down. Solid: occupied; dashed: unoccupied.')
        if not levels['complete']:
            note += ' This older output contains only the printed subset of virtual orbitals.'
        super().__init__([ipw.HTML('<h4>Orbital energy levels</h4>'),
                          ipw.HBox([self.lower, self.upper, reset], layout=ipw.Layout(flex_flow='row wrap')),
                          ipw.HTML('<p>'+note+' Counts mark levels whose bars overlap at this scale.</p>'),
                          self.error, self.plot, self.details])
        self.lower.observe(self.redraw, names='value')
        self.upper.observe(self.redraw, names='value')
        self.redraw()

    def reset(self, _=None):
        self.lower.value, self.upper.value = self.levels['default_range_ev']
        self.redraw()

    def redraw(self, _=None):
        lo, hi = self.lower.value, self.upper.value
        if not all(math.isfinite(v) for v in (lo, hi)) or hi <= lo:
            self.error.value = '<p style="color:#a02020">Enter a finite maximum greater than the minimum.</p>'
            return
        self.error.value = ''
        y = lambda e: 25+(hi-e)/(hi-lo)*340
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="420" viewBox="0 0 640 420" preserveAspectRatio="none" role="img" aria-label="Orbital energy levels">',
               '<rect width="640" height="420" fill="#fafbfd"/>']
        for i in range(6):
            energy = lo+(hi-lo)*i/5
            yy = y(energy)
            svg.append(f'<path d="M80 {yy} H600" stroke="#dce2e8"/><text x="70" y="{yy+4}" text-anchor="end" font-size="12">{energy:.2f}</text>')
        svg.append('<text x="15" y="195" transform="rotate(-90 15 195)" font-size="13">Orbital energy (eV)</text>')
        rows = []
        for spin, channel in enumerate(self.levels['channels']):
            color = ('#2563b7', '#d7473f')[spin]
            x = 140+260*spin if self.levels['spin_polarized'] else 270
            label = ('α · spin up', 'β · spin down')[spin] if self.levels['spin_polarized'] else 'Restricted (α + β)'
            svg.append(f'<text x="{x+55}" y="400" text-anchor="middle" fill="{color}" font-size="15">{label}</text>')
            for group in visible_groups(channel, lo, hi):
                energy = sum(v['energy_ev'] for v in group)/len(group)
                yy = y(energy)
                occupied = any(v['occupation'] > 1e-6 for v in group)
                details = '; '.join(f"MO {v['index']}: {v['energy_ev']:.4f} eV, occ {v['occupation']:g}" for v in group)
                dash = '' if occupied else ' stroke-dasharray="7 4"'
                svg.append(f'<g><title>{html.escape(details)}</title><line x1="{x}" x2="{x+110}" y1="{yy}" y2="{yy}" stroke="{color}" stroke-width="3"{dash}/>')
                if len(group)>1:
                    svg.append(f'<text x="{x+120}" y="{yy+4}" fill="{color}" font-size="13">{len(group)}</text>')
                svg.append('</g>')
                rows.extend(f"<tr><td>{label}</td><td>{v['index']}</td><td>{v['energy_ev']:.4f}</td><td>{v['occupation']:g}</td></tr>" for v in group)
        for name in ('homo', 'lumo'):
            energy = self.levels[name+'_ev']
            if lo <= energy <= hi:
                svg.append(f'<text x="610" y="{y(energy)-6}" text-anchor="end" fill="#546170" font-size="11">{name.upper()}</text>')
        svg.append('</svg>')
        self.plot.value = ''.join(svg)
        self.details.value = ('<details><summary>Visible orbital indices and occupations</summary><p>ORCA orbital numbers start at 0.</p>'
                              '<table><tr><th>Spin</th><th>MO</th><th>Energy (eV)</th><th>Occupation</th></tr>' + ''.join(rows)+'</table></details>')
