"""Carry an explicit spectral-maximum request through cube and map preparation."""

import html

import ipywidgets as ipw


class PeakMapMixin:
    def _init_peak_maps(self):
        self._peak_map_request = None
        self.peak_map_status = ipw.HTML()

    def _clear_peak_maps(self):
        self._peak_map_request = None
        self.peak_map_status.value = ''
        if hasattr(self, 'cube_states'):
            self.cube_states.disabled = False
        if self.map_panel:
            self.map_panel.review.disabled = False
            self.map_panel.kind.disabled = self.map_panel.selection.disabled = False
            if hasattr(self.map_panel, 'complete'):
                self.map_panel.complete.disabled = False

    def _validate_peak_map_request(self):
        request = self._peak_map_request
        if request and (not self.spectrum or self.spectrum.blend() != request['blend']):
            self._clear_peak_maps()
            self.peak_map_status.value = ('<p>Spectral settings changed. Choose a spectral maximum '
                'and use its peak energy again to prepare that map.</p>')

    def _peak_map_heading(self):
        request = self._peak_map_request
        blend = request['blend']
        return (f'<b>{html.escape(request["label"])} · spectral map at {blend["energy_ev"]:.6f} eV</b>'
            f'<p>All {len(request["ids"])} computed transitions contribute, including weak tails. '
            f'Lorentzian HWHM: {blend["eta_ev"]:g} eV; spin convention: '
            f'{html.escape(self.spectrum.spin.label)}. No calculation is submitted by this action.</p>')

    def _use_peak_energy(self):
        """Prepare the full spectral map; keep every submission explicit."""
        if not self.record or not self.spectrum:
            return
        peak = next((row for row in self.spectrum.peak_rows
            if row['energy_ev'] == self.spectrum.energy.value), None)
        if peak is None:
            return
        self._peak_map_request = dict(label=peak['label'], blend=dict(self.spectrum.blend()),
            transitions_uuid=self.record['transitions_uuid'],
            ids=[row['id'] for row in self.record['data']['transitions']])
        self.cube_states.value = tuple(range(len(self.record['data']['transitions'])))
        self.cube_states.disabled = True
        if hasattr(self, 'full_blend'):
            self.full_blend.value = True
        if self.on_show_maps:
            self.on_show_maps()
        self.set_view('maps')
        try:
            from .dyson_services import map_cube_inventory
            inventory = map_cube_inventory(self.record['transitions_uuid'])
            selected = inventory['cube_uuid'] or inventory['running_uuid']
            if selected:
                # Existing completed/running work is opened instead of duplicated.
                self._refresh_cubes(selected)
                if inventory['running_uuid'] and not inventory['cube_uuid']:
                    self.cube_calculation.toggle.value = False
                    self.peak_map_status.value = self._peak_map_heading() + (
                        '<p><b>Step 1 of 2: amplitude cubes are already running.</b> '
                        'Wait for this calculation; the spectral-map controls will open when it finishes.</p>')
                else:
                    self._sync_peak_map()
            else:
                self.cube_calculation.show()
                if self.map_panel:
                    self.map_panel.invalidate()
                    self.map_panel.review.disabled = True
                self.peak_map_status.value = self._peak_map_heading() + (
                    '<p><b>Step 1 of 2: prepare amplitude cubes.</b> '
                    f'The best saved set contains {inventory["available_count"]} of '
                    f'{len(self._peak_map_request["ids"])} required full-resolution amplitudes. '
                    'All transitions are selected below. Review the grid and storage settings, '
                    'then click <b>Review Dyson cubes / blend</b> and <b>Generate cubes / blend</b>. '
                    'Keep full cubes with Stash or Leave. The complete amplitude set is needed in one '
                    'cube calculation; it can be reused for other peak energies. '
                    'When it finishes, Step 2 opens automatically.</p>')
        except Exception as exc:
            self.peak_map_status.value = self._peak_map_heading() + (
                '<p>Could not check the saved amplitude cubes: '+html.escape(str(exc))+
                '. No calculation was submitted. Retry the peak action when access is restored.</p>')

    def _sync_peak_map(self):
        """Apply the pending request when a complete amplitude set becomes available."""
        request = self._peak_map_request
        if not request or not self.map_panel:
            return
        source = self.map_panel.source
        available = {row['transition_id'] for row in source['manifest']['cubes'] if row['kind'] == 'dyson'}
        if (source['table_uuid'] != request['transitions_uuid'] or
                not set(request['ids']) <= available or source['manifest']['retention'] == 'delete'):
            self.map_panel.invalidate()
            self.map_panel.review.disabled = True
            self.cube_calculation.show()
            return
        self.map_panel.review.disabled = False
        self.map_panel.kind.value = 'blend'
        self.map_panel.kind.disabled = self.map_panel.selection.disabled = True
        if hasattr(self.map_panel, 'complete'):
            self.map_panel.complete.value = True
            self.map_panel.complete.disabled = True
        self.map_panel.selection.value = tuple(request['ids'])
        self.map_panel.invalidate()
        self.map_panel.calculation.show()
        self.map_box.selected_index = 0
        self.cube_calculation.toggle.value = False
        self.peak_map_status.value = self._peak_map_heading() + (
            '<p><b>Step 2 of 2: compute the spectral map.</b> A saved amplitude set covers every '
            'transition; no new cubes are needed. The spectral blend is selected below at this '
            'peak energy. Review the source plane and observation heights, then click '
            '<b>Review constant-height maps</b> and <b>Compute numerical maps</b>. '
            'Map review verifies access to the full-resolution files before submission.</p>')
