"""Molecular trajectory and convergence display from serialized results."""

import base64
import html
import io

import ipywidgets as ipw
import matplotlib.pyplot as plt
import nglview as nv
from ase import Atoms


def settings_details(settings, *, single_point=False):
    """Expose the full effective specification, including expert overrides."""
    from aiida_empa_orca.protocols import PROTOCOLS, editable_settings, protocol_overrides, reference, approximation
    s = editable_settings(settings)
    label = PROTOCOLS[s["protocol"]]["label"] if settings.get("schema_version") == 2 else "Legacy geometry settings"
    basis = s["basis"] + (" + element overrides" if s["element_settings"] else "")
    text = f"{s['method']}/{basis} · {reference(s)} · {approximation(s)}"
    changes = protocol_overrides(s)
    if single_point:
        for key in ("optimization", "max_geometry_steps", "constraints"):
            changes.pop(key, None)
    from aiida_empa_orca.constraints import describe_constraints
    constraints = describe_constraints(s.get("constraints", []))
    constraint_text = ("<p><b>Geometry constraints:</b><br>" + "<br>".join(html.escape(c) for c in constraints) + "</p>"
                       if constraints else "<p>Geometry constraints: none.</p>")
    if single_point:
        constraint_text = "<p>Single-point SCF at fixed atomic positions.</p>"
        s = {k: v for k, v in s.items() if k not in ("optimization", "max_geometry_steps")}
    rows = "".join(f"<tr><th style='text-align:left;padding-right:15px'>{html.escape(key.replace('_', ' ').capitalize())}</th><td>{html.escape(str(value))}</td></tr>"
                   for key, value in s.items() if key not in ("schema_version", "protocol", "constraints"))
    return (f"<p><b>{html.escape(text)}</b></p><p>Starting protocol: {html.escape(label)}. "
            f"Changes: {html.escape(', '.join(k.replace('_', ' ') for k in changes) or 'none')}.</p>"
            f"{constraint_text}<details><summary>Effective calculation settings</summary><table>{rows}</table></details>")


def input_details(files, title="Submitted ORCA input"):
    if not files:
        return ""
    entries = []
    for name, content in files.items():
        encoded = base64.b64encode(content.encode()).decode()
        entries.append(f'<h4>{html.escape(name)}</h4><a download="{html.escape(name)}" href="data:text/plain;base64,{encoded}">Download {html.escape(name)}</a>'
                       f"<pre style='max-height:300px;overflow:auto'>{html.escape(content)}</pre>")
    return f"<details><summary>{html.escape(title)}</summary>{''.join(entries)}</details>"


def molecule(symbols, frames):
    trajectory = [Atoms(symbols, positions=positions) for positions in frames]
    view = nv.show_asetraj(trajectory)
    view.clear_representations()
    view.add_ball_and_stick()
    view.background = "#f5f7fa"
    view.layout = ipw.Layout(width="100%", height="360px")
    view.center()
    # A slight camera tilt avoids viewing the NO test molecule end-on along z.
    # This changes only the camera, never the stored coordinates.
    view.control.rotate([0, 0.3826834324, 0, 0.9238795325])
    # NGL already provides playback and a frame slider. Keep a single control.
    view.frame = len(frames)-1
    return view


_RESULT_STYLE = """<style>
.orca-results { width: 100%; min-width: 0; }
.orca-result-context { padding: 12px 16px; background: #f4f8fa; border-left: 4px solid #237b98; margin-bottom: 12px; }
.orca-result-context h3 { margin: 0 0 6px; }
.orca-result-context p { margin: 4px 0; }
.orca-compute-panel { margin: 10px 0; }
.orca-compute-panel > .widget-vbox { padding: 12px; border: 1px solid #dce4e9; background: #fafcfd; }
.orca-notice { padding: 12px 16px; background: #f4f8fa; border-left: 3px solid #9bbcc8; }
.orca-analysis-card { padding: 12px; border: 1px solid #dce4e9; border-radius: 5px; flex: 1 1 240px; min-width: 0; }
.orca-property-tabs > .lm-TabBar .lm-TabBar-tab { min-width: 0; flex: 0 1 auto; }
</style>"""


