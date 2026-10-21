"""SCF orbital analysis and optional shared-orbital inspection."""

import ipywidgets as ipw

from .presentation import LazyTabs


class FixedOrbitalWorkspace(ipw.VBox):
    """Inspect an imported basis without inventing a DFT orbital spectrum."""
    def __init__(self, common_uuid, use_window):
        from .inspection import OrbitalInspection
        self.common_uuid = str(common_uuid)
        self.inspection = OrbitalInspection(self.common_uuid,
            apply_window=lambda indices: use_window(self.common_uuid, indices))
        super().__init__([ipw.HTML('<h3>Imported fixed spatial orbitals</h3>'), self.inspection])

    def inspect_reference(self, common_uuid, indices):
        if str(common_uuid) != self.common_uuid:
            raise ValueError('Select the imported orbital reference')
        self.inspection.set_active_indices(indices)

    def set_active(self, active):
        self.inspection.set_active(active)


class OrbitalWorkspace(ipw.VBox):
    def __init__(self, data, prepare_common, use_window):
        self.data, self.prepare_common, self.use_window = data, prepare_common, use_window
        self.inspection = None
        self.active_indices = []
        self._active = True
        self.tabs = LazyTabs([
            ('scf', 'SCF orbitals & spin density', self._scf),
            ('common', 'QRO / UNO inspection', self._common),
        ])
        self.tabs.observe(lambda _: self.set_active(self._active), names='selected_index')
        super().__init__([ipw.HTML('<h3>Orbitals & density</h3>'), self.tabs])

    def _scf(self):
        from .levels import EnergyLevels
        from .orbitals import OrbitalProperties
        self.energy_view = EnergyLevels(self.data['levels'])
        self.scf_properties = OrbitalProperties(self.data, self.energy_view)
        return ipw.VBox([self.energy_view, self.scf_properties])

    def _common(self):
        self.reference = ipw.Dropdown(description='Common orbitals',
            style={'description_width': 'initial'}, layout=ipw.Layout(width='95%'))
        self.reference.observe(self._reference_changed, names='value')
        refresh = ipw.Button(description='Refresh orbital references', icon='refresh', layout=ipw.Layout(width='auto'))
        refresh.on_click(self._refresh)
        prepare = ipw.Button(description='Prepare common orbitals…', icon='plus', layout=ipw.Layout(width='auto'))
        prepare.on_click(lambda _: self.prepare_common())
        self.inspection_box = ipw.VBox()
        panel = ipw.VBox([ipw.HTML('<p>Optional spatial-orbital references for inspection and active-space selection. '
            'Ordinary SCF orbitals do not require this preparation.</p>'), self.reference,
            ipw.HBox([refresh, prepare], layout=ipw.Layout(flex_flow='row wrap')), self.inspection_box])
        self._refresh()
        return panel

    def _refresh(self, event=None):
        from . import casci_services as service
        previous = self.reference.value
        rows = service.reference_runs(self.data['uuid'])
        self.reference.options = [('Select common orbitals', None)] + [
            (f"{r['kind']} · {r['reference_uuid'][:8]}", r['uuid']) for r in rows]
        self.reference.value = previous if any(r['uuid'] == previous for r in rows) else rows[0]['uuid'] if rows else None
        if not rows:
            self.inspection_box.children = (ipw.HTML('<p class="orca-notice">No common-orbital reference has been prepared. '
                'Prepare one here if you want QRO/UNO inspection or CASCI; no CASCI calculation is required to inspect orbitals.</p>'),)

    def _reference_changed(self, change):
        if self.inspection:
            from .app import close_widget_tree
            close_widget_tree(self.inspection)
            self.inspection = None
        if not change['new']:
            self.inspection_box.children = ()
            return
        from .inspection import OrbitalInspection
        uuid = str(change['new'])
        self.inspection = OrbitalInspection(uuid, active_indices=self.active_indices,
            apply_window=lambda indices: self.use_window(uuid, indices))
        self.inspection_box.children = (self.inspection,)

    def inspect_reference(self, common_uuid, indices):
        self.active_indices = list(indices)
        self.tabs.show_section('common')
        self._refresh()
        self.reference.value = common_uuid
        if self.inspection:
            self.inspection.set_active_indices(indices)

    def set_active(self, active):
        self._active = active
        panel = getattr(self, 'scf_properties', None) if self.tabs.selected_index == 0 else self.inspection
        if panel:
            panel.set_active(active)
