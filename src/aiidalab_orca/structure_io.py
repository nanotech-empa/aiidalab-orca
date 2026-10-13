"""Import and edit records; ORM instances live only inside each operation."""

import copy
import hashlib
import io
from pathlib import Path
import tempfile

import ase.io
import numpy as np
from aiida import orm
from aiida.engine import calcfunction


@calcfunction
def record_structure_import(source_file, reviewed_model):
    """Record a user-reviewed imported geometry, without optimizing it."""
    return reviewed_model.clone()


@calcfunction
def record_structure_edit(source_structure, reviewed_model):
    """Record the user's new geometry while preserving the original structure."""
    return reviewed_model.clone()


def read_file(filename, content):
    """Read one geometry with ASE, preserving cell and periodicity for review."""
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix) as handle:
        handle.write(content)
        handle.flush()
        frames = ase.io.read(handle.name, index=":")
    if len(frames) != 1:
        raise ValueError("Import a file containing exactly one geometry.")
    return frames[0]


def load_structure(uuid):
    node = orm.load_node(uuid)
    if not isinstance(node, orm.StructureData):
        raise ValueError("Select an AiiDA StructureData.")
    atoms = node.get_ase()
    # Restore plain source metadata when this was a recorded CDXML import.
    from aiidalab_widgets_empa.cdxml_storage import restore_cdxml_metadata
    return restore_cdxml_metadata(atoms, str(node.uuid))


def same_geometry(first, second):
    return (np.array_equal(first.numbers, second.numbers)
            and np.array_equal(first.positions, second.positions)
            and np.array_equal(first.cell.array, second.cell.array)
            and np.array_equal(first.pbc, second.pbc)
            and np.array_equal(first.get_masses(), second.get_masses()))


def snapshot_cdxml(importer, atoms):
    """Capture the shared importer's reviewed documents at model creation time."""
    selected = importer._selected_cdxml_content()
    selected = selected.encode() if isinstance(selected, str) else bytes(selected)
    if hashlib.sha256(selected).hexdigest() != atoms.info["cdxml_source"]["sha256"]:
        raise ValueError("The generated model does not match the selected CDXML drawing.")
    return {"kind": "cdxml", "filename": Path(importer._cdxml_filename).name,
            "original": bytes(importer._cdxml_content),
            "reviewed": bytes(importer._preview_cdxml) or selected}


def store_reviewed_structure(atoms, source_uuid="", imported=None):
    """Preserve an unchanged source or create a linked record of the reviewed model."""
    source = orm.load_node(source_uuid) if source_uuid else None
    if source is not None and same_geometry(atoms, source.get_ase()):
        return str(source.uuid)
    model = orm.StructureData(ase=atoms)
    if source is not None:
        model = record_structure_edit(source, model)
    elif imported and imported["kind"] == "file":
        document = orm.SinglefileData(file=io.BytesIO(imported["content"]),
                                      filename=Path(imported["filename"]).name)
        model = record_structure_import(document, model)
    elif imported and imported["kind"] == "cdxml":
        from aiidalab_widgets_empa.cdxml_storage import model_fingerprint, record_cdxml_import
        filename = Path(imported["filename"])
        original = orm.SinglefileData(file=io.BytesIO(imported["original"]), filename=filename.name).store()
        reviewed = orm.SinglefileData(file=io.BytesIO(imported["reviewed"]), filename=f"{filename.stem}-reviewed.cdxml").store()
        fingerprint = model_fingerprint(atoms)
        generation = copy.deepcopy(atoms.info.get("cdxml_generation", {}))
        record = {"schema": 1, "source": copy.deepcopy(atoms.info["cdxml_source"]),
                  "generation": generation,
                  "documents": {"original_uuid": str(original.uuid), "reviewed_uuid": str(reviewed.uuid)},
                  "stored_model_hash": fingerprint,
                  "edited_after_generation": bool(generation.get("model_hash") and generation["model_hash"] != fingerprint)}
        model = record_cdxml_import(original, reviewed, orm.Dict(dict=record), model)
    else:
        model.store()
    model.label = "ORCA app reviewed geometry"
    return str(model.uuid)


def formula_from_attributes(attributes):
    """Formula for search, never an equivalence criterion for calculation reuse."""
    from aiida.orm.nodes.data.structure import get_formula
    kinds = {k["name"]: k for k in attributes["kinds"]}
    symbols = []
    for site in attributes["sites"]:
        kind = kinds[site["kind_name"]]
        symbols.append(kind["symbols"][0] if len(kind["symbols"]) == 1 else "X")
    return get_formula(symbols, mode="hill")


def search_structures(text="", offset=0, limit=20):
    query = orm.QueryBuilder().append(orm.StructureData, tag="s",
                                     project=["uuid", "label", "ctime", "attributes"])
    query.order_by({"s": {"ctime": "desc", "id": "desc"}})
    rows = []
    skipped = 0
    for uuid, label, created, attributes in query.iterall(batch_size=100):
        formula = formula_from_attributes(attributes)
        if text.casefold() not in f"{uuid} {label} {formula}".casefold():
            continue
        if skipped < offset:
            skipped += 1
            continue
        rows.append({"uuid": str(uuid), "label": label, "formula": formula,
                     "created": created.isoformat()})
        if len(rows) > limit:
            break
    return {"rows": rows[:limit], "has_more": len(rows) > limit}
