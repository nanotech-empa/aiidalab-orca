"""Visible analysis entry points without preparing or submitting calculations."""

import ipywidgets as ipw


ANALYSES = {
    'optical': ('Optical excitations · UV–Vis', 'Continue a converged DFT reference at fixed geometry, choose TDA or full TDDFT, then inspect the absorption spectrum and native NTO hole/particle pairs. Each calculation and preview requires review.'),
    'orbitals': ('Orbitals & density', 'Inspect SCF levels, orbital cubes and spin density. QRO/UNO inspection uses a prepared common-orbital reference.'),
    'casci': ('CAS energy levels', 'Inspect and confirm the active space, optionally optimize shared orbitals with CASSCF, then choose ORCA CASCI or quantum-assisted energies. ORCA CASCI requires no separate Hamiltonian export and holds the chosen orbitals fixed.'),
    'correlation': ('Correlation energies · MP2 / NEVPT2 / CASPT2', 'For single-reference correlation, converge a fresh HF reference and compute RI-MP2. For dynamical correlation beyond an active space, select verified CASSCF orbitals and choose SC, FIC or DLPNO-NEVPT2, or CASPT2 with explicit shifts. These energy-only results do not replace Dyson/Kondo state vectors.'),
    'dyson': ('Dyson spectra & maps', 'Use compatible CASCI states for the initial system and its N−1/N+1 electron sectors, then review Dyson transitions. Cubes and maps are separate optional calculations.'),
    'kondo': ('Kondo orbitals & maps', 'Use Dyson transitions for a spin-pure local moment with S > 0, review the charged states and chemical potential, then compute exchange channels and optional maps.'),
    'vibrations': ('IR / Raman', 'Start from a completed geometry optimization, then review the frequency calculation. Electronic-state calculations are independent.'),
}


def goal_path(goal):
    if goal not in ('casci','dyson','kondo'):
        return ''
    path = 'SCF / verified reference → prepared orbitals → inspect / confirm active space → CASCI states'
    if goal in ('dyson','kondo'):
        path += ' → Dyson transitions'
    if goal == 'kondo':
        path += ' → Kondo channels'
    return path


class AnalysisChooser(ipw.VBox):
    def __init__(self, choose):
        self.choice = ipw.Dropdown(description='Calculation goal',
            options=[('Geometry optimization / SCF only', None)] +
                    [(label, key) for key, (label, _) in ANALYSES.items()],
            style={'description_width': 'initial'}, layout=ipw.Layout(width='95%'))
        self.choice.observe(lambda event: choose(event['new']), names='value')
        super().__init__([ipw.HTML('<h3>Start a new calculation</h3><p>Choose your goal, '
            'then prepare the molecule and its SCF reference below. Each later calculation '
            'has its own settings and review.</p>'), self.choice])
