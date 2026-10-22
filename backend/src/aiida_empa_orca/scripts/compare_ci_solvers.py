"""Compare raw printed CI vectors; no normalization or orbital phase fitting."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from aiida_empa_orca.dyson_data import checked_ci

ENERGY_TOLERANCE = 1e-7
DEGENERACY_TOLERANCE = 1e-6
PROJECTOR_TOLERANCE = 1e-4
MAX_MISSING_NORM = 1e-5


def load_export(path, artifact):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1048576), b''):
            digest.update(block)
    if digest.hexdigest() != artifact['sha256']:
        raise ValueError('Export checksum differs')
    with gzip.open(path, 'rt') as handle:
        data = json.load(handle)
    if data['identity'] != artifact['identity'] or data['state_uuid'] != artifact['state_uuid']:
        raise ValueError('Export contents differ from provenance')
    return data


def compare(first, second):
    identity = first['identity']
    for key in ('structure_uuid', 'orbital_reference_uuid', 'active_space', 'active_electrons',
                'reference_charge', 'model', 'method', 'geometry_mode'):
        if identity[key] != second['identity'][key]:
            raise ValueError('CI solutions use different '+key)
    left, right = identity['states'], second['identity']['states']
    labels = lambda rows:[(r['root'], r['charge'], r['multiplicity']) for r in rows]
    if not left or labels(left) != labels(right):
        raise ValueError('CI root identities differ')
    a, b = first['wavefunction']['Molecule'], second['wavefunction']['Molecule']
    if a['Atoms'] != b['Atoms']:
        raise ValueError('Geometry or AO basis differs')
    overlap = np.asarray(a['S-Matrix'])
    ca, cb = (np.column_stack([mo['MOCoefficients'] for mo in mol['MolecularOrbitals']['MOs']])
              for mol in (a, b))
    occupied_and_active = slice(0, max(identity['active_space']['orbitals'])+1)
    if (not np.allclose(overlap, b['S-Matrix'], atol=1e-10, rtol=0) or ca.shape != cb.shape or
            not np.allclose(ca, cb, atol=1e-10, rtol=0) or
            not np.allclose(ca[:,occupied_and_active].T@overlap@cb[:,occupied_and_active],
                            np.eye(occupied_and_active.stop), atol=1e-7, rtol=0)):
        raise ValueError('Shared orbital coefficients or phases differ')
    vectors = []
    norms = []
    for bundle in (first, second):
        rows, row_norms = [], []
        for state in left:
            coefficients = bundle['ci_roots'][str(state['root'])]['coefficients']
            norm = checked_ci(coefficients, len(identity['active_space']['orbitals']),
                              identity['active_electrons'], state['multiplicity'])
            if norm < 1-MAX_MISSING_NORM:
                raise ValueError('CI printout is too truncated for solver validation')
            rows.append(coefficients)
            row_norms.append(norm)
        vectors.append(rows)
        norms.append(row_norms)
    determinants = set().union(*(row.keys() for rows in vectors for row in rows))
    if len(determinants)>1_000_000:
        raise ValueError('This numerical validation is limited to one million determinants')
    indices = {det:i for i, det in enumerate(sorted(determinants))}
    matrices = []
    for rows in vectors:
        matrix = np.zeros((len(indices), len(left)))
        for column, row in enumerate(rows):
            matrix[[indices[det] for det in row], column] = list(row.values())
        matrices.append(matrix)
    ga, gb = (matrix.T@matrix for matrix in matrices)
    cross = matrices[0].T@matrices[1]
    energies_a, energies_b = (np.asarray([row['energy_hartree'] for row in rows]) for rows in (left, right))
    if (not np.isfinite(energies_a).all() or not np.isfinite(energies_b).all() or
            np.any(np.diff(energies_a)<0) or np.any(np.diff(energies_b)<0)):
        raise ValueError('Invalid state energies')
    groups, start = [], 0
    for end in range(1, len(left)+1):
        if (end<len(left) and max(energies_a[end]-energies_a[end-1],
                                 energies_b[end]-energies_b[end-1])<=DEGENERACY_TOLERANCE):
            continue
        ix = np.s_[start:end, start:end]
        squared = np.sum(ga[ix]**2)+np.sum(gb[ix]**2)-2*np.sum(cross[ix]**2)
        distance = float(np.sqrt(max(0., squared)/(end-start)))
        groups.append({'roots':[row['root'] for row in left[start:end]],
                       'raw_projector_distance':distance,
                       'overlap_singular_values':np.linalg.svd(cross[ix], compute_uv=False).tolist()})
        start = end
    difference = float(np.max(np.abs(energies_a-energies_b)))
    orthogonality_error = max(float(np.max(np.abs(gram-np.eye(len(left))))) for gram in (ga, gb))
    passed = (difference<=ENERGY_TOLERANCE and orthogonality_error<=MAX_MISSING_NORM and
              all(group['raw_projector_distance']<=PROJECTOR_TOLERANCE for group in groups))
    return {'schema_version':1, 'passed':passed, 'roots':len(left), 'determinants':len(indices),
            'maximum_energy_difference_hartree':difference, 'ci_norms':norms,
            'maximum_orthogonality_error':orthogonality_error, 'groups':groups,
            'tolerances':{'energy_hartree':ENERGY_TOLERANCE, 'degeneracy_hartree':DEGENERACY_TOLERANCE,
                          'projector':PROJECTOR_TOLERANCE, 'maximum_missing_ci_norm':MAX_MISSING_NORM},
            'ci_normalization':'printed_coefficients_not_renormalized',
            'scope':'Numerical comparison in one unchanged orbital basis; not a large-case memory benchmark.'}


def main():
    request = json.loads(Path('request.json').read_text())
    data = [load_export(key+'.json.gz', request['artifacts'][key]) for key in ('first', 'second')]
    result = compare(*data)
    result['state_uuids'] = [bundle['state_uuid'] for bundle in data]
    result['solver_settings'] = request['settings']
    Path('comparison.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    print('CI solver comparison:', 'passed' if result['passed'] else 'failed')


if __name__=='__main__':
    main()
