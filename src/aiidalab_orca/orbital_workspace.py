"""SCF orbital analysis and optional shared-orbital inspection."""

import ipywidgets as ipw

from .presentation import LazyTabs


class OrbitalWorkspace(ipw.VBox):
    def __init__(self, data, prepare_common, use_window):
        self.data, self.prepare_common, self.use_window = data, prepare_common, use_window
        self.inspection = None
        self.active_indices = []
        self._active = True
        self.tabs = LazyTabs([
            ('scf', 'SCF orbitals & spin density', self._scf),
            ('pdos', 'PDOS & orbital character', self._pdos),
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

    def _pdos(self):
        from .pdos import PdosPanel
        self.pdos = PdosPanel(self.data['uuid'], on_select=self._inspect_scf)
        return self.pdos

    def _inspect_scf(self, pairs):
        self.tabs.show_section('scf')
        # Older text outputs can omit virtual levels that the native GBW retains.
        # Only add indices from this panel's verified native export, never guesses.
        available = {value for _, value in self.scf_properties.orbitals.options}
        missing = [pair for pair in pairs if pair not in available]
        if missing:
            a = self.pdos.record['arrays']
            native = {(int(s), int(i)) for s, i in zip(a['spin'], a['indices'])}
            if any(pair not in native for pair in missing):
                raise ValueError('The selected orbital does not belong to the verified native export')
            extra = [(f'{"α" if spin == 0 else "β"} MO {index} · native character export', (spin, index))
                     for spin, index in missing]
            self.scf_properties.orbitals.options = (*self.scf_properties.orbitals.options, *extra)
        self.scf_properties.orbitals.value = tuple(pairs)

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
        index = self.tabs.selected_index
        key = self.tabs.section_keys[index] if index is not None else None
        for name, section in (('scf_properties', 'scf'), ('inspection', 'common'), ('pdos', 'pdos')):
            panel = getattr(self, name, None)
            if panel:
                panel.set_active(active and key == section)
