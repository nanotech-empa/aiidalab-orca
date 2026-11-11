"""Plain plans and operation-local ORM access for the energy workflow."""

from aiida import engine, orm
from aiida_empa_orca import casci, common_orbitals
from aiida_empa_orca.energy import (
    EnergyExportWorkChain,
    EnergyStageCalculation,
    export_input,
    worker_manifest,
)
from . import casci_services
from .property_services import helper_code
from aiida_empa_orca.native_logs import output_policy
from aiida_empa_orca.energy_storage import hamiltonian_location
from .energy_route import (
    review_budget,
    STAGE_LABELS,
    orca_comparison,
    review_worker_solver,
)


def resources(operation):
    rows = []
    for uid in (
        orm.QueryBuilder().append(orm.InstalledCode, project=["uuid"]).all(flat=True)
    ):
        code = orm.load_code(uid)
        if code.is_hidden:
            continue
        try:
            worker_manifest(code, operation)
        except ValueError:
            continue
        rows.append(
            {
                "uuid": str(uid),
                "label": code.label,
                "computer": code.computer.label,
                "general_solver": bool(
                    code.base.extras.get("quantum_energy_tools", {})
                    .get("capabilities", {})
                    .get("resource_bounded_roots", False)
                ),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["computer"] != "localhost",
            row["computer"],
            not row["general_solver"]
            if operation in ("solve-full", "solve-sampled")
            else False,
            row["label"],
        ),
    )


def prepare_export(reference_uuid, space, values, worker_uuid, *, native_output_policy=None):
    node = orm.load_node(reference_uuid)
    reference = casci_services.reference_data(reference_uuid)
    space = casci.active_space(space, reference)
    settings = casci.casci_settings(
        values
        | {
            "charge": reference["charge"],
            "multiplicity": 1 + space["electrons"] % 2,
            "nroots": 1,
        },
        reference,
        space,
    )
    worker = worker_manifest(orm.load_code(worker_uuid), "validate")
    common_orbitals.reference_location(node)
    return {
        "operation": "export",
        "native_output_policy": output_policy(native_output_policy),
        "helper_uuid": helper_code(node.inputs.code.computer.uuid),
        "reference_uuid": str(reference_uuid),
        "space": space,
        "settings": settings,
        "worker_uuid": str(worker_uuid),
        "worker_manifest": worker,
        "computer": node.inputs.code.computer.label,
        "input": export_input(reference, space, settings),
    }


def models(reference_uuid, space):
    node = orm.load_node(reference_uuid)
    ids = (
        orm.QueryBuilder()
        .append(
            orm.Dict,
            filters={"uuid": str(node.outputs.orbital_reference.uuid)},
            tag="reference",
        )
        .append(
            orm.WorkChainNode,
            with_incoming="reference",
            filters={"process_type": "aiida.workflows:empa_orca.energy_export"},
            project=["uuid"],
        )
        .all(flat=True)
    )
    rows = []
    for uid in ids:
        old = orm.load_node(uid)
        if old.inputs.active_space.get_dict() != space:
            continue
        state = (
            f"failed (exit {old.exit_status})"
            if old.is_finished and not old.is_finished_ok
            else old.process_state.value
        )
        rows.append(
            {
                "uuid": str(uid),
                "state": state,
                "finished_ok": old.is_finished_ok,
                "created": old.ctime.isoformat(),
                "label": f"{old.ctime:%Y-%m-%d %H:%M} · charge {old.inputs.settings.get_dict()['charge']:+d}, multiplicity {old.inputs.settings.get_dict()['multiplicity']}",
                "charge": old.inputs.settings.get_dict()["charge"],
                "multiplicity": old.inputs.settings.get_dict()["multiplicity"],
            }
        )
    return sorted(rows, key=lambda row: row["created"])


def stages(model_uuid, operation, sector=None):
    model = orm.load_node(model_uuid)
    if not model.is_finished_ok:
        return []
    ids = (
        orm.QueryBuilder()
        .append(
            orm.Data,
            filters={"uuid": str(model.outputs.hamiltonian.uuid)},
            tag="model",
        )
        .append(
            orm.CalcJobNode,
            with_incoming="model",
            filters={"process_type": "aiida.calculations:empa_orca.energy_stage"},
            project=["uuid"],
        )
        .all(flat=True)
    )
    rows = []
    for uid in ids:
        node = orm.load_node(uid)
        if node.inputs.operation.value != operation:
            continue
        if sector is not None and (
            "sector" not in node.inputs or node.inputs.sector.get_dict() != sector
        ):
            continue
        state = (
            f"failed (exit {node.exit_status})"
            if node.is_finished and not node.is_finished_ok
            else node.process_state.value
        )
        record = node.outputs.result.get_dict() if node.is_finished_ok else None
        if record and operation == "sample-hardware":
            state += " · IBM " + record["status"] + " · job " + record["job_id"]
        rows.append(
            {
                "uuid": str(uid),
                "state": state,
                "finished_ok": node.is_finished_ok,
                "created": node.ctime.isoformat(),
                "label": f"{node.ctime:%Y-%m-%d %H:%M} · {STAGE_LABELS[operation]}",
                "result": record,
            }
        )
    return sorted(rows, key=lambda row: row["created"])


