"""Independent FCI matrix comparisons for projected spin sectors and roots."""

from itertools import combinations
import numpy as np
import pytest
from pyscf import fci
from pyscf.fci import cistring

from quantum_orbital_tools.hamiltonian import ActiveHamiltonian
from quantum_orbital_tools.polarized import selected_matrix
from quantum_orbital_tools.sampled_space import solve_space
from quantum_orbital_tools.solver_resources import solver_resources


def hamiltonian(norb, nelec):
    rng = np.random.default_rng(81)
    one = rng.normal(size=(norb, norb))
    one = (one + one.T) / 2
    factors = rng.normal(size=(norb, norb, 3))
    factors = (factors + factors.transpose(1, 0, 2)) / 2
    eri = np.einsum("ijL,klL->ijkl", factors, factors) * 0.05
    return ActiveHamiltonian(one, eri, -1.3, nelec, {})


def strings(norb, nel):
    return np.array(
        sorted(sum(1 << i for i in occ) for occ in combinations(range(norb), nel)),
        dtype=np.int64,
    )


def fci_selected_matrix(h, selected):
    shape = (len(strings(h.norb, h.nelec[0])), len(strings(h.norb, h.nelec[1])))
    addresses = [
        (
            cistring.str2addr(h.norb, h.nelec[0], int(a)),
            cistring.str2addr(h.norb, h.nelec[1], int(b)),
        )
        for a in selected[0]
        for b in selected[1]
    ]
    effective = fci.direct_spin1.absorb_h1e(h.h1, h.eri, h.norb, h.nelec, 0.5)
    matrix = np.empty((len(addresses), len(addresses)))
    for j, address in enumerate(addresses):
        unit = np.zeros(shape)
        unit[address] = 1
        value = (
            fci.direct_spin1.contract_2e(effective, unit, h.norb, h.nelec)
            + h.constant * unit
        )
        matrix[:, j] = [value[index] for index in addresses]
    return matrix


@pytest.mark.parametrize(
    "nelec", [(2, 0), (0, 2), (3, 0), (0, 3), (1, 0), (0, 1), (4, 0), (0, 4)]
)
def test_polarized_matrix_elements_and_levels_match_independent_fci(nelec):
    h = hamiltonian(4, nelec)
    basis = [strings(h.norb, n) for n in nelec]
    spin = 0 if nelec[0] else 1
    # Noncontiguous selected determinant support tests projection and phases.
    if len(basis[spin]) > 4:
        basis[spin] = basis[spin][[0, 2, 3, -1]]
    matrix = selected_matrix(h, basis[spin])
    reference = fci_selected_matrix(h, basis)
    assert np.max(np.abs(matrix - reference)) < 1e-12
    roots = len(basis[spin])
    energies, states, checks = solve_space(h, nelec, basis, nroots=roots, threads=1)
    assert energies == pytest.approx(np.linalg.eigvalsh(reference), abs=1e-11)
    expected = sum(nelec) / 2 * (sum(nelec) / 2 + 1)
    assert all(row["spin_squared"] == expected for row in checks["states"])
    assert all(row["projected_residual_passed"] for row in checks["states"])
    assert all(np.linalg.norm(state) == pytest.approx(1) for state in states)


def test_vacuum_is_the_inactive_and_nuclear_scalar_once():
    h = hamiltonian(3, (0, 0))
    energy, _, checks = solve_space(h, h.nelec, ([0], [0]), nroots=1)
    assert energy == pytest.approx([h.constant])
    assert checks["states"][0]["spin_squared"] == 0


@pytest.mark.parametrize("roots", [8, 36])
def test_mixed_spin_solver_has_no_four_or_thirty_two_root_cap(roots):
    h = hamiltonian(4, (2, 2))
    basis = [strings(4, 2), strings(4, 2)]
    reference = fci_selected_matrix(h, basis)
    energies, states, checks = solve_space(h, h.nelec, basis, nroots=roots, threads=1)
    assert len(energies) == len(states) == roots
    assert energies == pytest.approx(np.linalg.eigvalsh(reference)[:roots], abs=1e-9)
    assert all(row["projected_residual_passed"] for row in checks["states"])


def test_root_workspace_is_checked_before_allocating_the_eigensolver():
    with pytest.raises(ValueError, match="workspace"):
        solver_resources(7, 100000, 1000, 256)
    assert solver_resources(7, 1225, 12, 4096)["estimated_workspace_mib"] < 4096
    with pytest.raises(ValueError, match="root count"):
        solver_resources(4, 6, 7, 4096)


def test_memory_rejection_precedes_solver_construction(monkeypatch):
    from quantum_orbital_tools import sampled_space

    h = hamiltonian(7, (4, 3))
    basis = [strings(7, 4), strings(7, 3)]
    monkeypatch.setattr(
        sampled_space.selected_ci,
        "SCI",
        lambda: pytest.fail("Solver allocated before memory rejection"),
    )
    with pytest.raises(ValueError, match="workspace"):
        solve_space(h, h.nelec, basis, nroots=1225, memory_mb=256)


def test_polarized_circuits_samples_and_more_than_four_levels(tmp_path, monkeypatch):
    pytest.importorskip("qiskit_fermions")
    from pathlib import Path
    from pyscf.tools import fcidump
    from quantum_orbital_tools import energy
    from test_energy import execute

    monkeypatch.chdir(tmp_path)
    h = hamiltonian(4, (2, 0))
    fcidump.from_integrals(
        "hamiltonian.fcidump", h.h1, h.eri, 4, 2, nuc=h.constant, ms=2, tol=1e-16
    )
    request = {
        "worker_manifest": energy.manifest(),
        "native_export": {},
        "hamiltonian_sha256": energy.file_sha256(Path("hamiltonian.fcidump")),
        "settings": {"times": [1, 2], "randomizations": 2, "groups": 10, "seed": 42},
    }
    request["circuit_manifest"] = execute("generate", request)
    request["settings"] = {"shots": 3000, "seed": 42}
    execute("sample-simulator", request)
    request["settings"] = {"nroots": 6, "string_limit": 128, "threads": 1}
    sampled = execute("solve-sampled", request)
    request["settings"] = {"nroots": 6, "threads": 1}
    full = execute("solve-full", request)
    assert sampled["used_roots"] == 6
    assert [v["energy_hartree"] for v in sampled["levels"]] == pytest.approx(
        [v["energy_hartree"] for v in full["levels"]], abs=1e-10
    )
    assert all(v["spin_squared"] == pytest.approx(2) for v in sampled["levels"])
    assert sampled["software"]["capabilities"]["polarized_sampled_sectors"] is True
    assert sampled["qpu_jobs_submitted"] == 0
