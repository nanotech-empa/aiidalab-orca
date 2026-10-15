"""Geometry preparation composed with the upstream ORCA restart WorkChain."""

from aiida import orm
from aiida.common import AttributeDict
from aiida.engine import BaseRestartWorkChain, ToContext, WorkChain, if_
from aiida_orca.workchains.base import OrcaBaseWorkChain

from .artifacts import ElectronicStorageMixin
from .calculation import OptimizationCalculation
from .reuse import RESULT_TYPES, discover_results, validate_outputs, validate_result
from .settings import normalize_settings, orca_parameters, signature, validate_molecule


class OptimizationBaseWorkChain(OrcaBaseWorkChain):
    """Keep upstream restart handling and expose our narrow CalcJob additions."""

    _process_class = OptimizationCalculation

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.expose_inputs(OptimizationCalculation, namespace="orca")
        spec.expose_outputs(OptimizationCalculation)

    def setup(self):
        BaseRestartWorkChain.setup(self)
        self.ctx.inputs = AttributeDict(self.exposed_inputs(self._process_class, "orca"))


class GeometryWorkChain(ElectronicStorageMixin, WorkChain):
    """One geometry step, with an explicit, provenance-linked reuse input."""

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("structure", valid_type=orm.StructureData)
        spec.input("code", valid_type=orm.AbstractCode, required=False)
        spec.input("settings", valid_type=orm.Dict)
        spec.input("optimize", valid_type=orm.Bool, default=lambda: orm.Bool(True))
        spec.input("force_recompute", valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.input("bypass_cache", valid_type=orm.Bool, default=lambda: orm.Bool(False),
                   help="Set by planner when compatible results lack required artifacts.")
        spec.input("reuse_source", valid_type=orm.Str, required=False)
        spec.input_namespace("reuse", required=False)
        for name, data_type in RESULT_TYPES.items():
            spec.input(f"reuse.{name}", valid_type=data_type, required=False)
            spec.output(name, valid_type=data_type, required=name == "structure")
        spec.output("remote_folder", valid_type=orm.RemoteData, required=False)
        cls.storage_spec(spec)
        spec.outline(cls.setup, if_(cls.needs_calculation)(
            cls.run_optimization, cls.inspect_optimization,
            if_(cls.needs_cache_regeneration)(cls.run_optimization, cls.inspect_optimization),
        ), cls.results, if_(cls.should_preserve)(cls.preserve_electronic, cls.inspect_preservation))
        spec.exit_code(400, "ERROR_INVALID_INPUT", message="Invalid geometry settings; see workflow report.")
        spec.exit_code(401, "ERROR_REUSE_UNAVAILABLE", message="The selected reusable result changed or is unavailable. Review a new execution plan before recomputing.")
        spec.exit_code(402, "ERROR_OPTIMIZATION_FAILED", message="ORCA optimization failed; inspect the child calculation output and report.")
        spec.exit_code(403, "ERROR_REQUIRED_DATA", message="Required optimization data are unavailable. Inspect the report before forcing recomputation.")

    def setup(self):
        try:
            self.validate_storage_inputs()
            self.ctx.settings = normalize_settings(self.inputs.settings.get_dict())
            if self.inputs.optimize.value:
                validate_molecule(self.inputs.structure, self.ctx.settings)
                if "code" not in self.inputs:
                    raise ValueError("Optimization requires an ORCA code")
                if (self.inputs.code.computer.scheduler_type != "core.direct"
                        or self.inputs.code.computer.transport_type != "core.local"):
                    raise ValueError("This first milestone supports the local direct scheduler only")
            if self.inputs.force_recompute.value and "reuse_source" in self.inputs:
                raise ValueError("Cannot force recomputation and reuse a result simultaneously")
        except ValueError as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INVALID_INPUT
        self.ctx.reusing = "reuse_source" in self.inputs
        self.ctx.attempt = 0
        self.ctx.regenerate_cache = False
        if self.ctx.reusing:
            try:
                source = orm.load_node(self.inputs.reuse_source.value)
                expected = signature(self.inputs.structure, self.ctx.settings, self.inputs.code.uuid)
                validate_result(source, expected)
                for name in RESULT_TYPES:
                    if self.inputs.reuse[name].uuid != source.outputs[name].uuid:
                        raise ValueError(f"Reuse input {name} is not an output of the selected source")
            except (OSError, KeyError, ValueError) as exc:
                self.report(f"Reuse validation failed: {exc}")
                return self.exit_codes.ERROR_REUSE_UNAVAILABLE

    def needs_calculation(self):
        return self.inputs.optimize.value and not self.ctx.reusing

    def needs_cache_regeneration(self):
        return self.ctx.regenerate_cache

    def run_optimization(self):
        s = self.ctx.settings
        builder = OptimizationBaseWorkChain.get_builder()
        builder.orca.structure = self.inputs.structure
        builder.orca.code = self.inputs.code
        builder.orca.parameters = orm.Dict(dict=orca_parameters(s))
        builder.orca.maxcore_mb = orm.Int(int(0.75 * s["memory_mb"] / s["nprocs"]))
        builder.orca.metadata.options = {
            "resources": {"num_machines": 1, "num_mpiprocs_per_machine": s["nprocs"]},
            "withmpi": False,
            "parser_name": "empa_orca.optimization",
            "max_wallclock_seconds": s["wallclock_seconds"],
            "max_memory_kb": s["memory_mb"] * 1024,
        }
        builder.orca.metadata.disable_cache = bool(
            self.inputs.force_recompute or self.inputs.bypass_cache or self.ctx.regenerate_cache
        )
        builder.metadata.call_link_label = "optimization" if self.ctx.attempt == 0 else "regenerate_missing_data"
        self.ctx.attempt += 1
        self.ctx.regenerate_cache = False
        return ToContext(optimization=self.submit(builder))

    def inspect_optimization(self):
        if not self.ctx.optimization.is_finished_ok:
            self.report(f"Optimization child failed: {self.ctx.optimization.exit_message}")
            return self.exit_codes.ERROR_OPTIMIZATION_FAILED
        required = set(RESULT_TYPES) - {"structure"}
        try:
            outputs = {name: self.ctx.optimization.outputs[name] for name in required
                       if name in self.ctx.optimization.outputs}
            if "relaxed_structure" in self.ctx.optimization.outputs:
                outputs["structure"] = self.ctx.optimization.outputs.relaxed_structure
            validate_outputs(outputs)
        except (OSError, KeyError, ValueError) as exc:
            jobs = [child for child in self.ctx.optimization.called_descendants if isinstance(child, orm.CalcJobNode)]
            if self.ctx.attempt == 1 and any(job.base.caching.is_created_from_cache for job in jobs):
                self.report(f"Cached output lacks required data ({exc}); execute this step once with caching bypassed")
                self.ctx.regenerate_cache = True
                return
            self.report(f"Required optimization data unavailable: {exc}")
            return self.exit_codes.ERROR_REQUIRED_DATA

    def results(self):
        if not self.inputs.optimize.value:
            self.out("structure", self.inputs.structure)
        elif self.ctx.reusing:
            for name in RESULT_TYPES:
                self.out(name, self.inputs.reuse[name])
            self.report(f"Reused geometry from {self.inputs.reuse_source.value}; no ORCA calculation needed")
        else:
            outputs = self.ctx.optimization.outputs
            self.out("structure", outputs.relaxed_structure)
            for name in set(RESULT_TYPES) - {"structure"}:
                self.out(name, outputs[name])
            self.out("remote_folder", outputs.remote_folder)


def plan_geometry(structure, settings, code=None, *, optimize=True, force_recompute=False):
    """Plain-data execution plan suitable for review before submitting."""
    settings = normalize_settings(settings)
    if not optimize:
        return {"action": "keep", "source_uuid": None, "unavailable": []}
    validate_molecule(structure, settings)
    if code is None:
        raise ValueError("Select an ORCA code")
    if force_recompute:
        return {"action": "compute", "source_uuid": None, "unavailable": [], "force_recompute": True}
    return discover_results(structure, settings, code.uuid)


def get_builder(structure, settings, code=None, *, optimize=True, force_recompute=False, plan=None):
    """Build an independently usable workflow with explicit reuse data links.

    Passing the reviewed plan fixes the user's choice: vanished reuse outputs fail
    validation, never silently turn into an unexpected calculation.
    """
    settings = normalize_settings(settings)
    if plan is None:
        plan = plan_geometry(structure, settings, code, optimize=optimize, force_recompute=force_recompute)
    builder = GeometryWorkChain.get_builder()
    builder.structure = structure
    builder.settings = orm.Dict(dict=settings)
    builder.optimize = orm.Bool(optimize)
    builder.force_recompute = orm.Bool(force_recompute)
    builder.bypass_cache = orm.Bool(bool(plan.get("unavailable")))
    if code is not None:
        builder.code = code
    if plan["action"] == "reuse":
        source = orm.load_node(plan["source_uuid"])
        validate_result(source, signature(structure, settings, code.uuid))
        builder.reuse_source = orm.Str(source.uuid)
        for name in RESULT_TYPES:
            builder.reuse[name] = source.outputs[name]
    return builder
