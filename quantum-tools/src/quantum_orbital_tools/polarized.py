"""Slater–Condon Hamiltonian for a selected single-spin determinant basis.

Real spatial integrals use chemist notation. This constructs only the selected
matrix, never the full CAS vector. Both alpha-only and beta-only sectors have
this same Hamiltonian. Vacuum and one-electron cases follow the same rules.
"""

from itertools import combinations
import numpy as np
from scipy.linalg import eigh


def occupied(bits):
    positions = []
    while bits:
        low = bits & -bits
        positions.append(low.bit_length() - 1)
        bits ^= low
    return positions


def excitation_phase(ket, remove, create):
    phase = 1
    for position in remove:
        phase *= -1 if (ket & ((1 << position) - 1)).bit_count() % 2 else 1
        ket ^= 1 << position
    for position in create:
        phase *= -1 if (ket & ((1 << position) - 1)).bit_count() % 2 else 1
        ket |= 1 << position
    return phase


def selected_matrix(h, strings):
    """Exact matrix in the supplied determinant ordering, including the scalar."""
    strings = list(map(int, strings))
    matrix = np.zeros((len(strings), len(strings)), order="F")
    for column, ket in enumerate(strings):
        occ = occupied(ket)
        matrix[column, column] = (
            h.constant
            + sum(h.h1[i, i] for i in occ)
            + sum(
                h.eri[i, i, j, j] - h.eri[i, j, j, i] for i, j in combinations(occ, 2)
            )
        )
        for row in range(column):
            bra = strings[row]
            removed = ket & ~bra
            rank = removed.bit_count()
            if rank > 2:
                continue
            added = bra & ~ket
            if rank == 1:
                (i,) = occupied(removed)
                (a,) = occupied(added)
                value = excitation_phase(ket, [i], [a]) * (
                    h.h1[a, i]
                    + sum(h.eri[a, i, j, j] - h.eri[a, j, j, i] for j in occ if j != i)
                )
            elif rank == 2:
                i, j = occupied(removed)
                a, b = occupied(added)
                value = excitation_phase(ket, [i, j], [b, a]) * (
                    h.eri[a, i, b, j] - h.eri[a, j, b, i]
                )
            else:
                raise ValueError("Duplicate polarized determinants")
            matrix[row, column] = matrix[column, row] = value
    return matrix


def solve_polarized(h, nelec, strings, nroots):
    spin = 0 if nelec[0] else 1
    matrix = selected_matrix(h, strings[spin])
    energies, vectors = eigh(matrix, subset_by_index=(0, nroots - 1), check_finite=True)
    states = [vectors[:, i].reshape(tuple(map(len, strings))) for i in range(nroots)]
    spin_value = sum(nelec) / 2
    diagnostics = [
        {
            "spin_squared": spin_value * (spin_value + 1),
            "spin_diagnostic": "Exact S=N/2 for a fully polarized determinant sector",
            "projected_residual_hartree": float(
                np.linalg.norm(matrix @ vectors[:, i] - energy * vectors[:, i])
            ),
        }
        for i, energy in enumerate(energies)
    ]
    return energies, states, diagnostics
