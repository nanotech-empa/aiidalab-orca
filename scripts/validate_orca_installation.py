"""Validate local ORCA with serial and parallel app-submitted PBE0 calculations."""

import argparse
import json
from pathlib import Path
import re
import time


WATER = "3\nORCA runtime validation\nO 0 0 0.0626\nH -0.792 0 -0.4973\nH 0.792 0 -0.4973\n"


def code_identifiers(identifier):
    from aiida import orm
    from aiidalab_orca.property_services import helper_code

    code = orm.load_code(identifier)
    if code.computer.transport_type != "core.local":
        raise ValueError("This installation check is for a local ORCA code")
    return str(code.uuid), helper_code(str(code.computer.uuid))


def check_finished(identifier, processes):
    """Inspect nodes only during this operation; return plain verification data."""
    from aiida import orm
    from aiida_orca.parsers.cclib.utils import convertor
    from aiidalab_orca.property_services import wavefunction_status

    node = orm.load_node(identifier)
    if not node.is_finished_ok:
        raise RuntimeError(f"Installation check failed: {identifier}: {node.exit_message}")
    text = node.outputs.retrieved.base.repository.get_object_content("aiida.out")
    if "ORCA TERMINATED NORMALLY" not in text:
        raise RuntimeError("ORCA did not confirm normal termination")
    if processes > 1 and f"{processes} parallel MPI-processes" not in text:
        raise RuntimeError("Output does not confirm the requested MPI process count")
    raw = float(re.findall(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)", text)[-1])
    parsed = float(node.outputs.output_parameters.get_dict()["scfenergies"][-1]) / float(convertor(1.0, "hartree", "eV"))
    if abs(raw - parsed) > 1e-7:
        raise RuntimeError("Parsed and raw energies disagree")
    jobs = [c for c in node.called_descendants if isinstance(c, orm.CalcJobNode)]
    if not jobs or any(c.base.caching.is_created_from_cache for c in jobs):
        raise RuntimeError("Installation validation must execute real CalcJobs")
    files = wavefunction_status(identifier)
    if files["state"] not in ("repository", "stash"):
        raise RuntimeError("Wavefunction bundle was not preserved")
    return {"workflow_uuid": identifier, "processes": processes,
            "raw_energy_hartree": raw, "parsed_energy_hartree": parsed,
            "wavefunction_storage": files["state"],
            "calculation_uuids": [str(c.uuid) for c in jobs]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=True, help="Installed local ORCA code UUID or label")
    parser.add_argument("--output", required=True, type=Path, help="New JSON record path")
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--memory-mb", type=int, default=4096)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; preserve the earlier validation record")
    if args.processes < 2 or args.memory_mb < 256 * args.processes or args.timeout_seconds < 1:
        parser.error("Choose at least 2 processes, 256 MiB per process and a positive timeout")

    from aiida import load_profile
    load_profile()
    from aiida_empa_orca.protocols import protocol_settings
    from aiidalab_orca import services
    from aiidalab_orca.property_services import default_stash_directory

    code_uuid, storage_uuid = code_identifiers(args.code)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    record = {"code_uuid": code_uuid, "status": "running", "runs": []}

    def save():
        args.output.write_text(json.dumps(record, indent=2) + "\n")

    save()
    try:
        for processes in (1, args.processes):
            settings = protocol_settings("pbe0-v1", {
                "charge": 0, "multiplicity": 1, "reference": "RKS",
                "nprocs": processes, "memory_mb": args.memory_mb,
                "wallclock_seconds": args.timeout_seconds,
            })
            review = services.prepare(WATER, "", settings, code_uuid, False, True,
                storage={"policy": {"threshold_mb": 100,
                                     "stash_directory": default_stash_directory()},
                         "code_uuid": storage_uuid})
            identifier = services.submit_plan(review,
                f"ORCA installation check · PBE0 water · {processes} process(es)")
            entry = {"workflow_uuid": identifier, "processes": processes, "status": "submitted"}
            record["runs"].append(entry)
            save()
            print(f"Submitted {processes}-process app workflow: {identifier}", flush=True)
            deadline = time.monotonic() + args.timeout_seconds
            while not services.result(identifier)["finished"]:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Workflow {identifier} is still running; inspect AiiDA before resuming")
                time.sleep(5)
            entry.update(check_finished(identifier, processes), status="passed")
            save()
            print(f"Energy: {entry['raw_energy_hartree']:.12f} Hartree", flush=True)
        difference = abs(record["runs"][0]["raw_energy_hartree"] - record["runs"][1]["raw_energy_hartree"])
        record["energy_difference_hartree"] = difference
        if difference > 1e-7:
            raise RuntimeError("Serial/parallel energies differ by more than 1e-7 Hartree")
        record["status"] = "passed"
        save()
        print(f"Serial/parallel difference: {difference:.3g} Hartree; PASS", flush=True)
    except Exception as exc:
        record.update(status="failed", error=str(exc))
        save()
        raise


if __name__ == "__main__":
    main()
