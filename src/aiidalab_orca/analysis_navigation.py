"""Visible analysis entry points without preparing or submitting calculations."""

import ipywidgets as ipw


ANALYSES = {
    'orbitals': ('Orbitals & density', 'Inspect SCF levels, orbital cubes and spin density. QRO/UNO inspection uses a prepared common-orbital reference.'),
    'casci': ('CASCI states', 'Prepare common spatial orbitals, choose the active space, then review charge/spin sectors and roots. CASCI holds the orbitals fixed; it does not optimize them as CASSCF would.'),
    'dyson': ('Dyson spectra & maps', 'Use compatible CASCI states for the initial system and its N−1/N+1 electron sectors, then review Dyson transitions. Cubes and maps are separate optional calculations.'),
    'kondo': ('Kondo orbitals & maps', 'Use Dyson transitions for a spin-pure local moment with S > 0, review the charged states and chemical potential, then compute exchange channels and optional maps.'),
    'vibrations': ('IR / Raman', 'Start from a completed geometry optimization, then review the frequency calculation. Electronic-state calculations are independent.'),
}


class AnalysisChooser(ipw.VBox):
    def __init__(self, choose, *, select_reference=False):
        self.buttons = {}
        for key, (label, help_text) in ANALYSES.items():
            button = ipw.Button(description=label, tooltip=help_text,
                                layout=ipw.Layout(width='auto', margin='2px 6px 2px 0'))
            button.on_click(lambda _, task=key: choose(task))
            self.buttons[key] = button
        text = ('<h3>Other calculations</h3><p>Use the form below for geometry optimization or SCF. '
                'For another analysis, choose it here, then select a completed reference in '
                '<b>Search calculations</b>. Existing results can be reused.</p>' if select_reference else
                '<h4>Choose an analysis</h4><p>Open saved results or review a new calculation for this reference. '
                'Opening a workspace does not submit a calculation.</p>')
        super().__init__([ipw.HTML(text), ipw.HBox(list(self.buttons.values()),
            layout=ipw.Layout(flex_flow='row wrap'))])
