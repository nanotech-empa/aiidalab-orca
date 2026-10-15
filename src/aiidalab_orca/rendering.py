"""Render submission and results without retaining AiiDA nodes."""
import asyncio
import base64
import html

import ipywidgets as ipw
from . import render_services as service


class RenderPanel(ipw.VBox):
    def __init__(self, property_uuid, filename):
        self.property_uuid, self.filename = str(property_uuid), filename
        self.viewer=None
        self._task=None
        self.process_uuid=None
        self.quality=ipw.Dropdown(options=[('Stored reduced cube','preview'),('Full-resolution cube from scratch/stash','full')],
                                 description='Render source',style={'description_width':'120px'},layout=ipw.Layout(width='95%'))
        self.status=ipw.HTML()
        self.download=ipw.HTML()
        self.image=ipw.Image(format='png',layout=ipw.Layout(max_width='100%',display='none'))
        self.previous=ipw.Dropdown(description='Saved renders',style={'description_width':'120px'},layout=ipw.Layout(width='95%'))
        self.previous.observe(self._open,names='value')
        super().__init__([self.quality,ipw.HTML('<p>Choose the source here, then use <b>Render → Render image</b> above. Rendering is submitted as an AiiDA CalcJob on the calculation computer.</p>'),self.previous,self.status,self.download,self.image])
        self.refresh()

    def refresh(self):
        options=service.renders(self.property_uuid,self.filename)
        self.previous.options=[('Select a saved render',None)]+options
        if self.process_uuid and self.process_uuid in dict(options).values():
            self.previous.value=self.process_uuid

    def submit(self, settings):
        self.process_uuid=service.submit_render(self.property_uuid,self.filename,self.quality.value,settings)
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
        data=service.result(self.process_uuid)
        self.status.value=f"<p>Render: <b>{html.escape(data['state'])}</b> · <code>{self.process_uuid}</code></p>"
        if data['success']:
            self.image.layout.display=''
            self.image.value=data['image']
            encoded=base64.b64encode(data['image']).decode()
            self.download.value=f'<a download="{html.escape(self.filename)}.png" href="data:image/png;base64,{encoded}">Download rendered PNG</a>'
        elif data['finished']:
            self.status.value+='<pre>'+html.escape(data['message'])+'</pre>'
        return data['finished']

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
