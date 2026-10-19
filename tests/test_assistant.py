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
