"""Explicit noncontiguous-CAS planning and signed MO-table checks.

This is a preparation primitive, not a new accepted orbital-reference type.
It performs no file I/O, native execution, state-vector transformation or ORM
mutation. Activation requires a separately qualified CalcJob/WorkChain adapter.
"""

from copy import deepcopy
import hashlib
import json
import re
from uuid import UUID

import numpy as np

SCHEMA = 'orca_orbital_reordering/v1'
OCCUPATION_TOLERANCE = 1e-8
DATA_TOLERANCE = 1e-10
ORTHONORMALITY_TOLERANCE = 1e-7
_SPATIAL_CONTAINERS = {'RHF', 'RKS', 'ROHF', 'ROKS'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _real_array(value, label):
    raw = np.asarray(value)
    if raw.dtype.kind not in 'iuf':
        raise ValueError(label + ' must contain real numbers')
    array = raw.astype(float)
    if not np.isfinite(array).all():
        raise ValueError(label + ' must be finite')
    return array


def selection_plan(reference, space, occupations, *, source_reference_uuid, source_file_sha256):
    """Partition source MOs, preserving the user's explicit active ordering.

    Every excluded orbital must be doubly occupied or empty. In particular,
    this never freezes a SOMO/fractionally occupied orbital or silently changes
    the requested electron count. Fractional CASSCF occupations are diagnostic;
    their inclusion does not turn them into integer determinant occupations.
    """
    if reference.get('kind') not in ('restricted', 'QRO', 'CASSCF'):
        raise ValueError('Select shared restricted, QRO or verified CASSCF spatial orbitals')
    total, count = reference['n_electrons'], reference['n_orbitals']
    charge, multiplicity = reference['charge'], reference['source_multiplicity']
    if (any(type(x) is not int for x in (total, count, charge, multiplicity)) or
            count < 1 or not 0 <= total <= 2*count or multiplicity < 1):
        raise ValueError('Invalid reference electron/orbital/charge/spin counts')
    if set(space) != {'electrons', 'orbitals'}:
        raise ValueError('Provide active electrons and explicit zero-based source orbital indices')
    nel, indices = space['electrons'], space['orbitals']
    if (type(nel) is not int or not isinstance(indices, list) or not indices or
            any(type(i) is not int or not 0 <= i < count for i in indices) or
            len(set(indices)) != len(indices) or not 0 <= nel <= 2*len(indices)):
        raise ValueError('Invalid active electron count or duplicate/out-of-range orbital indices')
    unpaired = multiplicity - 1
    if (unpaired > min(nel, 2*len(indices)-nel) or (nel-unpaired) % 2 or
            (total-nel) % 2 or total < nel):
        raise ValueError('Active space cannot represent the reference electron count and spin')
    occ = _real_array(occupations, 'Spatial occupations')
    tol = OCCUPATION_TOLERANCE
    if (occ.shape != (count,) or np.any(occ < -tol) or np.any(occ > 2+tol) or
            abs(float(occ.sum())-total) > tol*count):
        raise ValueError('Spatial occupations do not match the reference electron count')
    chosen, inactive, external = set(indices), [], []
    for index, value in enumerate(occ):
        if index in chosen:
            continue
        if abs(value-2) <= tol:
            inactive.append(index)
        elif abs(value) <= tol:
            external.append(index)
        else:
            raise ValueError(f'Include partially occupied source MO {index} in the active space')
    if (2*len(inactive)+nel != total or
            abs(float(occ[indices].sum())-nel) > tol*count):
        raise ValueError('Selected electrons/orbitals disagree with the inactive/active partition')
    if str(UUID(str(source_reference_uuid))) != source_reference_uuid:
        raise ValueError('Use the canonical source orbital-reference UUID')
    if not isinstance(source_file_sha256, str) or not re.fullmatch('[0-9a-f]{64}', source_file_sha256):
        raise ValueError('Bind the plan to the source orbital-file SHA-256')
    forward = inactive + list(indices) + external
    inverse = [0]*count
    for native, original in enumerate(forward):
        inverse[original] = native
    result = {
        'schema': SCHEMA,
        'source_reference_uuid': source_reference_uuid,
        'source_file_sha256': source_file_sha256,
        'source_reference_sha256': _digest(reference),
        'source_active_space': deepcopy(space),
        'native_active_space': {'electrons': nel,
                                'orbitals': list(range(len(inactive), len(inactive)+len(indices)))},
        'inactive_source_indices': inactive,
        'external_source_indices': external,
        'native_to_source': forward,
        'source_to_native': inverse,
        'source_occupations': occ.tolist(),
        'phase_convention': 'preserve_signed_coefficients',
        'permutation_needed': forward != list(range(count)),
    }
    return result | {'plan_sha256': _digest(result)}


def _checked_plan(reference, plan):
    expected = selection_plan(reference, plan['source_active_space'], plan['source_occupations'],
        source_reference_uuid=plan['source_reference_uuid'],
        source_file_sha256=plan['source_file_sha256'])
    if expected != plan:
        raise ValueError('The orbital-reordering plan changed; review the source and selection again')


def _spatial_table(document, reference):
    """Require a narrow native export, never silently retain MO-indexed extras."""
    if set(document)-{'Molecule', 'ORCA Header'}:
        raise ValueError('Export geometry, basis, MOs and AO overlap only; omit density/integral arrays')
    mol = document['Molecule']
    allowed = {'Atoms', 'BaseName', 'Charge', 'CoordinateUnits', 'HFTyp', 'Multiplicity',
               'MolecularOrbitals', 'S-Matrix', 'PointGroup', 'NCorelessECP', 'Origin'}
    if set(mol)-allowed:
        raise ValueError('Unqualified native molecular fields; refusing to relabel unknown data')
    if mol['HFTyp'] not in _SPATIAL_CONTAINERS:
        raise ValueError('Require one qualified spatial MO container; no implicit UHF/CASSCF conversion')
    if (mol['Charge'] != reference['charge'] or
            mol['Multiplicity'] != reference['source_multiplicity']):
        raise ValueError('Native charge/spin differs from the reviewed reference')
    if mol['CoordinateUnits'] not in ('Angs', 'Angstrom', 'Bohrs'):
        raise ValueError('Unsupported native coordinate units')
    atoms = mol['Atoms']
    if not atoms or mol.get('NCorelessECP', 0) or any('ECP' in a for a in atoms):
        raise ValueError('Require a nonempty all-electron geometry; ECPs are not qualified')
    coordinates = _real_array([a['Coords'] for a in atoms], 'Coordinates')
    if coordinates.shape != (len(atoms), 3) or any(not a.get('Basis') for a in atoms):
        raise ValueError('Require complete native atom/basis records')
    charges = _real_array([a['NuclearCharge'] for a in atoms], 'Nuclear charges')
    if abs(float(charges.sum())-mol['Charge']-reference['n_electrons']) > DATA_TOLERANCE:
        raise ValueError('Native nuclear charges/electron count differ from the reference')
    table = mol['MolecularOrbitals']
    if set(table)-{'MOs', 'EnergyUnit', 'OrbitalLabels'} or table['EnergyUnit'] != 'Eh':
        raise ValueError('Unsupported native orbital metadata or energy units')
    rows = table['MOs']
    count = reference['n_orbitals']
    if len(rows) != count:
        raise ValueError('Incomplete spatial orbital table')
    coefficients = _real_array([r['MOCoefficients'] for r in rows], 'MO coefficients').T
    overlap = _real_array(mol['S-Matrix'], 'AO overlap')
    if coefficients.shape != (count, count) or overlap.shape != (count, count):
        raise ValueError('Require complete equal AO/MO dimensions; reduced-rank bases are not qualified')
    if np.max(np.abs(overlap-overlap.T)) > DATA_TOLERANCE:
        raise ValueError('The AO overlap matrix is not symmetric')
    occupations = _real_array([r['Occupancy'] for r in rows], 'Occupations')
    _real_array([r['OrbitalEnergy'] for r in rows], 'Orbital energies')
    error = float(np.max(np.abs(coefficients.T @ overlap @ coefficients - np.eye(count))))
    if error > ORTHONORMALITY_TOLERANCE:
        raise ValueError('The complete spatial orbitals fail CᵀSC = I')
    return mol, coefficients, overlap, occupations, error


def permute_document(document, reference, plan):
    """Copy complete native MO rows, including occupations, energies and signs."""
    _checked_plan(reference, plan)
    mol, _, _, occupations, _ = _spatial_table(document, reference)
    if np.max(np.abs(occupations-np.asarray(plan['source_occupations']))) > OCCUPATION_TOLERANCE:
        raise ValueError('Native occupations differ from the reviewed plan')
    result = deepcopy(document)
    rows = mol['MolecularOrbitals']['MOs']
    result['Molecule']['MolecularOrbitals']['MOs'] = [deepcopy(rows[i]) for i in plan['native_to_source']]
    return result


def verify_roundtrip(source, prepared, reference, plan):
    """Check re-exported arrays without fitting, rotating or repairing them.

    Passing these in-memory checks is not a native-readback certificate. A
    future preparation CalcJob must bind actual file checksums/provenance and
    independent frozen-CASCI readback before exposing a downstream reference.
    """
    expected = permute_document(source, reference, plan)
    a, ca, sa, oa, source_ortho = _spatial_table(expected, reference)
    b, cb, sb, ob, target_ortho = _spatial_table(prepared, reference)
    if set(a) != set(b):
        raise ValueError('Native roundtrip changed molecular fields')
    for key in set(a)-{'BaseName', 'Atoms', 'S-Matrix', 'MolecularOrbitals'}:
        if a[key] != b[key]:
            raise ValueError('Native roundtrip changed '+key)
    if len(a['Atoms']) != len(b['Atoms']):
        raise ValueError('Native roundtrip changed atoms')
    for first, second in zip(a['Atoms'], b['Atoms']):
        if (set(first) != set(second) or
                any(first[k] != second[k] for k in first if k != 'Coords') or
                np.max(np.abs(np.asarray(first['Coords'])-second['Coords'])) > DATA_TOLERANCE):
            raise ValueError('Native roundtrip changed atom order, geometry or basis')
    ta, tb = a['MolecularOrbitals'], b['MolecularOrbitals']
    if {k:v for k,v in ta.items() if k != 'MOs'} != {k:v for k,v in tb.items() if k != 'MOs'}:
        raise ValueError('Native roundtrip changed AO labels or orbital metadata')
    for first, second in zip(ta['MOs'], tb['MOs']):
        numeric = {'MOCoefficients', 'Occupancy', 'OrbitalEnergy'}
        if (set(first) != set(second) or
                any(first[k] != second[k] for k in first if k not in numeric)):
            raise ValueError('Native roundtrip changed orbital symmetry or row identity')
    energy_error = max(abs(x['OrbitalEnergy']-y['OrbitalEnergy']) for x,y in zip(ta['MOs'], tb['MOs']))
    errors = {'signed_coefficients': float(np.max(np.abs(ca-cb))),
              'ao_overlap': float(np.max(np.abs(sa-sb))),
              'occupations': float(np.max(np.abs(oa-ob))), 'orbital_energies': float(energy_error)}
    if any(value > DATA_TOLERANCE for value in errors.values()):
        raise ValueError('Native roundtrip changed signed orbitals, occupations, energies or AO overlap')
    # Check every entry, not just diagonal magnitudes or overlap eigenvalues.
    source_coefficients = _spatial_table(source, reference)[1]
    expected_overlap = np.eye(len(ca))[:, plan['native_to_source']]
    signed_overlap_error = float(np.max(np.abs(source_coefficients.T @ sa @ cb - expected_overlap)))
    if signed_overlap_error > ORTHONORMALITY_TOLERANCE:
        raise ValueError('The full signed source-to-prepared overlap differs from the reviewed permutation')
    density_error = float(np.max(np.abs((ca*oa) @ ca.T - (cb*ob) @ cb.T)))
    if density_error > ORTHONORMALITY_TOLERANCE:
        raise ValueError('Native roundtrip changed the occupation-weighted spatial density')
    return {'schema': SCHEMA, 'plan_sha256': plan['plan_sha256'],
            'array_checks_passed': True, 'native_readback_qualified': False,
            'errors': errors, 'source_orthonormality_error': source_ortho,
            'target_orthonormality_error': target_ortho,
            'full_signed_overlap_error': signed_overlap_error,
            'occupation_weighted_density_error': density_error,
            'phase_convention': plan['phase_convention']}
