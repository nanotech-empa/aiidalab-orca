"""Property review, progress and reduced-cube viewing for a geometry/SCF result."""
import asyncio
import base64
import html

import ipywidgets as ipw
from aiidalab_widgets_empa.cube import CubeViewer

from . import property_services as service


class CubeDisplayMixin:
    """Shared reduced-cube viewer, saved views and CalcJob rendering."""

    def _show_cube(self,_=None):
        if not self.process_uuid or not self.cube.value:
            return
        content=service.preview_content(self.process_uuid,self.cube.value)
        if getattr(self,'render_panel',None):
            self.render_panel.close()
        if self._cube_view:
            self._cube_view.close()
        from .rendering import RenderPanel
        self.render_panel=RenderPanel(self.process_uuid,self.cube.value)
        self._cube_view=CubeViewer(periodic=False,on_render=self.render_panel.submit)
        self._cube_view.set_content(content)
        self.render_panel.bind_viewer(self._cube_view,self._restore_view)
        self.cube_box.children=[self._cube_view]
        encoded=base64.b64encode(content.encode()).decode()
        self.download.value=f'<a download="{html.escape(self.cube.value)}" href="data:text/plain;base64,{encoded}">Download reduced cube</a><p>Blue/gold surfaces show positive/negative values. Orbital amplitudes and spin density use their respective atomic units; previews are for visual inspection.</p>'

    def _restore_view(self,record):
        self.cube.value=record['filename']
        self._cube_view.apply_view_settings(record['visualization'])
        self.render_panel.quality.value=record['quality']
        self.render_panel.saved.refresh(selected=[record['id']])



