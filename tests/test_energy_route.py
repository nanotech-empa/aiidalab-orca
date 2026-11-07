import pytest

from aiidalab_orca.energy_route import assess_space, matched_levels
from aiidalab_orca.energy_view import EnergyRoutes


def test_open_shell_size_and_warning():
    size = assess_space(7, list(range(40, 47)), 2)
    assert (size["alpha"], size["beta"], size["qubits"]) == (4, 3, 14)
    assert size["fixed_ms_dimension"] == 1225
    assert not size["large_example"]
    assert assess_space(8, list(range(8)), 1)["large_example"]
    with pytest.raises(ValueError, match="incompatible"):
        assess_space(7, list(range(7)), 1)


def test_export_belongs_only_to_quantum_route():
    calls = []
    widget = EnergyRoutes(
        "reference-uuid",
        {"source_multiplicity": 2},
        {"electrons": 7, "orbitals": list(range(40, 47))},
        lambda: calls.append("orca"),
        lambda: calls.append("quantum"),
    )
    try:
        assert calls == []
        assert "No separate Hamiltonian export" in widget.explanation.value
        widget.continue_button.click()
        assert calls == ["orca"]
        widget.choice.value = "quantum"
        assert calls == ["orca"]
        assert "must not solve the full CASCI" in widget.explanation.value
        widget.continue_button.click()
        assert calls == ["orca", "quantum"]
    finally:
        widget.close()


def test_same_cas_size_does_not_establish_comparability():
    data = {
        "hamiltonian_sha256": "a",
        "orbital_reference_uuid": "ref",
        "active_space": {"electrons": 7, "orbitals": list(range(7))},
        "charge": 0,
        "energy_unit": "hartree",
    }
    assert matched_levels(data, dict(data))
    with pytest.raises(ValueError, match="same Hamiltonian"):
        matched_levels(data, data | {"hamiltonian_sha256": "b"})


def test_quantum_workspace_does_not_submit_on_open_or_review(monkeypatch):
    from aiidalab_orca import quantum_energy

    calls = []
    reference = {
        "source_multiplicity": 2,
        "charge": 0,
        "settings": {"basis": "def2-TZVP"},
    }
    monkeypatch.setattr(
        quantum_energy.casci_services, "reference_data", lambda _: reference
    )
    monkeypatch.setattr(quantum_energy.service, "models", lambda *args: [])
    monkeypatch.setattr(quantum_energy.service, "resources", lambda _: [])
    monkeypatch.setattr(
        quantum_energy.service, "submit", lambda plan: calls.append(plan)
    )
    widget = quantum_energy.QuantumEnergy(
        "ref", {"electrons": 7, "orbitals": list(range(7))}
    )
    try:
        assert calls == []
        widget._choose("export")
        assert "Configure an energy worker" in widget.review.value
        assert widget.submit_button.disabled and calls == []
        widget.mode.value = "hardware"
        assert widget.hardware_box.layout.display == ""
        assert widget.hardware_ok.value is False and calls == []
    finally:
        widget.close()


def test_large_computations_are_blocked_at_review():
    from aiidalab_orca.energy_route import review_budget

    native = {
        "active_space": {"electrons": 32, "orbitals": list(range(32))},
        "multiplicity": 1,
    }
    with pytest.raises(ValueError, match="qubit cap"):
        review_budget(native, "sample-simulator", {"max_qubits": 20}, 4096)
    with pytest.raises(ValueError, match="dimension cap"):
        review_budget(native, "solve-full", {"max_dimension": 100000}, 4096)


def test_quantum_guide_is_packaged_and_provider_independent():
    from aiidalab_orca.energy_guidance import workflow_guides

    guides = workflow_guides()
    assert [guide["id"] for guide in guides] == ["orca.quantum-energy"]
    text = guides[0]["text"]
    assert "No separate Hamiltonian export" in text
    assert "blind resubmission" in text
    assert "Fixed Ms does not determine total S" in text


