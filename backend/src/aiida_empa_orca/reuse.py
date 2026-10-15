"""Operation-specific result discovery and verification, independent of caching."""

from aiida import orm

from .settings import signature

PROCESS_TYPE = "aiida.workflows:empa_orca.geometry"
RESULT_TYPES = {
    "structure": orm.StructureData,
    "trajectory": orm.TrajectoryData,
    "optimization_summary": orm.Dict,
    "output_parameters": orm.Dict,
    "retrieved": orm.FolderData,
}


def validate_result(node, expected_signature):
    """Check scientific inputs, provenance, and the data this operation consumes.

    Geometry reuse deliberately does not require a scratch GBW. Remote electronic
    artifacts will have separate contracts when electronic workflows are added.
    """
    if node.process_type != PROCESS_TYPE or not node.is_finished_ok:
        raise ValueError("Source is not a successful geometry workflow")
    if not node.inputs.optimize.value:
        raise ValueError("Source geometry was kept as supplied, not optimized")
    actual = signature(node.inputs.structure, node.inputs.settings.get_dict(), node.inputs.code.uuid)
    if actual != expected_signature:
        raise ValueError("The source has different geometry, settings, or code")
    validate_outputs(node.outputs)


def validate_outputs(outputs):
    """Check actual required data, also for freshly returned cache hits."""
    for name, data_type in RESULT_TYPES.items():
        if name not in outputs or not isinstance(outputs[name], data_type):
            raise ValueError(f"Source lacks required {name}")
    if not outputs["optimization_summary"].get_dict().get("converged"):
        raise ValueError("Source optimization is not converged")
    atoms = outputs["structure"].get_ase()
    trajectory = outputs["trajectory"]
    # Reading arrays checks their actual repository objects, not just attributes.
    if trajectory.numsteps < 1:
        raise ValueError("Empty trajectory")
    import numpy as np
    if list(trajectory.symbols) != atoms.get_chemical_symbols():
        raise ValueError("Trajectory atom ordering differs")
    if not np.allclose(trajectory.get_positions()[-1], atoms.positions, atol=1e-5):
        raise ValueError("Trajectory final frame differs")
    repository = outputs["retrieved"].base.repository
    for filename in ("aiida.out", "aiida.xyz", "aiida_trj.xyz"):
        if not repository.get_object_content(filename):
            raise ValueError(f"Empty required retrieved file: {filename}")


def discover_results(structure, settings, code_uuid):
    """Return only plain identifiers and reasons; do not retain ORM instances."""
    expected = signature(structure, settings, code_uuid)
    query = orm.QueryBuilder().append(
        orm.WorkChainNode, filters={"process_type": PROCESS_TYPE,
                                   "attributes.process_state": "finished",
                                   "attributes.exit_status": 0},
        project=["uuid"], tag="workflow",
    ).order_by({"workflow": {"ctime": "desc"}})
    unavailable = []
    for (uuid,) in query.all():
        node = orm.load_node(uuid)
        if not node.inputs.optimize.value:
            continue
        actual = signature(node.inputs.structure, node.inputs.settings.get_dict(), node.inputs.code.uuid)
        if actual != expected:
            continue
        try:
            validate_result(node, expected)
        except (OSError, KeyError, ValueError) as exc:
            unavailable.append({"uuid": str(uuid), "reason": str(exc)})
            continue
        return {"action": "reuse", "source_uuid": str(uuid), "unavailable": unavailable}
    return {"action": "compute", "source_uuid": None, "unavailable": unavailable}
