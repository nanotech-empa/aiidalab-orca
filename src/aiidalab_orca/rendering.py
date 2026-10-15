"""Render submission and results without retaining AiiDA nodes."""
import asyncio
import base64
import html

import ipywidgets as ipw
from aiidalab_widgets_empa.cube_views import SavedCubeViews
from . import render_services as service


class RenderPanel(ipw.VBox):
    def __init__(self, property_uuid, filename):
        self.property_uuid, self.filename = str(property_uuid), filename
        self.viewer=None
        self._task=None
        self.process_uuid=None
        self._pending=[]
        self._batch_message=''
        self._batch_jobs={}
        self.quality=ipw.Dropdown(options=[('Stored reduced cube','preview'),('Full-resolution cube from scratch/stash','full')],
                                 description='Render source',style={'description_width':'120px'},layout=ipw.Layout(width='95%'))
        self.status=ipw.HTML()
        self.download=ipw.HTML()
        self.image=ipw.Image(format='png',layout=ipw.Layout(max_width='100%',display='none'))
        self.previous=ipw.Dropdown(description='Saved renders',style={'description_width':'120px'},layout=ipw.Layout(width='95%'))
        self.previous.observe(self._open,names='value')
        super().__init__([self.quality,ipw.HTML('<p>Choose the source here, then use <b>Render → Render image</b> above. Rendering is submitted as an AiiDA CalcJob on the calculation computer.</p>'),self.previous,self.status,self.download,self.image])
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
        pane=viewer.tabs.children[2]
        pane.children=(*pane.children,self.previous,self.status,self.download,self.image)
        viewer.children=(viewer.tabs,self.quality,self.saved)

    def _save_view(self,name,identifier):
        return service.save_view(self.property_uuid,self.filename,self.quality.value,name,
                                 self.viewer.view_settings(),identifier)

    def _render_saved(self,identifiers):
        report=service.render_saved_views(self.property_uuid,identifiers)
        jobs=report['submitted']
        messages=[f'Submitted {len(jobs)} rendering CalcJob(s).'] if jobs else []
        messages += [f'{item["name"]}: {item["message"]}' for item in report['errors']]
        self._batch_message='<p>'+'<br>'.join(html.escape(text) for text in messages)+'</p>'
        if jobs:
            self._batch_jobs.update({item['uuid']:item['name'] for item in jobs})
            self._pending.extend(item['uuid'] for item in jobs)
            self.process_uuid=jobs[-1]['uuid']
            self.refresh()
            self._start_poll()
        else:
            self.status.value=self._batch_message
        self.viewer.tabs.selected_index=2

    def refresh(self):
        options=service.renders(self.property_uuid)
        self.previous.options=[('Select a saved render',None)]+options
        if self.process_uuid and self.process_uuid in dict(options).values():
            self.previous.value=self.process_uuid

    def submit(self, settings):
        self._batch_message=''
        self.process_uuid=service.submit_render(self.property_uuid,self.filename,self.quality.value,settings)
        self._pending.append(self.process_uuid)
        self._start_poll()

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
        if getattr(self,'_task',None):
            self._task.cancel()
        super().close()
