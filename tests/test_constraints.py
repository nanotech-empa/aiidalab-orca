"""Scientific constraints, atom numbering, provenance reuse and UI invalidation."""

import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca.calculation import OptimizationCalculation
from aiida_empa_orca.constraints import normalize_constraints, validate_constraints
from aiida_empa_orca.input import preview_input
from aiida_empa_orca.protocols import protocol_settings
from aiida_empa_orca.settings import normalize_settings, orca_parameters, signature, validate_molecule
from aiida_empa_orca.workchains import plan_geometry
from test_reuse import source  # shared disposable provenance fixture


def settings(constraints):
    return normalize_settings(protocol_settings(overrides={"constraints": constraints}))


def test_constraints_are_scientific_inputs_and_empty_preserves_reuse(source):
    structure, code = source.inputs.structure, source.inputs.code
    assert plan_geometry(structure, settings([]), code)["action"] == "reuse"
    frozen = settings([{"kind": "cartesian", "atoms": [0]}])
    assert plan_geometry(structure, frozen, code)["action"] == "compute"
    assert signature(structure, frozen, code.uuid) != signature(structure, settings([]), code.uuid)
    # Equivalent grouping/order must not trigger an unnecessary calculation.
    a = settings([{"kind": "cartesian", "atoms": [1, 0], "components": "xy"}])
    b = settings([{"kind": "cartesian", "atoms": [0], "components": "yx"},
                  {"kind": "cartesian", "atoms": [1], "components": "x"},
                  {"kind": "cartesian", "atoms": [1], "components": "y"}])
    assert signature(structure, a, code.uuid) == signature(structure, b, code.uuid)
    for kind, indices in [("distance", [0, 1]), ("angle", [0, 1, 2]), ("dihedral", [0, 1, 2, 3])]:
        assert normalize_constraints([{"kind": kind, "atoms": indices}]) == normalize_constraints([
            {"kind": kind, "atoms": indices[::-1]}])
    assert signature(structure, settings([{"kind": "distance", "atoms": [0, 1], "value": 1.2}]), code.uuid) != signature(
        structure, settings([{"kind": "distance", "atoms": [0, 1], "value": 1.3}]), code.uuid)


@pytest.mark.parametrize("constraint", [
    {"kind": "cartesian", "atoms": [-1]},
    {"kind": "cartesian", "atoms": [True]},
    {"kind": "cartesian", "atoms": [0], "components": "q"},
    {"kind": "cartesian", "atoms": [0], "value": 0},
    {"kind": "distance", "atoms": [0, 0]},
    {"kind": "angle", "atoms": [0, 1]},
    {"kind": "distance", "atoms": [0, 1], "value": -1},
    {"kind": "distance", "atoms": [0, 1], "value": float("nan")},
    {"kind": "angle", "atoms": [0, 1, 2], "value": 181},
    {"kind": "dihedral", "atoms": [0, 1, 2, 3], "value": "180 end"},
    {"kind": "other", "atoms": [0]},
])
def test_invalid_constraints_fail_before_submission(constraint):
    with pytest.raises(ValueError):
        settings([constraint])


def test_constraint_geometry_and_expert_conflicts(aiida_profile):
    atoms = Atoms("NO", positions=[[0, 0, 0], [0, 0, 1.3]])
    structure = orm.StructureData(ase=atoms)
    with pytest.raises(ValueError, match="absent atom"):
        validate_molecule(structure, settings([{"kind": "cartesian", "atoms": [2]}]))
    with pytest.raises(ValueError, match="All Cartesian"):
        validate_molecule(structure, settings([{"kind": "cartesian", "atoms": [0, 1]}]))
    with pytest.raises(ValueError, match="Repeated distance"):
        settings([{"kind": "distance", "atoms": [0, 1]}, {"kind": "distance", "atoms": [1, 0], "value": 1.2}])
    with pytest.raises(ValueError, match="only Cartesian constraints"):
        normalize_settings(protocol_settings(overrides={"constraints": [{"kind": "distance", "atoms": [0, 1]}],
                                                       "block_parameters": {"geom": {"CoordSys": "Cartesian"}}}))
    with pytest.raises(ValueError, match="dedicated control"):
        normalize_settings(protocol_settings(overrides={"block_parameters": {"geom": {"invertConstraints": True}}}))
    with pytest.raises(ValueError, match="undefined"):
        validate_constraints(Atoms("CCCC", positions=[[0, 0, i] for i in range(4)]),
                             [{"kind": "dihedral", "atoms": [0, 1, 2, 3]}])


