"""Native DMRG plans and short-lived ORM access for the browser workspace."""

import contextlib
import fcntl
import hashlib
import io
import json
import re
import tempfile
from importlib.resources import files
from pathlib import Path

import numpy as np
from aiida import engine, orm
from aiida.common import NotExistent
from aiida.orm.implementation import clean_value
from aiida_empa_orca import dmrg
from aiida_empa_orca.dmrg_storage import (
    ARRAY_LIMIT,
    checkpoint_node,
    validate_checkpoint,
)

PROCESS = "aiida.calculations:empa_orca.dmrg"
UPLOAD_LIMIT = 16 * 1024**2


def _code(uuid):
    try:
        code = orm.load_code(uuid)
    except NotExistent as exc:
        raise ValueError("The selected Block2 code no longer exists") from exc
    if (
        code.is_hidden
        or code.default_calc_job_plugin != "empa_orca.dmrg"
        or Path(str(code.filepath_executable)).name != "block2main"
        or code.base.extras.get("block2", {}).get("version") != "0.5.4"
    ):
        raise ValueError("Select a configured Block2 0.5.4 block2main code")
    return code


def codes():
    rows = []
    for uid in (
        orm.QueryBuilder().append(orm.InstalledCode, project="uuid").all(flat=True)
    ):
        try:
            code = _code(str(uid))
        except ValueError:
            continue
        rows.append((f"{code.label}@{code.computer.label}", str(uid)))
    return sorted(rows)


def _source(uuid):
    try:
        node = orm.load_node(uuid)
    except (NotExistent, ValueError) as exc:
        raise ValueError("The Hamiltonian UUID is unavailable") from exc
    if isinstance(node, orm.WorkChainNode):
        if (
            node.process_type != "aiida.workflows:empa_orca.energy_export"
            or not node.is_finished_ok
            or "validation" not in node.outputs
            or node.outputs.validation.get_dict().get("passed") is not True
        ):
            raise ValueError("Select a completed, validated Hamiltonian export")
        node = node.outputs.hamiltonian
    if not isinstance(node, (orm.SinglefileData, orm.Dict)):
        raise ValueError(
            "Use an FCIDUMP data UUID or a validated Hamiltonian export UUID"
        )
    native = None
    if isinstance(node, orm.Dict):
        producer = node.creator
        if producer is None or "native_export" not in producer.outputs:
            raise ValueError("The external Hamiltonian has no native export manifest")
        native = producer.outputs.native_export
    parameters = dmrg.hamiltonian_parameters(node, native)
    return node, native, parameters


def source(uuid):
    node, native, parameters = _source(uuid)
    return {
        "uuid": str(node.uuid),
        "native_export_uuid": str(native.uuid) if native else None,
        "sha256": dmrg.file_sha256(node),
        "parameters": parameters,
        "external": isinstance(node, orm.Dict),
        "label": node.label or "Active-space FCIDUMP",
    }


def store_upload(content, filename):
    """Explicit GUI import; no native execution or mutation of previous nodes."""
    content = bytes(content)
    if not content or len(content) > UPLOAD_LIMIT:
        raise ValueError(
            "Upload a nonempty FCIDUMP up to 16 MiB. Use an exported-model UUID for larger files."
        )
    text = content.decode("utf-8")
    dmrg.header_parameters(text[:16384])
    end = re.search(r"&END|/", text, re.I)
    if end is None or not text[end.end() :].strip():
        raise ValueError("The FCIDUMP contains no integral records")
    node = orm.SinglefileData(file=io.BytesIO(content), filename="hamiltonian.fcidump")
    node.label = Path(filename).name or "Uploaded FCIDUMP"
    node.description = (
        "FCIDUMP explicitly imported in the ORCA app native DMRG workspace"
    )
    node.store()
    return str(node.uuid)


def store_example():
    content = (
        files("aiidalab_orca").joinpath("data/dmrg-three-orbital.fcidump").read_bytes()
    )
    return store_upload(content, "Analytic three-orbital singlet · CAS(2,3)")


