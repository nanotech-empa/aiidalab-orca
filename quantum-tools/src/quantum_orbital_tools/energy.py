"""Portable energy workflow. Importing this module submits no calculation."""

import argparse
from dataclasses import replace
import hashlib
import importlib.metadata
import importlib.util
import json
from math import comb
from pathlib import Path

import numpy as np

from .hamiltonian import file_sha256, read_orca_fcidump, electron_sector

PROTOCOL = "quantum-energy/v1"


def manifest():
    source = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        source.update(path.name.encode())
        source.update(path.read_bytes())
    commands = ["validate", "solve-full", "solve-sampled"]
    if importlib.util.find_spec("qiskit"):
        commands.append("sample-simulator")
        if importlib.util.find_spec("qiskit_fermions"):
            commands.append("generate")
        if importlib.util.find_spec("qiskit_ibm_runtime"):
            commands.extend(["prepare-hardware", "sample-hardware"])
    return {
        "protocol": PROTOCOL,
        "source_sha256": source.hexdigest(),
        "commands": commands,
        "capabilities": {
            "resource_bounded_roots": True,
            "polarized_sampled_sectors": True,
            "empty_sampled_sector": True,
        },
        "versions": {
            name: importlib.metadata.version(name)
            for name in (
                "numpy",
                "scipy",
                "pyscf",
                "qiskit",
                "qiskit-fermions",
                "qiskit-ibm-runtime",
            )
            if importlib.util.find_spec(name.replace("-", "_"))
        },
    }


def integer(values, key, default, low, high):
    value = values.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{key} must be an integer between {low} and {high}")
    return value


def determinant_energy(h):
    """Highest-Ms diagnostic determinant, not a correlated state."""
    occupied = [list(range(n)) for n in h.nelec]
    value = h.constant + sum(h.h1[p, p] for spin in occupied for p in spin)
    for s in range(2):
        for t in range(2):
            value += 0.5 * sum(
                h.eri[p, p, q, q] - (h.eri[p, q, q, p] if s == t else 0)
                for p in occupied[s]
                for q in occupied[t]
            )
    return float(value)


def validate(h, request, settings):
    native = request["native_export"]
    if (
        native.get("native_csfs") != 1
        or native.get("not_a_correlated_CASCI_state") is not True
        or h.norb != len(native["active_space"]["orbitals"])
        or sum(h.nelec) != native["active_space"]["electrons"]
        or h.nelec[0] - h.nelec[1] != native["multiplicity"] - 1
    ):
        raise ValueError(
            "The export is not the requested one-configuration Hamiltonian"
        )
    error = determinant_energy(h) - native["diagnostic_energy_hartree"]
    if abs(error) > 1e-7:
        raise ValueError(
            "The Hamiltonian does not reproduce the native diagnostic energy"
        )
    return {
        "passed": True,
        "diagnostic_error_hartree": error,
        "native_export": native,
        "norb": h.norb,
        "nelec": list(h.nelec),
        "constant_hartree": h.constant,
        "full_casci_computed": False,
    }


