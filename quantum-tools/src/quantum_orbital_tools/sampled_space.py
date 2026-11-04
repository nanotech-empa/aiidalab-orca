"""Selected product-space eigensolver with explicit spin diagnostics."""

import time
from collections import Counter
import numpy as np
from pyscf import fci, lib
from pyscf.fci import selected_ci

from .solver_resources import solver_resources


def sampled_strings(samples, norb, nelec, string_limit):
    width = 2 * norb
    if samples["n_qubits"] != width:
        raise ValueError("Sample width differs from the Hamiltonian")
    layout = samples["qubit_to_classical"]
    if len(layout) != width or sorted(layout) != list(range(width)):
        raise ValueError("Invalid measurement mapping")
    if type(string_limit) is not int or not 1 <= string_limit <= 1024:
        raise ValueError("Invalid spin-string limit")
    counts = samples["counts"]
    marginals = [Counter(), Counter()]
    valid = 0
    observed = set()
    total = 0
    if not isinstance(counts, dict) or not counts:
        raise ValueError("No sample counts")
    for text, count in counts.items():
        if (
            len(text) != width
            or set(text) - set("01")
            or type(count) is not int
            or count < 1
        ):
            raise ValueError("Invalid sample bitstring/count")
        total += count
        bits = [int(text[width - 1 - layout[q]]) for q in range(width)]
        strings = [
            sum(bits[offset + p] << p for p in range(norb)) for offset in [0, norb]
        ]
        if tuple(s.bit_count() for s in strings) != tuple(nelec):
            continue
        valid += count
        observed.add(tuple(strings))
        for k in [0, 1]:
            marginals[k][strings[k]] += count
    if total != samples["shots"] or valid == 0:
        raise ValueError("Sample total mismatch or no valid electron sector")

    def top(counter):
        return np.array(
            sorted(
                s
                for s, _ in sorted(counter.items(), key=lambda v: (-v[1], v[0]))[
                    :string_limit
                ]
            ),
            dtype=np.int64,
        )

    if nelec[0] == nelec[1]:
        common = marginals[0] + marginals[1]
        a = top(common)
        strings = (a, a.copy())
    else:
        strings = tuple(top(m) for m in marginals)
    record = {
        "input_shots": total,
        "sector_valid_shots": valid,
        "sector_retention_fraction": valid / total,
        "observed_valid_determinants": len(observed),
        "alpha_strings": len(strings[0]),
        "beta_strings": len(strings[1]),
        "cartesian_subspace_dimension": len(strings[0]) * len(strings[1]),
        "spin_strings_truncated": (
            len(common) > string_limit
            if nelec[0] == nelec[1]
            else any(len(m) > string_limit for m in marginals)
        ),
        "basis_definition": "Cartesian product of selected spin strings; includes combinations not directly observed.",
    }
    return strings, record


def solve_space(
    h, nelec, strings, *, threads=2, max_dimension=65536, nroots=1, memory_mb=4096
):
    if h.norb > 32:
        raise ValueError(
            "Selected-space implementation is validated up to 32 spatial orbitals"
        )
    shape = tuple(map(len, strings))
    dimension = shape[0] * shape[1]
    if not 1 <= dimension <= max_dimension <= 1_000_000:
        raise ValueError("Selected product space exceeds its explicit dimension cap")
    if type(nroots) is not int or not 1 <= nroots <= dimension:
        raise ValueError("Invalid selected-space root count")
    for spin, col in enumerate(strings):
        if len(set(map(int, col))) != len(col) or any(
            int(s) < 0
            or int(s).bit_length() > h.norb
            or int(s).bit_count() != nelec[spin]
            for s in col
        ):
            raise ValueError("Invalid selected occupation strings")
    lib.num_threads(threads)
    start = time.monotonic()
    target = (abs(nelec[0] - nelec[1]) / 2) * (abs(nelec[0] - nelec[1]) / 2 + 1)
    resources = solver_resources(
        h.norb, dimension, nroots, memory_mb, dense=min(nelec) == 0
    )
    if min(nelec) == 0:
        from .polarized import solve_polarized

        energies, states, diagnostics = solve_polarized(h, nelec, strings, nroots)
    else:
        solver = selected_ci.SCI()
        solver.verbose = 0
        solver.max_memory = memory_mb
        solver.conv_tol = 1e-12
        solver.conv_tol_residual = 1e-8
        solver.lindep = 1e-20
        solver.max_cycle = 200
        solver.max_space = resources["davidson_max_space"]
        energies, states = solver.kernel_fixed_space(
            h.h1,
            h.eri,
            h.norb,
            nelec,
            strings,
            nroots=nroots,
            ecore=h.constant,
            tol_residual=1e-10,
        )
        if not np.all(solver.converged):
            raise RuntimeError("Selected-space eigensolver did not converge")
        energies = np.atleast_1d(energies)
        states = [states] if nroots == 1 else list(states)
        effective = fci.direct_spin1.absorb_h1e(h.h1, h.eri, h.norb, nelec, 0.5)
        diagnostics = []
        for energy, state in zip(energies, states):
            norm = np.linalg.norm(state)
            if abs(norm - 1) > 1e-8:
                raise ValueError("Selected state is not normalized")
            physical = solver.contract_2e(effective, state, h.norb, nelec)
            diagnostics.append(
                {
                    "spin_squared": float(solver.spin_square(state, h.norb, nelec)[0]),
                    "projected_residual_hartree": float(
                        np.linalg.norm(physical - (energy - h.constant) * state)
                    ),
                }
            )
    smin = abs(nelec[0] - nelec[1]) / 2
    smax = min(sum(nelec), 2 * h.norb - sum(nelec)) / 2
    allowed = [(smin + i) * (smin + i + 1) for i in range(int(smax - smin) + 1)]
    for state, d in zip(states, diagnostics):
        if abs(np.linalg.norm(state) - 1) > 1e-8:
            raise ValueError("Selected state is not normalized")
        d["minimum_spin_squared"] = target
        d["spin_expectation_consistent"] = (
            min(abs(d["spin_squared"] - value) for value in allowed) <= 1e-7
        )
        d["projected_residual_passed"] = d["projected_residual_hartree"] <= 1e-8
    return (
        np.asarray(energies),
        states,
        {
            "resources": resources,
            "dimension": dimension,
            "shape": list(shape),
            "states": diagnostics,
            "elapsed_seconds": time.monotonic() - start,
            "passed": all(
                d["spin_expectation_consistent"] and d["projected_residual_passed"]
                for d in diagnostics
            ),
            "residual_note": "Residual is for the projected Hamiltonian, not the full CAS Hamiltonian. No spin penalty was used.",
        },
    )
