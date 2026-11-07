"""Independent native Hamiltonian export and portable energy-worker stages.

These entry points do not replace the workers used by existing research jobs.
An export computes a single diagnostic configuration, never the full CAS.
"""

import hashlib
import io
import json
import re

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from . import casci, common_orbitals

PROTOCOL = "quantum-energy/v1"


def portable_fcidump(raw, electrons, multiplicity):
    """Keep all integral records verbatim; explicitly declare the target Ms.

    ORCA 6.1.1's tested DumpActInts output writes MS2=0 for open shells too.
    The target sector comes from the checked export input/output, never from
    the spin used to generate the starting orbitals. The raw file is retained.
    """
    header_end = re.search(rb"(?im)^\s*(?:&END|/)\s*$", raw)
    if header_end is None:
        raise ValueError("The native FCIDUMP header is incomplete")
    header = raw[: header_end.end()]

    def number(key):
        values = re.findall(rb"\b" + key + rb"\s*=\s*([+-]?\d+)", header, re.I)
        if len(values) != 1:
            raise ValueError("Missing or ambiguous native header " + key.decode())
        return int(values[0])

    if number(b"NELEC") != electrons:
        raise ValueError(
            "Native FCIDUMP electron count differs from the checked export"
        )
    norb, original = number(b"NORB"), number(b"MS2")
    unpaired = multiplicity - 1
    if (
        type(electrons) is not int
        or type(multiplicity) is not int
        or multiplicity < 1
        or (electrons - unpaired) % 2
        or unpaired > min(electrons, 2 * norb - electrons)
        or original not in (0, unpaired)
    ):
        raise ValueError("Native/target electron and spin sectors are inconsistent")
    corrected = re.sub(
        rb"(\bMS2\s*=\s*)[+-]?\d+",
        lambda match: match[1] + str(unpaired).encode(),
        header,
        count=1,
        flags=re.I,
    )
    portable = corrected + raw[header_end.end() :]
    return portable, {
        "raw_ms2": original,
        "target_ms2": unpaired,
        "alpha_electrons": (electrons + unpaired) // 2,
        "beta_electrons": (electrons - unpaired) // 2,
        "integral_records_changed": False,
        "spin_header_changed": original != unpaired,
    }


def export_input(reference, space, settings):
    space = casci.active_space(space, reference)
    settings = casci.casci_settings(settings, reference, space)
    if settings["nroots"] != 1 or len(space["orbitals"]) > 32:
        raise ValueError(
            "Export uses one diagnostic root and at most 32 spatial orbitals, the selected-space adapter limit"
        )
    electrons = space["electrons"] - settings["charge"] + reference["charge"]
    unpaired = settings["multiplicity"] - 1
    pairs = (electrons - unpaired) // 2
    occupation = ["2"] * pairs + ["1"] * unpaired
    occupation += ["0"] * (len(space["orbitals"]) - len(occupation))
    text = casci.casci_input(reference, space, settings)
    text = text.replace(
        " nroots 1\n", " nroots 1\n refs\n  {" + " ".join(occupation) + "}\n end\n", 1
    )
    text = text.replace("%output\n", "%output\n DumpActInts true\n", 1)
    return text.replace(" Print[P_Basis] 2", " Print[P_Basis] 0").replace(
        " Print[P_MOs] 1", " Print[P_MOs] 0"
    )


def worker_manifest(code, operation):
    record = code.base.extras.get("quantum_energy_tools", {})
    if (
        record.get("protocol") != PROTOCOL
        or operation not in record.get("commands", [])
        or not re.fullmatch(r"[0-9a-f]{64}", record.get("source_sha256", ""))
        or not isinstance(record.get("versions"), dict)
    ):
        raise ValueError(
            f"Choose an energy worker advertising {operation} with a verified source hash"
        )
    return {
        "protocol": PROTOCOL,
        "source_sha256": record["source_sha256"],
        "versions": record["versions"],
    }


class EnergyHamiltonianCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("structure", valid_type=orm.StructureData)
        spec.input("orbital_reference", valid_type=orm.Dict)
        spec.input("active_space", valid_type=orm.Dict)
        spec.input("settings", valid_type=orm.Dict)
        common_orbitals.source_spec(spec)
        spec.input(
            "metadata.options.parser_name", default="empa_orca.energy_hamiltonian"
        )
        spec.input("metadata.options.withmpi", default=False)
        spec.output("hamiltonian", valid_type=orm.SinglefileData)
        spec.output("native_export", valid_type=orm.Dict)
        spec.exit_code(
            310,
            "ERROR_EXPORT",
            message="Native one-configuration Hamiltonian export failed validation.",
        )

    def prepare_for_submission(self, folder):
        reference = self.inputs.orbital_reference.get_dict()
        if str(self.inputs.structure.uuid) != reference["structure_uuid"]:
            raise ValueError("Use the geometry bound to the prepared orbitals")
        producer = self.inputs.orbital_reference.creator
        if (
            producer is None
            or not producer.is_finished_ok
            or producer.process_type not in (
                "aiida.calculations:empa_orca.common_orbitals",
                "aiida.calculations:empa_orca.casscf",
            )
            or (producer.process_type == "aiida.calculations:empa_orca.casscf"
                and reference.get("preparation") != "casscf_verified_v1")
            or str(self.inputs.code.uuid) != str(producer.inputs.code.uuid)
        ):
            raise ValueError(
                "Use the ORCA code bound to the prepared orbital reference"
            )
        with folder.open("aiida.inp", "w") as stream:
            stream.write(
                export_input(
                    reference,
                    self.inputs.active_space.get_dict(),
                    self.inputs.settings.get_dict(),
                )
            )
        OrcaCalculation._write_structure(
            self.inputs.structure, folder, "aiida.coords.xyz"
        )
        info = common.CalcInfo()
        common_orbitals.copy_orbital(info, self.inputs)
        code = common.CodeInfo()
        code.code_uuid = self.inputs.code.uuid
        code.cmdline_params = ["aiida.inp"]
        code.stdout_name, code.join_files, code.withmpi = "aiida.out", True, False
        info.codes_info = [code]
        info.retrieve_list = ["aiida.out", "aiida.fcidump"]
        return info