def generate(h, request, settings):
    from qiskit import qpy
    from .sqdrift import grouped_generator, draw_fermionic

    times = settings.get("times", [1.0])
    if (
        not isinstance(times, list)
        or not 1 <= len(times) <= 3
        or any(
            type(t) not in (int, float) or not np.isfinite(t) or not 0 < t <= 10
            for t in times
        )
    ):
        raise ValueError(
            "Choose one to three positive evolution times, at most 10 Hartree⁻¹"
        )
    repetitions = integer(settings, "randomizations", 4, 1, 100)
    groups = integer(settings, "groups", 10, 1, 50)
    seed = integer(settings, "seed", 42, 0, 2**32 - 1000)
    remove_diagonal = settings.get("remove_diagonal", True)
    if type(remove_diagonal) is not bool:
        raise ValueError("remove_diagonal must be a boolean")
    initial = [
        settings.get(key, list(range(count)))
        for key, count in zip(("initial_alpha", "initial_beta"), h.nelec)
    ]
    for indices, count in zip(initial, h.nelec):
        if (
            not isinstance(indices, list)
            or len(indices) != count
            or indices != sorted(set(indices))
            or any(type(i) is not int or not 0 <= i < h.norb for i in indices)
        ):
            raise ValueError(
                "Initial occupations must match the target alpha/beta counts and active orbital indices"
            )
    occupation = [i in initial[spin] for spin in range(2) for i in range(h.norb)]
    operator, weights, grouping = grouped_generator(
        "hamiltonian.fcidump", remove_diagonal
    )
    circuits, rows = [], []
    for i, time in enumerate(times):
        for j in range(repetitions):
            draw_seed = seed + i * repetitions + j
            circuit = draw_fermionic(
                operator, weights, h.norb, h.nelec, time, groups, draw_seed, occupation
            )
            name = f"t{i}_r{j}"
            circuit.name = name
            rows.append(
                {
                    "name": name,
                    "time": time,
                    "seed": draw_seed,
                    "depth": circuit.depth(),
                    "two_qubit_gates": sum(
                        x.operation.num_qubits == 2 for x in circuit.data
                    ),
                }
            )
            circuit.measure_all()
            circuits.append(circuit)
    with Path("circuits.qpy").open("wb") as stream:
        qpy.dump(circuits, stream)
    return {
        "circuits": rows,
        "circuits_sha256": file_sha256(Path("circuits.qpy")),
        "qubits": 2 * h.norb,
        "nelec": list(h.nelec),
        "grouping": grouping,
        "full_statevector_constructed": False,
        "method": "sqdrift",
        "initial_occupations_local": {"alpha": initial[0], "beta": initial[1]},
        "filter_trivial": False,
        "mode_order": "blocked-alpha-beta",
    }


def sample(h, request, settings):
    from qiskit import qpy
    from qiskit.quantum_info import Statevector

    shots = integer(settings, "shots", 1000, 100, 100000)
    seed = integer(settings, "seed", 42, 0, 2**32 - 1000)
    max_qubits = integer(settings, "max_qubits", 20, 2, 24)
    if 2 * h.norb > max_qubits:
        raise ValueError(
            "Statevector simulation exceeds the reviewed qubit cap; use another simulator or smaller CAS"
        )
    if (
        file_sha256(Path("circuits.qpy"))
        != request["circuit_manifest"]["circuits_sha256"]
    ):
        raise ValueError("Prepared circuits changed")
    if (
        request["circuit_manifest"].get("sector") != request.get("sector")
        or tuple(request["circuit_manifest"]["nelec"]) != h.nelec
    ):
        raise ValueError(
            "The prepared circuits belong to a different electron/spin sector"
        )
    with Path("circuits.qpy").open("rb") as stream:
        circuits = qpy.load(stream)
    pooled = {}
    for i, circuit in enumerate(circuits):
        if circuit.num_qubits != 2 * h.norb:
            raise ValueError("Circuit/Hamiltonian qubit counts differ")
        state = Statevector.from_instruction(
            circuit.remove_final_measurements(inplace=False)
        )
        state.seed(seed + i)
        for bits, count in state.sample_counts(shots).items():
            pooled[bits] = pooled.get(bits, 0) + int(count)
    packet = {
        "n_qubits": 2 * h.norb,
        "nelec": list(h.nelec),
        "counts": pooled,
        "shots": shots * len(circuits),
        "qubit_to_classical": list(range(2 * h.norb)),
        "hamiltonian_sha256": request["hamiltonian_sha256"],
        "physical_samples": False,
        "execution_kind": "ideal_statevector_simulator",
        "circuits_sha256": file_sha256(Path("circuits.qpy")),
        "sector": request.get("sector"),
    }
    Path("samples.json").write_text(
        json.dumps(packet, indent=2, allow_nan=False) + "\n"
    )
    return {
        "execution_kind": packet["execution_kind"],
        "shots": packet["shots"],
        "samples_sha256": file_sha256(Path("samples.json")),
    }


