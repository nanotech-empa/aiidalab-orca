import pytest
from aiida import orm
from aiida.engine import run_get_node
from ase import Atoms

from aiida_empa_orca.parser import optimization_converged
from aiida_empa_orca.settings import normalize_settings, orca_parameters, signature, validate_molecule
from aiida_empa_orca.workchains import GeometryWorkChain, get_builder


@pytest.fixture
def no(aiida_profile):
    return orm.StructureData(ase=Atoms("NO", positions=[[0, 0, 0], [0, 0, 1.3]]))


def test_spin_and_geometry_validation(no):
    validate_molecule(no, normalize_settings({"multiplicity": 2}))
    with pytest.raises(ValueError, match="15 electrons"):
        validate_molecule(no, normalize_settings({"multiplicity": 1}))
    no.pbc = (False, False, True)
    with pytest.raises(ValueError, match="periodic"):
        validate_molecule(no, normalize_settings({}))


def test_explicit_input_and_exact_reuse_signature(no):
    params = orca_parameters({})
    assert "UKS" in params["input_keywords"] and "RI" in params["input_keywords"]
    assert params["charge"] == 0 and params["multiplicity"] == 2
    base = signature(no, {}, "code-a")
    assert base != signature(no, {"method": "PBE0"}, "code-a")
    assert base != signature(no, {}, "code-b")
    assert base != signature(orm.StructureData(ase=Atoms("ON", positions=[[0,0,1.3],[0,0,0]])), {}, "code-a")


def test_reject_misspelled_settings_and_invalid_memory():
    with pytest.raises(ValueError, match="Unknown"):
        normalize_settings({"multiplcity": 2})
    with pytest.raises(ValueError, match="256 MB"):
        normalize_settings({"memory_mb": 512, "nprocs": 4})


def test_normal_termination_is_not_convergence():
    assert not optimization_converged("The optimization did not converge\nORCA TERMINATED NORMALLY")
    assert optimization_converged("THE OPTIMIZATION HAS CONVERGED\nORCA TERMINATED NORMALLY")


def test_keep_geometry_has_provenance_and_no_calculation(no):
    outputs, process = run_get_node(get_builder(no, {}, optimize=False))
    assert process.is_finished_ok
    assert outputs["structure"].uuid == process.inputs.structure.uuid
    assert not process.called_descendants
    assert "optimization_summary" not in outputs


def test_forced_recompute_bypasses_child_cache(no, aiida_localhost, aiida_manager):
    from aiida.engine.utils import instantiate_process
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable="/bin/true").store()
    builder = get_builder(no, {}, code, force_recompute=True)
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        assert process.setup() is None
        captured = []
        def submit(child):
            captured.append(child)
            return orm.WorkChainNode().store()
        process.submit = submit
        process.run_optimization()
        assert captured[0].orca.metadata.disable_cache is True
        assert captured[0].orca.metadata.options.withmpi is False
        assert captured[0].orca.maxcore_mb.value == 768
    finally:
        process.close()