def prepare_stage(
    model_uuid,
    operation,
    settings,
    code_uuid,
    circuit_uuid=None,
    sample_uuid=None,
    prepared_uuid=None,
    sector=None,
    processes=2,
    memory_mb=4096,
    wallclock_seconds=1800,
):
    model = orm.load_node(model_uuid)
    if (
        not model.is_finished_ok
        or model.outputs.validation.get_dict().get("passed") is not True
    ):
        raise ValueError("Wait for a successful Hamiltonian export and validation")
    code = orm.load_code(code_uuid)
    identity = worker_manifest(code, operation)
    capabilities = code.base.extras.get("quantum_energy_tools", {}).get(
        "capabilities", {}
    )
    if processes < 1 or memory_mb < 256 * processes or wallclock_seconds < 1:
        raise ValueError(
            "Review positive CPU resources and at least 256 MiB per process"
        )
    native = model.outputs.native_export.get_dict()
    transfer = None
    if isinstance(model.outputs.hamiltonian, orm.Dict):
        location = hamiltonian_location(model.outputs.hamiltonian)
        remote = orm.load_node(location['uuid'])
        transfer = {'temporary_relay': remote.computer.uuid != code.computer.uuid,
                    'size_bytes': model.outputs.hamiltonian.get_dict()['size_bytes'],
                    'source_computer': remote.computer.label}
    sector = dict(
        sector or {"charge": native["charge"], "ms2": native["multiplicity"] - 1}
    )
    if set(sector) != {"charge", "ms2"} or any(
        type(value) is not int for value in sector.values()
    ):
        raise ValueError("Declare an integer charge and minimum multiplicity")
    target = native | {
        "active_space": native["active_space"]
        | {
            "electrons": native["active_space"]["electrons"]
            - (sector["charge"] - native["charge"])
        },
        "multiplicity": sector["ms2"] + 1,
    }
    size = review_budget(target, operation, settings, memory_mb)
    review_worker_solver(capabilities, operation, settings, size)
    if operation == "generate":
        for key, count in [
            ("initial_alpha", size["alpha"]),
            ("initial_beta", size["beta"]),
        ]:
            if key in settings and len(settings[key]) != count:
                raise ValueError(
                    "Initial alpha/beta occupations must match the selected Hamiltonian electron sector"
                )
    for uid, required in (
        (circuit_uuid, "circuits"),
        (sample_uuid, "samples"),
        (prepared_uuid, "prepared"),
    ):
        if uid:
            child = orm.load_node(uid)
            if (
                not child.is_finished_ok
                or required not in child.outputs
                or child.inputs.hamiltonian.uuid != model.outputs.hamiltonian.uuid
                or child.outputs.result.get_dict().get("sector") != sector
            ):
                raise ValueError(
                    "Select a completed stage belonging to this Hamiltonian"
                )
    if operation in ("sample-simulator", "prepare-hardware") and not circuit_uuid:
        raise ValueError("Prepare and select circuits before sampling")
    if operation == "solve-sampled" and not sample_uuid:
        raise ValueError("Select completed simulator or hardware samples")
    if operation == "sample-hardware" and not prepared_uuid:
        raise ValueError("Select a compiled and reviewed hardware preparation first")
    hardware_review = None
    if operation == "sample-hardware":
        prepared = orm.load_node(prepared_uuid)
        if str(prepared.inputs.code.uuid) != str(code_uuid):
            raise ValueError(
                "Use the same hardware worker that prepared this request and owns its job ledger"
            )
        hardware_review = prepared.outputs.result.get_dict()["hardware_plan"]
    return {
        "operation": operation,
        "hamiltonian_transfer": transfer,
        "model_uuid": str(model_uuid),
        "settings": dict(settings),
        "code_uuid": str(code_uuid),
        "worker_manifest": identity,
        "circuit_uuid": circuit_uuid,
        "sample_uuid": sample_uuid,
        "prepared_uuid": prepared_uuid,
        "sector": sector,
        "sector_electrons": target["active_space"]["electrons"],
        "hardware_review": hardware_review,
        "model_description": {
            key: native[key]
            for key in ("active_space", "charge", "multiplicity", "auxiliary_basis")
        },
        "processes": processes,
        "memory_mb": memory_mb,
        "wallclock_seconds": wallclock_seconds,
    }