def solve(h, request, settings, sampled=False):
    from pyscf import fci, lib

    lib.num_threads(integer(settings, "threads", 2, 1, 64))
    roots = integer(settings, "nroots", 4, 1, 1000000)
    limit = integer(settings, "max_dimension", 100000, 1, 1000000)
    memory = integer(settings, "memory_mb", 4096, 256, 262144)
    selection = None
    if sampled:
        from .sampled_space import sampled_strings, solve_space

        packet = json.loads(Path("samples.json").read_text())
        if file_sha256(Path("samples.json")) != request["samples_sha256"]:
            raise ValueError("Input samples changed")
        if (
            packet["hamiltonian_sha256"] != request["hamiltonian_sha256"]
            or packet["execution_kind"]
            not in ("ideal_statevector_simulator", "ibm_hardware")
            or tuple(packet["nelec"]) != h.nelec
            or packet.get("sector") != request.get("sector")
        ):
            raise ValueError(
                "Samples are not valid physical or simulated samples for this Hamiltonian"
            )
        strings, selection = sampled_strings(
            packet, h.norb, h.nelec, integer(settings, "string_limit", 128, 1, 1024)
        )
        count = len(strings[0]) * len(strings[1])
        used = min(roots, count)
        energies, states, checks = solve_space(
            h,
            h.nelec,
            strings,
            threads=settings.get("threads", 2),
            max_dimension=limit,
            nroots=used,
            memory_mb=memory,
        )
        if not all(d["projected_residual_passed"] for d in checks["states"]):
            raise ValueError("Projected eigensolver residual did not pass")
        squared_spins = [d["spin_squared"] for d in checks["states"]]
        resources = checks["resources"]
        np.savez_compressed(
            "states.npz",
            alpha_strings=strings[0],
            beta_strings=strings[1],
            **{f"root_{i}": np.asarray(c) for i, c in enumerate(states)},
        )
        method = "sampled product-space diagonalization"
    else:
        count = comb(h.norb, h.nelec[0]) * comb(h.norb, h.nelec[1])
        if count > limit:
            raise ValueError(
                "Full classical CAS exceeds the reviewed determinant-space cap"
            )
        used = min(roots, count)
        from .solver_resources import solver_resources

        resources = solver_resources(h.norb, count, used, memory)
        solver = fci.direct_spin1.FCI()
        solver.verbose = 0
        solver.max_memory = memory
        solver.max_cycle = 200
        solver.max_space = resources["davidson_max_space"]
        solver.conv_tol = 1e-11
        solver.conv_tol_residual = 1e-9
        solver.lindep = 1e-20
        energies, states = solver.kernel(
            h.h1, h.eri, h.norb, h.nelec, nroots=used, ecore=h.constant
        )
        if not np.all(solver.converged):
            raise ValueError("Full classical eigensolver did not converge")
        states = [states] if used == 1 else list(states)
        squared_spins = [
            float(fci.spin_op.spin_square(c, h.norb, h.nelec)[0]) for c in states
        ]
        effective = fci.direct_spin1.absorb_h1e(h.h1, h.eri, h.norb, h.nelec, 0.5)
        for energy, state in zip(np.atleast_1d(energies), states):
            residual = (
                fci.direct_spin1.contract_2e(effective, state, h.norb, h.nelec)
                - (energy - h.constant) * state
            )
            if np.linalg.norm(residual) > 1e-7:
                raise ValueError("Full classical eigensolver residual did not pass")
        np.savez_compressed(
            "states.npz", **{f"root_{i}": np.asarray(c) for i, c in enumerate(states)}
        )
        method = "full fixed-Ms CAS diagonalization"
    smin = abs(h.nelec[0] - h.nelec[1]) / 2
    smax = min(sum(h.nelec), 2 * h.norb - sum(h.nelec)) / 2
    spin_values = [(smin + i) * (smin + i + 1) for i in range(int(smax - smin) + 1)]
    return {
        "method": method,
        "solver_resources": resources,
        "dimension": count,
        "requested_roots": roots,
        "used_roots": used,
        "levels": [
            {"root": i, "energy_hartree": float(e), "spin_squared": s}
            for i, (e, s) in enumerate(zip(np.atleast_1d(energies), squared_spins))
        ],
        "spin_expectation_consistent": all(
            min(abs(s - value) for value in spin_values) <= 1e-6 for s in squared_spins
        ),
        "energy_unit": "hartree",
        "constant_added_once": True,
        "selection": selection,
        "states_sha256": file_sha256(Path("states.npz")),
        "samples_execution_kind": packet["execution_kind"] if sampled else None,
        "input_samples_sha256": request["samples_sha256"] if sampled else None,
        "spin_note": "Fixed Ms permits several total spins. A quantized S² expectation is a diagnostic, not a general certificate of higher-spin purity; inspect convergence and spin variance when assigning multiplets.",
    }


