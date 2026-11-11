#!/usr/bin/env python3
"""Report Block2 packaging and launcher identity without imports or execution.

Run inside the intended native runtime, not the AiiDAlab interpreter by guess.
This metadata check is a prerequisite report, not a scientific acceptance test.
It installs/registers nothing and never opens an AiiDA profile.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path


def inspect_runtime(executable=None):
    try:
        distribution = importlib.metadata.distribution("block2")
    except importlib.metadata.PackageNotFoundError:
        return {
            "status": "UNAVAILABLE",
            "error": "Block2 is not installed in this interpreter",
        }
    launchers = [
        Path(distribution.locate_file(item)).resolve()
        for item in distribution.files or []
        if Path(item).name == "block2main"
    ]
    launcher = Path(executable).resolve() if executable else next(iter(launchers), None)
    version = distribution.version
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    errors = []
    if version != "0.5.4":
        errors.append("The current adapter supports released Block2 0.5.4")
    if direct.get("vcs_info") or direct.get("dir_info"):
        errors.append(
            "An unreleased/editable source cannot qualify as the official release artifact"
        )
    if launcher is None or not launcher.is_file() or launcher.name != "block2main":
        errors.append("The block2main launcher is unavailable")
    elif launcher not in launchers:
        errors.append("The selected launcher is not owned by this Block2 distribution")
    digest = (
        hashlib.sha256(launcher.read_bytes()).hexdigest()
        if launcher and launcher.is_file()
        else None
    )
    return {
        "status": "FAIL" if errors else "METADATA_OK",
        "errors": errors,
        "version": version,
        "launcher": str(launcher) if launcher else None,
        "launcher_sha256": digest,
        "distribution_path": str(distribution.locate_file("")),
        "direct_url": direct,
        "native_import_checked": False,
        "native_execution_checked": False,
        "release_artifact_digest_checked": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", help="Exact intended block2main path")
    args = parser.parse_args()
    report = inspect_runtime(args.executable)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "METADATA_OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
