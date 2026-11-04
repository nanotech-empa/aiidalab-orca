"""Register one new immutable energy Code from its actual worker manifest."""

import argparse
import json
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--computer", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--label", required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--manifest-json", type=Path, required=True)
    parser.add_argument("--prepend-file", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest_json.read_text())
    if (
        manifest.get("protocol") != "quantum-energy/v1"
        or not re.fullmatch("[0-9a-f]{64}", manifest.get("source_sha256", ""))
        or not isinstance(manifest.get("versions"), dict)
        or not manifest.get("commands")
    ):
        raise ValueError(
            "Use the JSON emitted by the deployed quantum-energy manifest command"
        )
    from aiida import load_profile, orm
    from aiida.common.exceptions import NotExistent

    load_profile(args.profile)
    computer = orm.load_computer(args.computer)
    prepend = (
        args.prepend_file.read_text()
        if args.prepend_file
        else 'export AIIDA_PATH="$PWD/isolated-aiida"'
    )
    prepend = prepend.strip()
    try:
        existing = orm.load_code(args.label + "@" + computer.label)
    except NotExistent:
        existing = None
    if existing:
        if (
            str(existing.get_executable()) != args.executable
            or existing.prepend_text != prepend
            or existing.base.extras.get("quantum_energy_tools", {}) != manifest
        ):
            raise ValueError(
                "This Code already has a different deployment; choose a new versioned label"
            )
        print("Already configured:", existing.full_label, str(existing.uuid))
        return
    code = orm.InstalledCode(
        label=args.label,
        computer=computer,
        filepath_executable=args.executable,
        default_calc_job_plugin="empa_orca.energy_stage",
        with_mpi=False,
        prepend_text=prepend,
    ).store()
    code.base.extras.set("quantum_energy_tools", manifest)
    print("Registered:", code.full_label, str(code.uuid))


if __name__ == "__main__":
    main()