def run(operation, request_path):
    request = json.loads(Path(request_path).read_text())
    worker = manifest()
    if (
        request["worker_manifest"]["protocol"] != PROTOCOL
        or request["worker_manifest"]["source_sha256"] != worker["source_sha256"]
        or request["worker_manifest"]["versions"] != worker["versions"]
    ):
        raise ValueError("Worker source/protocol differs from the reviewed Code")
    if operation not in worker["commands"]:
        raise ValueError("This worker does not support the selected operation")
    sha = file_sha256(Path("hamiltonian.fcidump"))
    if sha != request["hamiltonian_sha256"]:
        raise ValueError("Hamiltonian checksum mismatch")
    h = read_orca_fcidump(Path("hamiltonian.fcidump"))
    sector = request.get("sector")
    if sector is not None:
        if operation == "validate":
            raise ValueError(
                "Hamiltonian validation uses the original export reference sector"
            )
        if (
            not isinstance(sector, dict)
            or set(sector) != {"charge", "ms2"}
            or type(sector["charge"]) is not int
            or type(sector["ms2"]) is not int
        ):
            raise ValueError(
                "Declare an integer charge and twice the spin projection (ms2)"
            )
        native = request["native_export"]
        electrons = native["active_space"]["electrons"] - (
            sector["charge"] - native["charge"]
        )
        h = replace(h, nelec=electron_sector(h.norb, electrons, sector["ms2"] + 1))
    settings = request["settings"]
    allowed = {
        "validate": set(),
        "generate": {
            "times",
            "randomizations",
            "groups",
            "seed",
            "remove_diagonal",
            "initial_alpha",
            "initial_beta",
        },
        "sample-simulator": {"shots", "seed", "max_qubits"},
        "solve-full": {"threads", "nroots", "max_dimension", "memory_mb"},
        "solve-sampled": {
            "threads",
            "nroots",
            "max_dimension",
            "memory_mb",
            "string_limit",
        },
        "prepare-hardware": {
            "backend",
            "shots",
            "max_execution_seconds",
            "budget_total_seconds",
            "budget_margin_seconds",
            "seed",
        },
        "sample-hardware": {"hardware_authorized"},
    }[operation]
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ValueError("Unsupported settings for the selected energy stage")
    if operation == "validate":
        result = validate(h, request, settings)
    elif operation == "generate":
        result = generate(h, request, settings)
    elif operation == "sample-simulator":
        result = sample(h, request, settings)
    elif operation in ("prepare-hardware", "sample-hardware"):
        from . import energy_hardware

        try:
            result = (
                energy_hardware.prepare
                if operation == "prepare-hardware"
                else energy_hardware.sample
            )(h, request, settings)
        except Exception as exc:
            # Provider exceptions can contain account information. Keep those
            # outside AiiDA's retrieved logs and return a safe diagnostic.
            raise RuntimeError(
                "Hardware adapter could not finish ("
                + type(exc).__name__
                + "). Check worker account configuration or retrieve the existing job; do not resubmit blindly."
            ) from None
    else:
        result = solve(h, request, settings, sampled=operation == "solve-sampled")
    result.setdefault("qpu_jobs_submitted", 0)
    result.update(
        operation=operation,
        software=worker,
        settings=settings,
        hamiltonian_sha256=sha,
        sector=sector,
        nelec=list(h.nelec),
    )
    Path("result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=[
            "manifest",
            "validate",
            "generate",
            "sample-simulator",
            "solve-full",
            "solve-sampled",
            "prepare-hardware",
            "sample-hardware",
        ],
    )
    parser.add_argument("--request", default="request.json")
    args = parser.parse_args()
    if args.operation == "manifest":
        print(json.dumps(manifest(), indent=2))
    else:
        run(args.operation, args.request)


if __name__ == "__main__":
    main()