def test_confirmed_cas_branches_without_submitting_or_losing_navigation(monkeypatch):
    import ipywidgets as ipw
    from aiidalab_orca import casci, viewer, quantum_energy
    from aiidalab_orca.presentation import ComputePanel
    from test_result_navigation import reference_data

    reference = {
        "n_electrons": 87,
        "n_orbitals": 100,
        "source_multiplicity": 2,
        "charge": 0,
    }
    monkeypatch.setattr(viewer, "molecule", lambda *args: ipw.Label("Geometry"))
    monkeypatch.setattr(casci.service, "reference_data", lambda _: reference)

    class StatePanel(ipw.VBox):
        def __init__(self, data, **kwargs):
            self.reference = ipw.Dropdown(options=[("Prepared QROs", "common")])
            self.electrons, self.norb = ipw.IntText(value=7), ipw.IntText(value=7)
            self.analysis = ipw.ToggleButtons(options=[("States", "states")])
            self._datasets, self._dyson = [], None
            self.calculation = ComputePanel("CASCI", [])
            super().__init__([self.analysis, self.calculation])

    opened = []

    def quantum(uid, space):
        opened.append((uid, space))
        return ipw.Label("Quantum workspace")

    monkeypatch.setattr(casci, "CasciStates", StatePanel)
    monkeypatch.setattr(quantum_energy, "QuantumEnergy", quantum)
    result = viewer.show_result(reference_data())
    try:
        result.tabs.show_section("states")
        result.confirmed_space = ("common", 7, 7)
        route = result.open_analysis("energy")
        route.continue_button.click()
        assert result.navigation.value == "casci" and opened == []
        result.open_analysis("energy")
        route.choice.value = "quantum"
        route.continue_button.click()
        assert result.navigation.value == "quantum_energy"
        assert opened == [("common", {"electrons": 7, "orbitals": list(range(40, 47))})]
        result.navigation.value = "energy"
        assert result.tabs.panels["energy"] is route
    finally:
        result.close()


def test_sector_choice_filters_saved_stages_and_is_reviewed_without_export(monkeypatch):
    from aiidalab_orca import quantum_energy

    calls = []
    stage_filters = []
    reference = {
        "source_multiplicity": 2,
        "charge": 0,
        "settings": {"basis": "def2-TZVP"},
    }
    monkeypatch.setattr(
        quantum_energy.casci_services, "reference_data", lambda _: reference
    )
    monkeypatch.setattr(
        quantum_energy.service,
        "models",
        lambda *args: [
            {
                "uuid": "model",
                "finished_ok": True,
                "state": "finished",
                "created": "2026-11-04",
                "label": "Saved Hamiltonian",
            }
        ],
    )

    monkeypatch.setattr(quantum_energy.service, "orca_comparisons", lambda *args: [])

    def stages(uid, operation, sector):
        stage_filters.append(dict(sector))
        return []

    monkeypatch.setattr(quantum_energy.service, "stages", stages)
    monkeypatch.setattr(
        quantum_energy.service,
        "resources",
        lambda _: [{"uuid": "worker", "label": "CPU worker", "computer": "localhost"}],
    )
    monkeypatch.setattr(
        quantum_energy.service, "submit", lambda plan: calls.append(plan)
    )

    def prepare(uid, operation, settings, code, **kwargs):
        calls.append((operation, kwargs["sector"]))
        return {
            "operation": operation,
            "settings": settings,
            "sector": kwargs["sector"],
            "sector_electrons": 6,
        }

    monkeypatch.setattr(quantum_energy.service, "prepare_stage", prepare)
    monkeypatch.setattr(
        quantum_energy.service,
        "prepare_export",
        lambda *args: pytest.fail("Sector selection must not rerun export"),
    )
    widget = quantum_energy.QuantumEnergy(
        "ref", {"electrons": 7, "orbitals": list(range(7))}
    )
    try:
        widget.charge.value = 1
        widget.mult.value = 1
        assert stage_filters[-1] == {"charge": 1, "ms2": 0}
        widget._choose("solve-full")
        assert calls and all(
            call == ("solve-full", {"charge": 1, "ms2": 0}) for call in calls
        )
        assert "6 active electrons" in widget.review.value
        assert "minimum multiplicity 1" in widget.review.value
        assert widget.submit_button.disabled is False
    finally:
        widget.close()


