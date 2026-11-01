"""Standard-library native XPS checks shared by the CalcJob and its finalizer."""

import math
import re

ENERGY_TOLERANCE = 1e-7
SPIN_TOLERANCE = 1e-5
HARTREE_TO_EV = 27.211386245988
GRADIENT_TARGETS = {'TightSCF': 1e-5, 'VeryTightSCF': 2e-6, 'ExtremeSCF': 1e-9}


def _orbital_readers():
    if __package__:
        from .core_orbitals import levels, populations
        return levels, populations
    import runpy
    from pathlib import Path
    helpers = runpy.run_path(str(Path(__file__).with_name('core_orbitals.py')))
    return helpers['levels'], helpers['populations']


def density_summary(text, *, require_scf=True, strict=False):
    states = re.findall(r'SCF (?:CONVERGED AFTER|NOT CONVERGED)', text)
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('Native ORCA did not terminate normally')
    if require_scf:
        if not states or states[-1] != 'SCF CONVERGED AFTER':
            raise ValueError('SCF convergence was not confirmed')
    elif ('MaxIter==0 has been chosen - skipping the SCF' not in text
          or states or not re.search(r'\bCalcGuessEnergy\b', text, re.I)):
        raise ValueError('Readback must evaluate the input density with NoIter CalcGuessEnergy')
    if strict:
        if 'POORLY NORMALIZED MO DETECTED' in text:
            raise ValueError('Poorly normalized orbitals; no XPS energy accepted')
        for marker in ('Input Geometry matches current geometry', 'Input basis set matches current basis set'):
            if marker not in text:
                raise ValueError('Core-hole geometry/basis mismatch')
        if 'Using GuessMode=CMatrix' in text:
            raise ValueError('CMatrix projected the individual core orbitals')
    energies = re.findall(r'FINAL SINGLE POINT ENERGY\s+([-+\d.Ee]+)', text)
    energy = float(energies[-1]) if energies else float('nan')
    if not math.isfinite(energy):
        raise ValueError('No finite final single-point energy')
    result = {'energy_hartree': energy}
    spins = re.findall(r'Expectation value of <S\*\*2>\s*:?\s*([-+\d.Ee]+)', text)
    if spins:
        result['spin_squared'] = float(spins[-1])
    return result


def gradient_check(text, expected_tolerance):
    values = re.findall(
        r'Last Orbital Gradient\s+\.\.\.\s+([-+\d.Ee]+)\s+Tolerance\s*:\s*([-+\d.Ee]+)', text)
    if not values:
        raise ValueError('Missing final native orbital-gradient report')
    gradient, tolerance = map(float, values[-1])
    if (not all(math.isfinite(v) for v in (gradient, tolerance)) or tolerance <= 0
            or abs(gradient) > tolerance or tolerance > expected_tolerance*(1+1e-5)):
        raise ValueError('The final orbital gradient did not satisfy the requested tolerance')
    return {'maximum_orbital_gradient': gradient, 'tolerance': tolerance,
            'criterion': 'Native maximum-gradient criterion; other density criteria are reported independently.'}


