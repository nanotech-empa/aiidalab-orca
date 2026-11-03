"""Explain chemical-potential choices without setting a physical alignment."""
import html
import math


def charging_context(table):
    """Return the lowest computed charging costs at mu=0 as plain values."""
    removal = [-row['energy_ev'] for row in table['transitions'] if row['side'] == 'removal']
    addition = [row['energy_ev'] for row in table['transitions'] if row['side'] == 'addition']
    if not removal or not addition or not all(math.isfinite(value) for value in removal + addition):
        raise ValueError('Both finite electron-removal and electron-addition energies are needed')
    return {'removal_ev': min(removal), 'addition_ev': min(addition)}


def chemical_potential_help(context, mu, error=''):
    """Render a general Au example plus the selected result's charging range."""
    text = (
        '<p><b>Example: Au(111).</b> Taking the vacuum energy as zero, clean Au(111) has '
        'a Fermi level of approximately <b>−5.3 eV</b> (work function ≈ 5.3 eV). '
        'With this app’s convention ε = E + (N−N₀)μ, a simple vacuum-aligned '
        'metal-reservoir estimate therefore uses <b>μ ≈ +5.3 eV</b>.</p>'
        '<p>This is a starting estimate: adsorption, interface dipoles and substrate screening '
        'change the molecular charging energies. For an exploratory sensitivity check, one '
        'could compare <b>μ = 3, 4 and 5 eV</b> and the bare-Au <b>5.3 eV</b> estimate, '
        '<b>using only values inside the charging range below</b>. '
        'These are examples, not a universal Au setting. The Kondo-model paper uses molecule-dependent '
        'effective μ values (3, 4, 5 and 4.3 eV), adjusted with the hybridization to describe experiment. '
        'An unaligned DFT Fermi-energy output cannot be entered directly.</p>'
        '<p><a href="https://pubs.acs.org/doi/10.1021/acs.langmuir.3c00572" '
        'target="_blank" rel="noopener noreferrer">Au(111) work-function example</a> · '
        '<a href="https://arxiv.org/html/2405.15958v2" target="_blank" '
        'rel="noopener noreferrer">Kondo model and μ choices, Sections II.4 and IV</a>.</p>')
    if context is None:
        return text + '<p>Could not read the selected charging range: ' + html.escape(error) + '. Review the source result before choosing μ.</p>'
    lower, upper = -context['addition_ev'], context['removal_ev']
    text += (f'<p><b>Selected computed states: {lower:.3f} &lt; μ &lt; {upper:.3f} eV.</b> '
        'Both charging costs must be positive. This interval covers the supplied roots, '
        'not uncomputed charge states or a fitted substrate alignment.</p>')
    examples = [value for value in (3., 4., 5., 5.3) if lower < value < upper]
    if examples:
        text += '<p>Illustrative values inside <b>this</b> range: ' + ', '.join(f'+{value:g}' for value in examples) + ' eV.</p>'
    if lower >= upper:
        return text + '<p><b>No μ makes both supplied charging costs positive. Review the molecular charge and source states.</b></p>'
    if not math.isfinite(mu):
        return text + '<p>Enter a finite μ in eV.</p>'
    removal, addition = upper - mu, mu - lower
    text += (f'<p>At the entered <b>μ = {mu:g} eV</b>: minimum removal cost '
        f'<b>{removal:.3f} eV</b>; minimum addition cost <b>{addition:.3f} eV</b>. ')
    if min(removal, addition) <= 0:
        text += '<b>This μ is outside the allowed range; change it before computing.</b> '
    elif min(removal, addition) < .1:
        text += '<b>A charging cost is below 0.1 eV; the local-moment approximation may fail.</b> '
    text += 'Stay away from a charging boundary: positive costs alone do not establish that virtual-charge perturbation theory is valid.</p>'
    if not lower < 5.3 < upper:
        text += '<p>The +5.3 eV bare-Au example is outside this result’s charging range; do not use it for these selected states.</p>'
    return text
