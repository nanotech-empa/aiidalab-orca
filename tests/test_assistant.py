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


def test_import_smiles_uses_gui_builder_and_preserves_smiles_provenance(adapter, aiida_profile):
    from aiida import orm
    from aiidalab_ai_assistant.tools import ToolRegistry
    from aiidalab_orca.structure_io import store_reviewed_structure
    registry = ToolRegistry()
    adapter.register(registry)
    result = registry.call("orca_import_smiles", {
        "smiles": "c1ccccc1", "expected_revision": adapter.context()["revision"],
    })
    assert "error" not in result, result
    assert result["formula"] == "C6H6" and result["formal_charge"] == 0
    assert adapter.app.structure.smiles.smiles.value == result["smiles"]
    assert adapter.app.structure.importers.selected_index == 3
    assert adapter.app.structure.ready
    assert not adapter.app._submitted
    uuid = store_reviewed_structure(adapter.app.structure.atoms,
                                   imported=adapter.app.structure.imported)
    node = orm.load_node(uuid)
    assert node.creator.process_label == "record_structure_import"
    assert node.creator.inputs.source_file.get_content() == result["smiles"]
    assert orm.QueryBuilder().append(orm.CalcJobNode).count() == 0


def test_smiles_failure_or_stale_revision_preserves_existing_structure(adapter):
    before = adapter.context()["revision"]
    with pytest.raises(ValueError):
        adapter.import_smiles("not a valid smiles", before)
    assert adapter.context()["revision"] == before
    assert adapter.app.structure.atoms.get_chemical_formula() == "NO"
    adapter.app.label.value = "Manual edit"
    with pytest.raises(ValueError, match="form changed"):
        adapter.import_smiles("c1ccccc1", before)
    adapter.app._submitted = True
    with pytest.raises(ValueError, match="submitted"):
        adapter.import_smiles("c1ccccc1", adapter.context()["revision"])