def parse_spin_density(text, core_reference, atom_index, electron_count, ground_energy,
                       initial_multiplicity, spin_channel, *, require_scf=True, strict=False):
    summary = density_summary(text, require_scf=require_scf, strict=strict)
    levels, populations = _orbital_readers()
    channels = levels(text)
    if len(channels) != 2:
        raise ValueError('Core ionization requires both spin channels')
    counts = [sum(r['occupation'] for r in c) for c in channels]
    difference = initial_multiplicity-1 + (-1 if spin_channel == 'alpha' else 1)
    if abs(sum(counts)-electron_count+1) > 1e-6 or abs(counts[0]-counts[1]-difference) > 1e-6:
        raise ValueError('The final electron counts do not match the requested spin ionization')
    holes = [(spin, row) for spin, channel in enumerate(channels) for row in channel
             if row['energy_hartree'] < -5 and row['occupation'] < .01]
    if len(holes) != 1:
        raise ValueError('Exactly one deep-core hole must survive orbital relaxation')
    spin, hole = holes[0]
    if spin != (0 if spin_channel == 'alpha' else 1):
        raise ValueError('The core hole moved to another spin channel')
    # Bound the atomic table before an optional angular table. Its labels (s,
    # p, ...) are not floating-point atomic populations.
    atomic_text = text.split('MULLIKEN REDUCED ORBITAL POPULATIONS PER MO', 1)[0]
    tables = populations(atomic_text, len(core_reference['assignments'][0]['atomic_populations']), method='MULLIKEN')
    if len(tables) != 2:
        raise ValueError('Both native spin-resolved MO population tables are required')
    values = tables[spin][hole['index']]
    if max(range(len(values)), key=values.__getitem__) != atom_index or values[atom_index] < .95:
        raise ValueError('The final core hole is not localized on the selected atom')
    if strict:
        # Atom identity alone would accept a collapsed Co 2p vacancy as Co 1s.
        # Use the final canonical spectrum, not the inherited energy labels
        # of localized input orbitals. Compare only the hole's spin channel.
        target_core = [row for row in channels[spin] if row['energy_hartree'] < -5
                       and tables[spin][row['index']][atom_index] >= .95]
        if min(target_core, key=lambda row: row['energy_hartree'])['index'] != hole['index']:
            raise ValueError('The requested 1s hole collapsed into another shell on the selected atom')
    s2 = summary.get('spin_squared')
    binding = (summary['energy_hartree']-ground_energy)*HARTREE_TO_EV
    if s2 is None or not math.isfinite(s2) or not math.isfinite(binding) or binding <= 0:
        raise ValueError('Invalid energy or missing spin diagnostic')
    branch = ('broken_symmetry_ms0' if spin_channel == 'alpha' else 'triplet_ms1') if initial_multiplicity == 2 else 'doublet'
    ideal = 2 if branch == 'triplet_ms1' else .75 if branch == 'doublet' else None
    return {'schema_version': 2, 'atom_index': atom_index, 'shell': '1s', 'spin_channel': spin_channel,
        'ground_energy_hartree': ground_energy, 'ionized_energy_hartree': summary['energy_hartree'],
        'binding_energy_ev': binding, 'initial_multiplicity': initial_multiplicity,
        'final_multiplicity': abs(difference)+1, 'spin_projection': difference/2, 'spin_assignment': branch,
        'electron_counts': counts, 'spin_squared': s2, 'hole_spin_channel': spin,
        'hole_orbital_index': hole['index'], 'hole_population': values[atom_index],
        'hole_population_method': 'ORCA Mulliken atomic population per MO', 'localization': core_reference['method'],
        'energy_reference': 'isolated molecule, vertical removal to vacuum',
        'warnings': ['High-spin UKS diagnostic differs appreciably from its target.'] if ideal is not None and abs(s2-ideal)>.1 else []}


def validate_stage(text, request, role):
    result = parse_spin_density(text, request['core_reference'], request['atom_index'],
        request['electron_count'], request['ground_energy_hartree'], 2, request['spin_channel'],
        require_scf=role != 'readback', strict=True)
    if role != 'readback':
        target = GRADIENT_TARGETS[request['scf_convergence']]
        if role == 'refinement':
            target = min(target, 1e-6)
        result['convergence'] = gradient_check(text, target)
    if role == 'preparation' and request['solver'] == 'freeze_release':
        marker = f'*** Constraining orbitals in {request["spin_channel"]} spin channel ***'
        if (marker not in text or 'No orbitals to constrain!' in text
                or '*** Unconstraining orbitals ***' not in text):
            raise ValueError('Freeze-and-release did not activate and release the requested orbitals')
    return result


def validate_bundle(preparation, refinement, readback, request):
    first = validate_stage(preparation, request, 'preparation')
    final = validate_stage(refinement, request, 'refinement')
    check = validate_stage(readback, request, 'readback')
    delta = check['ionized_energy_hartree']-final['ionized_energy_hartree']
    if abs(delta) > ENERGY_TOLERANCE:
        raise ValueError(f'Stored wavefunction changed energy by {delta:.9g} Hartree; no XPS result accepted')
    if (check['electron_counts'] != final['electron_counts']
            or abs(check['spin_squared']-final['spin_squared']) > SPIN_TOLERANCE):
        raise ValueError('Stored wavefunction changed the core-ion spin state')
    final['validation'] = {
        'contract': 'uks_1s_wavefunction_v1', 'solver': request['solver'],
        'preparation_energy_hartree': first['ionized_energy_hartree'],
        'preparation_convergence': first['convergence'],
        'readback_energy_hartree': check['ionized_energy_hartree'],
        'readback_energy_difference_hartree': delta, 'energy_tolerance_hartree': ENERGY_TOLERANCE,
        'readback_spin_squared': check['spin_squared'], 'readback_hole_population': check['hole_population'],
        'normalization_warnings': False,
    }
    return final
