"""Molecular trajectory and convergence display from serialized results."""

import base64
import html
import io

import ipywidgets as ipw
import matplotlib.pyplot as plt
import nglview as nv
from ase import Atoms

from .analysis_navigation import ANALYSES, goal_path


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
        from .presentation import LazyStack
        self.data = data
        self.confirmed_space = None
        self._selection_reference = None
        self._preparation_button = None
        self._preparation_status = None
        s = data['settings']
        self.scf = data.get('single_point', False)
        geometry = ('Geometry optimized with constraints' if data['optimized'] and s.get('constraints') else
                    'Optimized geometry' if data['optimized'] else
                    'Single-point SCF · fixed geometry' if self.scf else 'Supplied geometry')
        formula = Atoms(data.get('symbols', [])).get_chemical_formula()
        basis = s['basis'] + (' + element overrides' if s.get('element_settings') else '')
        summary = data.get('summary', {})
        energy = f" · E = {summary['energy_hartree']:.9f} Hartree" if 'energy_hartree' in summary else ''
        context = (f"<div class='orca-result-context'><h3>{html.escape(formula)} · {geometry}</h3>"
                   f"<p><b>Reference:</b> {html.escape(s['method'])}/{html.escape(basis)} · "
                   f"charge {s['charge']:+d} · multiplicity {s['multiplicity']}{energy}</p></div>")
        warnings = ''.join('<p class="orca-notice">'+html.escape(w)+'</p>' for w in data.get('warnings', []))
        self.tabs = LazyStack([
            ('overview', 'Overview', self._overview),
            ('orbitals', 'Orbitals & density', self._orbitals),
            ('active', 'Inspect orbitals / active space', self._active_space),
            ('states', 'CASCI, Dyson & Kondo', self._states),
            ('vibrations', 'Vibrations', self._vibrations),
            ('details', 'Calculation details', self._details),
        ])
        self.tabs.add_class('orca-workspace-body')
        views = [('Overview', 'overview'), ('Orbitals & density', 'orbitals'),
                 ('1. Prepare orbital reference', 'prepare'), ('2. Inspect / confirm active space', 'active'),
                 ('3. CASCI states and multiplicities', 'casci'), ('4. Dyson spectrum', 'dyson'),
                 ('Dyson orbitals & maps', 'maps'), ('5. Kondo orbitals & maps', 'kondo')]
        views += [(title, key) for key, title in zip(self.tabs.section_keys, self.tabs.titles)
                  if key not in ('overview', 'orbitals', 'active', 'states')]
        self.navigation = ipw.Dropdown(description='Analysis / results', options=views,
            style={'description_width': 'initial'}, layout=ipw.Layout(width='95%'))
        self._navigating = False
        self.navigation.observe(self._navigate, names='value')
        self.goal = data.get('requested_analysis')
        self.continue_goal = ipw.Button(description='Continue to '+ANALYSES[self.goal][0] if self.goal else '',
            icon='arrow-right', layout=ipw.Layout(width='auto', display='none'))
        self.continue_goal.on_click(lambda _: self.open_goal(self.goal) if self.goal else None)
        goal_text = '<p><b>Calculation goal:</b> '+html.escape(ANALYSES[self.goal][0])+'</p>' if self.goal else ''
        if self.goal in ('casci','dyson','kondo'):
            goal_text += '<p><b>Your path:</b> '+goal_path(self.goal)+'. Each calculation is reviewed and submitted separately.</p>'
        self.goal_hint = ipw.VBox([ipw.HTML(goal_text), self.continue_goal],
                                  layout=ipw.Layout(display='' if self.goal else 'none'))
        self.analysis_hint = ipw.HTML(layout=ipw.Layout(display='none'))
        self.prerequisites = ipw.VBox(layout=ipw.Layout(display='none'))
        super().__init__([ipw.HTML(_RESULT_STYLE+context+warnings), self.goal_hint, self.navigation,
                          self.analysis_hint, self.prerequisites, self.tabs], layout=ipw.Layout(width='100%', min_width='0'))
        self.add_class('orca-results')

    def _navigate(self, event):
        if not self._navigating:
            self.open_analysis(event['new'])

    def _sync_state_navigation(self, event):
        key = {'states': 'casci', 'spectrum': 'dyson'}.get(event['new'], event['new'])
        if not self._navigating:
            self.open_analysis(key)

    def _space_signature(self, panel):
        return (panel.reference.value,panel.electrons.value,panel.norb.value)

    def _space_ready(self, panel):
        return bool(panel._datasets) or self.confirmed_space == self._space_signature(panel)

    def open_goal(self, goal):
        if goal not in ('casci','dyson','kondo'):
            return self.open_analysis(goal)
        self._navigating = True
        try:
            panel = self.tabs.show_section('states')
        finally:
            self._navigating = False
        if not hasattr(panel,'analysis'):
            return self.open_analysis('prepare')
        if not panel.reference.value:
            return self.open_analysis('prepare')
        if not self._space_ready(panel):
            return self.open_analysis('active')
        if not panel._datasets:
            return self.open_analysis('casci')
        return self.open_analysis(goal)

    def _require(self, panel, message, task, label):
        panel.layout.display = 'none'
        self._preparation_button = None
        self._preparation_status = None
        old = self.prerequisites.children
        button = ipw.Button(description=label, icon='arrow-right', layout=ipw.Layout(width='auto'))
        button.on_click(lambda _: self.open_analysis(task))
        self.prerequisites.children = [ipw.HTML('<p class="orca-notice">'+message+'</p>'), button]
        self.prerequisites.layout.display = ''
        for widget in old:
            widget.close()

    def open_analysis(self, task):
        self._navigating = True
        try:
            self.prerequisites.layout.display = 'none'
            for panel in self.tabs.panels.values():
                panel.layout.display = ''
            if task in dict(self.navigation.options).values():
                self.navigation.value = task
            self.continue_goal.layout.display = '' if self.goal and task != self.goal else 'none'
            if task in ('overview', 'details'):
                self.analysis_hint.layout.display = 'none'
                return self.tabs.show_section(task)
            labels = {key: title for title, key in self.navigation.options}
            stage_help = {
                'prepare': ('Prepare the orbital reference', 'Start from the saved SCF wavefunction. Restricted orbitals are retained; unrestricted references produce QROs for CASCI and UNOs for inspection. Imported verified references can be reused.'),
                'active': ('Inspect and confirm the active space', 'Read orbital information, inspect occupations and shapes, then explicitly choose the active electrons and orbitals. State counts and multiplicities come after this choice.'),
            }
            label, help_text = stage_help.get(task,ANALYSES.get(task, ANALYSES['dyson'] if task == 'maps' else (labels.get(task, task), '')))
            self.analysis_hint.value = f'<p><b>{html.escape(label)}:</b> {html.escape(help_text)}</p>'
            self.analysis_hint.layout.display = ''
            if task in self.tabs.section_keys and task not in ('states','active'):
                return self.tabs.show_section(task)
            panel = self.tabs.show_section('states')
            if not hasattr(panel, 'analysis'):
                return panel
            if task in dict(self.navigation.options).values():
                self.navigation.value = task
            if task == 'prepare':
                panel.set_stage('prepare')
                self._require_next_preparation(panel)
                return panel
            if task in ('active','casci','dyson','maps','kondo') and not panel.reference.value:
                self._require(panel, 'First prepare an orbital reference from the saved SCF wavefunction.',
                              'prepare','Prepare orbital reference')
                return panel
            if task == 'active':
                self._refresh_selection(panel)
                return self.tabs.show_section('active')
            if task == 'casci' and not self._space_ready(panel):
                self._require(panel, 'Inspect the orbitals and confirm the active space before choosing multiplicities and electronic states.',
                              'active','Inspect and choose active orbitals')
                return panel
            mode = {'casci': 'states', 'dyson': 'spectrum'}.get(task, task)
            if hasattr(panel,'set_stage'):
                panel.set_stage('states' if task in ('casci','dyson','maps','kondo') else 'legacy')
            if task in ('dyson', 'maps', 'kondo') and (not panel.reference.value or not panel._datasets):
                target = 'casci' if self._space_ready(panel) else 'active'
                self._require(panel, 'This analysis needs compatible CASCI states first. '
                    'Use the prepared orbital reference and explicitly selected active space for the required charge/spin sectors.',
                    target,'Compute CASCI states' if target == 'casci' else 'Inspect and choose active orbitals')
                return panel
            panel.analysis.value = mode
            if task == 'casci' and (not panel.reference.value or not panel._datasets):
                panel.calculation.show()
            elif task in ('maps', 'kondo') and panel._dyson and not panel._dyson.record:
                self._require(panel, 'This analysis needs computed Dyson transitions first.',
                              'dyson', 'Compute Dyson transitions')
            elif task == 'dyson' and panel._dyson and not panel._dyson.record:
                panel._dyson.calculation.show()
            return panel
        finally:
            self._navigating = False

    def _require_next_preparation(self, panel):
        button = ipw.Button(description='View orbitals and choose active space',icon='eye',button_style='primary',
                            disabled=not bool(panel.reference.value),layout=ipw.Layout(width='auto'))
        button.on_click(lambda _: self.open_analysis('active'))
        old = (*self.prerequisites.children,*panel.preparation_actions.children)
        self.prerequisites.children = ()
        self.prerequisites.layout.display = 'none'
        self._preparation_status = ipw.HTML()
        panel.preparation_actions.children = [self._preparation_status,button]
        self._preparation_button = button
        self._prepared_reference_changed({'new':panel.reference.value})
        for widget in old:
            widget.close()

    def _prepared_reference_changed(self, event):
        if self._preparation_button is not None:
            self._preparation_button.disabled = not bool(event['new'])
        if self._preparation_status is not None:
            self._preparation_status.value = ('<p><b>Prepared orbital reference selected.</b> Continue below to list '
                'the orbitals and generate their 3D previews.</p>' if event['new'] else
                '<p>Prepare or select an orbital reference to continue to visualization.</p>')

    def _refresh_selection(self, panel):
        if self._selection_reference == panel.reference.value:
            return
        old = self.tabs.panels.pop('active',None)
        if old:
            from .app import close_widget_tree
            close_widget_tree(old)
        self._selection_reference = str(panel.reference.value)

    def _active_space(self):
        from .active_space_step import ActiveSpaceStep
        panel = self.tabs.panels['states']
        return ActiveSpaceStep(panel.reference.value,panel.electrons.value,panel.norb.value,self._confirm_space)

    def _confirm_space(self, common_uuid, space):
        panel = self.tabs.show_section('states')
        if str(panel.reference.value) != str(common_uuid):
            raise ValueError('The orbital reference changed; inspect the selected reference again.')
        panel._apply_orbital_window(space['orbitals'])
        self.confirmed_space = self._space_signature(panel)
        self.open_analysis('casci')

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
        items.append(ipw.HTML('<p>Use <b>Analysis / results</b> above to inspect orbitals, '
            'prepare CASCI states, compute Dyson or Kondo properties, or open vibrational spectroscopy. '
            'Each view explains its prerequisites and offers its own calculation review.</p>'))
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
        if not self.data.get('levels'):
            return ipw.HTML('<p class="orca-notice">Orbital analysis requires a completed SCF reference.</p>')
        from .orbital_workspace import OrbitalWorkspace
        return OrbitalWorkspace(self.data, self._prepare_common, self._use_window)

    def _states(self):
        if not self.data.get('levels'):
            return ipw.HTML('<p class="orca-notice">CASCI requires a completed SCF reference. '
                           'It is optional and is independent of vibrational spectroscopy.</p>')
        from .casci import CasciStates
        panel = CasciStates(self.data, on_inspect=self._inspect_window)
        panel.analysis.layout.display = 'none'
        modes = {value for _, value in self.navigation.options}
        extras = [(label, key) for label, key in panel.analysis.options
                  if key not in ('states', 'spectrum', 'maps', 'kondo') and key not in modes]
        if extras:
            self.navigation.options = (*self.navigation.options, *extras)
        panel.analysis.observe(self._sync_state_navigation, names='value')
        panel.reference.observe(self._prepared_reference_changed,names='value')
        return panel

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

    def _prepare_common(self):
        self.open_analysis('prepare')

    def set_active(self, active):
        self.tabs.set_active(active)

    def _inspect_window(self, common_uuid, indices):
        self.open_analysis('active')

    def _use_window(self, common_uuid, indices):
        panel = self.tabs.show_section('states')
        if hasattr(panel, '_apply_orbital_window'):
            if common_uuid not in [value for _, value in panel.reference.options]:
                panel._refresh()
            panel.reference.value = common_uuid
            panel._apply_orbital_window(indices)
            self.confirmed_space = self._space_signature(panel)
            self.open_analysis('casci')


def show_result(data):
    return ResultsView(data)
