"""Validation for explicitly imported, externally computed frozen orbitals."""
import math
from pathlib import PurePosixPath
import re

import numpy as np

PROCESS = 'aiida.workflows:empa_orca.import_fixed_orbitals'
CALCULATION = 'aiida.calculations:empa_orca.import_fixed_orbitals'
PREPARATION = 'external_frozen_casci_v1'


def checked_manifest(value):
    """Require explicit source identities; paths never come from output text."""
    data = dict(value)
    roles = {'gbw', 'input', 'output'}
    files = data['files']
    if len(files) != 3 or {row['role'] for row in files} != roles:
        raise ValueError('Provide the original GBW, input and output files')
    names = []
    for row in files:
        name = row['name']
        if (not isinstance(name, str) or PurePosixPath(name).name != name or
                name in ('.', '..') or type(row['size_bytes']) is not int or row['size_bytes'] < 1 or
                not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Source files require plain filenames, sizes and SHA256 checksums')
        names.append(name)
    if len(set(names)) != 3:
        raise ValueError('Source filenames must be distinct')
    space = data['active_space']
    if (set(space) != {'electrons', 'orbitals'} or type(space['electrons']) is not int or
            not isinstance(space['orbitals'], list) or not space['orbitals'] or
            any(type(i) is not int or i < 0 for i in space['orbitals']) or
            space['orbitals'] != list(range(space['orbitals'][0], space['orbitals'][-1]+1)) or
            not 0 <= space['electrons'] <= 2*len(space['orbitals'])):
        raise ValueError('Specify the original contiguous frozen CASCI active space')
    energies = data['energies_hartree']
    if (type(data['nroots']) is not int or data['nroots'] < 1 or
            len(energies) != data['nroots'] or any(not math.isfinite(float(e)) for e in energies)):
        raise ValueError('Provide every original CASCI root energy')
    if not isinstance(data['description'], str) or not data['description'].strip():
        raise ValueError('Describe the external calculation and its authorship')
    return data


def check_export(molecule, request):
    """Check geometry, all-electron counting and the actual exported subspace."""
    atoms = molecule['Atoms']
    numbers = request['atomic_numbers']
    settings = request['settings']
    if (molecule['CoordinateUnits'] not in ('Angs', 'Angstrom') or
            [a['ElementNumber'] for a in atoms] != numbers or
            not np.allclose([a['Coords'] for a in atoms], request['positions'], atol=1e-7, rtol=0)):
        raise ValueError('Imported orbitals have a different molecular geometry')
    if molecule['Charge'] != settings['charge'] or molecule['Multiplicity'] != settings['multiplicity']:
        raise ValueError('Imported charge or multiplicity differs from the source identity')
    if any(not a.get('Basis') or a['NuclearCharge'] != a['ElementNumber'] for a in atoms):
        raise ValueError('Import requires explicit all-electron basis shells')
    mos = molecule['MolecularOrbitals']['MOs']
    overlap = np.asarray(molecule['S-Matrix'], dtype=float)
    n = len(mos)
    if (overlap.shape != (n, n) or not np.isfinite(overlap).all() or
            not np.allclose(overlap, overlap.T, atol=1e-10, rtol=0)):
        raise ValueError('Require one spatial MO set with a finite symmetric AO overlap')
    electrons = sum(numbers)-settings['charge']
    if abs(sum(float(row['Occupancy']) for row in mos)-electrons) > 1e-5:
        raise ValueError('Exported occupations do not reproduce the electron count')
    indices = request['manifest']['active_space']['orbitals']
    if indices[-1] >= n or electrons-request['manifest']['active_space']['electrons'] != 2*indices[0]:
        raise ValueError('Frozen active space and inactive electron count disagree')
    c = np.column_stack([mos[i]['MOCoefficients'] for i in indices])
    if c.shape != (n, len(indices)) or not np.isfinite(c).all():
        raise ValueError('Invalid imported active-orbital coefficients')
    error = float(np.max(abs(c.T @ overlap @ c-np.eye(len(indices)))))
    if error > 1e-7:
        raise ValueError('Imported active orbitals are not orthonormal')
    return dict(n_orbitals=n, n_electrons=electrons, active_orthonormality_error=error)