def test_constraint_preview_matches_stored_calcjob(aiida_profile, aiida_localhost, aiida_manager):
    # Non-collinear atoms exercise all directive types and storage precision.
    structure = orm.StructureData(ase=Atoms("CHHH", positions=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]]))
    s = settings([{"kind": "cartesian", "atoms": [0]},
                  {"kind": "cartesian", "atoms": [1], "components": "yz"},
                  {"kind": "distance", "atoms": [1, 2], "value": 1.12345678901234567},
                  {"kind": "angle", "atoms": [0, 1, 2]},
                  {"kind": "dihedral", "atoms": [0, 1, 2, 3], "value": -60}])
    validate_molecule(structure, s)
    preview = preview_input(structure, s)
    builder = OptimizationCalculation.get_builder()
    builder.code = orm.InstalledCode(computer=aiida_localhost, filepath_executable="/bin/true").store()
    builder.structure = structure
    builder.parameters = orm.Dict(dict=orca_parameters(orm.Dict(dict=s).store().get_dict())).store()
    builder.maxcore_mb = orm.Int(768)
    builder.metadata.options.resources = {"num_machines": 1, "num_mpiprocs_per_machine": 2}
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        with SandboxFolder() as folder:
            process.prepare_for_submission(folder)
            for name, expected in preview.items():
                with open(folder.get_abs_path(name)) as stream:
                    assert stream.read() == expected
        text = preview["aiida.inp"]
        for directive in ("{ C 0 C }", "{ Y 1 C }", "{ Z 1 C }", "{ A 0 1 2 C }", "{ D 0 1 2 3 -60.0 C }"):
            assert directive in text
        assert "Constraints" in text and "MaxIter" in text
    finally:
        process.close()


def test_ui_selection_copy_geometry_changes_and_keep_mode(source, monkeypatch):
    from aiidalab_orca import services
    from aiidalab_orca.app import OrcaApp
    from aiidalab_orca.viewer import settings_details
    monkeypatch.setattr(services, "codes", lambda: [("Test ORCA", source.inputs.code.uuid)])
    app = OrcaApp()
    try:
        app.structure.example.click()
        app._confirm_structure()
        app._confirm_settings()
        app._review()
        assert app.review["plan"]["action"] == "reuse"
        editor = app.structure.constraints
        app.structure.viewer.selection = [0]
        editor.freeze.click()
        assert editor.rows[0][2].value == "1"  # Visible indices start at one.
        assert app.review is None and not app._settings_confirmed
        app._confirm_settings()
        app._review()
        assert app.review["plan"]["action"] == "compute"
        assert "{ C 0 C }" in app.review["input_files"]["aiida.inp"]
        assert "Atom 1: freeze xyz" in settings_details(app.review["settings"])
        # Applying a scientific protocol must not remove molecular constraints.
        app.science._apply()
        assert editor.values() == [{"kind": "cartesian", "atoms": [0], "components": "xyz"}]
        saved = app._settings()
        # Even an edit with the same species/count can reorder identical atoms.
        changed = app.structure.atoms.copy()
        changed.positions[1, 2] = 1.4
        app.structure.editor.structure = changed
        app._confirm_structure()
        app._confirm_settings()
        assert not app._settings_confirmed and "confirm constraints" in app.science_message.value
        editor.confirm.click()
        app._confirm_settings()
        assert app._settings_confirmed
        monkeypatch.setattr("aiidalab_orca.app.inspect_run", lambda _: {
            "settings": saved, "optimize": True, "code_uuid": source.inputs.code.uuid})
        app.copy_settings(source.uuid)
        assert app.steps.selected_index == 0 and editor._needs_confirmation
        editor.confirm.click()
        assert editor.values() == saved["constraints"]
        # Keep-as-is ignores even incomplete constraints, without erasing them.
        editor.append()
        app.optimize.value = False
        app._confirm_structure()
        app._confirm_settings()
        app._review()
        assert app.review["plan"]["action"] == "keep"
    finally:
        app.close()


def test_ui_ranges_and_internal_atom_order(aiida_profile):
    from aiidalab_orca.structures import StructureWidget
    widget = StructureWidget()
    try:
        widget.set_atoms(Atoms("CHHH", positions=[[0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]]))
        editor = widget.constraints
        editor.append()
        row, kind, indices, target, current = editor.rows[0]
        indices.value = "1 3..4"
        assert [c["atoms"] for c in editor.values()] == [[0], [2], [3]]
        for invalid in ("0", "4..2", "1 20", "2..999999999"):
            indices.value = invalid
            with pytest.raises(ValueError):
                editor.values()
        kind.value = "angle"
        indices.value = "1 3 2"
        target.value = "105.5"
        assert editor.values() == [{"kind": "angle", "atoms": [0, 2, 1], "value": 105.5}]
        target.value = ""
        assert "value" not in editor.values()[0]
        assert "Current: 45.00°" in current.value
        # The measurement remains independent of the requested target.
        target.value = "100"
        assert "Current: 45.00°" in current.value
        kind.value = "distance"
        indices.value = "1 2"
        assert "Current: 1.0000 Å" in current.value
        changed = widget.atoms.copy()
        changed.positions[1, 0] = 1.2
        widget.editor.structure = changed
        assert "Current: 1.2000 Å" in current.value
        kind.value = "angle"
        indices.value = "1 2 3"
        assert "Current: 78.69°" in current.value
        kind.value = "dihedral"
        indices.value = "1 2 3 4"
        assert "Current: 90.00°" in current.value
        changed.positions[3, 2] = -1
        widget.editor.structure = changed
        assert "Current: -90.00°" in current.value
        indices.value = "1 2 3 99"
        assert "Current: unavailable" in current.value
        changed.positions[2] = [2.4, 0, 0]
        widget.editor.structure = changed
        indices.value = "1 2 3 4"
        assert "Current: unavailable" in current.value
        kind.value = "xyz"
        indices.value = "1"
        target.value = "123"  # A hidden previous target cannot change Cartesian semantics.
        editor.confirm.click()
        assert "value" not in editor.values()[0]
    finally:
        widget.close()