def test_solver_labels_distinguish_orca_exported_and_sampled_operations():
    from aiidalab_orca.quantum_energy import QuantumEnergy
    from aiidalab_orca.energy_route import STAGE_LABELS

    assert STAGE_LABELS["solve-full"] == "PySCF: full exported Hamiltonian"
    assert "selected subspace" in STAGE_LABELS["solve-sampled"]
    assert (
        QuantumEnergy._solver_label({"samples_execution_kind": None})
        == "PySCF — full exported Hamiltonian"
    )
    assert (
        QuantumEnergy._solver_label(
            {"samples_execution_kind": "ideal_statevector_simulator"}
        )
        == "PySCF — simulator-selected subspace"
    )


def test_insufficient_sampling_is_flagged_before_comparing_cas_levels():
    from aiidalab_orca.quantum_energy import QuantumEnergy

    result = {
        "selection": {},
        "dimension": 1,
        "used_roots": 1,
        "requested_roots": 4,
        "nelec": [1, 1],
        "native_export": {"active_space": {"orbitals": [3, 4]}},
    }
    warning = QuantumEnergy._coverage_notice(result)
    assert "Insufficient sampled space" in warning
    assert "dimension 1 of 4" in warning
    assert "cannot supply the requested spectrum" in warning
    result.update(dimension=4, used_roots=4)
    assert "complete selected Mₛ sector" in QuantumEnergy._coverage_notice(result)
    result.update(dimension=1, used_roots=1, nelec=[2, 0])
    assert "Insufficient" not in QuantumEnergy._coverage_notice(result)


def test_orca_overlay_requires_exact_scientific_context():
    from copy import deepcopy
    from aiidalab_orca.energy_route import orca_comparison

    space = {"electrons": 3, "orbitals": [6, 7]}
    native = {
        "orbital_reference_uuid": "ref",
        "reference_active_space": space,
        "integral_transform": "RI",
        "auxiliary_basis": "def2-SVP/C",
    }
    summary = {
        "orbital_reference_uuid": "ref",
        "structure_uuid": "geometry",
        "active_space": space,
        "model": {"integral_transform": "RI", "auxiliary_basis": "def2-SVP/C"},
        "geometry_mode": "fixed",
        "method": "CASCI",
        "energy_unit": "hartree",
        "states": [
            {"root": 0, "charge": 0, "multiplicity": 2, "energy_hartree": -100.0}
        ],
    }
    args = {
        "input_reference_uuid": "ref",
        "input_space": space,
        "input_settings": {
            "charge": 0,
            "multiplicity": 2,
            "nroots": 1,
            "auxiliary_basis": "def2-SVP/C",
        },
        "structure_uuid": "geometry",
    }
    result = orca_comparison(native, {"charge": 0, "ms2": 1}, summary, **args)
    assert (
        result["origin"] == "orca_casci"
        and result["levels"][0]["energy_hartree"] == -100.0
    )
    assert "hamiltonian_sha256" not in result
    for key, value in [
        ("orbital_reference_uuid", "other"),
        ("structure_uuid", "relaxed"),
        ("active_space", {"electrons": 1, "orbitals": [7]}),
        ("model", {"integral_transform": "RI", "auxiliary_basis": "AutoAux"}),
    ]:
        bad = deepcopy(summary)
        bad[key] = value
        with pytest.raises(ValueError, match="same orbitals"):
            orca_comparison(native, {"charge": 0, "ms2": 1}, bad, **args)
    with pytest.raises(ValueError, match="same orbitals"):
        orca_comparison(native, {"charge": 1, "ms2": 0}, summary, **args)
    with pytest.raises(ValueError, match="multiplicity"):
        orca_comparison(native, {"charge": 0, "ms2": 3}, summary, **args)


