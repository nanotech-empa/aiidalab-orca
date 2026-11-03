"""Display recorded RASSCF energy checks separately from XPS spectra."""
import base64
import html
import json

import ipywidgets as ipw

from . import mr_core_benchmark_services as service


class MultireferenceCoreBenchmarks(ipw.VBox):
    def __init__(self, source_uuid):
        self.source_uuid = str(source_uuid)
        self.table, self.details = ipw.HTML(), ipw.HTML()
        self.refresh = ipw.Button(description='Refresh MR energy checks', icon='refresh',
                                  layout=ipw.Layout(width='auto'))
        self.section = ipw.Accordion(children=[ipw.VBox([self.refresh, self.table, self.details])],
                                     selected_index=None)
        self.section.set_title(0, 'Multireference Co 2p energy checks')
        super().__init__([self.section])
        self.refresh.on_click(self._refresh)
        self._refresh()

    def _refresh(self, event=None):
        self.table.value = ''
        try:
            result = service.records(self.source_uuid)
            rows = result['records']
            self.layout.display = '' if rows or result['diagnostics'] else 'none'
            self.details.value = ''
            if rows:
                self.table.value = (
                    '<p><b>Energy-only, spin-free RASSCF diagnostic.</b> Each energy uses the '
                    'recorded neutral doublet reference and the same fixed geometry. SOC and '
                    'photoionization intensities require separate treatment. The full 480-state '
                    'orbital average is a broad compromise; these checks do not establish the '
                    'physical ground state or a validated XPS spectrum.</p>')
                for record in rows:
                    model = record['model']
                    self.table.value += (
                        '<p><b>' + html.escape(model['cobalt_basis']) + ' (Co) / '
                        + html.escape(model['basis']) + ' (ligands)</b> · '
                        'Co 2p⁵ plus nine electrons in six valence orbitals · '
                        '270 triplets and 210 singlets.</p>'
                        '<table class="table"><thead><tr><th>Spin sector</th>'
                        '<th>Lowest frozen energy (eV)</th><th>Lowest relaxed energy (eV)</th>'
                        '</tr></thead><tbody>'
                        + ''.join('<tr><td>' + ('Singlet' if row['multiplicity'] == 1 else 'Triplet')
                                  + f'</td><td>{row["frozen_binding_energy_ev"]:.2f}</td>'
                                  + f'<td>{row["relaxed_binding_energy_ev"]:.2f}</td></tr>'
                                  for row in record['lowest_spin_free_energies'])
                        + '</tbody></table><p>E − E<sub>neutral doublet</sub>. '
                        'The two minima may have different configuration character.</p>')
                    self.details.value += (
                        f'<p>State-average lowering: {record["state_average_lowering_ev"]:.2f} eV. '
                        f'Final orbital gradient: {record["final_orbital_gradient"]:.2g}. '
                        'Saved-wavefunction readback passed for all 480 states; maximum difference '
                        f'{record["maximum_state_readback_difference_hartree"]:.2g} Hartree.'
                        '<br>Neutral reference <code>' + html.escape(record['reference_uuid'])
                        + '</code><br>Benchmark data <code>' + html.escape(record['data_uuid'])
                        + '</code></p>')
                encoded = base64.b64encode(json.dumps(result, indent=2, allow_nan=False).encode()).decode()
                self.details.value += (
                    '<a download="co-mr-energy-checks.json" href="data:application/json;base64,'
                    + encoded + '">Download MR energy checks and provenance</a>')
            self.details.value += ''.join(
                '<p style="color:#a02020">MR energy check unavailable: ' + html.escape(message) + '</p>'
                for message in result['diagnostics'])
        except Exception as exc:
            self.layout.display = ''
            self.table.value = ''
            self.details.value = '<p>MR energy checks could not be loaded: ' + html.escape(str(exc)) + '</p>'
