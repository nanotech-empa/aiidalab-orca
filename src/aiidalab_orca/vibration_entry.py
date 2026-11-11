"""Explicit routes to spectroscopy from a reference without optimization provenance."""

import html

import ipywidgets as ipw

from . import vibration_services as service


class VibrationEntry(ipw.VBox):
    def __init__(self, source_uuid, *, open_reference=None, optimize_reference=None):
        self.source_uuid = str(source_uuid)
        self._open_reference = open_reference
        self._optimize_reference = optimize_reference
        self._supplied_panel = None
        self.notice = ipw.HTML()
        self.content = ipw.VBox()
        try:
            matches = service.reference_context(source_uuid)['optimizations']
        except Exception as exc:
            matches = []
            self.notice.value = '<p class="orca-notice">Saved optimizations could not be checked: '+html.escape(str(exc))+'</p>'
        options = []
        if matches:
            options.append(('Use a matching saved optimization (recommended)', 'existing'))
        options += [('Prepare a geometry optimization'+('' if matches else ' (recommended)'), 'optimize'),
                    ('Use this geometry without optimization (advanced)', 'supplied')]
        self.route = ipw.RadioButtons(options=options, layout=ipw.Layout(width='100%'))
        self.saved = ipw.Dropdown(options=[(row['date']+' · '+(row['label'] or 'Optimization')+' · '+row['uuid'][:8], row['uuid'])
                                           for row in matches], layout=ipw.Layout(width='95%'))
        self.acknowledge = ipw.Checkbox(value=False, indent=False,
            description='Use the supplied coordinates; I understand that stationarity has not been verified.',
            layout=ipw.Layout(width='100%'))
        self.action = ipw.Button(button_style='primary', icon='arrow-right', layout=ipw.Layout(width='auto'))
        self.action.on_click(self._continue)
        self.route.observe(self._route_changed, names='value')
        self.acknowledge.observe(self._route_changed, names='value')
        super().__init__([ipw.HTML('<h3>Choose the geometry for IR / Raman</h3>'
            '<p>This SCF reference has no recorded geometry optimization. Its coordinates may have been optimized elsewhere. '
            'Choose how to continue; opening a route submits no calculation.</p>'), self.notice, self.route, self.content])
        self._route_changed()

    def _route_changed(self, event=None):
        if self.route.value == 'existing':
            self.action.description = 'Open optimized reference for IR / Raman'
            self.action.disabled = self._open_reference is None
            self.content.children = [ipw.HTML('<p>The saved optimization has matching coordinates, electronic settings and ORCA code. '
                'Open it directly; no new SCF or optimization is needed. Its settings and resources will be used.</p>'), self.saved, self.action]
        elif self.route.value == 'optimize':
            self.action.description = 'Prepare optimization for review'
            self.action.disabled = self._optimize_reference is None
            self.content.children = [ipw.HTML('<p>Prepare an optimization using this geometry and reference settings. '
                'Review and submit it in New calculation, then continue to IR / Raman.</p>'), self.action]
        else:
            children = [ipw.HTML('<p class="orca-notice"><b>Geometry will remain fixed.</b> An uploaded structure or a converged SCF '
                'does not establish stationarity at this method, basis, charge and multiplicity. Harmonic spectra may be unreliable '
                'away from a stationary point. No gradient check or optimization will run. Inspect imaginary modes after calculation.</p>'), self.acknowledge]
            if self.acknowledge.value:
                if self._supplied_panel is None:
                    from .vibrations import VibrationalSpectroscopy
                    self._supplied_panel = VibrationalSpectroscopy(self.source_uuid, allow_unverified_geometry=True)
                children.append(self._supplied_panel)
            elif self._supplied_panel is not None:
                self._supplied_panel._invalidate()
            self.content.children = children
        if self._supplied_panel is not None:
            self._supplied_panel.set_active(self.route.value == 'supplied' and self.acknowledge.value)

    def _continue(self, event=None):
        if self.route.value == 'existing' and self.saved.value and self._open_reference:
            self._open_reference(self.saved.value)
        elif self.route.value == 'optimize' and self._optimize_reference:
            self._optimize_reference(self.source_uuid)

    def set_active(self, active):
        if self._supplied_panel is not None:
            self._supplied_panel.set_active(active and self.route.value == 'supplied' and self.acknowledge.value)

    def close(self):
        if getattr(self, '_disposed', False):
            return
        self._disposed = True
        if self._supplied_panel is not None:
            from .app import close_widget_tree
            close_widget_tree(self._supplied_panel)
        super().close()
