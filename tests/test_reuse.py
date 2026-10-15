import io

import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.engine import ProcessState, run_get_node
from ase import Atoms

from aiida_empa_orca.reuse import PROCESS_TYPE, validate_result
from aiida_empa_orca.settings import normalize_settings, signature
from aiida_empa_orca.workchains import get_builder, plan_geometry


@pytest.fixture
def source(aiida_profile_clean, aiida_localhost):
    """Disposable provenance fixture with real repository objects."""
    node = orm.WorkChainNode(process_type=PROCESS_TYPE)
    structure = orm.StructureData(ase=Atoms("NO", positions=[[0,0,0],[0,0,1.3]])).store()
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable="/bin/true").store()
    for name, value in {"structure": structure, "code": code, "settings": orm.Dict(dict=normalize_settings({})),
                        "optimize": orm.Bool(True)}.items():
        value.store()
        node.base.links.add_incoming(value, link_type=LinkType.INPUT_WORK, link_label=name)
    node.store()
    final = structure.clone().store()
    trajectory = orm.TrajectoryData()
    trajectory.set_trajectory(stepids=np.array([0]), symbols=["N","O"], positions=np.array([[[0.,0.,0.],[0.,0.,1.3]]]))
    retrieved = orm.FolderData()
    for filename in ("aiida.out", "aiida.xyz", "aiida_trj.xyz"):
        retrieved.base.repository.put_object_from_filelike(io.StringIO("unit test artifact\n"), filename)
    for name, value in {"structure": final, "trajectory": trajectory, "retrieved": retrieved,
                        "optimization_summary": orm.Dict(dict={"converged": True}),
                        "output_parameters": orm.Dict(dict={})}.items():
        value.store()
        value.base.links.add_incoming(node, link_type=LinkType.RETURN, link_label=name)
    node.set_process_state(ProcessState.FINISHED)
    node.set_exit_status(0)
    return node


def test_reuse_with_no_remote_folder_and_explicit_links(source):
    assert "remote_folder" not in source.outputs
    builder = get_builder(source.inputs.structure, {}, source.inputs.code)
    assert builder.reuse_source.value == source.uuid
    outputs, node = run_get_node(builder)
    assert node.is_finished_ok and not node.called_descendants
    assert outputs["structure"].uuid == source.outputs.structure.uuid
    assert node.inputs.reuse.trajectory.uuid == source.outputs.trajectory.uuid


def test_missing_repository_artifact_proposes_recompute(source, monkeypatch):
    repository_class = type(source.outputs.retrieved.base.repository)
    read = repository_class.get_object_content
    def missing(self, path, *args, **kwargs):
        if path == "aiida_trj.xyz":
            raise FileNotFoundError("trajectory unavailable")
        return read(self, path, *args, **kwargs)
    monkeypatch.setattr(repository_class, "get_object_content", missing)
    plan = plan_geometry(source.inputs.structure, {}, source.inputs.code)
    assert plan["action"] == "compute" and plan["unavailable"]
    builder = get_builder(source.inputs.structure, {}, source.inputs.code, plan=plan)
    assert builder.bypass_cache.value and "reuse_source" not in builder


def test_reviewed_reuse_cannot_silently_turn_into_calculation(source, monkeypatch):
    plan = plan_geometry(source.inputs.structure, {}, source.inputs.code)
    def missing(*args, **kwargs):
        raise FileNotFoundError("Deleted after review")
    monkeypatch.setattr(type(source.outputs.retrieved.base.repository), "get_object_content", missing)
    with pytest.raises(FileNotFoundError):
        get_builder(source.inputs.structure, {}, source.inputs.code, plan=plan)


def test_method_change_does_not_reuse(source):
    assert plan_geometry(source.inputs.structure, {"method": "PBE0"}, source.inputs.code)["action"] == "compute"


def test_reuse_source_rejects_nonconvergence(source, monkeypatch):
    summary_class = type(source.outputs.optimization_summary)
    original = summary_class.get_dict
    def result(self):
        if self.uuid == source.outputs.optimization_summary.uuid:
            return {"converged": False}
        return original(self)
    monkeypatch.setattr(summary_class, "get_dict", result)
    with pytest.raises(ValueError, match="not converged"):
        validate_result(source, signature(source.inputs.structure, {}, source.inputs.code.uuid))


def test_invalid_cache_hit_regenerates_once_with_bypass(source, monkeypatch, aiida_manager):
    from types import SimpleNamespace
    from aiida.common import AttributeDict
    from aiida.engine.utils import instantiate_process
    from aiida_empa_orca import workchains
    builder = get_builder(source.inputs.structure, {}, source.inputs.code,
                          plan={"action": "compute", "unavailable": []})
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        process.setup()
        cached = orm.CalcJobNode().store()
        cached.base.extras.set("_aiida_cached_from", "unit-test-cache-source")
        outputs = AttributeDict({name: source.outputs[name] for name in source.outputs})
        outputs.relaxed_structure = outputs.pop("structure")
        process.ctx.optimization = SimpleNamespace(is_finished_ok=True, outputs=outputs, called_descendants=[cached])
        process.ctx.attempt = 1
        def missing(_):
            raise FileNotFoundError("Cached trajectory is missing")
        monkeypatch.setattr(workchains, "validate_outputs", missing)
        assert process.inspect_optimization() is None
        assert process.needs_cache_regeneration()
        captured = []
        def submit(child):
            captured.append(child)
            return orm.WorkChainNode().store()
        process.submit = submit
        process.run_optimization()
        assert captured[0].orca.metadata.disable_cache is True
        assert process.inspect_optimization().status == 403
        assert not process.needs_cache_regeneration()
    finally:
        process.close()
