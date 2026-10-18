"""Review, submit and reopen molecular vibrational spectroscopy."""

import asyncio
import base64
import html

import ipywidgets as ipw

from . import vibration_services as service
from .casci_services import progress


class VibrationalSpectroscopy(ipw.VBox):
    def __init__(self, source_uuid):
        self.source_uuid = str(source_uuid)
        self.plan, self._poll_task, self._running_uuid, self._shown_uuid = None, None, None, None
        self.raman = ipw.Checkbox(value=True, description='Also compute Raman activities and polarizability derivatives', indent=False,
                                 layout=ipw.Layout(width='auto'))
        self.force = ipw.Checkbox(description='Recompute even if compatible vibrational data are available', indent=False,
                                 layout=ipw.Layout(width='auto'))
        self.review = ipw.Button(description='Review vibrational calculation', icon='list', button_style='primary', layout=ipw.Layout(width='auto'))
        self.submit = ipw.Button(description='Compute vibrations', icon='play', button_style='success', disabled=True, layout=ipw.Layout(width='auto'))
        self.refresh = ipw.Button(description='Refresh calculations', icon='refresh', layout=ipw.Layout(width='auto'))
        self.previous = ipw.Dropdown(description='Vibrational calculations', style={'description_width': 'initial'}, layout=ipw.Layout(width='95%'))
        self.message, self.status, self.details, self.download = (ipw.HTML() for _ in range(4))
        self.viewer = ipw.VBox()
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        self.refresh.on_click(self._refresh)
        self.previous.observe(self._open, names='value')
        for control in (self.raman, self.force):
            control.observe(self._invalidate, names='value')
        super().__init__([ipw.HTML('<p>Compute harmonic normal modes and IR intensities at this optimized geometry, '
            'optionally with Raman activities. Method, basis, charge, multiplicity and resources are inherited from the reference. '
            'The Hessian and derivatives are retained in AiiDA. Resonance Raman is a separate next step.</p>'),
            self.raman, self.force, self.review, self.message, self.submit, self.status,
            self.refresh, self.previous, self.details, self.download, self.viewer])
        self._refresh()

    def _invalidate(self, event=None):
        self.plan = None
        self.submit.disabled = True
        self.message.value = ''

    def _error(self, exc):
        self.message.value = '<p style="color:#a02020">'+html.escape(str(exc))+'</p>'

    def _review(self, event=None):
        self._invalidate()
        try:
            self.plan = service.prepare(self.source_uuid, raman=self.raman.value, force_recompute=self.force.value)
            action = ('Reuse verified vibrational data; no ORCA calculation is needed.' if self.plan['reuse_uuid'] else
                      'Submit an independent ORCA analytical-frequency calculation at the selected optimized geometry.')
            warnings = ''.join('<p style="color:#a02020">'+html.escape(w)+'</p>' for w in self.plan['warnings'])
            self.message.value = '<p><b>'+action+'</b></p>'+warnings+'<details><summary>ORCA input</summary><pre>'+html.escape(self.plan['input_preview'])+'</pre></details>'
            self.submit.disabled = self._running_uuid is not None
        except Exception as exc:
            self._error(exc)

    def _submit(self, event=None):
        if not self.plan or self.submit.disabled:
            return
        try:
            uuid = service.submit_plan(self.plan)
            self._invalidate()
            self._start(uuid)
        except Exception as exc:
            self._error(exc)

    def _start(self, uuid):
        self._running_uuid = str(uuid)
        self.review.disabled = True
        self.submit.disabled = True
        self.status.value = '<p>Submitted vibrational workflow · <code>'+str(uuid)+'</code></p>'
        if self._poll_task:
            self._poll_task.cancel()
        self._poll_task = asyncio.get_running_loop().create_task(self._poll())

    async def _poll(self):
        try:
            while self._running_uuid:
                status = progress(self._running_uuid)
                self.status.value = '<p><b>'+html.escape(status['state'])+'</b> · <code>'+self._running_uuid+'</code></p>'
                if status['finished']:
                    uuid = self._running_uuid
                    self._running_uuid = None
                    self.review.disabled = False
                    self._refresh(preferred=uuid)
                    if not status['success']:
                        self._error(status['message']+'; '.join(status['reports']))
                    return
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._running_uuid = None
            self.review.disabled = False
            self._error(exc)

    def _refresh(self, event=None, *, preferred=None):
        try:
            rows = service.runs(self.source_uuid)
            previous = preferred or self.previous.value
            self.previous.options = [('Select a vibrational calculation', None)] + [
                (f"{row['date'][:16]} · {row['state']} · {row['label']}", row['uuid']) for row in rows]
            self.previous.value = previous if any(row['uuid'] == previous for row in rows) else rows[0]['uuid'] if rows else None
        except Exception as exc:
            self._error(exc)

    def _open(self, event):
        uuid = event['new']
        if not uuid or uuid == self._shown_uuid:
            return
        try:
            status = progress(uuid)
            if not status['finished']:
                if not self._running_uuid:
                    self._start(uuid)
                return
            if not status['success']:
                self._error(status['message']+'; '.join(status['reports']))
                return
            record = service.result(uuid)
            from .vibration_viewer import spectra_view
            view = spectra_view(record)
            from .app import close_widget_tree
            for child in self.viewer.children:
                close_widget_tree(child)
            self.viewer.children = (view,)
            self._shown_uuid = uuid
            summary = record['summary']
            warning = ''.join('<p style="color:#a02020">'+html.escape(w)+'</p>' for w in summary['warnings'])
            self.details.value = f"<p><b>{summary['number_of_modes']} vibrational modes</b> · " + ('no significant imaginary modes.' if not summary['imaginary_mode_indices'] else 'inspect imaginary modes before interpreting spectra.') + warning + f"</p><details><summary>Provenance</summary><p>Workflow: <code>{uuid}</code><br>Vibrational arrays: <code>{record['data_uuid']}</code><br>Hessian: <code>{record['hessian_uuid']}</code></p></details>"
            encoded = base64.b64encode(record['hessian_text'].encode()).decode()
            self.download.value = f'<a download="aiida.hess" href="data:text/plain;base64,{encoded}"><i class="fa fa-download"></i> Download Hessian and derivatives</a>'
        except Exception as exc:
            self._error(exc)

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        if self._poll_task:
            self._poll_task.cancel()
        super().close()