def prepare(
    source_uuid,
    code_uuid,
    settings,
    seconds=600,
    *,
    parent_uuid=None,
    continue_sweeps=False,
    maxsizeoutput=5 * 1024**2,
    recompute=False,
):
    if not code_uuid:
        raise ValueError("Configure and select a Block2 0.5.4 code before reviewing")
    code = _code(code_uuid)
    details = source(source_uuid)
    if type(seconds) is not int or not 1 <= seconds <= 7 * 86400:
        raise ValueError("Specify a positive wall time of at most seven days")
    if type(maxsizeoutput) is not int or maxsizeoutput < 0:
        raise ValueError("Specify a nonnegative native-output retrieval limit")
    parent_bond = None
    states_uuid = None
    if parent_uuid:
        try:
            parent = orm.load_node(parent_uuid)
        except (NotExistent, ValueError) as exc:
            raise ValueError("The checkpoint calculation UUID is unavailable") from exc
        if (
            not isinstance(parent, orm.CalcJobNode)
            or parent.process_type != PROCESS
            or "results" not in parent.outputs
        ):
            raise ValueError(
                "Select a completed native DMRG result as the checkpoint source"
            )
        states = checkpoint_node(parent)
        parent_bond = validate_checkpoint(
            states, code, settings, details["sha256"], continuation=continue_sweeps
        )
        states_uuid = str(states.uuid)
    elif continue_sweeps:
        raise ValueError("Fixed-M continuation needs a completed one-site checkpoint")
    native_input = dmrg.dmrg_input(
        details["parameters"], settings, parent_bond, continue_sweeps
    )
    plan = clean_value(
        {
            "source": details,
            "code_uuid": str(code.uuid),
            "computer_uuid": str(code.computer.uuid),
            "computer": code.computer.label,
            "block2": code.base.extras.get("block2"),
            "settings": settings,
            "seconds": seconds,
            "parent_uuid": str(parent_uuid) if parent_uuid else None,
            "states_uuid": states_uuid,
            "continue_sweeps": bool(continue_sweeps),
            "maxsizeoutput": maxsizeoutput,
            "recompute": bool(recompute),
            "input": native_input,
            "adapter_sha256": hashlib.sha256(
                Path(dmrg.__file__).read_bytes()
            ).hexdigest(),
            "service_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    )
    plan["digest"] = hashlib.sha256(
        json.dumps(plan, sort_keys=True).encode()
    ).hexdigest()
    return plan


def builder(plan):
    """Revalidate every source identity and checkpoint at the dispatch boundary."""
    fresh = prepare(
        plan["source"]["uuid"],
        plan["code_uuid"],
        plan["settings"],
        plan["seconds"],
        parent_uuid=plan["parent_uuid"],
        continue_sweeps=plan["continue_sweeps"],
        maxsizeoutput=plan["maxsizeoutput"],
        recompute=plan["recompute"],
    )
    if fresh != plan:
        raise ValueError(
            "The reviewed DMRG source, code or settings changed. Review again."
        )
    result = dmrg.DmrgCalculation.get_builder()
    result.code = orm.load_code(plan["code_uuid"])
    result.hamiltonian = orm.load_node(plan["source"]["uuid"])
    if plan["source"]["native_export_uuid"]:
        result.native_export = orm.load_node(plan["source"]["native_export_uuid"])
    result.settings = orm.Dict(dict=plan["settings"])
    result.continue_sweeps = orm.Bool(plan["continue_sweeps"])
    if plan["states_uuid"]:
        result.parent_states = orm.load_node(plan["states_uuid"])
    result.maxsizeoutput = orm.Int(plan["maxsizeoutput"])
    threads = plan["settings"]["threads"]
    result.metadata.options = {
        "resources": {
            "num_machines": 1,
            "num_mpiprocs_per_machine": 1,
            "num_cores_per_mpiproc": threads,
        },
        "max_wallclock_seconds": plan["seconds"],
        "withmpi": False,
        "environment_variables": {
            "OMP_NUM_THREADS": str(threads),
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
        },
    }
    return result


@contextlib.contextmanager
def _dispatch_lock(computer_uuid):
    from aiida.manage import get_manager

    profile = get_manager().get_profile().uuid
    path = Path(tempfile.gettempdir()) / f"aiidalab-dmrg-{profile}-{computer_uuid}.lock"
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def submit(plan, label):
    """One reviewed native job, or explicit reuse of an identical saved request."""
    with _dispatch_lock(plan["computer_uuid"]):
        build = builder(plan)
        for uid in (
            orm.QueryBuilder()
            .append(
                orm.CalcJobNode,
                filters={
                    "process_type": PROCESS,
                    "extras.aiidalab_orca_dmrg.digest": plan["digest"],
                },
                project="uuid",
            )
            .all(flat=True)
        ):
            node = orm.load_node(uid)
            if not node.is_terminated or (
                not plan["recompute"]
                and node.is_finished
                and node.exit_status in (0, 311)
            ):
                return {"uuid": str(uid), "reused": True}
        active = (
            orm.QueryBuilder()
            .append(
                orm.Computer, filters={"uuid": plan["computer_uuid"]}, tag="computer"
            )
            .append(
                orm.CalcJobNode,
                with_computer="computer",
                filters={
                    "attributes.process_state": {
                        "in": ["created", "waiting", "running"]
                    }
                },
                project="uuid",
            )
            .all(flat=True)
        )
        if active:
            raise ValueError(
                "Another native job is active on this computer. Wait before submitting DMRG."
            )
        from aiida.engine.daemon.client import get_daemon_client

        if not get_daemon_client().is_daemon_running:
            raise ValueError("The AiiDA daemon is not running")
        build.metadata.label = label.strip() or "Native DMRG · active-space singlets"
        build.metadata.description = "Reviewed in the ORCA app native DMRG workspace"
        node = engine.submit(build)
        node.base.extras.set(
            "aiidalab_orca_dmrg", {"digest": plan["digest"], "review": plan}
        )
        return {"uuid": str(node.uuid), "reused": False}


def history(hamiltonian_uuid=None):
    filters = {"process_type": PROCESS}
    rows = []
    for uid, date, label in (
        orm.QueryBuilder()
        .append(
            orm.CalcJobNode,
            filters=filters,
            project=["uuid", "ctime", "label"],
            tag="run",
        )
        .order_by({"run": {"ctime": "desc"}})
        .limit(100)
        .all()
    ):
        node = orm.load_node(uid)
        if hamiltonian_uuid and str(node.inputs.hamiltonian.uuid) != hamiltonian_uuid:
            continue
        state = node.process_state.value
        rows.append(
            (
                f"{date:%Y-%m-%d %H:%M} · {label or 'DMRG'} · {state} · {str(uid)[:8]}",
                str(uid),
            )
        )
    return rows


def result(uuid):
    try:
        node = orm.load_node(uuid)
    except (NotExistent, ValueError) as exc:
        raise ValueError("The native DMRG result UUID is unavailable") from exc
    if not isinstance(node, orm.CalcJobNode) or node.process_type != PROCESS:
        raise ValueError("Select a native DMRG calculation UUID")
    output = {
        "uuid": str(node.uuid),
        "state": node.process_state.value,
        "terminated": node.is_terminated,
        "finished_ok": node.is_finished_ok,
        "exit_status": node.exit_status,
        "exit_message": node.exit_message,
        "source_uuid": str(node.inputs.hamiltonian.uuid),
        "settings": node.inputs.settings.get_dict(),
        "results": None,
        "paused": node.paused,
        "checkpoint_uuid": None,
        "sweep_energies": [],
    }
    if "results" not in node.outputs:
        return output
    output["results"] = node.outputs.results.get_dict()
    try:
        output["checkpoint_uuid"] = str(checkpoint_node(node).uuid)
    except (KeyError, OSError, ValueError):
        pass
    repository = node.outputs.retrieved.base.repository
    path = (
        "sweep_energies.npy"
        if output["results"].get("checkpoint_storage") == "remote"
        else "mps/sweep_energies.npy"
    )
    with repository.open(path, mode="rb") as stream:
        content = stream.read(ARRAY_LIMIT + 1)
    if len(content) > ARRAY_LIMIT:
        raise ValueError("The compact sweep array exceeds the supported size")
    energies = np.load(io.BytesIO(content), allow_pickle=False)
    if energies.ndim != 2 or not np.isfinite(energies).all():
        raise ValueError("The stored sweep array is invalid")
    output["sweep_energies"] = energies.tolist()
    return output
