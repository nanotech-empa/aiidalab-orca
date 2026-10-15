"""Contracts between protocol choices, provenance reuse, preview and submission."""

import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca.calculation import OptimizationCalculation
from aiida_empa_orca.input import preview_input, render_input
from aiida_empa_orca.protocols import editable_settings, protocol_settings
from aiida_empa_orca.settings import normalize_settings, orca_parameters, signature, validate_molecule
from aiida_empa_orca.workchains import plan_geometry
from test_reuse import source  # shared finished-run fixture


def test_yaml_defaults_and_legacy_compatibility(source):
    legacy = source.inputs.settings.get_dict()
    modern = normalize_settings(protocol_settings())
    assert orca_parameters(legacy) == orca_parameters(modern)
    structure, code = source.inputs.structure, source.inputs.code
    assert plan_geometry(structure, modern, code)["action"] == "reuse"
    # Protocol identity is context; effective inputs determine compatibility.
    same = protocol_settings("pbe0-v1", {"method": "PBE"})
    assert signature(structure, same, code.uuid) == signature(structure, modern, code.uuid)
    for change in ({"reference": "UHF", "method": "HF"}, {"grid": "DEFGRID3"},
                   {"scf_convergence": "VeryTightSCF"}, {"optimization": "VeryTightOpt"},
                   {"element_settings": {"N": {"basis": "def2-TZVP"}}},
                   {"block_parameters": {"scf": {"TolE": 1e-9}}}):
        assert plan_geometry(structure, protocol_settings(overrides=change), code)["action"] == "compute"
    detached = protocol_settings()
    detached["element_settings"]["N"] = {"basis": "def2-TZVP"}
    assert not protocol_settings()["element_settings"]


@pytest.mark.parametrize("overrides,message", [
    ({"reference": "RKS"}, "multiplicity 1"),
    ({"reference": "UHF"}, "RHF/UHF"),
    ({"method": "B97"}, "explicitly"),
    ({"block_parameters": {"method": {"ScalHFX": .3}}}, "explicitly"),
    ({"block_parameters": {"scf": {"MAXITER": 1}}}, "dedicated control"),
    ({"block_parameters": {"scf": {"Guess": "MORead"}}}, "dedicated control"),
    ({"block_parameters": {"scf": {"TolE": float("nan")}}}, "finite"),
    ({"basis": "def2-SVP\n! Freq"}, "one ORCA name"),
])
def test_conflicts_fail_before_submission(overrides, message):
    with pytest.raises(ValueError, match=message):
        normalize_settings(protocol_settings(overrides=overrides))


@pytest.mark.parametrize("method,ri", [
    ("bp86", "RI"), ("R2SCAN", "RI"), ("SCANFUNC", "RI"),
    ("TPSSH", "RIJCOSX"), ("CAM-B3LYP", "RIJCOSX"), ("HF", "RIJCOSX"),
])
def test_suggested_method_exchange_treatment(method, ri):
    settings = protocol_settings(overrides={"method": method})
    keywords = orca_parameters(settings)["input_keywords"]
    assert ri in keywords and "def2/J" in keywords
    assert ("UHF" if method == "HF" else "UKS") in keywords
    assert {"RI", "RIJCOSX", "NoRI"}.intersection(keywords) == {ri}
    # An explicit expert choice still takes precedence.
    keywords = orca_parameters(settings | {"approximation": "NoRI"})["input_keywords"]
    assert "NoRI" in keywords and "def2/J" not in keywords
    # A customized exchange fraction must not inherit that classification.
    with pytest.raises(ValueError, match="explicitly"):
        normalize_settings(settings | {"block_parameters": {"method": {"ScalHFX": .3}}})