def test_orca_plot_and_energy_differences_do_not_shift_total_energies():
    from aiidalab_orca.quantum_energy import QuantumEnergy

    reference = {
        "origin": "orca_casci",
        "multiplicity": 2,
        "selection": None,
        "levels": [{"root": 0, "multiplicity": 2, "energy_hartree": -100.0}],
    }
    result = {
        "samples_execution_kind": "ideal_statevector_simulator",
        "selection": {},
        "levels": [{"root": 0, "spin_squared": 0.75, "energy_hartree": -99.9}],
    }
    text = QuantumEnergy._orca_comparison_table(result, reference)
    assert "1.000e-01 Hartree" in text
    assert "without alignment shifts" in text
    assert "ORCA CASCI" in QuantumEnergy._solver_label(reference)
    assert "Existing saved calculation" in QuantumEnergy._level_table(reference)


def test_solver_review_distinguishes_new_and_legacy_worker_support():
    from aiidalab_orca.energy_route import review_budget, review_worker_solver
    from aiidalab_orca.quantum_energy import QuantumEnergy

    native = {
        "active_space": {"electrons": 7, "orbitals": list(range(7))},
        "multiplicity": 2,
    }
    size = review_budget(native, "solve-sampled", {"nroots": 8}, 4096)
    assert size["fixed_ms_dimension"] == 1225
    with pytest.raises(ValueError, match="legacy worker supports at most 4"):
        review_worker_solver({}, "solve-sampled", {"nroots": 8}, size)
    current = {
        "resource_bounded_roots": True,
        "polarized_sampled_sectors": True,
        "empty_sampled_sector": True,
    }
    review_worker_solver(current, "solve-sampled", {"nroots": 8}, size)
    polarized = {
        "active_space": {"electrons": 2, "orbitals": [3, 4]},
        "multiplicity": 3,
    }
    size = review_budget(polarized, "solve-sampled", {"nroots": 1}, 4096)
    with pytest.raises(ValueError, match="legacy sampled-space worker"):
        review_worker_solver({}, "solve-sampled", {"nroots": 1}, size)
    review_worker_solver(current, "solve-sampled", {"nroots": 1}, size)
    previous = {
        "selection": {},
        "dimension": 1225,
        "used_roots": 4,
        "requested_roots": 8,
        "nelec": [4, 3],
        "native_export": {"active_space": {"orbitals": list(range(7))}},
    }
    notice = QuantumEnergy._coverage_notice(previous)
    assert (
        "at most four levels" in notice and "Insufficient sampled space" not in notice
    )
    previous["software"] = {"capabilities": current}
    assert "Insufficient sampled space" in QuantumEnergy._coverage_notice(previous)
    previous["used_roots"] = 8
    assert "at most four levels" not in QuantumEnergy._coverage_notice(previous)
    assert "Insufficient sampled space" not in QuantumEnergy._coverage_notice(previous)


def test_quantum_helper_preserves_existing_app_guides_without_duplicates(monkeypatch):
    from aiidalab_orca import guidance, energy_guidance

    base = [{"id": "orca.app", "text": "Existing app instructions"}]
    monkeypatch.setattr(guidance, "workflow_guides", lambda: list(base))
    guides = energy_guidance.combined_workflow_guides()
    assert [guide["id"] for guide in guides] == ["orca.app", "orca.quantum-energy"]
    assert guides[0]["text"] == "Existing app instructions"
    base.append(energy_guidance.workflow_guides()[0])
    assert len(energy_guidance.combined_workflow_guides()) == 2
