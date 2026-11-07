"""Löwdin orbital character from a native ORCA JSON export (CalcJob worker).

The complete AO overlap and MO coefficients stay on the source computer.
Only atom/angular weights and p-shell orientation tensors are retrieved.
"""
import hashlib
import json
from pathlib import Path
import re

import numpy as np

HARTREE_TO_EV = 27.211386245988
ANGULAR = ['s', 'p', 'd', 'f', 'g', 'h', 'i']


def character(document, kind='SCF'):
    molecule = document['Molecule']
    table = molecule['MolecularOrbitals']
    labels, orbitals = table['OrbitalLabels'], table['MOs']
    natoms = len(molecule['Atoms'])
    if molecule.get('NCorelessECP', 0) or any('ECP' in a for a in molecule['Atoms']):
        raise ValueError('ECP orbital character has not been qualified in this draft')
    overlap = np.asarray(molecule['S-Matrix'], dtype=float)
    if overlap.ndim != 2 or overlap.shape[0] != overlap.shape[1] or not np.isfinite(overlap).all():
        raise ValueError('Missing finite full AO overlap matrix')
    nbf = overlap.shape[0]
    if table['EnergyUnit'] != 'Eh' or not 1 <= nbf <= 6000:
        raise ValueError('Unsupported energy units or AO dimension (limit: 6000 AOs)')
    # ORCA 6.1 repeats the same AO-label list for the two UKS spin blocks.
    if len(labels) == 2 * nbf and labels[:nbf] == labels[nbf:]:
        labels = labels[:nbf]
    elif len(labels) != nbf:
        raise ValueError('Native AO labels do not match the overlap basis')
    if np.max(np.abs(overlap - overlap.T)) > 1e-10:
        raise ValueError('The AO overlap matrix is not symmetric')
    eigenvalues, vectors = np.linalg.eigh(overlap)
    if eigenvalues[0] <= 0:
        raise ValueError('Nonpositive overlap eigenvalue; no regularization is applied')
    root = (vectors * np.sqrt(eigenvalues)) @ vectors.T
    del vectors
    parsed, p_shells = [], {}
    for i, label in enumerate(labels):
        match = re.fullmatch(r'\s*(\d+)([A-Z][a-z]?)\s+(\d+)([spdfghi])(.*)', label)
        if not match:
            raise ValueError('Unsupported native AO label: ' + label)
        atom, element, radial, angular, component = match.groups()
        atom = int(atom)
        if atom >= natoms or element != molecule['Atoms'][atom]['ElementLabel']:
            raise ValueError('AO label and native atom identity differ')
        parsed.append((atom, ANGULAR.index(angular)))
        if angular == 'p':
            if component not in ('x', 'y', 'z'):
                raise ValueError('Unsupported real p-orbital convention')
            key = (atom, radial)
            p_shells.setdefault(key, {})[component] = i
    if any(set(shell) != {'x', 'y', 'z'} for shell in p_shells.values()):
        raise ValueError('An incomplete p shell cannot define directional character')
    spatial = kind != 'SCF' or str(molecule['HFTyp']).upper() in ('RHF', 'RKS', 'ROHF', 'ROKS')
    channels = ['spatial'] if spatial else ['alpha', 'beta']
    if len(orbitals) != nbf * len(channels):
        raise ValueError('Unsupported native spin/AO dimensions; refusing to guess the spin ordering')
    weights = np.zeros((len(orbitals), natoms, len(ANGULAR)))
    p_tensor = np.zeros((len(orbitals), natoms, 3, 3))
    spins, indices, occupations, energies, errors = [], [], [], [], []
    for spin, channel in enumerate(channels):
        rows = orbitals[spin * nbf:(spin + 1) * nbf]
        coefficients = np.asarray([row['MOCoefficients'] for row in rows], dtype=float).T
        if coefficients.shape != (nbf, nbf) or not np.isfinite(coefficients).all():
            raise ValueError('Invalid real MO coefficients')
        error = float(np.max(np.abs(coefficients.T @ overlap @ coefficients - np.eye(nbf))))
        if error > 1e-7:
            raise ValueError(f'{channel} MOs fail CᵀSC = I: {error:.3g}')
        errors.append(error)
        orthogonal = root @ coefficients
        offset = spin * nbf
        for ao, (atom, angular) in enumerate(parsed):
            weights[offset:offset + nbf, atom, angular] += orthogonal[ao] ** 2
        for (atom, _), shell in p_shells.items():
            components = orthogonal[[shell[a] for a in ('x', 'y', 'z')]].T
            p_tensor[offset:offset + nbf, atom] += np.einsum('ni,nj->nij', components, components)
        for index, row in enumerate(rows):
            occupation = float(row['Occupancy'])
            if not np.isfinite(occupation) or not -1e-7 <= occupation <= (2 if spatial else 1) + 1e-7:
                raise ValueError('Invalid native orbital occupation')
            occupations.append(occupation)
            spins.append(spin)
            indices.append(index)
            if kind not in ('UNO', 'CASSCF'):
                energies.append(float(row['OrbitalEnergy']) * HARTREE_TO_EV)
    n_electrons = sum(float(a['NuclearCharge']) for a in molecule['Atoms']) - molecule['Charge']
    if abs(sum(occupations) - n_electrons) > 1e-5:
        raise ValueError('Native occupations do not reproduce the electron count')
    if not spatial:
        difference = sum(occupations[:nbf]) - sum(occupations[nbf:])
        if abs(difference - (molecule['Multiplicity'] - 1)) > 1e-5:
            raise ValueError('Native alpha/beta ordering does not reproduce the spin projection')
    if np.max(np.abs(weights.sum(axis=(1, 2)) - 1)) > 2e-7:
        raise ValueError('The complete Löwdin partition does not sum to one per MO')
    arrays = {'weights': weights, 'p_tensor': p_tensor, 'spin': np.asarray(spins),
              'indices': np.asarray(indices), 'occupations': np.asarray(occupations)}
    if energies:
        arrays['energies_ev'] = np.asarray(energies)
    if not all(np.isfinite(value).all() for value in arrays.values()):
        raise ValueError('Nonfinite orbital character data')
    metadata = {'schema': 'orca_orbital_character_v1', 'method': 'symmetric_Loewdin',
                'kind': kind, 'channels': channels, 'angular': ANGULAR, 'n_ao': nbf,
                'n_electrons': n_electrons, 'charge': molecule['Charge'],
                'multiplicity': molecule['Multiplicity'], 'atoms': molecule['Atoms'],
                'coordinate_units': molecule['CoordinateUnits'], 'orthonormality_errors': errors,
                'minimum_overlap_eigenvalue': float(eigenvalues[0]),
                'energy_meaning': ('none' if kind in ('UNO', 'CASSCF') else 'QRO_reference_labels' if kind == 'QRO' else 'SCF_orbital_energies'),
                'p_direction_meaning': 'Perpendicular p contribution only; not a full pi/sigma symmetry classification',
                'orca_version': document.get('ORCA Header', {}).get('Version', '').strip()}
    # Basis primitives are only needed remotely, never in the compact result.
    metadata['atoms'] = [{k: a[k] for k in ('Idx', 'ElementLabel', 'ElementNumber', 'Coords')}
                         for a in metadata['atoms']]
    return metadata, arrays


def main():
    request = json.loads(Path('request.json').read_text())
    with Path('orbitals.gbw').open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    expected = request['file']
    if Path('orbitals.gbw').stat().st_size != expected['size_bytes'] or (
            expected.get('sha256') and digest != expected['sha256']):
        raise ValueError('The staged orbital file differs from its recorded identity')
    path = Path('orbitals.json')
    # Conservative preflight for Python JSON objects plus dense matrix workspaces.
    # This is a software resource guard, not an electronic-structure truncation.
    if path.stat().st_size * 12 > request['memory_kb'] * 1024:
        raise ValueError('The full native export exceeds this analysis memory budget; increase Analysis memory and retry')
    metadata, arrays = character(json.loads(path.read_text()), request['kind'])
    metadata.update(source_sha256=digest, source_filename=expected['name'],
                    source_uuid=request['source_uuid'], structure_uuid=request['structure_uuid'])
    Path('character.json').write_text(json.dumps(metadata, allow_nan=False))
    np.savez_compressed('character.npz', **arrays)
    # Remove only this job's copied GBW and large temporary export.
    Path('orbitals.gbw').unlink()
    Path('orbitals.json').unlink()


if __name__ == '__main__':
    main()
