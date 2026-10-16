"""Interactive spectra from durable transition tables; no electronic jobs needed."""
import base64
import csv
import html
import io
import json

import ipywidgets as ipw
import numpy as np

from aiida_empa_orca.dyson_data import spectrum,weighted_table


class SpectralViewer(ipw.VBox):
    def __init__(self,table,on_change=None):
        self.table = table
        self.on_change = on_change
        style = {'description_width':'145px'}
        self.spin = ipw.Dropdown(options=[('Unpolarized · spin summed','unpolarized'),
            ('Highest M_S component · Andrés tool','highest_ms_component')],description='Spin convention',style=style,layout=ipw.Layout(width='95%'))
        self.side = ipw.Dropdown(layout=ipw.Layout(width='350px'),options=[('Addition and removal','both'),('Removal','removal'),('Addition','addition')],description='Show',style=style)
        self.eta = ipw.BoundedFloatText(value=.04,min=.0001,max=10,step=.01,description='HWHM η (eV)',style=style)
        self.shift = ipw.FloatText(value=0.,step=.01,description='Energy offset (eV)',style=style)
        self.lower = ipw.FloatText(step=.01,description='Minimum (eV)',style=style)
        self.upper = ipw.FloatText(step=.01,description='Maximum (eV)',style=style)
        reset = ipw.Button(description='Show all transitions',icon='arrows-v',layout=ipw.Layout(width='auto'))
        reset.on_click(self._reset)
        self.plot,self.info,self.download,self.transition_table = ipw.HTML(),ipw.HTML(),ipw.HTML(),ipw.HTML()
        self.energy = ipw.FloatText(value=round(table['transitions'][0]['energy_ev'],2),step=.01,description='Selected energy (eV)',style=style)
        self.mode = ipw.ToggleButtons(options=[('At energy','energy'),('Energy window','window')])
        self.window_lower = ipw.FloatText(value=round(self.energy.value-.05,2),step=.01,description='Window start (eV)',style=style)
        self.window_upper = ipw.FloatText(value=round(self.energy.value+.05,2),step=.01,description='Window end (eV)',style=style)
        super().__init__([ipw.HBox([self.spin,self.side],layout=ipw.Layout(flex_flow='row wrap')),
            ipw.HBox([self.eta,self.shift],layout=ipw.Layout(flex_flow='row wrap')),
            ipw.HBox([self.lower,self.upper,reset],layout=ipw.Layout(flex_flow='row wrap')),
            self.info,self.plot,self.download,self.transition_table,
            ipw.HTML('<p><b>Spectral intensity blend</b> · select an energy or integrate over a window. Uses the selected transitions below.</p>'),
            self.mode,self.energy,ipw.HBox([self.window_lower,self.window_upper],layout=ipw.Layout(flex_flow='row wrap'))])
        for w in (self.spin,self.side,self.eta,self.shift,self.lower,self.upper,self.mode,self.energy,self.window_lower,self.window_upper):
            w.observe(self._update,names='value')
        self._reset()

    def _reset(self,_=None):
        energies = [r['energy_ev']+self.shift.value for r in self.table['transitions']]
        self.lower.value,self.upper.value = round(min(energies)-.5,2),round(max(energies)+.5,2)
        self._update()

    def blend(self):
        return {'mode':self.mode.value,'energy_ev':self.energy.value,'lower_ev':self.window_lower.value,
                'upper_ev':self.window_upper.value,'eta_ev':self.eta.value,
                'spin_convention':self.spin.value,'shift_ev':self.shift.value}

    def _update(self,_=None):
        for control in (self.lower,self.upper,self.shift,self.energy,self.window_lower,self.window_upper):
            if np.isfinite(control.value) and control.value != round(control.value,2):
                control.value = round(control.value,2)
                return
        self.energy.layout.display = '' if self.mode.value == 'energy' else 'none'
        self.window_lower.layout.display = self.window_upper.layout.display = '' if self.mode.value == 'window' else 'none'
        if self.upper.value <= self.lower.value or not np.isfinite([self.lower.value,self.upper.value,self.eta.value,self.shift.value]).all():
            self.info.value = '<p style="color:#a02020">Choose a finite, increasing energy range.</p>'
            return
        table = weighted_table(self.table,self.spin.value)
        omega = np.linspace(self.lower.value,self.upper.value,1600)
        # Include each visible peak and its neighbourhood when eta is narrow.
        focused = np.concatenate([r['energy_ev']+self.shift.value+self.eta.value*np.linspace(-10,10,81)
                                  for r in table['transitions']])
        focused = focused[(focused >= self.lower.value)&(focused <= self.upper.value)]
        omega = np.unique(np.concatenate([omega,focused]))
        curves = spectrum(table,omega,self.eta.value,self.side.value,self.shift.value)
        ymax = max(float(curves['total'].max()),1e-12)*1.1
        x = lambda value:65+850*(value-self.lower.value)/(self.upper.value-self.lower.value)
        y = lambda value:295-245*value/ymax
        parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="350" viewBox="0 0 960 350" role="img" aria-label="Dyson spectral function">',
                 '<path d="M65 35V295H920" fill="none" stroke="#666"/>']
        for tick in np.linspace(self.lower.value,self.upper.value,7):
            parts.append(f'<text x="{x(tick):.1f}" y="318" text-anchor="middle" font-size="13">{tick:.2f}</text>')
        for side,color in (('removal','#2c7be5'),('addition','#f06431')):
            points = ' '.join(f'{x(w):.2f},{y(v):.2f}' for w,v in zip(omega,curves[side]))
            parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
            for row in table['transitions']:
                pole = row['energy_ev']+self.shift.value
                if row['side'] == side and self.side.value in ('both',side) and self.lower.value <= pole <= self.upper.value:
                    strength = row['strength']
                    parts.append(f'<line x1="{x(pole):.2f}" x2="{x(pole):.2f}" y1="295" y2="{295-40*min(strength,2):.2f}" stroke="{color}" opacity=".6"><title>{html.escape(row["id"])} · {pole:.3f} eV · weight {strength:.5f}</title></line>')
        if self.lower.value <= self.energy.value <= self.upper.value:
            parts.append(f'<path d="M{x(self.energy.value):.2f} 35V295" stroke="#555" stroke-dasharray="4 4"/>')
        parts.append('<text x="470" y="344" text-anchor="middle">Transition energy + offset (eV)</text><text transform="translate(18 190) rotate(-90)" text-anchor="middle">Spectral intensity</text></svg>')
        self.plot.value = ''.join(parts)
        self.info.value = ('<p><span style="color:#2c7be5">● Removal</span> · <span style="color:#f06431">● Addition</span>. '
            'η is half-width at half-maximum; FWHM = 2η. Curves use Andrés’s convention: integrated peak area = π × weight. '
            'Only the computed final states contribute.</p>')
        rows = []
        for raw,row in zip(self.table['transitions'],table['transitions']):
            rows.append(f'<tr><td>{html.escape(row["id"])}</td><td>{row["side"]}</td><td>{row["final_charge"]:+d}</td><td>{row["final_multiplicity"]}</td><td>{row["final_root"]}</td><td>{row["energy_ev"]+self.shift.value:.3f}</td><td>{raw["strength"]:.5f}</td><td>{row["strength"]:.5f}</td><td>{row["final_ci_norm"]:.8f}</td></tr>')
        self.transition_table.value = '<details><summary>Transition energies, strengths and CI norms</summary><table><tr><th>ID</th><th>Branch</th><th>Charge</th><th>Mult.</th><th>Root</th><th>Energy (eV)</th><th>Component strength</th><th>Selected weight</th><th>Retained CI norm</th></tr>'+''.join(rows)+'</table></details>'
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['energy_ev','removal','addition','total'])
        writer.writerows(zip(omega,curves['removal'],curves['addition'],curves['total']))
        metadata = dict(transitions=table,eta_hwhm_ev=self.eta.value,shift_ev=self.shift.value,
                        lower_ev=self.lower.value,upper_ev=self.upper.value,side=self.side.value,
                        lorentzian_normalization='eta/((omega-pole)^2+eta^2); area=pi*strength')
        csv_data = base64.b64encode(buffer.getvalue().encode()).decode()
        json_data = base64.b64encode(json.dumps(metadata,indent=2,allow_nan=False).encode()).decode()
        self.download.value = f'<a download="dyson_spectrum.csv" href="data:text/csv;base64,{csv_data}">Download spectrum CSV</a> · <a download="dyson_spectrum.json" href="data:application/json;base64,{json_data}">Download transitions and settings</a>'
        if self.on_change:
            self.on_change()
