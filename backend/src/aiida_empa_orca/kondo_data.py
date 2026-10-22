"""Spin-free exchange eigenchannels, following PRB 110, 165113 (2024), Eqs. 7–8.

The input is the unnormalized highest-Ms Dyson component, not a spin-summed
spectral weight. For either charging direction, conversion of Eq. 8 to this
component gives +1/S for S_final=S-1/2 and -1/(S+1/2) for S_final=S+1/2.
"""
import math

import numpy as np

REFERENCE = 'https://doi.org/10.1103/PhysRevB.110.165113'


def parameters(values, table):
    if set(values) - {'chemical_potential_ev', 'transition_ids'}:
        raise ValueError('Unknown Kondo parameters')
    mu = values.get('chemical_potential_ev', 0.)
    if type(mu) not in (int, float) or not math.isfinite(mu):
        raise ValueError('Specify a finite chemical potential in eV')
    ids = values.get('transition_ids', [r['id'] for r in table['transitions']])
    available = {r['id'] for r in table['transitions']}
    if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or
            any(not isinstance(i, str) for i in ids) or not set(ids) <= available):
        raise ValueError('Select unique existing Dyson transitions')
    return dict(chemical_potential_ev=float(mu), transition_ids=sorted(ids))


def exchange(table, values):
    """Return J/V² (eV⁻¹) and normalized active-space eigenvectors.

    This is a local-moment, equal-hybridization model. It does not estimate
    Kondo temperatures or spectral weights, or replace an NRG calculation.
    """
    p = parameters(values, table)
    if table.get('strength_convention') != 'highest_ms_component':
        raise ValueError('Use raw highest-Ms Dyson components; do not apply spectral spin weights twice')
    initial = table['initial_state']
    mult = initial['multiplicity']
    if type(mult) is not int or mult < 2:
        raise ValueError('The local-moment Kondo model requires S > 0; a singlet needs a different model')
    spin = (mult - 1) / 2
    indices = table['active_space']['orbitals']
    if not indices or len(indices) != len(set(indices)):
        raise ValueError('Missing or duplicate active-orbital indices')
    matrix = np.zeros((len(indices), len(indices)))
    contributions, sectors = [], set()
    lower, upper = -math.inf, math.inf
    for row in table['transitions']:
        if row['id'] not in p['transition_ids']:
            continue
        mf, side = row['final_multiplicity'], row['side']
        if abs(mf - mult) != 1 or side not in ('addition', 'removal'):
            raise ValueError('Single-electron virtual states require ΔS = ±1/2 and N±1')
        dq = row['final_charge'] - initial['charge']
        if dq != (1 if side == 'removal' else -1):
            raise ValueError('Charging direction and charge identity disagree')
        d = np.asarray(row['active_coefficients'], dtype=float)
        if d.shape != (len(indices),) or not np.isfinite(d).all() or row['active_indices'] != indices:
            raise ValueError('Dyson amplitudes must use the same explicit active-orbital basis')
        if not np.isclose(d @ d, row['strength'], rtol=1e-6, atol=1e-9):
            raise ValueError('Raw Dyson norm differs from its active-space amplitudes')
        gap0 = row['energy_ev'] * (-1 if side == 'removal' else 1)
        if not math.isfinite(gap0):
            raise ValueError('Nonfinite charging energy')
        # Paper convention: epsilon_M = E_M + (N_M-N_0) mu.
        gap = gap0 - dq * p['chemical_potential_ev']
        if side == 'removal':
            upper = min(upper, gap0)
        else:
            lower = max(lower, -gap0)
        if gap <= 0:
            raise ValueError(f"Nonpositive charging gap for {row['id']}: {gap:.6g} eV; change the charge reference or chemical potential")
        factor = 1 / spin if mf < mult else -1 / (spin + .5)
        term = factor * np.outer(d, d) / gap
        matrix += term
        sectors.add((side, mf))
        contributions.append(dict(transition_id=row['id'], side=side,
            final_state_uuid=row['final_state_uuid'], final_root=row['final_root'],
            final_multiplicity=mf, charging_gap_ev=gap, component_exchange_factor=factor,
            frobenius_norm_inv_ev=float(np.linalg.norm(term))))
    if {side for side, _ in sectors} != {'addition', 'removal'}:
        raise ValueError('Provide both electron-addition and electron-removal sectors')
    vals, vectors = np.linalg.eigh(matrix)
    order = np.argsort(vals)[::-1]
    vals, vectors = vals[order], vectors[:, order]
    tol = 1e-10 * max(1., float(np.max(np.abs(vals))))
    warnings = ['Only selected computed roots contribute; check convergence against the charged-state manifold.']
    if len(sectors) < 4:
        warnings.append('Some allowed charge/spin sectors are absent; this is a truncated exchange model.')
    if min(c['charging_gap_ev'] for c in contributions) < .1:
        warnings.append('A charging gap is below 0.1 eV; the local-moment perturbative approximation may fail.')
    channels = []
    for i, val in enumerate(vals):
        u = vectors[:, i]
        if u[np.argmax(np.abs(u))] < 0:
            u = -u
        group = [j+1 for j, other in enumerate(vals) if abs(other-val) <= tol]
        channels.append(dict(id=f'ko_{i+1}', index=i, exchange_over_v2_inv_ev=float(val),
            coupling='AFM' if val > tol else 'FM' if val < -tol else 'zero',
            active_coefficients=u.tolist(), degenerate_channels=group))
    if any(len(c['degenerate_channels']) > 1 for c in channels):
        warnings.append('Degenerate eigenchannels have arbitrary individual orbitals; their subspace is the invariant result.')
    return dict(schema_version=1, observable='kondo_channels', reference=REFERENCE,
        initial_state_uuid=table['initial_state_uuid'], initial_state=initial,
        orbital_reference_uuid=table['orbital_reference_uuid'], active_space=table['active_space'],
        parameters=p, exchange_over_v2_inv_ev=matrix.tolist(), channels=channels,
        contributions=contributions, warnings=warnings,
        stability_interval_ev=[lower, upper],
        chemical_potential_convention='epsilon_M = E_M + (N_M-N_0) mu',
        hybridization='equal scalar V for all active orbitals; report J/V^2',
        map_convention='individual normalized eigenchannel |psi(r)|^2; no NRG spectral weight')
