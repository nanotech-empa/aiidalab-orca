"""Independent fixed-geometry SCF workflow and electronic-artifact reuse."""

import hashlib
import json
from pathlib import PurePosixPath
import stat

import numpy as np
from aiida import orm
from aiida.common import AttributeDict
from aiida.engine import BaseRestartWorkChain, ToContext, WorkChain, if_
from aiida_orca.workchains.base import OrcaBaseWorkChain

from .calculation import SinglePointCalculation
from .choices import OPTIMIZATION
from .parser import reference_summary
from .protocols import editable_settings
from .reuse import PROCESS_TYPE as GEOMETRY_PROCESS, validate_outputs as validate_geometry
from .settings import orca_parameters, validate_molecule

PROCESS_TYPE = "aiida.workflows:empa_orca.reference"
# ORCA 6.1 orbital and density data. None is retrieved into the AiiDA repository.
ELECTRONIC_FILES = ("aiida.gbw", "aiida.densities", "aiida.densitiesinfo")
RESULT_TYPES = {"reference_summary": orm.Dict, "output_parameters": orm.Dict,
                "retrieved": orm.FolderData, "remote_folder": orm.RemoteData}


class ArtifactUnavailable(RuntimeError):
    """Storage cannot be checked; this is not evidence that files were deleted."""


def reference_settings(values):
    """Resolve electronic settings; geometry controls have no effect on SCF."""
    s = editable_settings(values)
    s["constraints"] = []
    s["block_parameters"].pop("geom", None)
    return s


def single_point_parameters(settings):
    parameters = orca_parameters(reference_settings(settings))
    parameters["input_keywords"] = [k for k in parameters["input_keywords"]
                                    if k not in ("Opt", *OPTIMIZATION)] + ["SP"]
    parameters["input_blocks"].pop("geom", None)
    return parameters


