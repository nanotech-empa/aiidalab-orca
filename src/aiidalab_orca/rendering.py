"""Render submission and results without retaining AiiDA nodes."""
import asyncio
import base64
import html

import ipywidgets as ipw
from aiidalab_widgets_empa.cube_views import SavedCubeViews
from . import render_services as service
from .resources import MemoryInput, memory_label


class RenderPanel(ipw.VBox):
    def __init__(self, property_uuid, filename):
        self.property_uuid, self.filename = str(property_uuid), filename
        self.viewer=None
        self._disposed = False
        self._task=None
        self.process_uuid=None
        self._pending=[]
        self._batch_message=''
        self._batch_jobs={}
        self.plan = None
        self._review_mode = None
        self._watched = {}
        self.memory = MemoryInput(value=2048, style={'description_width': 'initial'})
        self.wallclock = ipw.BoundedIntText(value=10, min=1, max=10080,
            description='Render wall time (minutes)', style={'description_width': 'initial'})
        self.resources = ipw.Accordion(children=[ipw.VBox([self.memory, self.wallclock,
            ipw.HTML('<p>Each reviewed image uses one serial rendering CalcJob.</p>')])], selected_index=None)
        self.resources.set_title(0, 'Rendering resources')
        self.review_html = ipw.HTML()
        self.submit_button = ipw.Button(description='Submit reviewed render', icon='play',
            button_style='success', disabled=True, layout=ipw.Layout(width='auto'))
        self.submit_button.on_click(self._submit_reviewed)
        self.quality=ipw.Dropdown(options=[('Stored reduced cube','preview'),('Full-resolution cube from scratch/stash','full')],
                                 description='Render source',style={'description_width':'120px'},layout=ipw.Layout(width='95%'))
        self.status=ipw.HTML()
        self.download=ipw.HTML()
        self.image=ipw.Image(format='png',layout=ipw.Layout(max_width='100%',display='none'))
        self.previous=ipw.Dropdown(description='Saved renders',style={'description_width':'120px'},layout=ipw.Layout(width='95%'))
        self.previous.observe(self._open,names='value')
        super().__init__([self.quality, self.resources,
            ipw.HTML('<p>Review the current or saved view, then submit the reviewed rendering job.</p>'),
            self.review_html, self.submit_button, self.previous,self.status,self.download,self.image])
        for control in (self.memory, self.wallclock, self.quality):
            control.observe(self._invalidate, names='value')
        self.refresh()

    def bind_viewer(self, viewer, restore):
        self.viewer=viewer
        self.saved=SavedCubeViews(
            save=self._save_view,
            list_views=lambda: service.saved_views(self.property_uuid),
            load=lambda identifier: restore(service.saved_view(self.property_uuid,identifier)),
            remove=lambda identifier: service.remove_view(self.property_uuid,identifier),
            render=self._render_saved,
        )
        self.saved.render_button.description = 'Review selected views'
        self.saved.saved.observe(self._saved_changed, names='value')
        viewer.render_button.description = 'Review current view'
        viewer.render_button.tooltip = 'Review the render source and resources; no job is submitted'
        pane=viewer.tabs.children[2]
        controls = tuple(child for child in pane.children if child not in (viewer.render_button, viewer.render_message))
        pane.children=(*controls, self.resources, viewer.render_button, viewer.render_message,
                       self.review_html, self.submit_button, self.previous,self.status,self.download,self.image)
        viewer.children=(viewer.tabs,self.quality,self.saved)
        self._watch_viewer(viewer.tabs)
        viewer.viewer3d.viewer.observe(self._view_changed, names='_camera_orientation')

    def _save_view(self,name,identifier):
        return service.save_view(self.property_uuid,self.filename,self.quality.value,name,
                                 self.viewer.view_settings(),identifier)

    def _budget(self):
        return {'memory_mb': self.memory.value, 'wallclock_seconds': self.wallclock.value * 60}

    def _invalidate(self, _=None):
        self.plan = None
        self._review_mode = None
        self.submit_button.disabled = True
        self.review_html.value = ''

    def _view_changed(self, _=None):
        if self._review_mode == 'current':
            self._invalidate()

    def _viewer_children_updated(self, event):
        for child in event['new']:
            self._watch_viewer(child)
        self._view_changed()

    def _watch_viewer(self, widget):
        if id(widget) in self._watched:
            return
        self._watched[id(widget)] = widget
        if isinstance(widget, ipw.ValueWidget) and not isinstance(widget, (ipw.HTML, ipw.Image, ipw.Label)):
            widget.observe(self._view_changed, names='value')
        if 'children' in widget.traits():
            widget.observe(self._viewer_children_updated, names='children')
            for child in widget.children:
                self._watch_viewer(child)

    def _saved_changed(self, _=None):
        if self._review_mode == 'saved':
            self._invalidate()

    def _review(self, report, mode):
        self._invalidate()
        plans = report['plans']
        rows = []
        for plan in plans:
            p = plan['settings']
            label = plan['view_name'] or 'Current view'
            source = 'full resolution' if plan['quality'] == 'full' else 'reduced preview'
            rows.append('<li>' + html.escape(label) + ' · ' + html.escape(plan['filename']) +
                f" · {source} · {p['width']} × {p['height']} px · slicing plane: " +
                ('included' if 'slice_plane' in p else 'hidden') + ' · ' + html.escape(plan['code_label']) + '</li>')
        text = '<p><b>Render review — no job submitted</b></p><ul>' + ''.join(rows) + '</ul>'
        if plans:
            budget = plans[0]['resources']
            text += (f"<p><b>{len(plans)} CalcJob(s), each: 1 process, {memory_label(budget['memory_mb'])}, "
                     f"up to {budget['wallclock_seconds'] / 60:g} minutes.</b> Only PNG and render log are retrieved.</p>")
        text += ''.join('<p class="orca-notice">' + html.escape(item['name'] + ': ' + item['message']) + '</p>'
                        for item in report['errors'])
        self.review_html.value = text
        self.plan = plans or None
        self._review_mode = mode if plans else None
        self.submit_button.disabled = not bool(plans)
        if self.viewer:
            self.viewer.tabs.selected_index = 2

    def _render_saved(self, identifiers):
        self._review(service.prepare_saved_renders(self.property_uuid, identifiers, resources=self._budget()), 'saved')

    def _submit_reviewed(self, _=None):
        if not self.plan or self.submit_button.disabled:
            return
        plans, mode = self.plan, self._review_mode
        self._invalidate()  # An uncertain or repeated click must not duplicate jobs.
        try:
            if mode == 'current' and self.viewer and self.viewer.render_settings() != plans[0]['settings']:
                raise ValueError('The view changed; review it again before submitting.')
        except (ValueError, TypeError, KeyError) as exc:
            self.review_html.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'
            return
        jobs, errors = [], []
        for plan in plans:
            name = plan['view_name'] or 'Current view'
            try:
                uuid = service.submit_reviewed_render(plan)
                jobs.append({'uuid': uuid, 'name': name})
            except Exception as exc:
                errors.append(name + ': ' + str(exc))
        self._batch_message = '<p>' + '<br>'.join(html.escape(item) for item in
            ([f'Submitted {len(jobs)} rendering CalcJob(s).'] + errors)) + '</p>'
        if jobs:
            self._batch_jobs.update({item['uuid']: item['name'] for item in jobs})
            self._pending.extend(item['uuid'] for item in jobs)
            self.process_uuid = jobs[-1]['uuid']
            self.refresh()
            self._start_poll()
        else:
            self.status.value = self._batch_message

    def refresh(self):
        options=service.renders(self.property_uuid)
        self.previous.options=[('Select a saved render',None)]+options
        if self.process_uuid and self.process_uuid in dict(options).values():
            self.previous.value=self.process_uuid

    def submit(self, settings):
        """Shared-viewer callback: prepare a review, never submit immediately."""
        self._invalidate()
        try:
            plan = service.prepare_render(self.property_uuid, self.filename, self.quality.value, settings,
                                          resources=self._budget())
            self._review({'plans': [plan], 'errors': []}, 'current')
        except Exception as exc:
            self.review_html.value = '<p class="orca-notice">' + html.escape(str(exc)) + '</p>'

    def _open(self,change):
        if change['new']:
            self.process_uuid=change['new']
            self._start_poll()

    def _start_poll(self):
        if self._task:
            self._task.cancel()
        if not self._update():
            self._task=asyncio.get_running_loop().create_task(self._poll())

    def _update(self):
        states={uuid:service.result(uuid,include_image=False) for uuid in set(self._pending)|self._batch_jobs.keys()}
        self._pending=[uuid for uuid in self._pending if not states[uuid]['finished']]
        data=service.result(self.process_uuid)
        self.status.value=self._batch_message+f"<p>Render: <b>{html.escape(data['state'])}</b> · <code>{self.process_uuid}</code></p>"
        for uuid,name in self._batch_jobs.items():
            state=states[uuid]
            message=state['state'] if not state['finished'] or state['success'] else 'failed: '+state['message']
            self.status.value+='<p>'+html.escape(name)+': '+html.escape(message)+'</p>'
        if self._pending:
            self.status.value+=f'<p>{len(self._pending)} rendering job(s) still running.</p>'
        if data['success']:
            self.image.layout.display=''
            self.image.value=data['image']
            encoded=base64.b64encode(data['image']).decode()
            self.download.value=f'<a download="{html.escape(data["filename"])}.png" href="data:image/png;base64,{encoded}">Download rendered PNG</a>'
        else:
            self.image.layout.display='none'
            self.image.value=b''
            self.download.value=''
            if data['finished']:
                self.status.value+='<pre>'+html.escape(data['message'])+'</pre>'
        return data['finished'] and not self._pending

    async def _poll(self):
        try:
            while not self._update():
                await asyncio.sleep(3)
            self.refresh()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.status.value='<p>'+html.escape(str(exc))+'</p>'

    def close(self):
        if self._disposed:
            return
        self._disposed = True
        for widget in self._watched.values():
            if isinstance(widget, ipw.ValueWidget) and not isinstance(widget, (ipw.HTML, ipw.Image, ipw.Label)):
                widget.unobserve(self._view_changed, names='value')
            if 'children' in widget.traits():
                widget.unobserve(self._viewer_children_updated, names='children')
        self._watched.clear()
        if self.viewer:
            self.viewer.viewer3d.viewer.unobserve(self._view_changed, names='_camera_orientation')
            self.saved.saved.unobserve(self._saved_changed, names='value')
        for control in (self.memory, self.wallclock, self.quality):
            control.unobserve(self._invalidate, names='value')
        if getattr(self,'_task',None):
            self._task.cancel()
        super().close()
