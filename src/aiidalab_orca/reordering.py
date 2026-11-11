"""Explicit preparation review for a noncontiguous spatial CAS selection."""

import asyncio
import html

import ipywidgets as ipw

from . import reordering_services as service
from .casci_services import progress
from .resources import MemoryInput, memory_label
from .retention import FullFileRetention, description


class OrbitalReordering(ipw.VBox):
    def __init__(self, common_uuid, selection, export_code, prepared):
        self.common_uuid, self.selection, self.export_code, self.prepared = str(common_uuid), selection, export_code, prepared
        self.plan, self._job_uuid, self._task = None, None, None
        self.memory = MemoryInput(value=2048)
        self.walltime = ipw.BoundedIntText(value=10, min=1, max=10080,
            description='Preparation wall time (minutes)', style={'description_width': 'initial'})
        self.retention = FullFileRetention()
        self.review = ipw.Button(description='Review selected CAS orbital preparation', icon='list')
        self.submit = ipw.Button(description='Prepare reordered common orbitals', icon='play', disabled=True,
                                 button_style='success', layout=ipw.Layout(width='auto'))
        self.message = ipw.HTML()
        self.refresh = ipw.Button(description='Refresh orbital preparation', icon='refresh')
        self.refresh.on_click(self._refresh)
        self.review.on_click(self._review)
        self.submit.on_click(self._submit)
        self.memory.observe(self.invalidate, names='value')
        self.walltime.observe(self.invalidate, names='value')
        self.retention.observe(self.invalidate, names='revision')
        self.export_code.observe(self.invalidate, names='value')
        super().__init__([ipw.HTML('<h4>Prepare a noncontiguous CAS selection</h4>'
            '<p>A new shared reference packs the selected original MOs into a contiguous CAS window. '
            'Every signed coefficient, occupation, energy and the whole source-to-prepared overlap '
            'are checked. No SCF, orbital optimization or CASCI is performed. '
            'Inspect and explicitly confirm the new reference afterwards. '
            'Original QRO/restricted references only; CASSCF/imported inputs are not yet qualified.</p>'),
            self.memory, self.walltime, self.retention, ipw.HBox([self.review, self.submit]),
            self.refresh, self.message])

    def invalidate(self, _=None):
        self.plan = None
        self.submit.disabled = True
        if not self._job_uuid:
            self.message.value = ''

    def _review(self, _=None):
        if self._job_uuid:
            return
        self.invalidate()
        try:
            space = self.selection()
            self.plan = service.review(self.common_uuid, space, self.export_code.value,
                resources={'memory_mb': self.memory.value, 'wallclock_seconds': self.walltime.value*60},
                native_output_policy=self.retention.values())
            p = self.plan['plan']
            rows = ''.join(f'<tr><td>{i}</td><td>{original}</td><td>{role}</td></tr>'
                for i, original in enumerate(p['native_to_source'])
                for role in [('active' if i in p['native_active_space']['orbitals'] else
                              'inactive' if original in p['inactive_source_indices'] else 'virtual')])
            if self.plan['reuse_uuid']:
                budget = self.plan['reused_resources']
                execution = (f'Reuse existing preparation {self.plan["reuse_uuid"]}. No new CalcJob is submitted. '
                    f'Original budget: 1 process / {memory_label(budget["memory_mb"])} / '
                    f'{budget["wallclock_seconds"]/60:g} minutes. Original retention: '
                    + html.escape(description(self.plan['reused_policy'])))
            else:
                execution = ('One serial preparation CalcJob: export → copy MO rows → write GBW → re-export → verify. '
                    f'1 process / {memory_label(self.memory.value)} / up to {self.walltime.value} minutes. '
                    'Any requested separate stash job follows with the same budget. No automatic PDOS job. '
                    + html.escape(description(self.retention.values())))
            self.message.value = ('<p>'+execution+'</p>'
                f'<p>Source reference {p["source_reference_uuid"]}; plan {p["plan_sha256"]}.</p>'
                f'<p>Selected source MOs: {p["source_active_space"]["orbitals"]}; '
                f'active electrons: {p["source_active_space"]["electrons"]}; '
                f'prepared CAS indices: {p["native_active_space"]["orbitals"]}.</p>'
                '<details><summary>Inspect the complete orbital mapping</summary>'
                '<table><tr><th>Prepared MO</th><th>Original MO</th><th>Subspace</th></tr>'+rows+'</table></details>')
            self.submit.disabled = False
        except (ValueError, KeyError, OSError) as exc:
            self.message.value = '<p>'+html.escape(str(exc))+'</p>'

    def _submit(self, _=None):
        if not self.plan or self._job_uuid or self.submit.disabled:
            return
        self.review.disabled, self.submit.disabled = True, True
        try:
            if self.selection() != self.plan['space']:
                raise ValueError('The visible source selection or electron count changed; review again')
            self._job_uuid = service.submit(self.plan)
            self.plan = None
            self.message.value = '<p>Orbital preparation '+self._job_uuid+'</p>'
            self._task = asyncio.get_running_loop().create_task(self._poll())
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.plan = None
            self.review.disabled = bool(self._job_uuid)
            self.message.value = '<p>'+html.escape(str(exc))+'</p>'

    async def _poll(self):
        while not getattr(self, '_disposed', False) and self._job_uuid:
            if self._refresh():
                return
            await asyncio.sleep(3)

    def _refresh(self, _=None):
        if not self._job_uuid:
            return False
        state = progress(self._job_uuid)
        self.message.value = '<p>'+self._job_uuid+' · '+html.escape(state['state']+' · '+state['message'])+'</p>'
        if not state['finished']:
            return False
        uuid = self._job_uuid
        self._job_uuid = None
        self.review.disabled = False
        if state['success']:
            self.prepared(uuid, service.prepared_space(uuid))
        return True

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        if self._task:
            self._task.cancel()
        self.export_code.unobserve(self.invalidate, names='value')
        self.retention.close()
        super().close()
