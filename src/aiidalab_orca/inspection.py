"""Inspect common spatial orbitals before choosing a CASCI active window."""
import asyncio
import base64
import html
import json

import ipywidgets as ipw

from . import inspection_services as service
from .casci_services import progress
from .orbitals import CubeDisplayMixin
from . import property_services


class OrbitalInspection(CubeDisplayMixin, ipw.VBox):
    def __init__(self, common_uuid, *, active_indices=(), apply_window=None):
        self.common_uuid = str(common_uuid)
        self.active_indices = list(active_indices)
        self.apply_window = apply_window
        self.catalog_record, self.plan, self.process_uuid = None,None,None
        self._cube_view, self.render_panel, self._poll_task = None,None,None
        self._job_uuid, self._job_kind, self._displayed_uuid = None,None,None
        style = {'description_width':'140px'}
        wide = ipw.Layout(width='95%')
        choices = service.codes(self.common_uuid)
        self.export_code = ipw.Dropdown(options=choices['export'],description='ORCA export',style=style,layout=wide)
        self.force = ipw.Checkbox(description='Read metadata again',value=False,layout=ipw.Layout(width='auto'))
        self.read = ipw.Button(description='Read orbital information',icon='list',button_style='primary',layout=ipw.Layout(width='auto'))
        self.read.on_click(self._read)
        self.kind = ipw.Dropdown(description='Orbital set',style=style,layout=wide)
        self.kind.observe(self._kind_changed,names='value')
        self.info, self.occupations, self.table, self.metadata_download = (ipw.HTML() for _ in range(4))
        self.orbitals = ipw.SelectMultiple(description='Orbitals to inspect',style=style,layout=ipw.Layout(width='95%',height='170px'))
        self.use_window = ipw.Button(description='Use selected QRO window for CASCI',icon='check',layout=ipw.Layout(width='auto'))
        self.use_window.on_click(self._apply_window)
        self.window_message = ipw.HTML()
        self.grid = ipw.BoundedIntText(value=80,min=40,max=256,description='Grid points/axis',style=style)
        self.retention = ipw.Dropdown(options=[('Stash full-resolution cubes','stash'),('Leave full cubes in calculation directory','leave'),
                    ('Delete full cubes after preview validation','delete')],value='stash',description='Full cubes',style=style,layout=wide)
        self.stash = ipw.Text(value=property_services.default_stash_directory(),description='Cube stash directory',style=style,layout=wide)
        self.retention.observe(self._retention_changed,names='value')
        self.plot_code = ipw.Dropdown(options=choices['plot'],description='ORCA plot',style=style,layout=wide)
        self.cubehandler_code = ipw.Dropdown(options=choices['cubehandler'],description='Cubehandler',style=style,layout=wide)
        advanced = ipw.Accordion(children=[ipw.VBox([self.grid,self.export_code,self.plot_code,self.cubehandler_code,self.force])],selected_index=None)
        advanced.set_title(0,'Inspection grid and codes')
        self.review = ipw.Button(description='Review inspection cubes',icon='list',layout=ipw.Layout(width='auto'))
        self.review.on_click(self._review)
        self.submit = ipw.Button(description='Compute inspection cubes',icon='play',button_style='success',disabled=True,layout=ipw.Layout(width='auto'))
        self.submit.on_click(self._submit)
        self.message, self.status, self.result_info = ipw.HTML(),ipw.HTML(),ipw.HTML()
        self.previous = ipw.Dropdown(description='Inspection results',style=style,layout=wide)
        self.previous.observe(self._open_previous,names='value')
        self.cube = ipw.Dropdown(description='Preview cube',style=style,layout=wide)
        self.cube.observe(self._show_cube,names='value')
        self.download, self.cube_box = ipw.HTML(),ipw.VBox()
        from .presentation import ComputePanel
        self.calculation = ComputePanel('Read orbital information / compute previews…', [self.read,
            self.retention,self.stash,advanced,self.review,self.message,self.submit,self.status])
        super().__init__([ipw.HTML('<p>Inspect the preserved orbital files, then select orbitals to visualize. '
            'The source SCF and CASCI results are linked through their common-orbital reference.</p>'),
            self.kind,self.info,self.occupations,self.metadata_download,self.table,self.orbitals,self.use_window,self.window_message,
            self.previous,self.result_info,self.calculation,
            self.cube,self.download,self.cube_box])
        for widget in (self.orbitals,self.grid,self.retention,self.stash,self.plot_code,self.cubehandler_code):
            widget.observe(self._invalidate,names='value')
        self._refresh_catalog()
        self._retention_changed()

    def _refresh_catalog(self):
        self.catalog_record = service.catalog(self.common_uuid)
        if not self.catalog_record:
            self.info.value = '<p>Read the saved orbital files to obtain their occupations and orbital indices.</p>'
            self.kind.options = []
            self.review.disabled, self.use_window.disabled = True,True
            return
        data = self.catalog_record['data']
        previous = self.kind.value
        options = [(('QRO · integer reference occupations' if kind == 'QRO' else
                    'UNO · fractional natural occupations' if kind == 'UNO' else 'Restricted SCF orbitals'),kind)
                   for kind in data['sets']]
        self.kind.options = options
        self.kind.value = previous if previous in data['sets'] else options[0][1]
        self._kind_changed()
        encoded = base64.b64encode(json.dumps(data,indent=2).encode()).decode()
        self.metadata_download.value = f'<a download="orbital_inspection.json" href="data:application/json;base64,{encoded}">Download orbital information and provenance</a>'

    def _kind_changed(self,_=None):
        self._invalidate()
        self.window_message.value = ''
        if not self.catalog_record or not self.kind.value:
            return
        kind = self.kind.value
        data = self.catalog_record['data']
        record = data['sets'][kind]
        self.review.disabled = False
        self.use_window.disabled = kind == 'UNO' or self.apply_window is None
        self.use_window.description = ('Use selected orbital window for CASCI' if kind == 'restricted' else
                                       'Use selected QRO window for CASCI')
        description = ('Fractional occupations diagonalize the source SCF spin-summed density matrix. '
            'They are diagnostics of that SCF reference, not correlated CASCI occupations. UNO indices belong to the UNO ordering; '
            'they are not a one-to-one assignment to QROs.' if kind == 'UNO' else
            'Integer occupations describe this orbital reference. The orbital energies are QRO labels, not CASCI state energies.' if kind == 'QRO' else
            'Restricted SCF orbitals are retained without an unrestricted-to-QRO conversion.')
        if kind == 'QRO' and 'UNO' not in data['sets']:
            description += ' UNO information is unavailable for this preparation; use Common-orbital regeneration above to prepare a new reference.'
        self.info.value = '<p><b>'+html.escape(kind)+'</b> · reference <code>'+data['orbital_reference_uuid'][:8]+'</code>. '+description+'</p>'
        options, table = [],[]
        for row in record['levels']:
            index, occ = row['index'],row['occupation']
            display_occ = max(0.,min(2.,occ))  # Only suppress round-off at endpoints in display.
            label = f'{kind} {index} · '+('natural occ ' if kind == 'UNO' else 'reference occ ')+f'{display_occ:.6f}'
            energy = f'{row["energy_ev"]:.2f}' if 'energy_ev' in row else '—'
            if 'energy_ev' in row:
                label += f' · {energy} eV'
            active = kind != 'UNO' and index in self.active_indices
            if active:
                label += ' · current CASCI active'
            options.append((label,index))
            table.append(f'<tr><td>{index}</td><td>{display_occ:.6f}</td><td>{energy}</td><td>{"active" if active else ""}</td></tr>')
        self.orbitals.options = options
        if kind == 'UNO':
            fractional = [row['index'] for row in record['levels'] if .02 < row['occupation'] < 1.98]
            center = fractional[0] if fractional else max(0,data['n_electrons']//2-1)
            indices = sorted(set(fractional+[max(0,center-1),min(data['n_orbitals']-1,center+1)]))
        else:
            indices = [i for i in self.active_indices if i < data['n_orbitals']]
        self.orbitals.value = tuple(indices)
        self.table.value = '<details><summary>All orbital indices and occupations</summary><table><tr><th>Index</th><th>Occupation</th><th>Orbital energy (eV)</th><th>CASCI window</th></tr>'+''.join(table)+'</table></details>'
        self._occupation_plot(record['levels'],kind)
        self._refresh_runs()

    def _occupation_plot(self,levels,kind):
        points = ' '.join(f'{45+620*i/max(1,len(levels)-1):.2f},{130-50*max(0.,min(2.,row["occupation"])):.2f}' for i,row in enumerate(levels))
        self.occupations.value = ('<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="165" viewBox="0 0 700 165" role="img" aria-label="Orbital occupations">'
            '<path d="M45 20V130H675" fill="none" stroke="#a1a9b3"/><text x="20" y="34">2</text><text x="20" y="84">1</text><text x="20" y="134">0</text>'
            f'<polyline points="{points}" fill="none" stroke="#2563b7" stroke-width="2"/><text x="250" y="155">{kind} orbital index · occupations</text></svg>')

    def set_active_indices(self,indices):
        if list(indices) != self.active_indices:
            selected = self.orbitals.value
            self.active_indices = list(indices)
            self._kind_changed()
            if all(index in dict(self.orbitals.options).values() for index in selected):
                self.orbitals.value = selected

    def _apply_window(self,_=None):
        try:
            if self.kind.value == 'UNO' or not self.apply_window:
                return
            indices = sorted(self.orbitals.value)
            if not indices or indices != list(range(indices[0],indices[-1]+1)):
                raise ValueError('Select a contiguous QRO window; arbitrary orbital reordering is a later step')
            self.apply_window(indices)
            self.window_message.value = '<p>CASCI active window updated. Review the electron count and calculation before submitting.</p>'
        except Exception as exc:
            self.window_message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _invalidate(self,_=None):
        self.plan = None
        self.submit.disabled = True
        self.message.value = ''

    def _retention_changed(self,_=None):
        self.stash.layout.display = '' if self.retention.value == 'stash' else 'none'

    def _read(self,_=None):
        try:
            uuid = service.submit_catalog(self.common_uuid,self.export_code.value,self.force.value)
            self._start(uuid,'catalog')
        except Exception as exc:
            self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review(self,_=None):
        self._invalidate()
        try:
            self.plan = service.review_cubes(self.common_uuid,self.catalog_record['uuid'],self.kind.value,
                {'orbitals':[[0,index] for index in self.orbitals.value],'spin_density':False,'grid_points':self.grid.value,
                 'retention':self.retention.value,'stash_directory':self.stash.value.strip()},
                {'plot':self.plot_code.value,'cubehandler':self.cubehandler_code.value})
            action = 'Reuse verified inspection cubes.' if self.plan['action'] == 'reuse' else 'Generate selected orbital cubes and reduce them with cubehandler.'
            self.message.value = '<p><b>'+action+'</b> Full cubes: '+html.escape(self.retention.label)+'.</p>'
            self.submit.disabled = self._job_uuid is not None
        except Exception as exc:
            self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _submit(self,_=None):
        if self.plan and not self.submit.disabled:
            try:
                uuid = service.submit_cubes(self.plan)
                self._invalidate()
                self._start(uuid,'cubes')
            except Exception as exc:
                self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _start(self,uuid,kind):
        self._job_uuid,self._job_kind = str(uuid),kind
        self.read.disabled,self.submit.disabled = True,True
        self.status.value = '<p>Submitted '+kind+' workflow · <code>'+str(uuid)+'</code></p>'
        if self._poll_task:
            self._poll_task.cancel()
        self._poll_task = asyncio.get_running_loop().create_task(self._poll())

    async def _poll(self):
        try:
            while self._job_uuid:
                data = progress(self._job_uuid)
                self.status.value = '<p><b>'+self._job_kind+': '+html.escape(data['state'])+'</b> · <code>'+self._job_uuid+'</code></p>'
                if data['finished']:
                    uuid,kind = self._job_uuid,self._job_kind
                    self._job_uuid = None
                    self.read.disabled = False
                    if data['success']:
                        if kind == 'catalog':
                            self._refresh_catalog()
                        else:
                            self.process_uuid = uuid
                            self._refresh_runs()
                            self._show_result()
                    else:
                        self.message.value = '<p style="color:#a02020">'+html.escape(data['message']+'; '.join(data['reports']))+'</p>'
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._job_uuid = None
            self.read.disabled = False
            self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _refresh_runs(self):
        options = service.cube_runs(self.common_uuid,self.kind.value) if self.kind.value else []
        self.previous.options = [('Select inspection cubes',None)]+options
        values = [value for _,value in options]
        self.previous.value = self.process_uuid if self.process_uuid in values else values[0] if values else None
        if not self.previous.value:
            self.process_uuid = None
            self.cube.options = []
            self._clear_cube()

    def _open_previous(self,change):
        if change['new']:
            self.cube.options = []
            self._clear_cube()
            self.process_uuid = change['new']
            data = property_services.property_result(self.process_uuid)
            if data['finished']:
                self._show_result()
            elif not self._job_uuid:
                self._start(self.process_uuid,'cubes')

    def _show_result(self):
        if not self.process_uuid:
            return
        data = property_services.property_result(self.process_uuid)
        if not data['successful']:
            self.result_info.value = '<p>'+html.escape(data['message'])+'</p>'
            return
        manifest = data['manifest']
        text = 'Reduced previews are stored in AiiDA. '
        text += ('Full cubes were deleted after preview validation.' if manifest['retention'] == 'delete' else
                 'Full cubes: '+html.escape(data['full_cube_path']))
        self.result_info.value = '<p>'+text+'</p>'
        self.cube.unobserve(self._show_cube,names='value')
        try:
            self.cube.options = [(row['filename'],row['filename']) for row in manifest['cubes']]
            self.cube.value = manifest['cubes'][0]['filename']
        finally:
            self.cube.observe(self._show_cube,names='value')
        self._show_cube()

    def _clear_cube(self):
        if self.render_panel:
            self.render_panel.close()
            self.render_panel = None
        if self._cube_view:
            self._cube_view.close()
            self._cube_view = None
        self.cube_box.children = ()
        self.download.value,self.result_info.value = '',''

    def close(self):
        if getattr(self,'_disposed',False):
            return
        self._disposed = True
        if self._poll_task:
            self._poll_task.cancel()
        self._clear_cube()
        from .app import close_widget_tree
        for child in self.children:
            close_widget_tree(child)
        super().close()
