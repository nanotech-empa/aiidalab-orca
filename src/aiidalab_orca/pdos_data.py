"""Display-only DOS broadening and directional views of saved Löwdin tensors."""
import numpy as np


def gaussian_dos(energies, weights, grid, fwhm):
    energies, weights, grid = (np.asarray(a, dtype=float) for a in (energies, weights, grid))
    if (energies.ndim != 1 or weights.shape != energies.shape or grid.ndim != 1 or
            not all(np.isfinite(a).all() for a in (energies, weights, grid)) or
            not np.isfinite(fwhm) or fwhm <= 0 or np.any(weights < -1e-10)):
        raise ValueError('DOS requires finite energies, nonnegative weights and positive FWHM')
    sigma = fwhm / np.sqrt(8 * np.log(2))
    result = np.zeros(len(grid))
    # Include tails from all orbitals; occupations do not weight a state DOS.
    for start in range(0, len(energies), 128):
        delta = (grid[None, :] - energies[start:start + 128, None]) / sigma
        result += weights[start:start + 128] @ np.exp(-.5 * delta**2) / (sigma * np.sqrt(2 * np.pi))
    return result


def p_perpendicular(arrays, atoms, normal):
    normal = np.asarray(normal, dtype=float)
    if normal.shape != (3,) or not np.isfinite(normal).all() or np.linalg.norm(normal) < 1e-12:
        raise ValueError('Enter a finite nonzero plane normal')
    normal = normal / np.linalg.norm(normal)
    tensor = arrays['p_tensor'][:, list(atoms)].sum(axis=1)
    return np.einsum('i,nij,j->n', normal, tensor, normal)


def molecular_normal(positions):
    positions = np.asarray(positions, dtype=float)
    _, singular, directions = np.linalg.svd(positions - positions.mean(axis=0), full_matrices=True)
    if len(singular) < 2 or singular[1] < 1e-6:
        return np.array([0., 0., 1.]), 'No unique plane for this linear/single-atom geometry; choose the normal explicitly.'
    normal = directions[-1]
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    ratio = singular[-1] / singular[1] if len(singular) > 2 else 0.
    notice = ('Best-fit molecular plane; check it for nonplanar molecules.' if ratio > .05 else
              'Normal to the best-fit molecular plane.')
    return normal, notice
