import pytest
from ase import Atoms

from aiidalab_orca.app import OrcaApp
from aiidalab_orca.assistant import OrcaAssistantAdapter


@pytest.fixture
def adapter(aiida_profile, monkeypatch):
    monkeypatch.setattr("aiidalab_orca.services.codes", lambda: [])
    app = OrcaApp(enable_assistant=False)
    app.structure.set_atoms(Atoms("NO", positions=[[0, 0, 0], [0, 0, 1.2]]))
    yield OrcaAssistantAdapter(app)
    app.close()


def test_updates_actual_widgets_validates_spin_and_undo(adapter):
    before = adapter.context()
    after = adapter.update(before["revision"], settings={"method": "PBE", "multiplicity": 2}, nprocs=8)
    assert adapter.app.nprocs.value == 8
    assert adapter.app.science.multiplicity.value == 2
    assert adapter.app._structure_confirmed
    assert not adapter.app.confirm_settings.disabled
    assert adapter.app.steps.selected_index == 1
    assert not adapter.app._settings_confirmed
    assert adapter.app.submit_button.disabled
    adapter.undo(after["state"]["revision"])
    assert adapter.app.nprocs.value == before["nprocs"]
    before = adapter.context()
    with pytest.raises(ValueError):
        adapter.update(before["revision"], settings={"multiplicity": 1}, nprocs=8)
    assert adapter.context()["revision"] == before["revision"]


def test_manual_changes_and_submission_invalidate_edit_and_undo(adapter):
    before = adapter.context()
    adapter.app.nprocs.value = 4
    with pytest.raises(ValueError, match="form changed"):
        adapter.update(before["revision"], nprocs=8)
    result = adapter.update(adapter.context()["revision"], nprocs=8)
    adapter.app.label.value = "My manual label"
    with pytest.raises(ValueError):
        adapter.undo(result["state"]["revision"])
    adapter.app._submitted = True
    with pytest.raises(ValueError, match="submitted"):
        adapter.update(adapter.context()["revision"], nprocs=2)


def test_out_of_range_does_not_silently_clamp(adapter):
    before = adapter.context()
    with pytest.raises(ValueError, match="range"):
        adapter.update(before["revision"], nprocs=999)
    assert adapter.context()["revision"] == before["revision"]


def test_load_structure_preserves_source_uuid(adapter, aiida_profile):
    from aiida import orm
    original = orm.StructureData(ase=Atoms("H2", positions=[[0, 0, 0], [0, 0, 0.7]])).store()
    result = adapter.load_structure(str(original.uuid), adapter.context()["revision"])
    assert result["source_uuid"] == str(original.uuid)
    assert adapter.app.structure.atoms.get_chemical_formula() == "H2"


def test_review_from_assistant_worker_records_import_provenance(adapter, tmp_path, aiida_profile_clean, aiida_localhost):
    """Exercise the real calcfunction review path from a running notebook loop."""
    import asyncio
    from aiida import orm
    AssistantPanel = pytest.importorskip("aiidalab_ai_assistant.panel").AssistantPanel
    from aiidalab_ai_assistant.sessions import SessionStore

    original = b"2\nNO\nN 0 0 0\nO 0 0 1.2\n"
    adapter.app.structure.set_atoms(
        Atoms("NO", positions=[[0, 0, 0], [0, 0, 1.2]]),
        imported={"kind": "file", "filename": "no.xyz", "content": original},
    )
    # This disposable code is only reviewed; no CalcJob is submitted.
    code_uuid = str(orm.InstalledCode(
        computer=aiida_localhost, filepath_executable="/bin/true",
        default_calc_job_plugin="orca.orca",
    ).store().uuid)
    adapter.app.code.options = [("Test ORCA code", code_uuid)]
    adapter.app.code.value = code_uuid
    adapter.app.wavefunction_storage.enabled.value = False

    async def scenario():
        panel = AssistantPanel(adapter=adapter, store=SessionStore(tmp_path), autoconnect=False)
        try:
            result = await asyncio.to_thread(
                panel.service.registry.call, "orca_review",
                {"expected_revision": adapter.context()["revision"]},
            )
            assert "error" not in result, result
            assert adapter.app.review is not None
            assert not adapter.app.submit_button.disabled
            assert not adapter.app._submitted
            return result["review"]["structure_uuid"]
        finally:
            panel.close()

    uuid = asyncio.run(scenario())
    node = orm.load_node(uuid)
    assert node.creator.process_label == "record_structure_import"
    assert node.creator.is_finished_ok
    assert node.creator.inputs.source_file.get_content().encode() == original
    assert orm.QueryBuilder().append(orm.CalcJobNode).count() == 0


def test_review_failure_exposes_displayed_error_without_changing_revision(adapter, monkeypatch):
    ToolRegistry = pytest.importorskip("aiidalab_ai_assistant.tools").ToolRegistry

    message = "Cannot run awaitable: no greenback portal; use <current task> & retry."

    def fail(*args, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr("aiidalab_orca.services.prepare", fail)
    adapter.app.wavefunction_storage.enabled.value = False
    registry = ToolRegistry()
    adapter.register(registry)
    before = registry.call("orca_get_state", {})
    result = registry.call("orca_review", {"expected_revision": before["revision"]})
    assert result["error"] == "resources: " + message
    after = registry.call("orca_get_state", {})
    assert after["messages"]["resources"] == message
    assert after["revision"] == before["revision"]
    assert after["review_ready"] is False
    assert after["setup_step"] == 2
