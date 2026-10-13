"""Search, provenance and GUI/backend boundary regressions on isolated storage."""

import io

import numpy as np
import pytest
from aiida import orm
from ase import Atoms

from test_reuse import source  # noqa: F401 -- existing disposable provenance fixture
from aiidalab_orca import history, structure_io
from aiidalab_orca.structures import StructureWidget

CDXML = b'''<CDXML><page><fragment id="1"><n id="2" p="0 0"/><n id="3" p="30 0"/><b id="4" B="2" E="3" Order="2"/></fragment></page></CDXML>'''


def test_unchanged_structure_is_reused_edits_create_provenance(aiida_profile_clean):
    atoms = Atoms("NO", positions=[[0, 0, 0], [0, 0, 1.3]])
    original = orm.StructureData(ase=atoms).store()
    assert structure_io.store_reviewed_structure(atoms, original.uuid) == original.uuid
    changed = atoms.copy()
    changed.positions[1, 2] = 1.2
    edited = orm.load_node(structure_io.store_reviewed_structure(changed, original.uuid))
    assert edited.creator.process_label == "record_structure_edit"
    assert edited.creator.inputs.source_structure.uuid == original.uuid
    assert edited.get_ase().positions[1, 2] == 1.2
    assert orm.load_node(original.uuid).get_ase().positions[1, 2] == 1.3


def test_file_import_keeps_original_bytes(aiida_profile_clean):
    data = b"2\nNO\nN 0 0 0\nO 0 0 1.3\n"
    atoms = structure_io.read_file("no.xyz", data)
    uuid = structure_io.store_reviewed_structure(atoms, imported={"kind": "file", "filename": "no.xyz", "content": data})
    node = orm.load_node(uuid)
    assert node.creator.inputs.source_file.get_content().encode() == data
    assert node.get_formula() == "NO"


def test_cdxml_edit_records_source_documents_and_reviewed_model(aiida_profile_clean):
    widget = StructureWidget()
    try:
        widget.cdxml._on_file_upload({"new": {"ethene.cdxml": {"content": CDXML}}})
        widget.cdxml.create_button.click()
        assert widget.atoms.get_chemical_formula() == "C2H4"
        assert widget.imported["kind"] == "cdxml"
        changed = widget.atoms.copy()
        changed.positions[0, 2] += 0.2
        widget.editor.structure = changed
        uuid = structure_io.store_reviewed_structure(widget.atoms, imported=widget.imported)
        node = orm.load_node(uuid)
        assert node.creator.process_label == "record_cdxml_import"
        record = node.creator.inputs.parameters.get_dict()
        assert record["edited_after_generation"]
        assert node.creator.inputs.original_document.get_content().encode() == CDXML
        assert np.allclose(node.get_ase().positions, changed.positions)
        widget.mark_stored(uuid)
        widget.cdxml.structure = None  # The shared importer invalidates changed settings.
        assert not widget.ready
    finally:
        widget.close()


def test_search_filters_and_pagination(source):
    source.label = "Nitric oxide test"
    assert history.search_runs("NO")["rows"][0]["uuid"] == source.uuid
    assert history.search_runs("nitric", state="succeeded", method="PBE")["rows"]
    assert not history.search_runs(method="PBE0")["rows"]
    assert not history.search_runs(state="failed")["rows"]
    assert not history.search_runs(offset=1)["rows"]
    page = structure_io.search_structures("NO", limit=1)
    assert len(page["rows"]) == 1 and page["has_more"]
    assert structure_io.search_structures("NO", offset=1, limit=1)["rows"][0]["uuid"] != page["rows"][0]["uuid"]


def test_missing_optimization_artifact_does_not_hide_geometry(source, monkeypatch):
    original = type(source.outputs.retrieved.base.repository).get_object_content
    def missing(self, path, *args, **kwargs):
        if path == "aiida_trj.xyz":
            raise FileNotFoundError("trajectory deleted")
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(type(source.outputs.retrieved.base.repository), "get_object_content", missing)
    data = history.inspect_run(source.uuid)
    assert data["structure_uuid"] == source.outputs.structure.uuid
    assert "needs recomputation" in data["reuse_status"]
    assert data["settings"]["method"] == "PBE"


def test_unreachable_storage_is_not_reported_as_missing(source, monkeypatch):
    def inaccessible(*args, **kwargs):
        raise PermissionError("storage offline")
    monkeypatch.setattr(history, "validate_outputs", inaccessible)
    assert "retry when storage is reachable" in history.inspect_run(source.uuid)["reuse_status"]


def test_periodic_import_is_not_silently_made_molecular(aiida_profile_clean):
    atoms = Atoms("NO", positions=[[0, 0, 0], [0, 0, 1.3]], cell=[10, 10, 10], pbc=True)
    handle = io.StringIO()
    from ase.io import write
    write(handle, atoms, format="extxyz")
    read = structure_io.read_file("no.extxyz", handle.getvalue().encode())
    assert read.pbc.all()
    widget = StructureWidget()
    try:
        widget.set_atoms(read)
        assert widget.atoms.pbc.all()
        widget._isolate()
        assert not widget.atoms.pbc.any()
        assert np.array_equal(widget.atoms.positions, atoms.positions)
    finally:
        widget.close()


def test_edit_invalidates_review_and_copy_settings_keeps_geometry(source, monkeypatch):
    from aiidalab_orca import services
    from aiidalab_orca.app import OrcaApp
    monkeypatch.setattr(services, "codes", lambda: [("Test ORCA", source.inputs.code.uuid)])
    app = OrcaApp()
    try:
        assert app.structure.atoms is None and not app.structure.xyz.value
        assert not app.structure.ready
        assert app.structure.geometry_panel.layout.display == "none"
        assert app.next_step.disabled and app.review_button.disabled and app.submit_button.disabled
        app._review()
        assert app.review is None and "Import a molecular structure" in app.error.value
        app.structure.example.click()
        assert app.structure.atoms.get_chemical_formula() == "NO"
        assert not app.next_step.disabled and not app.review_button.disabled
        assert app.structure.geometry_panel.layout.display == ""
        app._review()
        assert app.review and app.review["plan"]["action"] == "reuse"
        changed = app.structure.atoms.copy()
        changed.positions[1, 2] = 1.4
        app.structure.editor.structure = changed
        assert app.review is None and app.submit_button.disabled
        app.method.value = "PBE0"
        app.copy_settings(source.uuid)
        assert app.method.value == "PBE"
        assert app.structure.atoms.positions[1, 2] == 1.4
        assert app.review is None
    finally:
        app.close()



def test_history_default_filters_display_existing_runs(source):
    widget = history.HistoryWidget(lambda _: None, lambda _: None, lambda _: None)
    try:
        widget.refresh()
        assert widget.method.value == "" and widget.state.value == ""
        assert len(widget.rows.children) == 1
        widget.select(source.uuid)
        assert not widget.geometry.disabled and not widget.copy.disabled
    finally:
        widget.close()