def builder(plan):
    if plan["operation"] == "export":
        checked = prepare_export(
            plan["reference_uuid"], plan["space"], plan["settings"], plan["worker_uuid"],
            native_output_policy=plan.get('native_output_policy')
        )
        if checked != plan:
            raise ValueError("Export context changed; review it again")
        node = orm.load_node(plan["reference_uuid"])
        result = EnergyExportWorkChain.get_builder()
        result.orbital_reference, result.source_remote = (
            node.outputs.orbital_reference,
            node.outputs.remote_folder,
        )
        result.active_space, result.settings = (
            orm.Dict(dict=plan["space"]),
            orm.Dict(dict=plan["settings"]),
        )
        result.orca_code, result.worker_code = (
            node.inputs.code,
            orm.load_code(plan["worker_uuid"]),
        )
        result.compact_code = orm.load_code(plan['helper_uuid'])
        result.native_output_policy = orm.Dict(dict=plan['native_output_policy'])
        result.metadata.label = "Active-space Hamiltonian export · no full CASCI"
        return result
    checked = prepare_stage(
        **{
            k: plan[k]
            for k in (
                "model_uuid",
                "operation",
                "settings",
                "code_uuid",
                "circuit_uuid",
                "sample_uuid",
                "prepared_uuid",
                "sector",
                "processes",
                "memory_mb",
                "wallclock_seconds",
            )
        }
    )
    if checked != plan:
        raise ValueError("Energy stage changed; review it again")
    model = orm.load_node(plan["model_uuid"])
    result = EnergyStageCalculation.get_builder()
    result.code = orm.load_code(plan["code_uuid"])
    result.hamiltonian, result.native_export = (
        model.outputs.hamiltonian,
        model.outputs.native_export,
    )
    result.operation, result.settings = (
        orm.Str(plan["operation"]),
        orm.Dict(dict=plan["settings"]),
    )
    result.sector = orm.Dict(dict=plan["sector"])
    if plan.get("circuit_uuid"):
        child = orm.load_node(plan["circuit_uuid"])
        result.circuits, result.circuit_manifest = (
            child.outputs.circuits,
            child.outputs.result,
        )
    if plan.get("sample_uuid"):
        result.samples = orm.load_node(plan["sample_uuid"]).outputs.samples
    if plan.get("prepared_uuid"):
        prepared = orm.load_node(plan["prepared_uuid"])
        result.prepared, result.prepared_manifest = (
            prepared.outputs.prepared,
            prepared.outputs.result,
        )
    result.metadata.options = {
        "resources": {"num_machines": 1, "num_mpiprocs_per_machine": plan["processes"]},
        "max_memory_kb": plan["memory_mb"] * 1024,
        "max_wallclock_seconds": plan["wallclock_seconds"],
        "withmpi": False,
        "environment_variables": {
            key: str(plan["processes"])
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }
    result.metadata.label = STAGE_LABELS[plan["operation"]]
    return result


def submit(plan):
    return str(engine.submit(builder(plan)).uuid)


def orca_comparisons(model_uuid, sector):
    """Discover compatible stored states without remote access or calculations."""
    model = orm.load_node(model_uuid)
    if not model.is_finished_ok:
        return []
    native = model.outputs.native_export.get_dict()
    reference = orm.load_node(native["orbital_reference_uuid"])
    expected_code = reference.creator.inputs.code.uuid
    structure_uuid = reference.get_dict()["structure_uuid"]
    rows = []
    for uid in casci.existing_calculations(native["orbital_reference_uuid"]):
        node = orm.load_node(uid)
        if (
            not node.is_finished_ok
            or "state_energies" not in node.outputs
            or node.inputs.code.uuid != expected_code
        ):
            continue
        try:
            result = orca_comparison(
                native,
                sector,
                node.outputs.state_energies.get_dict(),
                input_reference_uuid=str(node.inputs.orbital_reference.uuid),
                input_space=node.inputs.active_space.get_dict(),
                input_settings=node.inputs.settings.get_dict(),
                structure_uuid=structure_uuid,
            )
        except (ValueError, KeyError):
            continue
        result["source_uuid"] = str(uid)
        rows.append(
            {
                "uuid": str(uid),
                "created": node.ctime.isoformat(),
                "result": result,
                "multiplicity": result["multiplicity"],
                "nroots": result["used_roots"],
                "label": f"{node.ctime:%Y-%m-%d %H:%M} · ORCA CASCI · multiplicity {result['multiplicity']} · {result['used_roots']} states",
            }
        )
    # Existing calculations arrive newest first; ties keep that ordering.
    return sorted(rows, key=lambda row: (row["multiplicity"], -row["nroots"]))
