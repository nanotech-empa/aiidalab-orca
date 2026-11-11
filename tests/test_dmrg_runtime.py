"""The readiness helper reads packaging only and never runs the native launcher."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def helper():
    path = Path(__file__).resolve().parents[1] / "scripts/check_dmrg_runtime.py"
    spec = importlib.util.spec_from_file_location("dmrg_runtime_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_distribution_is_not_a_green_readiness_result(helper, monkeypatch):
    def missing(_):
        raise helper.importlib.metadata.PackageNotFoundError("block2")

    monkeypatch.setattr(helper.importlib.metadata, "distribution", missing)
    assert helper.inspect_runtime()["status"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "version,direct,status",
    [
        ("0.5.4", {}, "METADATA_OK"),
        ("0.5.3", {}, "FAIL"),
        ("0.5.4", {"vcs_info": {"commit_id": "a" * 40}}, "FAIL"),
        ("0.5.4", {"dir_info": {"editable": True}}, "FAIL"),
    ],
)
def test_official_metadata_and_launcher_ownership(
    helper, monkeypatch, tmp_path, version, direct, status
):
    # Deliberately nonexecutable: metadata inspection must not try to run it.
    (tmp_path / "block2main").write_text("launcher fixture\n")
    dist = SimpleNamespace(
        version=version,
        files=[Path("block2main")],
        locate_file=lambda name: tmp_path / name,
        read_text=lambda name: json.dumps(direct),
    )
    monkeypatch.setattr(helper.importlib.metadata, "distribution", lambda _: dist)
    result = helper.inspect_runtime()
    assert result["status"] == status
    assert len(result["launcher_sha256"]) == 64
    assert (
        not result["native_import_checked"] and not result["native_execution_checked"]
    )
    foreign = tmp_path / "foreign/block2main"
    foreign.parent.mkdir()
    foreign.write_text("different launcher\n")
    assert helper.inspect_runtime(str(foreign))["status"] == "FAIL"
