"""Independent Co 2p preparation and multiplet-spectrum workspace."""
import asyncio
import base64
import csv
import html
import io
import json

import ipywidgets as ipw
import numpy as np
import plotly.graph_objects as go
from scipy.special import voigt_profile

from . import cobalt_services as service
from .cobalt_services import calculation_progress as progress
from .presentation import ComputePanel


class CobaltSpectrum(ipw.VBox):
    def __init__(self,record):
        self.record=record
        self.shift=ipw.FloatText(value=0,description='Display shift (eV)',step=.01,style={'description_width':'initial'})
        self.gaussian=ipw.BoundedFloatText(value=1.5,min=.01,max=10,step=.01,description='Gaussian FWHM (eV)',style={'description_width':'initial'})
        self.lorentzian=ipw.BoundedFloatText(value=.54,min=.01,max=10,step=.01,description='Lorentzian FWHM (eV)',style={'description_width':'initial'})
        self.figure=go.FigureWidget()
        self.figure.update_layout(template='plotly_white',height=430,yaxis_title='Relative intensity · core-transition approximation',
            margin=dict(l=65,r=25,t=30,b=55))
        self.table,self.download=ipw.HTML(),ipw.HTML()
        super().__init__([ipw.HTML('<p class="orca-notice"><b>Frozen-orbital RAS-CI + spin–orbit coupling.</b> Ionized-state orbital relaxation is omitted, and the absolute binding energies are not validated. Relative peak weights use a bound core-to-core transition approximation to XPS; no continuum photoelectron is calculated. The display shift changes plot alignment and is saved separately.</p>'),
            ipw.HBox([self.shift,self.gaussian,self.lorentzian],layout=ipw.Layout(flex_flow='row wrap')),
            self.figure,self.table,self.download])
        for w in (self.shift,self.gaussian,self.lorentzian):w.observe(self._update,names='value')
        self._update()

    def _update(self,event=None):
        sticks=self.record['sticks']
        energies=np.array([r['binding_energy_ev'] for r in sticks])+self.shift.value
        weights=np.array([r['weight'] for r in sticks])
        grid=np.linspace(energies.min()-5,energies.max()+5,4000)
        sigma=self.gaussian.value/np.sqrt(8*np.log(2));gamma=self.lorentzian.value/2
        curve=sum(w*voigt_profile(grid-e,sigma,gamma) for e,w in zip(energies,weights))
        self.figure.data=()
        self.figure.add_scatter(x=grid,y=curve,name='Co 2p multiplets',line=dict(color='#7c3aed',width=2))
        self.figure.add_scatter(x=np.column_stack([energies,energies,np.full_like(energies,np.nan)]).ravel(),
            y=np.column_stack([np.zeros_like(weights),weights,np.full_like(weights,np.nan)]).ravel(),
            name='Discrete transitions',mode='lines',line=dict(color='#a78bfa',width=1))
        self.figure.update_xaxes(title='Co 2p binding energy + display shift (eV)',autorange='reversed')
        self.table.value=f'<p>{len(sticks)} nonzero final-state contributions · total relative weight {weights.sum():.3f} · model <code>{html.escape(self.record["protocol"])}</code>.</p>'
        stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(['final_soc_state','unshifted_binding_energy_eV','displayed_binding_energy_eV','relative_weight'])
        writer.writerows((r['final_state'],r['binding_energy_ev'],r['binding_energy_ev']+self.shift.value,r['weight']) for r in sticks)
        table=base64.b64encode(stream.getvalue().encode()).decode()
        snapshot=self.record|{'view':{'energy_shift_ev':self.shift.value,'gaussian_fwhm_ev':self.gaussian.value,'lorentzian_fwhm_ev':self.lorentzian.value}}
        config=base64.b64encode(json.dumps(snapshot,indent=2).encode()).decode()
        self.download.value=f'<a download="co-2p-sticks.csv" href="data:text/csv;base64,{table}">Download Co 2p transitions</a> · <a download="co-2p-view.json" href="data:application/json;base64,{config}">Download view and provenance</a>'