class ResultsView(ipw.VBox):
    """Independent analysis workspaces sharing one serialized reference."""

    def __init__(self, data):
        from .presentation import LazyTabs
        self.data = data
        s = data['settings']
        self.scf = data.get('single_point', False)
        geometry = ('Geometry optimized with constraints' if data['optimized'] and s.get('constraints') else
                    'Optimized geometry' if data['optimized'] else
                    'Imported fixed-orbital reference' if data.get('imported_reference') else
                    'Single-point SCF · fixed geometry' if self.scf else 'Supplied geometry')
        formula = Atoms(data.get('symbols', [])).get_chemical_formula()
        basis = s['basis'] + (' + element overrides' if s.get('element_settings') else '')
        summary = data.get('summary', {})
        energy = f" · E = {summary['energy_hartree']:.9f} Hartree" if 'energy_hartree' in summary else ''
        context = (f"<div class='orca-result-context'><h3>{html.escape(formula)} · {geometry}</h3>"
                   f"<p><b>Reference:</b> {html.escape(s['method'])}/{html.escape(basis)} · "
                   f"charge {s['charge']:+d} · multiplicity {s['multiplicity']}{energy}</p></div>")
        warnings = ''.join('<p class="orca-notice">'+html.escape(w)+'</p>' for w in data.get('warnings', []))
        self.tabs = LazyTabs([
            ('overview', 'Overview', self._overview),
            ('orbitals', 'Orbitals & density', self._orbitals),
            ('states', 'States & Dyson', self._states),
            ('vibrations', 'Vibrations', self._vibrations),
            ('xps', 'XPS', self._xps),
            ('details', 'Calculation details', self._details),
        ])
        self.tabs.add_class('orca-property-tabs')
        super().__init__([ipw.HTML(_RESULT_STYLE+context+warnings), self.tabs], layout=ipw.Layout(width='100%', min_width='0'))
        self.add_class('orca-results')

    def _overview(self):
        data = self.data
        items = []
        if 'positions' in data:
            items.append(molecule(data['symbols'], data.get('frames', [data['positions']])))
            encoded = base64.b64encode(data['xyz'].encode()).decode()
            items.append(ipw.HTML(f'<a download="geometry.xyz" href="data:text/plain;base64,{encoded}">'
                                  '<i class="fa fa-download"></i> Download final XYZ</a>'))
        if data.get('source_uuid'):
            items.append(ipw.HTML('<p>Reused an available reference. No new ORCA calculation was needed.</p>'))
        if 'spin_squared' in data.get('summary', {}):
            items.append(ipw.HTML(f"<p>Reference ⟨S²⟩ = {data['summary']['spin_squared']:.5f}</p>"))
        cards = []
        for key, title, description, icon in [
            ('orbitals', 'Orbitals & density', 'SCF levels, orbital cubes, spin density and QRO/UNO inspection.', 'cubes'),
            ('states', 'States & Dyson', 'CASCI states on their own, or optional Dyson transitions, spectra and maps.', 'exchange'),
            ('vibrations', 'Vibrations', 'Normal modes, IR and Raman at an optimized geometry.', 'music'),
            ('xps', 'XPS', 'Core binding energies and chemical shifts for selected atoms.', 'bullseye'),
        ]:
            button = ipw.Button(description=title, icon=icon, layout=ipw.Layout(width='auto'))
            button.on_click(lambda _, section=key: self.tabs.show_section(section))
            card = ipw.VBox([button, ipw.HTML('<p>'+description+'</p>')])
            card.add_class('orca-analysis-card')
            cards.append(card)
        items += [ipw.HTML('<h4>Optional analyses</h4>'),
                  ipw.HBox(cards, layout=ipw.Layout(flex_flow='row wrap', gap='10px'))]
        energies = data.get('summary', {}).get('scf_evaluation_energies_hartree', [])
        if data['optimized'] and energies:
            fig, ax = plt.subplots(figsize=(7.4, 2.7))
            ax.plot(range(1, len(energies)+1), [(e-energies[-1])*27.211386245988 for e in energies], 'o-', color='#237b98')
            ax.set(xlabel='SCF evaluation (including final evaluation)', ylabel='E − final E (eV)')
            ax.grid(alpha=.2)
            fig.tight_layout()
            stream = io.BytesIO()
            fig.savefig(stream, format='png', dpi=140)
            plt.close(fig)
            convergence = ipw.Accordion(children=[ipw.Image(value=stream.getvalue(), format='png')], selected_index=None)
            convergence.set_title(0, 'Geometry optimization · energy convergence')
            items.append(convergence)
        return ipw.VBox(items)

    def _orbitals(self):
        if self.data.get('imported_reference'):
            from .orbital_workspace import FixedOrbitalWorkspace
            return FixedOrbitalWorkspace(self.data['uuid'], self._use_window)
        if not self.data.get('levels'):
            return ipw.HTML('<p class="orca-notice">Orbital analysis requires a completed SCF reference.</p>')
        from .orbital_workspace import OrbitalWorkspace
        return OrbitalWorkspace(self.data, self._prepare_common, self._use_window)

    def _states(self):
        if not self.data.get('levels') and not self.data.get('imported_reference'):
            return ipw.HTML('<p class="orca-notice">CASCI requires a completed SCF reference. '
                           'It is optional and is independent of vibrational spectroscopy.</p>')
        from .casci import CasciStates
        return CasciStates(self.data, on_inspect=self._inspect_window)

    def _vibrations(self):
        if not self.data['optimized']:
            return ipw.HTML('<h3>Vibrational spectroscopy</h3><p class="orca-notice">'
                'This draft requires a completed geometry optimization before computing vibrations. '
                'Use the final geometry to prepare an optimization. Orbital analysis and CASCI remain independent.</p>')
        from .vibrations import VibrationalSpectroscopy
        return VibrationalSpectroscopy(self.data['uuid'])

    def _details(self):
        data = self.data
        provenance = '<p>'+html.escape(data['source_description'])+'</p>'
        for label, key in [('Workflow', 'uuid'), ('Source workflow', 'source_uuid'), ('Structure', 'structure_uuid')]:
            if data.get(key):
                provenance += f'<p>{label}: <code>{html.escape(str(data[key]))}</code></p>'
        items = [ipw.HTML('<h3>Calculation details</h3>')]
        if data.get('artifact_status'):
            items.append(ipw.HTML('<p><b>Electronic files:</b> '+html.escape(data['artifact_status'])+'</p>'))
        if data['optimized'] or self.scf:
            items.append(ipw.HTML(settings_details(data['settings'], single_point=self.scf)
                                  + input_details(data.get('input_files', {}))))
        items.append(ipw.HTML('<h4>Provenance and identifiers</h4>'+provenance))
        return ipw.VBox(items)

    def _xps(self):
        if not self.data.get('levels'):
            return ipw.HTML('<p class="orca-notice">XPS requires a completed SCF reference at this geometry.</p>')
        from .xps import XpsSpectroscopy
        return XpsSpectroscopy(self.data['uuid'])

    def _prepare_common(self):
        panel = self.tabs.show_section('states')
        if hasattr(panel, 'calculation'):
            panel.analysis.value = 'states'
            panel.calculation.show()

    def set_active(self, active):
        self.tabs.set_active(active)

    def _inspect_window(self, common_uuid, indices):
        panel = self.tabs.show_section('orbitals')
        if hasattr(panel, 'inspect_reference'):
            panel.inspect_reference(common_uuid, indices)

    def _use_window(self, common_uuid, indices):
        panel = self.tabs.show_section('states')
        if hasattr(panel, '_apply_orbital_window'):
            if common_uuid not in [value for _, value in panel.reference.options]:
                panel._refresh()
            panel.reference.value = common_uuid
            panel._apply_orbital_window(indices)
            panel.analysis.value = 'states'
            panel.calculation.show()


def show_result(data):
    return ResultsView(data)