class EnergyHamiltonianParser(Parser):
    def parse(self, **kwargs):
        try:
            text = self.retrieved.base.repository.get_object_content("aiida.out")
            reference = self.node.inputs.orbital_reference.get_dict()
            space = self.node.inputs.active_space.get_dict()
            settings = casci.casci_settings(
                self.node.inputs.settings.get_dict(), reference, space
            )
            counts = re.findall(r"#\(CSFs\)\s+\.\.\.\s+(\d+)", text)
            if not counts or any(int(count) != 1 for count in counts):
                raise ValueError(
                    "Hamiltonian export must contain exactly one diagnostic CSF"
                )
            skipped = (
                "MaxIter==0 has been chosen - skipping the SCF" in text
                or "Occupation numbers from the input are taken because of NoIter"
                in text
            )
            if not skipped or re.search(
                r"SCF CONVERGED AFTER\s+[1-9]\d*\s+CYCLES", text
            ):
                raise ValueError("Unexpected SCF during fixed-orbital export")
            if (
                "Input Geometry matches current geometry" not in text
                or "Input basis set matches current basis set" not in text
            ):
                raise ValueError(
                    "The native geometry or basis differs from the prepared orbitals"
                )
            parsed = casci.parse_states(text, reference, space, settings)
            version = re.search(r"Program Version\s+(\S+)", text)
            with self.retrieved.base.repository.open("aiida.fcidump", "rb") as stream:
                raw = stream.read()
            portable, sector = portable_fcidump(
                raw, parsed["active_electrons"], settings["multiplicity"]
            )
            sha = hashlib.sha256(portable).hexdigest()
            self.out(
                "hamiltonian",
                orm.SinglefileData(
                    file=io.BytesIO(portable), filename="hamiltonian.fcidump"
                ),
            )
            record = {
                "native_csfs": 1,
                "not_a_correlated_CASCI_state": True,
                "orbital_reference_uuid": str(self.node.inputs.orbital_reference.uuid),
                "active_space": {
                    "electrons": parsed["active_electrons"],
                    "orbitals": space["orbitals"],
                },
                "reference_active_space": space,
                "charge": settings["charge"],
                "multiplicity": settings["multiplicity"],
                "orca_version": version.group(1) if version else None,
                "auxiliary_basis": settings["auxiliary_basis"],
                "integral_transform": "RI",
                "diagnostic_energy_hartree": parsed["states"][0]["energy_hartree"],
                "hamiltonian_sha256": sha,
                "raw_fcidump_sha256": hashlib.sha256(raw).hexdigest(),
                "sector": sector,
                "full_casci_computed": False,
            }
            self.out("native_export", orm.Dict(dict=record))
        except (ValueError, OSError, KeyError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_EXPORT


class EnergyStageCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("hamiltonian", valid_type=orm.SinglefileData)
        spec.input("native_export", valid_type=orm.Dict)
        spec.input("operation", valid_type=orm.Str)
        spec.input("sector", valid_type=orm.Dict, required=False)
        spec.input("settings", valid_type=orm.Dict)
        spec.input("circuit_manifest", valid_type=orm.Dict, required=False)
        spec.input("circuits", valid_type=orm.SinglefileData, required=False)
        spec.input("samples", valid_type=orm.SinglefileData, required=False)
        spec.input("prepared", valid_type=orm.SinglefileData, required=False)
        spec.input("prepared_manifest", valid_type=orm.Dict, required=False)
        spec.input("metadata.options.parser_name", default="empa_orca.energy_stage")
        spec.input("metadata.options.withmpi", default=False)
        spec.output("result", valid_type=orm.Dict)
        for name in ("circuits", "samples", "states", "prepared"):
            spec.output(name, valid_type=orm.SinglefileData, required=False)
        spec.exit_code(
            310, "ERROR_STAGE", message="Energy stage failed; inspect the stage report."
        )

    def prepare_for_submission(self, folder):
        operation = self.inputs.operation.value
        if operation not in (
            "validate",
            "generate",
            "sample-simulator",
            "solve-full",
            "solve-sampled",
            "prepare-hardware",
            "sample-hardware",
        ):
            raise ValueError("Unsupported energy operation")
        native = self.inputs.native_export.get_dict()
        with self.inputs.hamiltonian.open(mode="rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if sha != native["hamiltonian_sha256"]:
            raise ValueError("Hamiltonian and native export manifest differ")
        creator = self.inputs.hamiltonian.creator
        if (
            creator is None
            or not creator.is_finished_ok
            or self.inputs.native_export.creator is None
            or creator.uuid != self.inputs.native_export.creator.uuid
        ):
            raise ValueError(
                "Use the Hamiltonian and manifest from the same successful native export"
            )
        request = {
            "worker_manifest": worker_manifest(self.inputs.code, operation),
            "hamiltonian_sha256": sha,
            "native_export": native,
            "settings": self.inputs.settings.get_dict(),
            "sector": self.inputs.sector.get_dict()
            if "sector" in self.inputs
            else None,
        }
        info = common.CalcInfo()
        info.local_copy_list = [
            (
                self.inputs.hamiltonian.uuid,
                self.inputs.hamiltonian.filename,
                "hamiltonian.fcidump",
            )
        ]
        if operation in ("sample-simulator", "prepare-hardware"):
            manifest = self.inputs.circuit_manifest.get_dict()
            producer = self.inputs.circuits.creator
            if (
                producer is None
                or not producer.is_finished_ok
                or self.inputs.circuit_manifest.creator is None
                or manifest["hamiltonian_sha256"] != sha
                or manifest.get("sector") != request["sector"]
                or producer.uuid != self.inputs.circuit_manifest.creator.uuid
            ):
                raise ValueError(
                    "Use matching circuits and manifest for this Hamiltonian"
                )
            request["circuit_manifest"] = manifest
            info.local_copy_list.append(
                (
                    self.inputs.circuits.uuid,
                    self.inputs.circuits.filename,
                    "circuits.qpy",
                )
            )
        if operation == "sample-hardware":
            prepared = self.inputs.prepared_manifest.get_dict()
            if (
                self.inputs.prepared.creator is None
                or not self.inputs.prepared.creator.is_finished_ok
                or self.inputs.prepared_manifest.creator is None
                or prepared["hamiltonian_sha256"] != sha
                or prepared.get("sector") != request["sector"]
                or self.inputs.prepared.creator.uuid
                != self.inputs.prepared_manifest.creator.uuid
                or self.inputs.prepared.creator.inputs.code.uuid
                != self.inputs.code.uuid
                or any(
                    prepared["software"][key] != value
                    for key, value in request["worker_manifest"].items()
                )
            ):
                raise ValueError("Use the reviewed preparation for this Hamiltonian")
            request["prepared_manifest"] = prepared
            info.local_copy_list.append(
                (
                    self.inputs.prepared.uuid,
                    self.inputs.prepared.filename,
                    "prepared.qpy",
                )
            )
        if operation == "solve-sampled":
            with self.inputs.samples.open(mode="rb") as stream:
                request["samples_sha256"] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
            info.local_copy_list.append(
                (self.inputs.samples.uuid, self.inputs.samples.filename, "samples.json")
            )
        with folder.open("request.json", "w") as stream:
            json.dump(request, stream, allow_nan=False)
        code = common.CodeInfo()
        code.code_uuid = self.inputs.code.uuid
        code.cmdline_params = [operation, "--request", "request.json"]
        code.stdout_name, code.join_files, code.withmpi = "driver.log", True, False
        info.codes_info = [code]
        artifact = {
            "generate": "circuits.qpy",
            "sample-simulator": "samples.json",
            "solve-full": "states.npz",
            "solve-sampled": "states.npz",
            "prepare-hardware": "prepared.qpy",
            "sample-hardware": "samples.json",
        }.get(operation)
        info.retrieve_list = ["driver.log", "result.json"] + (
            [artifact] if artifact else []
        )
        return info


class EnergyStageParser(Parser):
    def parse(self, **kwargs):
        try:
            result = json.loads(
                self.retrieved.base.repository.get_object_content("result.json")
            )
            operation = self.node.inputs.operation.value
            if (
                result["operation"] != operation
                or result.get("sector")
                != (
                    self.node.inputs.sector.get_dict()
                    if "sector" in self.node.inputs
                    else None
                )
                or result["settings"] != self.node.inputs.settings.get_dict()
                or result["hamiltonian_sha256"]
                != self.node.inputs.native_export.get_dict()["hamiltonian_sha256"]
                or result["qpu_jobs_submitted"]
                not in ((0, 1) if operation == "sample-hardware" else (0,))
                or any(
                    result["software"][key] != value
                    for key, value in worker_manifest(
                        self.node.inputs.code, operation
                    ).items()
                )
            ):
                raise ValueError(
                    "Energy result identity differs from the reviewed request"
                )
            artifact = {
                "generate": ("circuits", "circuits.qpy"),
                "sample-simulator": ("samples", "samples.json"),
                "solve-full": ("states", "states.npz"),
                "solve-sampled": ("states", "states.npz"),
                "prepare-hardware": ("prepared", "prepared.qpy"),
                "sample-hardware": ("samples", "samples.json")
                if result.get("samples_available")
                else None,
            }.get(operation)
            if artifact:
                key, filename = artifact
                with self.retrieved.base.repository.open(filename, "rb") as stream:
                    if (
                        hashlib.file_digest(stream, "sha256").hexdigest()
                        != result[key + "_sha256"]
                    ):
                        raise ValueError("Energy artifact checksum differs")
                    stream.seek(0)
                    self.out(key, orm.SinglefileData(file=stream, filename=filename))
            result["native_export"] = self.node.inputs.native_export.get_dict()
            if operation == "solve-sampled":
                with self.node.inputs.samples.open(mode="rb") as stream:
                    if (
                        hashlib.file_digest(stream, "sha256").hexdigest()
                        != result["input_samples_sha256"]
                    ):
                        raise ValueError(
                            "The analysis refers to different input samples"
                        )
            self.out("result", orm.Dict(dict=result))
        except (ValueError, OSError, KeyError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_STAGE


class EnergyExportWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {
            "orbital_reference": orm.Dict,
            "source_remote": orm.RemoteData,
            "active_space": orm.Dict,
            "settings": orm.Dict,
            "orca_code": orm.AbstractCode,
            "worker_code": orm.AbstractCode,
        }.items():
            spec.input(key, valid_type=typ)
        spec.output("hamiltonian", valid_type=orm.SinglefileData)
        spec.output("native_export", valid_type=orm.Dict)
        spec.output("validation", valid_type=orm.Dict)
        spec.outline(cls.export, cls.inspect_export, cls.validate, cls.results)
        spec.exit_code(
            400, "ERROR_INPUT", message="The active-space export inputs are invalid."
        )
        spec.exit_code(
            401, "ERROR_CHILD", message="The native export or validation failed."
        )

    def export(self):
        try:
            reference = casci.validate_reference(
                self.inputs.orbital_reference, self.inputs.source_remote
            )
            space = casci.active_space(self.inputs.active_space.get_dict(), reference)
            settings = casci.casci_settings(
                self.inputs.settings.get_dict(), reference, space
            )
            export_input(reference, space, settings)
            worker_manifest(self.inputs.worker_code, "validate")
            location = common_orbitals.reference_location(
                self.inputs.orbital_reference.creator
            )
            builder = EnergyHamiltonianCalculation.get_builder()
            builder.orbital_reference, builder.active_space = (
                self.inputs.orbital_reference,
                self.inputs.active_space,
            )
            builder.structure = orm.load_node(reference["structure_uuid"])
            builder.settings, builder.code = self.inputs.settings, self.inputs.orca_code
            common_orbitals.attach_orbital(builder, location, reference["filename"])
            builder.metadata.options = common_orbitals.options(settings)
            builder.metadata.label = "Export fixed-orbital Hamiltonian · no full CASCI"
            return engine.ToContext(pending=self.submit(builder))
        except (ValueError, KeyError, OSError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INPUT

    def inspect_export(self):
        if not self.ctx.pending.is_finished_ok:
            return self.exit_codes.ERROR_CHILD
        self.ctx.export_uuid = str(self.ctx.pending.uuid)
        del self.ctx["pending"]

    def validate(self):
        native = orm.load_node(self.ctx.export_uuid)
        builder = EnergyStageCalculation.get_builder()
        builder.code = self.inputs.worker_code
        builder.hamiltonian, builder.native_export = (
            native.outputs.hamiltonian,
            native.outputs.native_export,
        )
        builder.operation, builder.settings = orm.Str("validate"), orm.Dict(dict={})
        builder.metadata.options = {
            "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1},
            "withmpi": False,
            "max_memory_kb": 4 * 1024**2,
            "max_wallclock_seconds": 600,
        }
        return engine.ToContext(pending=self.submit(builder))

    def results(self):
        if (
            not self.ctx.pending.is_finished_ok
            or not self.ctx.pending.outputs.result.get_dict().get("passed")
        ):
            return self.exit_codes.ERROR_CHILD
        native = orm.load_node(self.ctx.export_uuid)
        self.out("hamiltonian", native.outputs.hamiltonian)
        self.out("native_export", native.outputs.native_export)
        self.out("validation", self.ctx.pending.outputs.result)