class CobaltXpsPanel(ipw.VBox):
    def __init__(self,source_uuid):
        from .core_benchmark_view import ScalarCoreBenchmarks
        self.source_uuid=str(source_uuid);self.plan=None;self.plan_kind=None;self._poll_task=None;self._running_uuid=None;self._running_kind=None;self._disposed=False
        self.benchmarks=ScalarCoreBenchmarks(self.source_uuid)
        self.message,self.status,self.details=ipw.HTML(),ipw.HTML(),ipw.HTML()
        self.reference_notice=ipw.HTML()
        self.integration=ipw.HTML('<p><b>Integration protocol:</b> Consistent grid (recommended). Applied automatically to orbital preparation, neutral reconvergence and the Co 2p spectrum.</p><details><summary>Numerical settings</summary><p>COSX angular grids 3,3,3 with default radial accuracy. Generated grids are validated. The neutral-energy tolerance remains 10⁻⁷ Hartree.</p></details>')
        self.validation_help=ipw.HTML('<details><summary>Automatic checks and supported scope</summary><p>This draft supports neutral doublet CoPc only. Fe, Zn and other molecular models need separately validated protocols.</p><p>You do not need to enable checks: the workflows verify the active-space character, integration grids, frozen-reference energy, Co 1s/2p identities and final RAS/SOC results. Core identities are read from the producing CASSCF output; its wavefunction is left unchanged.</p><p>A failed check stops the affected stage. Review the diagnostic before retrying; valid earlier steps are reused when their required files remain available. An older integration protocol has a dedicated reference-update action below.</p></details>')
        self.references=ipw.Dropdown(description='Valence orbitals',style={'description_width':'initial'},layout=ipw.Layout(width='95%'))
        self.previous=ipw.Dropdown(description='Co 2p calculations',style={'description_width':'initial'},layout=ipw.Layout(width='95%'))
        self.refresh=ipw.Button(description='Refresh Co calculations',icon='refresh',layout=ipw.Layout(width='auto'))
        self.review_reference=ipw.Button(description='Review Co orbital preparation',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.prepare=ipw.Button(description='Prepare Co valence orbitals',icon='play',button_style='success',disabled=True,layout=ipw.Layout(width='auto'))
        self.review_recovery=ipw.Button(description='Review reference update',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.reconverge=ipw.Button(description='Reconverge reference with consistent grid',icon='play',button_style='success',disabled=True,layout=ipw.Layout(width='auto'))
        self.recovery_controls=ipw.HBox([self.review_recovery,self.reconverge],layout=ipw.Layout(flex_flow='row wrap',display='none'))
        self.review_spectrum=ipw.Button(description='Review Co 2p calculation',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.submit=ipw.Button(description='Compute Co 2p multiplets',icon='play',button_style='success',disabled=True,layout=ipw.Layout(width='auto'))
        self.force=ipw.Checkbox(value=False,description='Recompute this stage even when compatible artifacts exist',indent=False)
        self.viewer=ipw.VBox()
        self.compute=ComputePanel('Prepare / compute Co 2p…',[
            ipw.HTML('<p>Neutral CoPc · CoII d7 + ligand π² model. Prepare SA-CASSCF(9,6) orbitals first, then compute RAS-CI(16,10) and spin–orbit-coupled Co 2p multiplets. The geometry stays fixed. Basis: cc-pwCVTZ on Co, cc-pVTZ on C/N/H. This is a multireference calculation, separate from 1s ΔSCF.</p>'),
            self.integration,self.validation_help,self.references,self.reference_notice,self.recovery_controls,self.force,
            ipw.HBox([self.review_reference,self.prepare],layout=ipw.Layout(flex_flow='row wrap')),
            ipw.HBox([self.review_spectrum,self.submit],layout=ipw.Layout(flex_flow='row wrap')),self.message])
        super().__init__([ipw.HTML('<h4>Co 2p multiplets · draft</h4><p>Published RAS-CI/SOC core-transition protocol. <a href="https://doi.org/10.26434/chemrxiv-2026-t0g71" target="_blank">Method and approximations (preprint)</a>.</p>'),
            self.benchmarks,self.previous,self.refresh,self.status,self.compute,self.details,self.viewer])
        self.review_reference.on_click(self._review_reference);self.prepare.on_click(self._prepare)
        self.review_recovery.on_click(self._review_recovery);self.reconverge.on_click(self._reconverge)
        self.review_spectrum.on_click(self._review_spectrum);self.submit.on_click(self._submit)
        self.refresh.on_click(self._refresh);self.previous.observe(self._open,names='value')
        self.references.observe(self._reference_changed,names='value');self.force.observe(self._invalidate,names='value')
        try:service.reference_info(self.source_uuid)
        except ValueError as exc:
            self.compute.layout.display='none';self.message.value='';self.status.value='<p>'+html.escape(str(exc))+'</p>'
            self.refresh.disabled=True;self.previous.layout.display='none';return
        self._refresh()

    def _invalidate(self,event=None):
        self.plan=None;self.plan_kind=None;self.prepare.disabled=True;self.submit.disabled=True;self.reconverge.disabled=True

    def _reference_changed(self,event=None):
        self._invalidate()
        try:
            status=service.reference_status(self.source_uuid,self.references.value)
            self.reference_notice.value='<p class="orca-notice"><b>'+html.escape(status['message'])+'</b></p>'
            self.recovery_controls.layout.display='' if status['recoverable'] else 'none'
            self.review_recovery.disabled=bool(self._running_uuid)
            self.review_spectrum.disabled=not status['compatible'] or bool(self._running_uuid)
        except Exception as exc:
            self.reference_notice.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'
            self.review_spectrum.disabled=True;self.recovery_controls.layout.display='none'

    def _review_reference(self,event=None):
        self._invalidate()
        try:
            self.plan=service.prepare_valence(self.source_uuid,force=self.force.value)
            self.plan_kind='valence'
            self.message.value='<p>'+html.escape(self.plan['description'])+'</p><p><b>Resources:</b> 8 processes, 12 GiB budget. Existing compatible intermediate orbitals are reused after checking their files.</p>'
            self.prepare.disabled=bool(self._running_uuid)
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _prepare(self,event=None):
        if self.plan_kind!='valence' or self.prepare.disabled or self._running_uuid:return
        try:self._start(service.submit_valence(self.plan),'valence')
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review_recovery(self,event=None):
        self._invalidate()
        try:
            self.plan=service.prepare_recovery(self.source_uuid,self.references.value,force=self.force.value)
            self.plan_kind='recovery'
            self.message.value='<p>'+html.escape(self.plan['description'])+'</p><p><b>Resources:</b> 8 processes, 12 GiB budget. The saved wavefunction was found in '+html.escape(self.plan['orbital_location'])+' storage.</p>'
            self.reconverge.disabled=bool(self._running_uuid)
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _reconverge(self,event=None):
        if self.plan_kind!='recovery' or self.reconverge.disabled or self._running_uuid:return
        try:self._start(service.submit_valence(self.plan),'recovery')
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review_spectrum(self,event=None):
        self._invalidate()
        try:
            self.plan=service.prepare_spectrum(self.source_uuid,self.references.value,force=self.force.value)
            self.plan_kind='spectrum'
            self.message.value='<p>'+html.escape(self.plan['description'])+'</p>'+('<p><b>Existing verified spectrum will be reused; no wavefunction is required.</b></p>' if self.plan.get('reuse_calculation_uuid') else '')+'<p>The dominant neutral configuration is checked before using the single-configuration 1s-hole spectator approximation.</p>'
            self.submit.disabled=bool(self._running_uuid)
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _submit(self,event=None):
        if self.plan_kind!='spectrum' or self.submit.disabled or self._running_uuid:return
        try:self._start(service.submit_spectrum(self.plan),'spectrum')
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _start(self,uuid,kind=None):
        self._invalidate();self._running_uuid=str(uuid);self._running_kind=kind
        self.review_spectrum.disabled=True;self.review_recovery.disabled=True
        if self._poll_task:self._poll_task.cancel()
        self._poll_task=asyncio.get_running_loop().create_task(self._poll())

    async def _poll(self):
        try:
            while self._running_uuid:
                s=progress(self._running_uuid)
                self.status.value='<p><b>'+html.escape(s['state'])+'</b> · <code>'+self._running_uuid+'</code></p>'
                if s['finished']:
                    finished=self._running_uuid;kind=self._running_kind
                    self._running_uuid=None;self._running_kind=None
                    self._refresh(preferred_reference=finished if s['success'] and kind in ('valence','recovery') else None)
                    if s['success'] and kind in ('valence','recovery'):
                        self.message.value='<p>The neutral reference is ready with the consistent integration protocol. Review the Co 2p calculation to continue.</p>'
                    if not s['success']:self.message.value='<p style="color:#a02020">'+html.escape(s['message']+'; '.join(s['reports']))+'</p>'
                    return
                await asyncio.sleep(5)
        except asyncio.CancelledError:pass
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _refresh(self,event=None,preferred_reference=None):
        refs=service.valence_runs(self.source_uuid)
        old=self.references.value
        self.references.options=[('Select prepared valence orbitals',None)]+[(r['date'][:16]+' · '+r['state']+(' · update required' if r['success'] and not r['compatible'] else '')+' · '+r['uuid'][:8],r['uuid']) for r in refs]
        self.references.value=next((uid for uid in (preferred_reference,old) if uid and any(r['uuid']==uid for r in refs)),
            next((r['uuid'] for r in refs if r['compatible']),next((r['uuid'] for r in refs if r['success']),None)))
        self._reference_changed()
        rows=service.spectrum_runs(self.source_uuid)
        self.previous.options=[('Select a Co 2p calculation',None)]+[(r['date'][:16]+' · '+r['state']+' · '+r['uuid'][:8],r['uuid']) for r in rows]
        if rows:self.previous.value=rows[0]['uuid']
        pending=next(((r['uuid'],'valence' if r in refs else 'spectrum') for r in refs+rows if r['state'] in ('created','running','waiting')),None)
        if pending and not self._running_uuid:self._start(*pending)

    def _open(self,event):
        from .app import close_widget_tree
        for child in self.viewer.children:close_widget_tree(child)
        self.viewer.children=[];self.details.value=''
        if not event['new']:return
        try:
            s=progress(event['new'])
            if not s['finished']:return
            if not s['success']:
                self.details.value='<details><summary>Stopped Co 2p calculation · '+html.escape(event['new'][:8])+'</summary><p>Historical run <code>'+html.escape(event['new'])+'</code>. The selected valence reference is checked separately above.</p><p>'+html.escape(s['message']+'; '.join(s['reports']))+'</p></details>'
                return
            record=service.result(event['new'])
            self.viewer.children=[CobaltSpectrum(record)]
            self.details.value='<details><summary>Co 2p provenance and approximations</summary><p>Spectrum data <code>'+record['spectrum_uuid']+'</code></p><p>'+html.escape(record.get('intensity_model',''))+'</p><p>Dominant neutral configuration after natural-orbital canonicalization: '+f"{100*record['neutral_configuration_weight']:.1f}%"+'.</p><p>Neutral reference above the lowest computed neutral spin sector: '+f"{record['reference_above_computed_neutral_minimum_ev']:.3f} eV"+'.</p></details>'
        except Exception as exc:self.message.value='<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def close(self):
        if getattr(self,'_disposed',False):return
        self._disposed=True
        if self._poll_task:self._poll_task.cancel()
        super().close()
