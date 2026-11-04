"""Plain-data decisions shared by classical and quantum energy workflows."""

from math import comb, isfinite

STAGE_LABELS = {
    "export": "Hamiltonian export",
    "generate": "Circuit generation",
    "sample-simulator": "Ideal simulator sampling",
    "prepare-hardware": "Real QPU circuit preparation",
    "sample-hardware": "Real QPU sampling / retrieval",
    "solve-sampled": "PySCF: QPU/simulator-selected subspace",
    "solve-full": "PySCF: full exported Hamiltonian",
}


def assess_space(electrons, orbitals, multiplicity):
    """Estimate representation sizes; this is not a hardware feasibility claim."""
    if (
        type(electrons) is not int
        or type(multiplicity) is not int
        or multiplicity < 1
        or not isinstance(orbitals, list)
        or not orbitals
        or any(type(i) is not int or i < 0 for i in orbitals)
        or orbitals != sorted(set(orbitals))
    ):
        raise ValueError(
            "Use an integer electron count, multiplicity and explicit orbital indices."
        )
    n = len(orbitals)
    unpaired = multiplicity - 1
    if (
        not 0 <= electrons <= 2 * n
        or (electrons - unpaired) % 2
        or unpaired > min(electrons, 2 * n - electrons)
    ):
        raise ValueError("The active electron count and multiplicity are incompatible.")
    alpha, beta = (electrons + unpaired) // 2, (electrons - unpaired) // 2
    dimension = comb(n, alpha) * comb(n, beta)
    return {
        "electrons": electrons,
        "orbitals": list(orbitals),
        "multiplicity": multiplicity,
        "alpha": alpha,
        "beta": beta,
        "qubits": 2 * n,
        "fixed_ms_dimension": dimension,
        "statevector_gib": 16 * 2 ** (2 * n) / 2**30,
        "dense_matrix_gib": 8 * dimension**2 / 2**30,
        "large_example": electrons > 7 or n > 7,
    }


def matched_levels(left, right):
    """Comparison requires the same exported Hamiltonian, not just the CAS size."""
    keys = ("hamiltonian_sha256", "orbital_reference_uuid", "active_space", "charge")
    if any(
        key not in left or key not in right or left[key] != right[key] for key in keys
    ):
        raise ValueError(
            "Compare only levels with the same Hamiltonian, orbitals, active space and charge."
        )
    if left.get("energy_unit") != "hartree" or right.get("energy_unit") != "hartree":
        raise ValueError("Comparison requires explicitly recorded Hartree energies.")
    return True


def review_budget(native, operation, settings, memory_mb):
    """Reject obviously oversized local work before creating a process."""
    size = assess_space(
        native["active_space"]["electrons"],
        native["active_space"]["orbitals"],
        native["multiplicity"],
    )
    if operation in ("solve-sampled", "solve-full"):
        roots = settings.get("nroots", 4)
        if type(roots) is not int or not 1 <= roots <= 1000000:
            raise ValueError(
                "Request a positive integer number of energy levels within the determinant dimension limit"
            )
    if operation == "sample-simulator":
        if size["qubits"] > settings.get("max_qubits", 20):
            raise ValueError("This CAS exceeds the reviewed simulator qubit cap.")
        if size["statevector_gib"] * 1024 > memory_mb:
            raise ValueError("The statevector alone exceeds the requested CPU memory.")
    if operation == "solve-full" and size["fixed_ms_dimension"] > settings.get(
        "max_dimension", 100000
    ):
        raise ValueError(
            "The full CAS determinant space exceeds the reviewed classical dimension cap."
        )
    return size


def orca_comparison(
    native,
    sector,
    summary,
    *,
    input_reference_uuid,
    input_space,
    input_settings,
    structure_uuid,
):
    """Read-only display data; matching does not invent an exported-file hash."""
    model = {key: native[key] for key in ("integral_transform", "auxiliary_basis")}
    if (
        str(input_reference_uuid) != native["orbital_reference_uuid"]
        or input_space != native["reference_active_space"]
        or summary.get("orbital_reference_uuid") != native["orbital_reference_uuid"]
        or summary.get("structure_uuid") != str(structure_uuid)
        or summary.get("active_space") != input_space
        or summary.get("model") != model
        or summary.get("geometry_mode") != "fixed"
        or summary.get("method") != "CASCI"
        or summary.get("energy_unit") != "hartree"
        or input_settings["charge"] != sector["charge"]
        or input_settings["auxiliary_basis"] != native["auxiliary_basis"]
    ):
        raise ValueError(
            "ORCA comparison requires the same orbitals, geometry, active space, charge and integral model"
        )
    mult = input_settings["multiplicity"]
    if mult - 1 < sector["ms2"] or (mult - 1 - sector["ms2"]) % 2:
        raise ValueError("The ORCA multiplicity does not occur in this Ms sector")
    states = summary.get("states", [])
    if (
        len(states) != input_settings["nroots"]
        or sorted(row["root"] for row in states) != list(range(len(states)))
        or any(
            row["charge"] != sector["charge"]
            or row["multiplicity"] != mult
            or not isfinite(row["energy_hartree"])
            for row in states
        )
    ):
        raise ValueError("The stored ORCA state family is incomplete or inconsistent")
    return {
        "origin": "orca_casci",
        "method": "ORCA CASCI",
        "multiplicity": mult,
        "levels": [
            dict(row) for row in sorted(states, key=lambda row: row["energy_hartree"])
        ],
        "used_roots": len(states),
        "selection": None,
        "samples_execution_kind": None,
        "orbital_reference_uuid": native["orbital_reference_uuid"],
        "active_space": dict(input_space),
        "charge": sector["charge"],
        "model": model,
        "energy_unit": "hartree",
    }


def review_worker_solver(capabilities, operation, settings, size):
    """Keep old versioned workers usable without overstating their support."""
    if operation not in ("solve-sampled", "solve-full"):
        return
    legacy_cap = 4 if operation == "solve-sampled" else 32
    if settings.get("nroots", 4) > legacy_cap and not capabilities.get(
        "resource_bounded_roots", False
    ):
        raise ValueError(
            f"This legacy worker supports at most {legacy_cap} levels for this operation. Select an upgraded energy worker; reuse the existing Hamiltonian and samples."
        )
    if operation == "solve-sampled" and min(size["alpha"], size["beta"]) == 0:
        feature = (
            "empty_sampled_sector"
            if size["electrons"] == 0
            else "polarized_sampled_sectors"
        )
        if size["electrons"] != 1 and not capabilities.get(feature, False):
            raise ValueError(
                "This legacy sampled-space worker does not support this empty/fully polarized sector. Select an upgraded energy worker; keep the intended spin choice."
            )
