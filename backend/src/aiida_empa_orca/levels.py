"""Orbital energies and occupations from the final printed ORCA orbital table."""

import math
import re


def orbital_levels(text, expected_nmo=None):
    """Preserve ORCA's zero-based indices and occupations, including open shells."""
    table = text.rsplit('ORBITAL ENERGIES', 1)[-1] if 'ORBITAL ENERGIES' in text else ''
    channels, spin, started = [[]], 0, False
    for line in table.splitlines():
        if 'SPIN UP ORBITALS' in line:
            continue
        if 'SPIN DOWN ORBITALS' in line:
            channels.append([])
            spin = 1
            continue
        match = re.fullmatch(r'\s*(\d+)\s+([\d.]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*', line)
        if match:
            index, occupation, hartree, ev = match.groups()
            values = [float(occupation), float(hartree), float(ev)]
            if not all(math.isfinite(v) for v in values):
                raise ValueError('Non-finite orbital level')
            channels[spin].append({'index': int(index), 'spin': spin,
                                   'occupation': values[0], 'energy_ev': values[2]})
            started = True
        elif started and ('POPULATION ANALYSIS' in line or line.strip().startswith('*Only')):
            break
    if not channels[0] or any(not c for c in channels):
        raise ValueError('No complete orbital table in the stored ORCA output')
    for channel in channels:
        if [v['index'] for v in channel] != list(range(len(channel))):
            raise ValueError('Orbital indices in the printed table are not consecutive')
    occupied = [v['energy_ev'] for c in channels for v in c if v['occupation'] > 1e-6]
    vacant = [v['energy_ev'] for c in channels for v in c if v['occupation'] < (1 if len(channels) == 2 else 2)-1e-6]
    if not occupied or not vacant:
        raise ValueError('Occupied and unoccupied levels are needed to define HOMO and LUMO')
    homo, lumo = max(occupied), min(vacant)
    return {'channels': channels, 'homo_ev': homo, 'lumo_ev': lumo,
            'default_range_ev': [homo-1, lumo+1], 'energy_unit': 'eV',
            'complete': bool(expected_nmo and all(len(c) == expected_nmo for c in channels)),
            'spin_polarized': len(channels) == 2}


def visible_groups(channel, lower, upper, height=340, linewidth=3):
    """Group overlapping bars in vertical display pixels, independently per spin."""
    if not all(math.isfinite(v) for v in (lower, upper)) or upper <= lower:
        raise ValueError('The upper energy must be greater than the lower energy')
    tolerance = (upper-lower)*linewidth/height
    groups = []
    for level in sorted((v for v in channel if lower <= v['energy_ev'] <= upper), key=lambda v: v['energy_ev']):
        if not groups or level['energy_ev']-groups[-1][-1]['energy_ev'] > tolerance:
            groups.append([])
        groups[-1].append(level)
    return groups
