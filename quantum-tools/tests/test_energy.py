import json
from pathlib import Path

import numpy as np
import pytest
from pyscf.tools import fcidump

from quantum_orbital_tools import energy
from quantum_orbital_tools.hamiltonian import read_orca_fcidump, file_sha256


def model(tmp_path, monkeypatch, electrons=2, spin=0):
    monkeypatch.chdir(tmp_path)
    h1 = np.array([[-1.1, 0.03], [0.03, -0.2]])
    eri = np.zeros((2,) * 4)
    eri[0, 0, 0, 0] = 0.5
    eri[1, 1, 1, 1] = 0.3
    eri[0, 0, 1, 1] = eri[1, 1, 0, 0] = 0.15
    for indices in [(0, 1, 0, 1), (1, 0, 1, 0), (0, 1, 1, 0), (1, 0, 0, 1)]:
        eri[indices] = 0.04
    fcidump.from_integrals(
        "hamiltonian.fcidump", h1, eri, 2, electrons, nuc=0.7, ms=spin, tol=1e-16
    )
    sha = file_sha256(Path("hamiltonian.fcidump"))
    return {
        "worker_manifest": energy.manifest(),
        "hamiltonian_sha256": sha,
        "settings": {},
        "native_export": {},
    }


def execute(operation, request):
    if operation == "solve-sampled":
        request["samples_sha256"] = file_sha256(Path("samples.json"))
    Path("request.json").write_text(json.dumps(request))
    energy.run(operation, "request.json")
    return json.loads(Path("result.json").read_text())


@pytest.mark.parametrize("electrons,spin", [(2, 0), (3, 1)])
def test_export_validation_and_classical_diagonalization(
    tmp_path, monkeypatch, electrons, spin
):
    request = model(tmp_path, monkeypatch, electrons, spin)
    h = read_orca_fcidump(Path("hamiltonian.fcidump"))
    request["native_export"] = {
        "native_csfs": 1,
        "not_a_correlated_CASCI_state": True,
        "active_space": {"electrons": electrons, "orbitals": [0, 1]},
        "multiplicity": spin + 1,
        "diagnostic_energy_hartree": energy.determinant_energy(h),
    }
    assert execute("validate", request)["full_casci_computed"] is False
    result = execute("solve-full", request)
    assert result["constant_added_once"]
    assert result["qpu_jobs_submitted"] == 0
    assert result["used_roots"] <= result["requested_roots"]
    if spin:
        assert result["levels"][0]["spin_squared"] == pytest.approx(0.75)


def test_export_requires_matching_native_diagnostic(tmp_path, monkeypatch):
    request = model(tmp_path, monkeypatch)
    request["native_export"] = {
        "native_csfs": 1,
        "not_a_correlated_CASCI_state": True,
        "active_space": {"electrons": 2, "orbitals": [0, 1]},
        "multiplicity": 1,
        "diagnostic_energy_hartree": 999.0,
    }
    with pytest.raises(ValueError, match="diagnostic energy"):
        execute("validate", request)


def test_mismatching_worker_or_hamiltonian_is_rejected(tmp_path, monkeypatch):
    request = model(tmp_path, monkeypatch)
    request["worker_manifest"] = dict(
        request["worker_manifest"], source_sha256="0" * 64
    )
    with pytest.raises(ValueError, match="Worker source"):
        execute("solve-full", request)


@pytest.mark.parametrize("electrons,spin", [(2, 0), (3, 1)])
def test_circuits_simulator_and_projected_energy(
    tmp_path, monkeypatch, electrons, spin
):
    pytest.importorskip("qiskit_fermions")
    request = model(tmp_path, monkeypatch, electrons, spin)
    request["settings"] = {"times": [1.0], "randomizations": 2, "groups": 5, "seed": 42}
    circuits = execute("generate", request)
    assert circuits["qubits"] == 4
    assert not circuits["full_statevector_constructed"]
    request["circuit_manifest"] = circuits
    request["settings"] = {"shots": 2000, "seed": 42, "max_qubits": 14}
    assert (
        execute("sample-simulator", request)["execution_kind"]
        == "ideal_statevector_simulator"
    )
    request["settings"] = {"nroots": 2, "string_limit": 10, "max_dimension": 100}
    projected = execute("solve-sampled", request)
    request["settings"] = {"nroots": 2, "max_dimension": 100}
    full = execute("solve-full", request)
    assert (
        projected["levels"][0]["energy_hartree"]
        >= full["levels"][0]["energy_hartree"] - 1e-8
    )
    assert projected["qpu_jobs_submitted"] == 0
    assert projected["selection"]["sector_retention_fraction"] == pytest.approx(1)


def test_simulator_and_full_solver_caps_precede_expensive_work(tmp_path, monkeypatch):
    request = model(tmp_path, monkeypatch)
    request["settings"] = {"max_dimension": 1}
    with pytest.raises(ValueError, match="determinant-space cap"):
        execute("solve-full", request)


@pytest.mark.parametrize(
    "charge,ms2,expected", [(0, 0, [1, 1]), (1, 1, [1, 0]), (-1, 1, [2, 1])]
)
def test_same_integrals_support_explicit_charge_and_spin_sectors(
    tmp_path, monkeypatch, charge, ms2, expected
):
    request = model(tmp_path, monkeypatch)
    request["native_export"] = {"charge": 0, "active_space": {"electrons": 2}}
    request["sector"] = {"charge": charge, "ms2": ms2}
    request["settings"] = {"nroots": 1}
    original = Path("hamiltonian.fcidump").read_bytes()
    result = execute("solve-full", request)
    assert result["nelec"] == expected
    assert result["sector"] == request["sector"]
    assert Path("hamiltonian.fcidump").read_bytes() == original


def test_circuits_cannot_cross_solver_sectors(tmp_path, monkeypatch):
    pytest.importorskip("qiskit_fermions")
    request = model(tmp_path, monkeypatch)
    request["native_export"] = {"charge": 0, "active_space": {"electrons": 2}}
    request["sector"] = {"charge": 0, "ms2": 0}
    request["settings"] = {"times": [1.0], "randomizations": 1, "groups": 1}
    request["circuit_manifest"] = execute("generate", request)
    request["sector"] = {"charge": 1, "ms2": 1}
    request["settings"] = {"shots": 100}
    with pytest.raises(ValueError, match="different electron/spin sector"):
        execute("sample-simulator", request)


def test_initial_occupations_are_used_without_changing_active_space(
    tmp_path, monkeypatch
):
    pytest.importorskip("qiskit_fermions")
    request = model(tmp_path, monkeypatch)
    request["settings"] = {
        "times": [1e-8],
        "randomizations": 1,
        "groups": 1,
        "initial_alpha": [1],
        "initial_beta": [0],
    }
    circuits = execute("generate", request)
    assert circuits["initial_occupations_local"] == {"alpha": [1], "beta": [0]}
    request["circuit_manifest"] = circuits
    request["settings"] = {"shots": 100, "seed": 42}
    execute("sample-simulator", request)
    packet = json.loads(Path("samples.json").read_text())
    assert packet["counts"] == {"0110": 100}
