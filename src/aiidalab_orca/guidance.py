"""Compact preparation guidance shared by the state and Kondo panels."""
import ipywidgets as ipw


def kondo_preparation_guide():
    guide = ipw.Accordion(children=[ipw.HTML(
        '<p>For optional CASCI → Dyson → Kondo analysis. CASCI and Dyson results can also be used independently.</p>'
        '<ol><li><b>Choose the molecular state.</b> Review the fixed geometry, common orbitals, '
        'active space and initial spin. A singlet is outside this local-moment model.</li>'
        '<li><b>Complete the charged states.</b> Include electron removal and addition, with '
        'allowed final spins S ± ½. Check CI convergence and exported CI norms before Dyson analysis.</li>'
        '<li><b>Review μ.</b> Keep both charging costs positive. Without a known substrate alignment, '
        'compare several μ values inside the displayed interval.</li>'
        '<li><b>Inspect the channels.</b> Compare results as more charged roots are included. '
        'Nearly degenerate channels should be assessed together.</li>'
        '<li><b>Generate and compare maps.</b> Use the same plane, observation height and colour '
        'scale. Reduced cubes are previews; full cubes supply the numerical maps.</li></ol>'
        '<p><b>If a step stops:</b> open its calculation report. An unavailable SSH connection '
        'does not mean files are deleted. Inspect convergence before requesting another CI run; '
        'do not fix a norm failure by renormalizing or loosening the cutoff.</p>'
        '<p>Individual channel maps describe this molecular exchange model. They do not establish '
        'the surface charge, experimental Kondo brightness, temperature or linewidth. '
        'Adaptive CI retries and a single validation dashboard are still planned.</p>')], selected_index=None)
    guide.set_title(0, 'Quick guide · preparation, checks and recovery')
    return guide


def workflow_guides():
    """Return fresh, packaged operating guidance for the shared AiiDAlab chat."""
    from importlib.resources import files

    return [{
        'id': 'orca.casci-kondo',
        'title': 'ORCA CASCI, Dyson and Kondo validation',
        'topics': ['orca', 'casci', 'casscf', 'dyson', 'kondo', 'qro', 'uno'],
        'source': 'aiidalab_orca/knowledge/casci-kondo.md',
        'text': files('aiidalab_orca').joinpath('knowledge/casci-kondo.md').read_text(),
    }]