def test_import_structure_fills_file_draft_and_retains_exact_source(adapter, aiida_profile):
    import hashlib
    from aiida import orm
    from aiidalab_ai_assistant.tools import ToolRegistry
    from aiidalab_orca.structure_io import store_reviewed_structure

    text = "2\nH2; test geometry in angstrom; https://example.org/source\nH 0 0 0\nH 0 0 0.74\n"
    registry = ToolRegistry()
    adapter.register(registry)
    before = orm.QueryBuilder().append(orm.Node).count()
    result = registry.call("orca_import_structure", {
        "filename": "literature.xyz", "content": text,
        "expected_revision": adapter.context()["revision"],
    })
    assert "error" not in result, result
    assert orm.QueryBuilder().append(orm.Node).count() == before
    assert result["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert result["state"]["geometry"]["formula"] == "H2"
    assert result["state"]["geometry"]["atom_count"] == 2
    assert result["state"]["geometry"]["pbc"] == [False] * 3
    assert adapter.app.structure.xyz.value == text
    assert adapter.app.structure.importers.selected_index == 0
    assert result["state"]["setup_step"] == 0
    assert adapter.app.structure.ready and not adapter.app._submitted
    uuid = store_reviewed_structure(adapter.app.structure.atoms,
                                   imported=adapter.app.structure.imported)
    stored = orm.load_node(uuid)
    assert stored.creator.process_label == "record_structure_import"
    assert stored.creator.inputs.source_file.get_content() == text
    assert stored.creator.inputs.source_file.filename == "literature.xyz"
    assert orm.QueryBuilder().append(orm.CalcJobNode).count() == 0


@pytest.mark.parametrize("filename, content", [
    ("incomplete.xyz", "2\nmissing row\nH 0 0 0\n"),
    ("frames.xyz", "1\nfirst\nH 0 0 0\n1\nsecond\nH 0 0 1\n"),
    ("nan.xyz", "1\ninvalid\nH nan 0 0\n"),
    ("../other.xyz", "1\ntest\nH 0 0 0\n"),
    ("source.bin", "unknown format"),
    ("empty.xyz", ""),
    ("large.xyz", "é" * (1024 * 1024 + 1)),
])
def test_invalid_structure_file_preserves_existing_draft(adapter, filename, content):
    before = adapter.context()
    with pytest.raises(Exception):
        adapter.import_structure(filename, content, before["revision"])
    assert adapter.context()["revision"] == before["revision"]
    assert adapter.app.structure.atoms.get_chemical_formula() == "NO"


def test_structure_file_respects_newer_edits_and_submitted_state(adapter):
    text = "2\nH2\nH 0 0 0\nH 0 0 .74\n"
    revision = adapter.context()["revision"]
    adapter.app.label.value = "Newer manual edit"
    with pytest.raises(ValueError, match="form changed"):
        adapter.import_structure("h2.xyz", text, revision)
    adapter.app._submitted = True
    with pytest.raises(ValueError, match="submitted"):
        adapter.import_structure("h2.xyz", text, adapter.context()["revision"])
    assert adapter.app.structure.atoms.get_chemical_formula() == "NO"


def test_extxyz_import_keeps_periodic_input_for_explicit_review(adapter):
    text = ('1\nLattice="4 0 0 0 5 0 0 0 6" Properties=species:S:1:pos:R:3 pbc="T F F"\n'
            'C 0 0 0\n')
    result = adapter.import_structure("source.extxyz", text, adapter.context()["revision"])
    assert result["state"]["geometry"]["pbc"] == [True, False, False]
    assert result["state"]["geometry"]["cell_angstrom"] == [[4., 0., 0.], [0., 5., 0.], [0., 0., 6.]]
    assert "Periodic input" in adapter.app.structure.summary.value
    assert not adapter.app._submitted


def test_review_from_assistant_worker_records_import_provenance(adapter, tmp_path, aiida_profile_clean, aiida_localhost, configured_orca_tools):
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
    adapter.app.pdos_enabled.value = False

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
    adapter.app.pdos_enabled.value = False
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



def test_cdxml_import_and_creation_use_existing_gui_and_provenance(adapter, aiida_profile):
    from aiida import orm
    from aiidalab_ai_assistant.tools import ToolRegistry
    from aiidalab_orca.structure_io import store_reviewed_structure

    text = '<CDXML><page><fragment><n id="1" p="0 0" Element="6"/><n id="2" p="10 0" Element="6"/><b B="1" E="2" Order="2"/></fragment></page></CDXML>'
    registry = ToolRegistry()
    adapter.register(registry)
    result = registry.call("orca_import_structure", {
        "filename": "ethene.cdxml", "content": text,
        "expected_revision": adapter.context()["revision"],
    })
    assert "error" not in result, result
    assert result["status"] == "cdxml_uploaded"
    assert adapter.app.structure.atoms.get_chemical_formula() == "NO"
    revision = adapter.context()["revision"]
    widget = adapter.app.structure.cdxml
    widget.symmetrize_geometry.value = not widget.symmetrize_geometry.value
    assert "error" in registry.call("orca_prepare_cdxml", {
        "expected_revision": revision, "create_model": True,
    })
    result = registry.call("orca_prepare_cdxml", {
        "expected_revision": adapter.context()["revision"], "create_model": True,
    })
    assert "error" not in result, result
    assert result["status"] == "model_created"
    assert result["state"]["geometry"]["formula"] == "C2H4"
    assert adapter.app.structure.importers.selected_index == 2
    assert adapter.app.structure.imported["original"] == text.encode()
    uuid = store_reviewed_structure(adapter.app.structure.atoms, imported=adapter.app.structure.imported)
    node = orm.load_node(uuid)
    assert node.creator.process_label == "record_cdxml_import"
    assert orm.QueryBuilder().append(orm.CalcJobNode).count() == 0
    adapter.app._submitted = True
    assert "error" in registry.call("orca_prepare_cdxml", {
        "expected_revision": adapter.context()["revision"], "create_model": True,
    })
