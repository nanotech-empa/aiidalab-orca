"""Short-lived ORM access. Public UI service methods return plain data only."""

import io

import ase.io
from aiida import orm
from aiida.engine import submit

from aiida_empa_orca.reuse import PROCESS_TYPE
from aiida_empa_orca.settings import normalize_settings, validate_molecule
from aiida_empa_orca.workchains import get_builder, plan_geometry
from aiida_empa_orca.reference import (
    PROCESS_TYPE as REFERENCE_PROCESS, get_reference_builder, plan_reference, reference_settings,
)

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
        if (code.default_calc_job_plugin in ("orca.orca", "empa_orca.optimization", "empa_orca.single_point")
                and code.computer.scheduler_type == "core.direct" and code.computer.transport_type == "core.local"):
            result.append((f"{label}@{code.computer.label}", str(uuid)))
    return sorted(result)


def validate_configuration(atoms, settings, optimize):
    """Check scientific inputs with the backend's existing validation rules."""
    # Resources are confirmed in the following step; use their valid defaults
    # here so a resource error cannot block access to the resource controls.
    values = {k: v for k, v in settings.items()
              if k not in ("nprocs", "memory_mb", "wallclock_seconds")}
    values = normalize_settings(values) if optimize else reference_settings(values)
    validate_molecule(orm.StructureData(ase=atoms), values)


def prepare(xyz, source_uuid, settings, code_uuid, optimize, force_recompute, *, atoms=None, imported=None):
    if atoms is not None:
        structure = orm.StructureData(ase=atoms)
    elif source_uuid.strip():
        structure = orm.load_node(source_uuid.strip())
        if not isinstance(structure, orm.StructureData):
            raise ValueError("The identifier must refer to an AiiDA StructureData")
    else:
        structure = orm.StructureData(ase=parse_xyz(xyz))
        structure.label = "ORCA app imported geometry"
    settings = normalize_settings(settings) if optimize else reference_settings(settings)
    code = orm.load_code(code_uuid) if code_uuid else None
    plan = (plan_geometry(structure, settings, code, force_recompute=force_recompute) if optimize else
            plan_reference(structure, settings, code, force_recompute=force_recompute))
    if atoms is not None:
        from .structure_io import store_reviewed_structure
        structure = orm.load_node(store_reviewed_structure(atoms, source_uuid, imported))
    else:
        structure.store()
    from aiida_empa_orca.input import preview_input
    return {"structure_uuid": str(structure.uuid), "code_uuid": str(code.uuid) if code else None,
            "settings": settings, "optimize": optimize, "force_recompute": force_recompute,
            "plan": plan, "formula": structure.get_formula(),
            "source_description": structure_origin(structure),
            "input_files": preview_input(structure, settings, single_point=not optimize)}


def structure_origin(structure):
    creator = structure.creator
    if creator is None:
        return f"Supplied geometry ({structure.uuid}); no calculation method recorded."
    if creator.process_label == "record_structure_edit":
        return f"User-edited geometry based on: {structure_origin(creator.inputs.source_structure)}"
    if creator.process_label in ("record_structure_import", "record_cdxml_import"):
        return f"User-reviewed imported starting geometry ({structure.uuid}); no ORCA optimization performed."
    if "parameters" in creator.inputs:
        params = creator.inputs.parameters.get_dict()
        return f"Geometry from {creator.process_label} ({creator.uuid}): " + " ".join(params.get("input_keywords", []))
    return f"Geometry from {creator.process_label} ({creator.uuid})."


def submit_plan(review, label):
    from aiida.engine.daemon.client import get_daemon_client
    if not get_daemon_client().is_daemon_running:
        raise ValueError("The AiiDA daemon is not running. Start it before submitting.")
    build = get_builder if review["optimize"] else get_reference_builder
    builder = build(
        orm.load_node(review["structure_uuid"]), review["settings"],
        orm.load_code(review["code_uuid"]) if review["code_uuid"] else None,
        force_recompute=review["force_recompute"], plan=review["plan"],
    )
    builder.metadata.label = label.strip() or f"{review['formula']} {'optimization' if review['optimize'] else 'SCF'}"
    builder.metadata.description = "Submitted from AiiDAlab ORCA electronic structure app"
    node = submit(builder)
    node.base.extras.set("aiidalab_orca", {"version": "0.1.0", "view": "geometry" if review["optimize"] else "scf"})
    return str(node.uuid)


def recent_runs():
    rows = orm.QueryBuilder().append(orm.WorkChainNode, filters={"process_type": {"in": [PROCESS_TYPE, REFERENCE_PROCESS]}},
                                    project=["uuid", "label", "ctime"], tag="run").order_by(
                                        {"run": {"ctime": "desc"}}).limit(50).all()
    return [(f"{date:%Y-%m-%d %H:%M} · {label or 'Geometry'} · {str(uuid)[:8]}", str(uuid)) for uuid, label, date in rows]


def result(uuid):
    node = orm.load_node(uuid)
    if node.process_type not in (PROCESS_TYPE, REFERENCE_PROCESS):
        raise ValueError("Select an ORCA geometry or SCF workflow")
    scf = node.process_type == REFERENCE_PROCESS
    data = {"uuid": node.uuid, "label": node.label, "state": node.process_state.value,
            "finished": node.is_terminated, "successful": node.is_finished_ok,
            "exit_message": node.exit_message, "settings": node.inputs.settings.get_dict(),
            "optimized": not scf and node.inputs.optimize.value, "single_point": scf,
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
    # Read the actual CalcJob input (including a source run for explicit reuse),
    # rather than regenerating historical input using today's renderer.
    source = orm.load_node(data["source_uuid"]) if data["source_uuid"] else node
    seen = set()
    while "reuse_source" in source.inputs and source.uuid not in seen:
        seen.add(source.uuid)
        source = orm.load_node(source.inputs.reuse_source.value)
    jobs = sorted((c for c in source.called_descendants if isinstance(c, orm.CalcJobNode)), key=lambda c: c.ctime)
    data["input_files"] = {}
    if jobs:
        repository = jobs[-1].base.repository
        for filename in ("aiida.inp", "aiida.coords.xyz"):
            try:
                data["input_files"][filename] = repository.get_object_content(filename)
            except (FileNotFoundError, OSError):
                pass
    data["warnings"] = []
    data["source_description"] = ""
    if "structure" in node.outputs:
        try:
            structure = node.outputs.structure
            atoms = structure.get_ase()
            handle = io.StringIO()
            ase.io.write(handle, atoms, format="xyz")
            data.update(structure_uuid=str(structure.uuid), xyz=handle.getvalue(),
                        symbols=atoms.get_chemical_symbols(), positions=atoms.positions.tolist(),
                        source_description=structure_origin(structure))
        except (KeyError, ValueError, OSError) as exc:
            data["warnings"].append(f"Final geometry could not be read: {exc}")
    if "trajectory" in node.outputs:
        try:
            data["frames"] = node.outputs.trajectory.get_positions().tolist()
        except (KeyError, ValueError, OSError) as exc:
            data["warnings"].append(f"Optimization trajectory could not be read: {exc}. Showing the final geometry when available.")
    if "optimization_summary" in node.outputs:
        data["summary"] = node.outputs.optimization_summary.get_dict()
    if "reference_summary" in node.outputs:
        data["summary"] = node.outputs.reference_summary.get_dict()
    if scf and node.is_finished_ok:
        from .history import inspect_run
        data["artifact_status"] = inspect_run(uuid)["reuse_status"]
    return data
