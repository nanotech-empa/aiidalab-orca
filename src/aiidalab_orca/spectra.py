"""Interactive spectra from durable transition tables; no electronic jobs needed."""
import base64
import csv
import html
import io
import json
import math

import ipywidgets as ipw
import numpy as np

from aiida_empa_orca.dyson_data import spectrum,weighted_table,spin_factor
from .interactive_svg import InteractiveSvg
from .transitions import TransitionDiagram, peak_groups, action_attributes


class SpectralViewer(ipw.VBox):
    def __init__(self,table,on_change=None,*,states=None,on_selection=None,on_use=None):
        self.table = table
        self.on_change = on_change
        self.on_selection,self.on_use = on_selection,on_use
        self._ready = False
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
        self.plot = InteractiveSvg(on_action=self._action)
        self.info,self.download,self.transition_table = ipw.HTML(),ipw.HTML(),ipw.HTML()
        self.energy = ipw.FloatText(value=round(table['transitions'][0]['energy_ev'],2),step=.01,description='Selected energy (eV)',style=style)
        self.mode = ipw.ToggleButtons(options=[('At energy','energy'),('Energy window','window')])
        self.window_lower = ipw.FloatText(value=round(self.energy.value-.05,2),step=.01,description='Window start (eV)',style=style)
        self.window_upper = ipw.FloatText(value=round(self.energy.value+.05,2),step=.01,description='Window end (eV)',style=style)
        self.selected = ipw.SelectMultiple(description='Selected transitions',style=style,
            options=[(self._choice(r),r['id']) for r in table['transitions']],
            layout=ipw.Layout(width='95%',height='100px'))
        best = max(weighted_table(table,'unpolarized')['transitions'],key=lambda r:r['strength'])
        self.selected.value = (best['id'],)
        self.selection_info = ipw.HTML()
        self.preview_info = ipw.HTML()
        self.use_selection = ipw.Button(description='Use selection for cubes / maps',icon='check',layout=ipw.Layout(width='auto'))
        self.use_selection.on_click(self._use_selection)
        self.show_states = ipw.Checkbox(value=bool(states),disabled=not bool(states),description='Show connected many-electron states',layout=ipw.Layout(width='auto',margin='0 20px 0 0'))
        self.diagram = TransitionDiagram(states,table,self._action) if states else None
        self.diagram_box = ipw.VBox([self.diagram] if self.diagram else [],layout=ipw.Layout(flex='1 1 420px',min_width='min(100%,420px)',margin='0 8px 0 0'))
        self.diagram_box.layout.display = '' if states else 'none'
        spectrum_box = ipw.VBox([ipw.HTML('<b>Addition/removal spectrum</b>'),self.plot,
            ipw.HTML('<p style="font-size:12px;color:#475569">Click a peak to select nearby transition poles, including computed dark states. Drag across the spectrum to select an energy window. Unresolved roots remain individually selectable below.</p>')],
            layout=ipw.Layout(flex='1 1 420px',min_width='min(100%,420px)',margin='0 0 0 8px'))
        self.chart_layout = ipw.ToggleButtons(options=[('Side by side','side'),('Stacked','stacked')],description='Charts',
            style={'description_width':'50px'},layout=ipw.Layout(width='380px'))
        self._chart_columns = [self.diagram_box,spectrum_box]
        self.chart_layout.observe(self._chart_layout_changed,names='value')
        linked = ipw.HBox(self._chart_columns,layout=ipw.Layout(flex_flow='row wrap',align_items='flex-start'))
        super().__init__([ipw.HBox([self.spin,self.side],layout=ipw.Layout(flex_flow='row wrap')),
            ipw.HBox([self.eta,self.shift],layout=ipw.Layout(flex_flow='row wrap')),
            ipw.HBox([self.lower,self.upper,reset],layout=ipw.Layout(flex_flow='row wrap')),
            self.info,ipw.HBox([self.show_states,self.chart_layout],layout=ipw.Layout(flex_flow='row wrap')),linked,self.selected,self.selection_info,self.preview_info,self.use_selection,self.download,self.transition_table,
            ipw.HTML('<p><b>Spectral intensity blend</b> · select an energy or integrate over a window. Uses the selected transitions below.</p>'),
            self.mode,self.energy,ipw.HBox([self.window_lower,self.window_upper],layout=ipw.Layout(flex_flow='row wrap'))])
        for w in (self.spin,self.side,self.eta,self.shift,self.lower,self.upper,self.mode,self.energy,self.window_lower,self.window_upper):
            w.observe(self._update,names='value')
        self.selected.observe(self._selection_changed,names='value')
        self.show_states.observe(self._show_states,names='value')
        self._ready = True
        self._reset()

    @staticmethod
    def _choice(row):
        return f"{row['id']} · {row['side']} · mult {row['final_multiplicity']} · root {row['final_root']} · {row['energy_ev']:.6f} eV"

    def _show_states(self,_=None):
        self.diagram_box.layout.display = '' if self.show_states.value and self.diagram else 'none'

    def _chart_layout_changed(self,_=None):
        for column in self._chart_columns:
            column.layout.flex = '1 1 420px' if self.chart_layout.value == 'side' else '1 1 100%'

    def _selection_changed(self,_=None):
        if not self._ready:
            return
        chosen = [r for r in self.table['transitions'] if r['id'] in self.selected.value]
        if chosen:
            if self.side.value != 'both' and any(r['side'] != self.side.value for r in chosen):
                self.side.value = 'both'
            poles = [r['energy_ev']+self.shift.value for r in chosen]
            self.lower.value = min(self.lower.value,math.floor((min(poles)-.25)*100)/100)
            self.upper.value = max(self.upper.value,math.ceil((max(poles)+.25)*100)/100)
            if self.diagram:
                self.diagram.reveal(self.selected.value)
        self._update()
        if self.on_selection:
            self.on_selection(list(self.selected.value))

    def _use_selection(self,_=None):
        if self.on_use and self.selected.value:
            self.on_use(list(self.selected.value))

    def _set_selection(self,identifiers):
        previous = self.selected.value
        self.selected.value = tuple(identifiers)
        if self.selected.value == previous:
            self._selection_changed()

    def _action(self,action):
        """Validate browser events; selection never submits a calculation."""
        kind = action.get('action')
        rows = [r for r in self.table['transitions'] if self.side.value in ('both',r['side'])]
        valid = {r['id'] for r in self.table['transitions']}
        if kind == 'select':
            ids = action.get('ids')
            if not isinstance(ids,list) or not ids or any(not isinstance(i,str) or i not in valid for i in ids):
                return
            chosen = [r for r in self.table['transitions'] if r['id'] in ids]
            # State/connector clicks use exact recorded poles for selecting the blend energy.
            energy = action.get('energy',sum(r['energy_ev']+self.shift.value for r in chosen)/len(chosen))
            if not isinstance(energy,(int,float)) or not np.isfinite(energy):
                return
            self.energy.value = round(energy,2)
            self.mode.value = 'energy'
            if self.diagram:
                self.show_states.value = True
            self._set_selection(r['id'] for r in chosen)
        elif kind == 'window':
            lo,hi = action.get('lower'),action.get('upper')
            if (not isinstance(lo,(int,float)) or not isinstance(hi,(int,float)) or
                    not np.isfinite([lo,hi]).all() or hi <= lo):
                return
            # Round outwards so a narrow drag cannot discard the peak under it.
            self.window_lower.value,self.window_upper.value = math.floor(lo*100)/100,math.ceil(hi*100)/100
            if self.window_upper.value <= self.window_lower.value:
                self.window_upper.value = self.window_lower.value+.01
            self.mode.value = 'window'
            self._set_selection(r['id'] for r in rows if self.window_lower.value <= r['energy_ev']+self.shift.value <= self.window_upper.value)
        elif kind == 'energy':
            energy = action.get('energy')
            if not isinstance(energy,(int,float)) or not np.isfinite(energy):
                return
            tolerance = max(self.eta.value, (self.upper.value-self.lower.value)*10/850)
            self.energy.value,self.mode.value = round(energy,2),'energy'
            self._set_selection(r['id'] for r in rows if abs(r['energy_ev']+self.shift.value-energy) <= tolerance)

    def _reset(self,_=None):
        energies = [r['energy_ev']+self.shift.value for r in self.table['transitions']]
        self.lower.value,self.upper.value = round(min(energies)-.5,2),round(max(energies)+.5,2)
        self._update()

    def blend(self):
        return {'mode':self.mode.value,'energy_ev':self.energy.value,'lower_ev':self.window_lower.value,
                'upper_ev':self.window_upper.value,'eta_ev':self.eta.value,
                'spin_convention':self.spin.value,'shift_ev':self.shift.value}

    def _update(self,_=None):
        if not self._ready:
            return
        if isinstance(_,dict) and _.get('owner') is self.side and self.side.value != 'both':
            rows = [r for r in weighted_table(self.table,self.spin.value)['transitions'] if r['side'] == self.side.value]
            if rows:
                selected = tuple(r['id'] for r in rows if r['id'] in self.selected.value)
                selected = selected or (max(rows,key=lambda r:r['strength'])['id'],)
                if selected != self.selected.value:
                    self.selected.value = selected
                    return
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
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="350" viewBox="0 0 960 350" data-energy-min="{self.lower.value}" data-energy-max="{self.upper.value}" role="img" aria-label="Dyson spectral function">',
                 '<path d="M65 35V295H920" fill="none" stroke="#666"/>']
        if self.mode.value == 'window':
            a,b = max(self.lower.value,self.window_lower.value),min(self.upper.value,self.window_upper.value)
            if a < b:
                parts.append(f'<rect x="{x(a):.2f}" y="35" width="{x(b)-x(a):.2f}" height="260" fill="#0e7490" opacity=".10"/>')
        for tick in np.linspace(self.lower.value,self.upper.value,7):
            parts.append(f'<text x="{x(tick):.1f}" y="318" text-anchor="middle" font-size="18">{tick:.2f}</text>')
        for side,color in (('removal','#2c7be5'),('addition','#f06431')):
            points = ' '.join(f'{x(w):.2f},{y(v):.2f}' for w,v in zip(omega,curves[side]))
            parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
            for row in table['transitions']:
                pole = row['energy_ev']+self.shift.value
                if row['side'] == side and self.side.value in ('both',side) and self.lower.value <= pole <= self.upper.value:
                    strength = row['strength']
                    if row['id'] in self.selected.value:
                        parts.append(f'<path d="M{x(pole):.2f} 35V295" stroke="#fbbf24" stroke-width="7" opacity=".5"/>')
                    parts.append(f'<line x1="{x(pole):.2f}" x2="{x(pole):.2f}" y1="295" y2="{295-40*min(strength,2):.2f}" stroke="{color}" opacity=".6"><title>{html.escape(row["id"])} · {pole:.3f} eV · weight {strength:.5f}</title></line>')
        if self.lower.value <= self.energy.value <= self.upper.value:
            parts.append(f'<path d="M{x(self.energy.value):.2f} 35V295" stroke="#555" stroke-dasharray="4 4"/>')
        targets = [dict(r,pole_ev=r['energy_ev']+self.shift.value) for r in table['transitions'] if self.side.value in ('both',r['side'])]
        for group in peak_groups(targets,self.lower.value,self.upper.value):
            a,b = max(65.,x(group[0]['pole_ev'])-6),min(915.,x(group[-1]['pole_ev'])+6)
            title = '; '.join(f"{r['id']} · {r['pole_ev']:.6f} eV · weight {r['strength']:.6g}" for r in group)
            parts.append(f'<rect {action_attributes([r["id"] for r in group],title)} x="{a:.2f}" y="35" width="{b-a:.2f}" height="260" fill="transparent"><title>{html.escape(title)}</title></rect>')
        parts.append('<text x="470" y="344" text-anchor="middle" font-size="18">Transition energy + offset (eV)</text><text transform="translate(18 190) rotate(-90)" text-anchor="middle" font-size="18">Spectral intensity</text></svg>')
        self.plot.value = ''.join(parts)
        if self.diagram:
            self.diagram.update(self.selected.value,self.spin.value,self.side.value,self.lower.value,self.upper.value,self.shift.value)
        self._selection_details(table)
        self.info.value = ('<p><span style="color:#2c7be5">● Removal</span> · <span style="color:#f06431">● Addition</span>. '
            'η is half-width at half-maximum; FWHM = 2η. Curves use Andrés’s convention: integrated peak area = π × weight. '
            'Unpolarized weights include the Clebsch–Gordan spin-multiplet factors relative to the stored highest-M_S component. '
            'Only the computed final states contribute.</p>')
        rows = []
        for raw,row in zip(self.table['transitions'],table['transitions']):
            rows.append(f'<tr><td>{html.escape(row["id"])}</td><td>{row["side"]}</td><td>{row["final_charge"]:+d}</td><td>{row["final_multiplicity"]}</td><td>{row["final_root"]}</td><td>{row["energy_ev"]+self.shift.value:.3f}</td><td>{raw["strength"]:.5f}</td><td>{row["spin_factor"]:.5g}</td><td>{row["strength"]:.5f}</td><td>{row["final_ci_norm"]:.8f}</td></tr>')
        self.transition_table.value = '<details><summary>Transition energies, strengths and CI norms</summary><table><tr><th>ID</th><th>Branch</th><th>Charge</th><th>Mult.</th><th>Root</th><th>Energy (eV)</th><th>Component strength</th><th>Spin factor</th><th>Selected weight</th><th>Retained CI norm</th></tr>'+''.join(rows)+'</table></details>'
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['energy_ev','removal','addition','total'])
        writer.writerows(zip(omega,curves['removal'],curves['addition'],curves['total']))
        metadata = dict(transitions=table,eta_hwhm_ev=self.eta.value,shift_ev=self.shift.value,
                        lower_ev=self.lower.value,upper_ev=self.upper.value,side=self.side.value,
                        selected_transition_ids=list(self.selected.value),
                        lorentzian_normalization='eta/((omega-pole)^2+eta^2); area=pi*strength')
        csv_data = base64.b64encode(buffer.getvalue().encode()).decode()
        json_data = base64.b64encode(json.dumps(metadata,indent=2,allow_nan=False).encode()).decode()
        self.download.value = f'<a download="dyson_spectrum.csv" href="data:text/csv;base64,{csv_data}">Download spectrum CSV</a> · <a download="dyson_spectrum.json" href="data:application/json;base64,{json_data}">Download transitions and settings</a>'
        if self.on_change:
            self.on_change()

    def _selection_details(self,weighted):
        selected = [r for r in weighted['transitions'] if r['id'] in self.selected.value]
        self.use_selection.disabled = not selected or self.on_use is None
        if not selected:
            self.selection_info.value = '<p>No transition selected. Click a peak, state or connector, or drag an energy window.</p>'
            return
        initial = self.table['initial_state']
        rows = []
        for row in selected:
            factor = spin_factor(initial['multiplicity'],row['final_multiplicity'],'unpolarized')
            gap = -row['energy_ev'] if row['side'] == 'removal' else row['energy_ev']
            rows.append('<tr>'+''.join(f'<td style="padding:5px 8px">{value}</td>' for value in [
                html.escape(row['id']),row['side'],f"q={row['final_charge']:+d}, mult {row['final_multiplicity']}, r{row['final_root']}",
                f'{gap:.6f}',f"{row['energy_ev']+self.shift.value:.6f}",f"{row['component_strength']:.5f}",
                f'{factor:.5g}',f"{row['strength']:.5f}"] )+'</tr>')
        names = ['Transition','Branch','Final state','E_final − E_initial (eV)','Peak + offset (eV)','Component Z','CG multiplet F','Displayed W']
        self.selection_info.value = ('<div style="padding:12px;border:1px solid #dbe3ec;border-radius:8px;background:#f8fafc">'
            f'<b>{len(selected)} selected transition'+('s' if len(selected)!=1 else '')+'</b>'
            '<div style="overflow-x:auto"><table><tr>'+''.join(f'<th style="padding:5px 8px;text-align:left">{n}</th>' for n in names)+'</tr>'+''.join(rows)+'</table></div>'
            '<p style="font-size:12px">F is the Clebsch–Gordan-derived spin-multiplet factor, not a signed CG amplitude. '
            'Unpolarized: W = Z × F; highest-M_S component: W = Z. The factor is applied once. '
            'Peak positions include the energy offset; state-energy differences do not.</p></div>')

    def close(self):
        if getattr(self,'_disposed',False):
            return
        self._disposed = True
        self.on_change = self.on_selection = self.on_use = None
        from .app import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()