def reference_signature(structure, settings, code_uuid):
    from aiida.orm.implementation import clean_value
    s = reference_settings(settings)
    atoms = structure.get_ase()
    payload = {"operation": "single_point", "numbers": atoms.numbers.tolist(),
               "positions": atoms.positions.tolist(), "parameters": clean_value(single_point_parameters(s)),
               "resources": {k: s[k] for k in ("nprocs", "memory_mb", "wallclock_seconds")},
               "code_uuid": str(code_uuid)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def check_wavefunction(remote):
    """Inspect actual files through AiiDA's transport, never just the folder node."""
    files = []
    try:
        with remote.computer.get_transport() as transport:
            for name in ELECTRONIC_FILES:
                path = str(PurePosixPath(remote.get_remote_path()) / name)
                attributes = transport.get_attribute(path)
                if not stat.S_ISREG(attributes.st_mode) or attributes.st_size <= 0:
                    raise ValueError(f"Required electronic file is empty or not a regular file: {name}")
                files.append({"name": name, "size_bytes": attributes.st_size})
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Required electronic file is missing: {path}") from exc
    except OSError as exc:
        raise ArtifactUnavailable(f"Cannot check electronic files; retry when storage is reachable: {exc}") from exc
    return files


def validate_outputs(outputs):
    for name, cls in RESULT_TYPES.items():
        if name not in outputs or not isinstance(outputs[name], cls):
            raise ValueError(f"Source lacks required {name}")
    summary = outputs["reference_summary"].get_dict()
    if not summary.get("converged") or not np.isfinite(summary.get("energy_hartree", float("nan"))):
        raise ValueError("No converged finite SCF energy")
    try:
        text = outputs["retrieved"].base.repository.get_object_content("aiida.out")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ArtifactUnavailable(f"Cannot read the stored SCF output: {exc}") from exc
    parsed = reference_summary(text)
    if not np.isclose(parsed["energy_hartree"], summary["energy_hartree"], rtol=0, atol=1e-9):
        raise ValueError("Stored energy differs from the ORCA output")
    return check_wavefunction(outputs["remote_folder"])


def source_outputs(node):
    """Adapt a completed reference or the final state of an optimization."""
    if node.process_type == PROCESS_TYPE:
        return {name: node.outputs[name] for name in RESULT_TYPES}
    if node.process_type != GEOMETRY_PROCESS or not node.inputs.optimize.value:
        raise ValueError("Source is not an electronic calculation")
    validate_geometry(node.outputs)
    # Explicit geometry reuse may not return a remote folder; follow the actual
    # producer of its retrieved data, rather than guessing from directory names.
    producer = node.outputs.retrieved.creator
    if producer is None or "remote_folder" not in producer.outputs:
        raise ValueError("The optimization has no electronic-file provenance")
    return {"reference_summary": node.outputs.optimization_summary,
            "output_parameters": node.outputs.output_parameters,
            "retrieved": node.outputs.retrieved, "remote_folder": producer.outputs.remote_folder}


def validate_source(node, expected):
    if not node.is_finished_ok or node.process_type not in (PROCESS_TYPE, GEOMETRY_PROCESS):
        raise ValueError("Source is not a successful ORCA electronic workflow")
    if "code" not in node.inputs:
        raise ValueError("Source has no ORCA calculation code")
    structure = node.inputs.structure if node.process_type == PROCESS_TYPE else node.outputs.structure
    if reference_signature(structure, node.inputs.settings.get_dict(), node.inputs.code.uuid) != expected:
        raise ValueError("Source has different coordinates, electronic settings or code")
    outputs = source_outputs(node)
    validate_outputs(outputs)
    return outputs


def plan_reference(structure, settings, code=None, *, force_recompute=False):
    s = reference_settings(settings)
    validate_molecule(structure, s)
    if code is None:
        raise ValueError("Select an ORCA code for the single-point SCF calculation")
    if force_recompute:
        return {"action": "compute", "source_uuid": None, "unavailable": [], "force_recompute": True}
    expected = reference_signature(structure, s, code.uuid)
    query = orm.QueryBuilder().append(orm.WorkChainNode, filters={
        "process_type": {"in": [PROCESS_TYPE, GEOMETRY_PROCESS]},
        "attributes.process_state": "finished", "attributes.exit_status": 0},
        project=["uuid"], tag="run").order_by({"run": {"ctime": "desc"}})
    unavailable = []
    for (uuid,) in query.iterall():
        node = orm.load_node(uuid)
        if "code" not in node.inputs or (node.process_type == GEOMETRY_PROCESS and not node.inputs.optimize.value):
            continue
        try:
            candidate = node.inputs.structure if node.process_type == PROCESS_TYPE else node.outputs.structure
            if reference_signature(candidate, node.inputs.settings.get_dict(), node.inputs.code.uuid) != expected:
                continue
        except (KeyError, ValueError, OSError):
            continue
        try:
            validate_source(node, expected)
        except (KeyError, ValueError, FileNotFoundError) as exc:
            unavailable.append({"uuid": str(uuid), "reason": str(exc)})
            continue
        # ArtifactUnavailable deliberately propagates, blocking an unreviewed
        # replacement when storage is merely inaccessible.
        return {"action": "reuse", "source_uuid": str(uuid), "unavailable": unavailable}
    return {"action": "compute", "source_uuid": None, "unavailable": unavailable}


class ReferenceBaseWorkChain(OrcaBaseWorkChain):
    _process_class = SinglePointCalculation

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.expose_inputs(SinglePointCalculation, namespace="orca")
        spec.expose_outputs(SinglePointCalculation)

    def setup(self):
        BaseRestartWorkChain.setup(self)
        self.ctx.inputs = AttributeDict(self.exposed_inputs(self._process_class, "orca"))


class ReferenceWorkChain(WorkChain):
    """One SCF reference step, independent of geometry optimization and viewers."""

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("structure", valid_type=orm.StructureData)
        spec.input("settings", valid_type=orm.Dict)
        spec.input("code", valid_type=orm.AbstractCode)
        spec.input("force_recompute", valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.input("bypass_cache", valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.input("reuse_source", valid_type=orm.Str, required=False)
        spec.input_namespace("reuse", required=False)
        for name, cls_ in RESULT_TYPES.items():
            spec.input(f"reuse.{name}", valid_type=cls_, required=False)
            spec.output(name, valid_type=cls_)
        spec.output("structure", valid_type=orm.StructureData)
        spec.outline(cls.setup, if_(cls.needs_calculation)(
            cls.run_scf, cls.inspect_scf,
            if_(cls.needs_regeneration)(cls.run_scf, cls.inspect_scf)), cls.results)
        spec.exit_code(400, "ERROR_INVALID_INPUT", message="Invalid SCF settings; see workflow report.")
        spec.exit_code(401, "ERROR_REUSE_UNAVAILABLE", message="The reviewed electronic state is unavailable. Review a new plan.")
        spec.exit_code(402, "ERROR_SCF_FAILED", message="ORCA SCF failed; inspect the child calculation.")
        spec.exit_code(403, "ERROR_REQUIRED_DATA", message="Required electronic files or SCF results are missing or invalid.")
        spec.exit_code(404, "ERROR_STORAGE_UNAVAILABLE", message="Electronic storage cannot be checked; see workflow report.")

    def setup(self):
        self.ctx.reusing = "reuse_source" in self.inputs
        self.ctx.attempt = 0
        self.ctx.regenerate = False
        try:
            self.ctx.settings = reference_settings(self.inputs.settings.get_dict())
            validate_molecule(self.inputs.structure, self.ctx.settings)
            if (self.inputs.code.computer.scheduler_type != "core.direct"
                    or self.inputs.code.computer.transport_type != "core.local"):
                raise ValueError("This milestone supports the local direct scheduler only")
            if self.inputs.force_recompute.value and self.ctx.reusing:
                raise ValueError("Cannot force recomputation and reuse simultaneously")
        except ValueError as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INVALID_INPUT
        if self.ctx.reusing:
            try:
                outputs = validate_source(orm.load_node(self.inputs.reuse_source.value),
                    reference_signature(self.inputs.structure, self.ctx.settings, self.inputs.code.uuid))
                for name in RESULT_TYPES:
                    if self.inputs.reuse[name].uuid != outputs[name].uuid:
                        raise ValueError(f"Reuse input {name} has different provenance")
            except (KeyError, ValueError, OSError, ArtifactUnavailable) as exc:
                self.report(str(exc))
                return self.exit_codes.ERROR_REUSE_UNAVAILABLE

    def needs_calculation(self):
        return not self.ctx.reusing

    def needs_regeneration(self):
        return self.ctx.regenerate

    def run_scf(self):
        s = self.ctx.settings
        builder = ReferenceBaseWorkChain.get_builder()
        builder.orca.structure = self.inputs.structure
        builder.orca.code = self.inputs.code
        builder.orca.parameters = orm.Dict(dict=single_point_parameters(s))
        builder.orca.maxcore_mb = orm.Int(int(.75*s["memory_mb"]/s["nprocs"]))
        builder.orca.metadata.options = {
            "resources": {"num_machines": 1, "num_mpiprocs_per_machine": s["nprocs"]},
            "withmpi": False, "parser_name": "empa_orca.single_point",
            "max_wallclock_seconds": s["wallclock_seconds"], "max_memory_kb": s["memory_mb"]*1024}
        builder.orca.metadata.disable_cache = bool(
            self.inputs.force_recompute.value or self.inputs.bypass_cache.value or self.ctx.regenerate)
        builder.metadata.call_link_label = "scf" if self.ctx.attempt == 0 else "regenerate_missing_data"
        self.ctx.attempt += 1
        self.ctx.regenerate = False
        return ToContext(scf=self.submit(builder))

    def inspect_scf(self):
        if not self.ctx.scf.is_finished_ok:
            return self.exit_codes.ERROR_SCF_FAILED
        try:
            validate_outputs(self.ctx.scf.outputs)
        except ArtifactUnavailable as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_STORAGE_UNAVAILABLE
        except (KeyError, ValueError, OSError) as exc:
            cached = any(c.base.caching.is_created_from_cache for c in self.ctx.scf.called_descendants
                         if isinstance(c, orm.CalcJobNode))
            if self.ctx.attempt == 1 and cached:
                self.report(f"Cached electronic files unavailable ({exc}); execute once with caching bypassed")
                self.ctx.regenerate = True
                return
            self.report(str(exc))
            return self.exit_codes.ERROR_REQUIRED_DATA

    def results(self):
        outputs = self.inputs.reuse if self.ctx.reusing else self.ctx.scf.outputs
        self.out("structure", self.inputs.structure)
        for name in RESULT_TYPES:
            self.out(name, outputs[name])


def get_reference_builder(structure, settings, code, *, force_recompute=False, plan=None):
    s = reference_settings(settings)
    if plan is None:
        plan = plan_reference(structure, s, code, force_recompute=force_recompute)
    builder = ReferenceWorkChain.get_builder()
    builder.structure, builder.code, builder.settings = structure, code, orm.Dict(dict=s)
    builder.force_recompute = orm.Bool(force_recompute)
    builder.bypass_cache = orm.Bool(bool(plan.get("unavailable")))
    if plan["action"] == "reuse":
        outputs = validate_source(orm.load_node(plan["source_uuid"]), reference_signature(structure, s, code.uuid))
        builder.reuse_source = orm.Str(plan["source_uuid"])
        for name, value in outputs.items():
            builder.reuse[name] = value
    return builder
