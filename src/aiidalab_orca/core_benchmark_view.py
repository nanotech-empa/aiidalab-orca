"""Energy-only diagnostics, kept separate from the Co multiplet spectrum."""
import base64
import html
import json

import ipywidgets as ipw

from . import core_benchmark_services as service


class ScalarCoreBenchmarks(ipw.VBox):
    def __init__(self, source_uuid):
        self.source_uuid = str(source_uuid)
        self.table, self.details = ipw.HTML(), ipw.HTML()
        self.refresh = ipw.Button(description='Refresh energy checks', icon='refresh', layout=ipw.Layout(width='auto'))
        self.section = ipw.Accordion(children=[ipw.VBox([self.refresh, self.table, self.details])], selected_index=None)
        self.section.set_title(0, 'Scalar Co 2p energy checks')
        super().__init__([self.section])
        self.refresh.on_click(self._refresh)
        self._refresh()

    def _refresh(self, event=None):
        try:
            result = service.records(self.source_uuid)
            rows = result['records']
            self.layout.display = '' if rows or result['diagnostics'] else 'none'
            self.table.value = ('<p>Energy-only diagnostics for a single M<sub>S</sub>=1 core-hole determinant. '
                'The DFT model has its own basis and scalar-relativistic Hamiltonian. Spin purity and SOC multiplets '
                'require separate treatment; this relaxation lowering does not calibrate the frozen RAS-CI spectrum.</p>'
                '<table class="table"><thead><tr><th>Frozen (eV)</th><th>Relaxed (eV)</th>'
                '<th>Relaxation lowering (eV)</th><th>QE scalar (eV)</th><th>Final S²</th></tr></thead><tbody>' +
                ''.join(f'<tr><td>{r["frozen_binding_energy_ev"]:.2f}</td><td>{r["relaxed_binding_energy_ev"]:.2f}</td>'
                        f'<td>{r["core_relaxation_lowering_ev"]:.2f}</td><td>{r["qe_scalar_binding_energy_ev"]:.2f}</td>'
                        f'<td>{r["final_spin_squared"]:.4f}</td></tr>' for r in rows) + '</tbody></table>') if rows else ''
            self.details.value = ''.join(
                '<p><b>' + html.escape(r['model']) + '</b><br>Saved-wavefunction readback passed: '
                f'{r["readback_energy_difference_hartree"]:.2g} Hartree; final gradient {r["final_gradient"]:.2g}.'
                '<br>Reference <code>' + html.escape(r['reference_uuid']) + '</code><br>Benchmark data <code>' +
                html.escape(r['data_uuid']) + '</code></p>' for r in rows)
            self.details.value += ''.join('<p style="color:#a02020">Energy check unavailable: ' +
                                         html.escape(message) + '</p>' for message in result['diagnostics'])
            if rows:
                encoded = base64.b64encode(json.dumps(result, indent=2, allow_nan=False).encode()).decode()
                self.details.value += f'<a download="co-scalar-energy-checks.json" href="data:application/json;base64,{encoded}">Download energy checks and provenance</a>'
        except Exception as exc:
            self.layout.display = ''
            self.table.value = ''
            self.details.value = '<p>Energy checks could not be loaded: ' + html.escape(str(exc)) + '</p>'
