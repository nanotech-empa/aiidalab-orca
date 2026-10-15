"""Short-lived ORM access. Public UI service methods return plain data only."""

import io

import ase.io
from aiida import orm
from aiida.engine import submit

from aiida_empa_orca.reuse import PROCESS_TYPE
from aiida_empa_orca.settings import normalize_settings
from aiida_empa_orca.workchains import get_builder, plan_geometry

NO_XYZ = "2\nNO, neutral doublet, stretched test geometry\nN 0 0 0\nO 0 0 1.3\n"


def parse_xyz(text):
    frames = ase.io.read(io.StringIO(text), format="xyz", index=":")
    if len(frames) != 1:
        raise ValueError("Please provide exactly one XYZ geometry")
    atoms = frames[0]
    atoms.pbc = False
    return atoms


def codes():
    result = []
    for uuid, label in orm.QueryBuilder().append(orm.InstalledCode, project=["uuid", "label"]).all():
        code = orm.load_code(uuid)
        if (code.default_calc_job_plugin in ("orca.orca", "empa_orca.optimization")
                and code.computer.scheduler_type == "core.direct" and code.computer.transport_type == "core.local"):
            result.append((f"{label}@{code.computer.label}", str(uuid)))
    return sorted(result)


def prepare(xyz, source_uuid, settings, code_uuid, optimize, force_recompute):
    if source_uuid.strip():
        structure = orm.load_node(source_uuid.strip())
        if not isinstance(structure, orm.StructureData):
            raise ValueError("The identifier must refer to an AiiDA StructureData")
    else:
        structure = orm.StructureData(ase=parse_xyz(xyz))
        structure.label = "ORCA app imported geometry"
    settings = normalize_settings(settings)
    code = orm.load_code(code_uuid) if code_uuid else None
    plan = plan_geometry(structure, settings, code, optimize=optimize, force_recompute=force_recompute)
    structure.store()
    return {"structure_uuid": structure.uuid, "code_uuid": str(code.uuid) if code else None,
            "settings": settings, "optimize": optimize, "force_recompute": force_recompute,
            "plan": plan, "formula": structure.get_formula(),
            "source_description": structure_origin(structure)}


def structure_origin(structure):
    creator = structure.creator
    if creator is None:
        return f"Supplied geometry ({structure.uuid}); no calculation method recorded."
    if "parameters" in creator.inputs:
        params = creator.inputs.parameters.get_dict()
        return f"Geometry from {creator.process_label} ({creator.uuid}): " + " ".join(params.get("input_keywords", []))
    return f"Geometry from {creator.process_label} ({creator.uuid})."


def submit_plan(review, label):
    from aiida.engine.daemon.client import get_daemon_client
    if not get_daemon_client().is_daemon_running:
        raise ValueError("The AiiDA daemon is not running. Start it before submitting.")
    builder = get_builder(
        orm.load_node(review["structure_uuid"]), review["settings"],
        orm.load_code(review["code_uuid"]) if review["code_uuid"] else None,
        optimize=review["optimize"], force_recompute=review["force_recompute"], plan=review["plan"],
    )
    builder.metadata.label = label.strip() or f"{review['formula']} geometry"
    builder.metadata.description = "Submitted from AiiDAlab ORCA geometry app"
    node = submit(builder)
    node.base.extras.set("aiidalab_orca", {"version": "0.1.0", "view": "geometry"})
    return str(node.uuid)


def recent_runs():
    rows = orm.QueryBuilder().append(orm.WorkChainNode, filters={"process_type": PROCESS_TYPE},
                                    project=["uuid", "label", "ctime"], tag="run").order_by(
                                        {"run": {"ctime": "desc"}}).limit(50).all()
    return [(f"{date:%Y-%m-%d %H:%M} · {label or 'Geometry'} · {str(uuid)[:8]}", str(uuid)) for uuid, label, date in rows]


def result(uuid):
    node = orm.load_node(uuid)
    if node.process_type != PROCESS_TYPE:
        raise ValueError("Select an ORCA geometry workflow")
    data = {"uuid": node.uuid, "label": node.label, "state": node.process_state.value,
            "finished": node.is_terminated, "successful": node.is_finished_ok,
            "exit_message": node.exit_message, "settings": node.inputs.settings.get_dict(),
            "optimized": node.inputs.optimize.value,
            "source_uuid": node.inputs.reuse_source.value if "reuse_source" in node.inputs else None,
            "reports": [entry.message for entry in orm.Log.collection.get_logs_for(node)]}
    data["calculations"] = []
    for child in node.called_descendants:
        if isinstance(child, orm.CalcJobNode):
            data["calculations"].append({"uuid": child.uuid, "state": child.process_state.value,
                                         "exit_message": child.exit_message,
                                         "cached": child.base.caching.is_created_from_cache})
            if child.is_failed and "retrieved" in child.outputs:
                files = child.outputs.retrieved.base.repository
                if "aiida.out" in files.list_object_names():
                    data["output_tail"] = files.get_object_content("aiida.out")[-6000:]
    if "structure" in node.outputs:
        structure = node.outputs.structure
        atoms = structure.get_ase()
        handle = io.StringIO()
        ase.io.write(handle, atoms, format="xyz")
        data.update(structure_uuid=structure.uuid, xyz=handle.getvalue(),
                    symbols=atoms.get_chemical_symbols(), positions=atoms.positions.tolist(),
                    source_description=structure_origin(structure))
    if "trajectory" in node.outputs:
        data["frames"] = node.outputs.trajectory.get_positions().tolist()
    if "optimization_summary" in node.outputs:
        data["summary"] = node.outputs.optimization_summary.get_dict()
    return data