def test_documented_choices_review_and_copy(source, monkeypatch):
    from aiidalab_orca import services
    from aiidalab_orca.app import OrcaApp
    monkeypatch.setattr(services, "codes", lambda: [("Test ORCA", source.inputs.code.uuid)])
    app = OrcaApp()
    try:
        app.structure.example.click()
        app._confirm_structure()
        science = app.science
        science.method.value = "R2SCAN"
        science.basis.value = "ma-def2-SVP"
        science.scf_convergence.value = "VeryTightSCF"
        science.convergence.value = "VeryTightOpt"
        science.dispersion.value = "D3ZERO"
        app._confirm_settings()
        app._review()
        assert app.review["plan"]["action"] == "compute"
        preview = app.review["input_files"]["aiida.inp"]
        for keyword in ("R2SCAN", "ma-def2-SVP", "RI", "VeryTightSCF", "VeryTightOpt", "D3ZERO"):
            assert keyword in preview.split()
        copied = app.review["settings"]
        science._apply()
        assert science.scf_convergence.value == "TightSCF"
        assert science.convergence.value == "NormalOpt"
        science.set_values(copied)
        app._confirm_settings()
        app._review()
        assert app.review["input_files"]["aiida.inp"] == preview
        # Both threshold controls are visible before opening Advanced.
        assert science.convergence in science.optimization_controls.children
        assert science.scf_convergence in science.optimization_controls.children
        # A typed name outside the suggestions still works with explicit RI.
        science.method.value = "B97"
        science.approximation.value = "RIJCOSX"
        science.basis.value = "6-31G(d,p)"
        science.dispersion.value = "default"
        app._confirm_settings()
        app._review()
        assert "B97 6-31G(d,p)" in app.review["input_files"]["aiida.inp"]
    finally:
        app.close()


def test_custom_model_preview_is_calcjob_input(aiida_profile, aiida_localhost, aiida_manager):
    structure = orm.StructureData(ase=Atoms("NO", positions=[[0, 0, 0], [0, 0, 1.3]]))
    settings = normalize_settings(protocol_settings(overrides={
        "method": "BP86", "approximation": "RI", "basis": "6-31G*", "reference": "UKS",
        "element_settings": {"N": {"basis": "def2-TZVP", "ecp": "none"}},
        "block_parameters": {"scf": {"TolE": 1e-8}},
    }))
    validate_molecule(structure, settings)
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable="/bin/true").store()
    builder = OptimizationCalculation.get_builder()
    builder.structure, builder.code = structure, code
    builder.parameters = orm.Dict(dict=orca_parameters(settings))
    builder.maxcore_mb = orm.Int(768)
    builder.metadata.options.resources = {"num_machines": 1, "num_mpiprocs_per_machine": 2}
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        with SandboxFolder() as folder:
            process.prepare_for_submission(folder)
            for filename, expected in preview_input(structure, settings).items():
                with open(folder.get_abs_path(filename)) as stream:
                    assert stream.read() == expected
        content = preview_input(structure, settings)["aiida.inp"]
        assert 'NewGTO N "def2-TZVP" end' in content
        assert "DelECP N" in content and "tole 1e-08" in content
        params = orca_parameters(settings)
        params["input_blocks"] = {k: dict(reversed(list(v.items())))
                                  for k, v in reversed(list(params["input_blocks"].items()))}
        assert render_input(params, 768, "aiida.coords.xyz") == content
    finally:
        process.close()
    settings["element_settings"]["Fe"] = {"basis": "def2-TZVP"}
    with pytest.raises(ValueError, match="absent"):
        validate_molecule(structure, settings)


def test_expert_controls_copy_reset_and_invalidate(source, monkeypatch):
    from aiidalab_orca import services
    from aiidalab_orca.app import OrcaApp
    monkeypatch.setattr(services, "codes", lambda: [("Test ORCA", source.inputs.code.uuid)])
    app = OrcaApp()
    try:
        app.structure.example.click()
        app._confirm_structure()
        app._confirm_settings()
        app._review()
        assert app.review["plan"]["action"] == "reuse"
        assert "aiida.inp" in app.review["input_files"]
        app.science.parameters.append(["scf", "TolE", "1e-8"])
        assert app.review is None and not app._settings_confirmed
        app.science.elements.append(["N", "def2-TZVP", "", "none"])
        app._confirm_settings()
        app._review()
        assert app.review["plan"]["action"] == "compute"
        saved = app.review["settings"]
        app.science.set_values(saved)
        assert editable_settings(app.science.values())["element_settings"] == saved["element_settings"]
        app.memory.value = 4096
        app.charge.value = 1
        app.multiplicity.value = 1
        app.science.protocol.value = "pbe0-v1"
        app.science._apply()
        assert app.method.value == "PBE0"
        assert app.memory.value == 4096 and app.charge.value == 1 and app.multiplicity.value == 1
        assert not app.science.elements.values() and not app.science.parameters.values()
        # SCF still validates its active scientific settings.
        app.science.parameters.append(["scf", "TolE", ""])
        app.optimize.value = False
        app._confirm_settings()
        assert not app._settings_confirmed
        assert "Complete both" in app.science_message.value
    finally:
        app.close()
