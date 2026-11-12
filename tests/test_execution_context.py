"""Execution captions follow the actual configured Computer without connections."""

import pytest
from aiida import orm

from aiidalab_orca import services
from aiidalab_orca.resources import execution_hint


@pytest.mark.parametrize("transport,scheduler", [
    ("core.local", "core.direct"),
    ("core.ssh", "core.slurm"),
    ("core.ssh", "core.pbspro"),
])
def test_context_uses_plain_computer_metadata(aiida_profile_clean, transport, scheduler):
    computer = orm.Computer(
        label="configured-computer", hostname="unused.invalid",
        transport_type=transport, scheduler_type=scheduler,
    ).store()
    code = orm.InstalledCode(
        label="configured-orca", computer=computer,
        filepath_executable="/configured/orca", default_calc_job_plugin="orca.orca",
    ).store()
    context = services.execution_context(code.uuid)
    assert context == {"computer": "configured-computer", "transport": transport,
                       "scheduler": scheduler}
    hint = execution_hint(context)
    assert transport in hint and scheduler in hint
    assert ("does not enforce a hard memory limit" in hint) == (scheduler == "core.direct")
    assert "75%" in hint and "Local execution" not in hint


def test_missing_code_never_claims_local_execution(aiida_profile_clean):
    assert services.execution_context(None) is None
    assert services.execution_context("00000000-0000-4000-8000-000000000000") is None
    assert "Select an available ORCA code" in execution_hint(None)
    assert "hard memory limit" not in execution_hint(None)


def test_caption_escapes_metadata_and_does_not_filter_other_plugins():
    hint = execution_hint({"computer": "<remote>", "transport": "custom.transport",
                           "scheduler": "custom.scheduler"})
    assert "&lt;remote&gt;" in hint and "<remote>" not in hint
    assert "custom.transport" in hint and "custom.scheduler" in hint


def test_real_app_refreshes_remote_local_and_cleared_code(aiida_profile_clean, monkeypatch):
    from aiidalab_orca.app import OrcaApp

    codes = []
    for label, transport, scheduler in [
        ("remote-computer", "core.ssh", "core.slurm"),
        ("local-computer", "core.local", "core.direct"),
    ]:
        computer = orm.Computer(label=label, hostname="unused.invalid",
                               transport_type=transport, scheduler_type=scheduler).store()
        code = orm.InstalledCode(label="orca", computer=computer,
                                 filepath_executable="/configured/orca",
                                 default_calc_job_plugin="orca.orca").store()
        codes.append((label, code.uuid))
    monkeypatch.setattr(services, "codes", lambda: codes)
    app = OrcaApp()
    try:
        assert "remote-computer" in app.resource_hint.value
        assert "core.ssh" in app.resource_hint.value and "core.slurm" in app.resource_hint.value
        assert "does not enforce" not in app.resource_hint.value
        app.review = {"reviewed": True}
        app.code.value = codes[1][1]
        assert app.review is None and app.submit_button.disabled
        assert "local-computer" in app.resource_hint.value
        assert "core.local" in app.resource_hint.value and "core.direct" in app.resource_hint.value
        assert "does not enforce a hard memory limit" in app.resource_hint.value
        app.code.options = []
        assert "Select an available ORCA code" in app.resource_hint.value
        assert "local-computer" not in app.resource_hint.value
    finally:
        app.close()