class OrbitalProperties(CubeDisplayMixin, ipw.VBox):
    def __init__(self, data, energy_view):
        self.source_uuid=str(data['uuid'])
        self.symbols, self.positions=data['symbols'],data['positions']
        self.levels=data['levels']
        self.energy_view=energy_view
        self.plan=None
        self.process_uuid=None
        self._poll_task=None
        self._cube_view=None
        self._displayed_uuid=None
        choices=service.source_tools(self.source_uuid)
        options=[]
        for channel in self.levels['channels']:
            for level in channel:
                spin='α' if level['spin']==0 else 'β'
                label=f"{spin} MO {level['index']} · {level['energy_ev']:.2f} eV · occ {level['occupation']:g}"
                options.append((label,(level['spin'],level['index'])))
        style={'description_width':'140px'}
        self.orbitals=ipw.SelectMultiple(options=options,description='Orbitals',style=style,layout=ipw.Layout(width='95%',height='170px'))
        select_visible=ipw.Button(description='Select levels in displayed energy range',icon='list',layout=ipw.Layout(width='auto'))
        select_visible.on_click(self._select_visible)
        self.spin=ipw.Checkbox(value=self.levels['spin_polarized'],disabled=not self.levels['spin_polarized'],description='Spin density (α − β)',layout=ipw.Layout(width='auto'))
        self.grid=ipw.BoundedIntText(value=80,min=40,max=256,description='Full grid points/axis',style={'description_width':'160px'},layout=ipw.Layout(width='300px'))
        self.retention=ipw.Dropdown(options=[('Stash full-resolution cubes','stash'),('Leave full cubes in calculation directory','leave'),('Delete full cubes after preview validation','delete')],value='stash',description='Full cubes',style=style,layout=ipw.Layout(width='95%'))
        self.stash=ipw.Text(value=service.default_stash_directory(),description='Cube stash directory',style=style,layout=ipw.Layout(width='95%'))
        self.threshold=ipw.BoundedFloatText(value=100,min=0,max=10000,description='WFN retrieval (MiB)',style={'description_width':'160px'},layout=ipw.Layout(width='300px'))
        self.wfn_stash=ipw.Text(description='WFN stash directory',style=style,layout=ipw.Layout(width='95%'))
        self.wfn_info=ipw.HTML()
        self.wfn_policy=ipw.Accordion(children=[ipw.VBox([self.threshold,self.wfn_stash])],selected_index=None)
        self.wfn_policy.set_title(0,'Preservation policy for unarchived or regenerated wavefunctions')
        self.check_wfn=ipw.Button(description='Check wavefunction',icon='refresh',layout=ipw.Layout(width='auto'))
        self.check_wfn.on_click(self._check_wavefunction)
        self.codes={key:ipw.Dropdown(options=choices[key],description=label,layout=ipw.Layout(width='95%'))
                    for key,label in (('plot','ORCA plot'),('cubehandler','Cubehandler'))}

        advanced=ipw.Accordion(children=[ipw.VBox([self.grid,*self.codes.values()])],selected_index=None)
        advanced.set_title(0,'Cube grid and codes')
        self.review_button=ipw.Button(description='Review orbital calculation',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.review_button.on_click(self._review)
        self.submit_button=ipw.Button(description='Compute cubes',icon='play',button_style='success',disabled=True)
        self.submit_button.on_click(self._submit)
        self.message=ipw.HTML()
        self.progress=ipw.HTML()
        self.previous=ipw.Dropdown(description='Property results',style=style,layout=ipw.Layout(width='auto',flex='1 1 auto'))
        refresh=ipw.Button(description='Refresh property results',icon='refresh',layout=ipw.Layout(width='auto'))
        refresh.on_click(self._refresh_runs)
        self.previous.observe(self._open_previous,names='value')
        self.cube=ipw.Dropdown(description='Preview cube',style=style,layout=ipw.Layout(width='95%'))
        self.cube.observe(self._show_cube,names='value')
        self.download=ipw.HTML()
        self.cube_box=ipw.VBox()
        self.result_info=ipw.HTML()
        super().__init__([ipw.HTML('<p>Compute orbital amplitudes and, for an unrestricted reference, spin density. Select multiple orbitals with Ctrl/Cmd. Only cubehandler-reduced previews are retrieved.</p>'),
                          select_visible,self.orbitals,self.spin,self.wfn_info,self.check_wfn,self.wfn_policy,self.retention,self.stash,advanced,
                          self.review_button,self.message,self.submit_button,self.progress,
                          ipw.HBox([self.previous,refresh]),self.result_info,self.cube,self.download,self.cube_box])
        for w in (self.orbitals,self.spin,self.grid,self.retention,self.stash,self.threshold,self.wfn_stash,*self.codes.values()):
            w.observe(self._invalidate,names='value')
        self.retention.observe(self._retention_changed,names='value')
        self._retention_changed()
        self._check_wavefunction(inherit=True)
        self._select_visible()
        self._refresh_runs()

    def _retention_changed(self,_=None):
        self.stash.layout.display='' if self.retention.value=='stash' else 'none'

    def _check_wavefunction(self,_=None,*,inherit=False):
        status=service.wavefunction_status(self.source_uuid)
        if inherit:
            self.threshold.value=status['policy']['threshold_mb']
            self.wfn_stash.value=status['policy']['stash_directory']
        state=status['state']
        label={'repository':'Preserved in the AiiDA repository','stash':'Preserved in the stash',
               'remote':'Available in the calculation directory; not yet archived',
               'missing':'Missing: a new SCF will be required before computing new cubes',
               'unavailable':'Storage could not be checked; retry when accessible'}[state]
        self.wfn_info.value='<p><b>Wavefunction:</b> '+label+'.</p>'
        if status.get('path'):
            self.wfn_info.value+='<p><code>'+html.escape(status['path'])+'</code></p>'
        self.wfn_policy.layout.display='' if state in ('remote','missing') else 'none'
        if state in ('remote','missing'):
            self.wfn_info.value+='<p>'+('Uses the preservation policy recorded with the reference.' if status['inherited'] else 'This older reference has no preservation policy; review the defaults below.')+'</p>'
        if status.get('message'):
            self.wfn_info.value+='<p>'+html.escape(status['message'])+'</p>'

    def _invalidate(self,_=None):
        self.plan=None
        self.submit_button.disabled=True
        self.message.value=''

    def _select_visible(self,_=None):
        lo,hi=self.energy_view.lower.value,self.energy_view.upper.value
        self.orbitals.value=tuple((v['spin'],v['index']) for c in self.levels['channels'] for v in c if lo<=v['energy_ev']<=hi)

    def _review(self,_=None):
        self._invalidate()
        try:
            self._check_wavefunction()
            self.plan=service.prepare_property(self.source_uuid,
                {'orbitals':[list(pair) for pair in self.orbitals.value],'spin_density':self.spin.value,
                 'grid_points':self.grid.value,'retention':self.retention.value,'stash_directory':self.stash.value.strip()},
                {'threshold_mb':self.threshold.value,'stash_directory':self.wfn_stash.value.strip()},
                {key:w.value for key,w in self.codes.items()})
            action='Reuse available cube results' if self.plan['action']=='reuse' else 'Generate cubes and reduce them with cubehandler'
            text=f'<p><b>{action}</b></p>'
            if self.plan['regenerate_reference']:
                text+='<p><b>The wavefunction files are missing. This submission will first recompute SCF at the saved final geometry, with the original electronic settings. Calculation caching will be bypassed where required.</b></p>'
            elif self.plan['action']!='reuse':
                size=self.plan['wavefunction_bytes']/1024**2
                text+=f"<p>Wavefunction bundle: {size:.2f} MiB · {html.escape(self.plan['storage_action'])}.</p>"
            text+=f'<p>Full-resolution cubes: <b>{html.escape(self.retention.label)}</b>.</p>'
            if self.retention.value=='stash':
                text+='<p>Native AiiDA stashing keeps a separate copy. Working-directory originals remain until that directory is cleaned.</p>'
            self.message.value=text
            self.submit_button.disabled=False
        except Exception as exc:
            self.message.value=f'<p style="color:#a02020">{html.escape(str(exc))}</p>'

    def _submit(self,_=None):
        if not self.plan or self.submit_button.disabled:
            return
        self.submit_button.disabled=True
        try:
            self.process_uuid=service.submit_property(self.plan)
            self.plan=None
            self._refresh_status()
            if self._poll_task:
                self._poll_task.cancel()
            self._poll_task=asyncio.get_running_loop().create_task(self._poll())
        except Exception as exc:
            self.message.value=f'<p style="color:#a02020">{html.escape(str(exc))}</p>'

    async def _poll(self):
        try:
            while not self._refresh_status():
                await asyncio.sleep(3)
            self._refresh_runs()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.progress.value=f'<p>{html.escape(str(exc))}</p>'

    def _refresh_runs(self,_=None):
        rows=service.property_runs(self.source_uuid)
        keep=self.process_uuid
        self.previous.options=[('Select a property calculation',None)]+[(f"{r['date'][:16]} · {r['state']} · {r['uuid'][:8]}",r['uuid']) for r in rows]
        if keep and keep in [r['uuid'] for r in rows]:
            self.previous.value=keep
        elif rows:
            self.previous.value=rows[0]['uuid']

    def _open_previous(self,change):
        if change['new']:
            self.process_uuid=change['new']
            finished = self._refresh_status()
            if not finished:
                if self._poll_task:
                    self._poll_task.cancel()
                try:
                    self._poll_task=asyncio.get_running_loop().create_task(self._poll())
                except RuntimeError:
                    pass

    def _refresh_status(self):
        if not self.process_uuid:
            return False
        data=service.property_result(self.process_uuid)
        self.progress.value=f"<p><b>Orbital calculation: {html.escape(data['state'])}</b> · <code>{data['uuid']}</code></p>"
        if data['finished'] and not data['successful']:
            self.progress.value+=f"<p style='color:#a02020'>{html.escape(data['message'])}</p><pre>{html.escape(chr(10).join(data['reports']))}</pre>"
        if data['successful'] and self._displayed_uuid != self.process_uuid:
            self._check_wavefunction()
            manifest=data['manifest']
            text='<p>Cubehandler previews are stored in AiiDA. '
            if manifest['retention']=='delete':
                text+='Full-resolution cubes were deleted after preview validation.'
            else:
                text+='Full-resolution cubes: <code>'+html.escape(data['full_cube_path'])+'</code>.'
            text+='</p>'
            self.result_info.value=text
            self.cube.unobserve(self._show_cube,names='value')
            try:
                self.cube.options=[(c['filename'],c['filename']) for c in manifest['cubes']]
                self.cube.value=manifest['cubes'][0]['filename']
            finally:
                self.cube.observe(self._show_cube,names='value')
            self._show_cube()
            self._displayed_uuid=self.process_uuid
        return data['finished']

    def close(self):
        if self._poll_task:
            self._poll_task.cancel()
        if getattr(self,'render_panel',None):
            self.render_panel.close()
        if self._cube_view:
            self._cube_view.close()
        super().close()
