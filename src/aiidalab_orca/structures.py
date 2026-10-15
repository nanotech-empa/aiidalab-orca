"""Molecular import/edit panel using shared widgets with ASE/UUID state only."""

import copy
import html
import io

import ase.io
import ipywidgets as ipw
import traitlets as tl
from aiidalab_widgets_base import BasicStructureEditor, SmilesWidget
from aiidalab_widgets_base.viewers import StructureDataViewer
from aiidalab_widgets_empa import CdxmlUploadWidget

from . import services, structure_io
from .constraints import ConstraintEditor


class StructureWidget(ipw.VBox):
    revision = tl.Int(0)

    def __init__(self):
        self.source_uuid = ""
        self.imported = None
        self.atoms = None
        self.ready = False
        self._active_importer = None
        self._updating = False
        self._original = None
        self._search_offset = 0
        self.message = ipw.HTML()
        self.summary = ipw.HTML()
        self.upload = ipw.FileUpload(description="Upload geometry", accept=".xyz,.extxyz,.cif,.pdb,.mol,.sdf", multiple=False, layout=ipw.Layout(width="auto"))
        self.upload.observe(self._upload, names="value")
        self.xyz = ipw.Textarea(value="", placeholder="Paste a molecular geometry in XYZ format", layout=ipw.Layout(width="100%", height="150px"))
        apply_xyz = ipw.Button(description="Import XYZ text", icon="file-text-o", layout=ipw.Layout(width="auto"))
        apply_xyz.on_click(self._import_xyz)
        self.example = ipw.Button(description="Load NO doublet example", icon="flask", layout=ipw.Layout(width="auto"))
        self.example.on_click(self._load_example)
        self.query = ipw.Text(placeholder="Formula, label, or structure UUID", layout=ipw.Layout(width="400px"))
        search = ipw.Button(description="Find structures", icon="search")
        search.on_click(lambda _: self._search(0))
        self.matches = ipw.Select(options=[], rows=7, layout=ipw.Layout(width="100%"))
        use = ipw.Button(description="Import selected structure", icon="check", layout=ipw.Layout(width="auto"))
        use.on_click(self._use_selected)
        self.previous = ipw.Button(description="Previous", disabled=True)
        self.next = ipw.Button(description="Next", disabled=True)
        self.previous.on_click(lambda _: self._search(max(0, self._search_offset-20)))
        self.next.on_click(lambda _: self._search(self._search_offset+20))
        self.identifier = ipw.Text(placeholder="Exact StructureData UUID", layout=ipw.Layout(width="400px"))
        load = ipw.Button(description="Load UUID")
        load.on_click(lambda _: self._load_uuid(self.identifier.value.strip()))
        self.cdxml = CdxmlUploadWidget(title="CDXML")
        self.cdxml.observe(self._from_cdxml, names="structure")
        self.smiles = SmilesWidget(title="SMILES", add_auxiliary_cell=False)
        self.smiles.observe(self._from_smiles, names="structure")
        self.importers = ipw.Tab(children=[
            ipw.VBox([self.upload, ipw.HTML("<p>Import one geometry: XYZ, Extended XYZ, CIF, PDB, MOL or SDF.</p>"), self.xyz, apply_xyz, self.example]),
            ipw.VBox([ipw.HTML("<p>Structures from any AiiDA calculation, including ORCA, QE and CP2K.</p>"), ipw.HBox([self.query, search]), self.matches, ipw.HBox([self.previous, self.next, use]), ipw.HBox([self.identifier, load])]),
            ipw.VBox([ipw.HTML("<p>Create a finite molecular model and review its atoms. CDXML supplies a starting geometry; charge and multiplicity must be set in Calculation settings.</p>"), self.cdxml]),
            ipw.VBox([ipw.HTML("<p>Generate a starting molecular conformer with RDKit. Review charge and multiplicity before submitting.</p>"), self.smiles]),
        ])
        for i, title in enumerate(["File / XYZ", "AiiDA structures", "CDXML", "Build from SMILES"]):
            self.importers.set_title(i, title)
        self.viewer = StructureDataViewer(configuration_tabs=["Selection", "Appearance", "Download"])
        self.constraints = ConstraintEditor(self.viewer)
        self.constraint_panel = ipw.Accordion(children=[self.constraints], selected_index=None)
        self.constraint_panel.set_title(0, "Geometry optimization constraints (optional)")
        self.editor = BasicStructureEditor(title="Edit atoms")
        self.editor.observe(self._edited, names="structure")
        self._links = [tl.link((self.editor, "selection"), (self.viewer, "selection")),
                       tl.dlink((self.editor, "input_selection"), (self.viewer, "input_selection")),
                       tl.dlink((self.viewer._viewer, "_camera_orientation"), (self.editor, "camera_orientation"))]
        reset = ipw.Button(description="Reset edits")
        reset.on_click(self._reset)
        isolate = ipw.Button(description="Treat as isolated molecule", layout=ipw.Layout(width="240px"))
        isolate.on_click(self._isolate)
        self.editing = ipw.Accordion(children=[ipw.VBox([ipw.HBox([reset, isolate]), self.editor])], selected_index=None)
        self.editing.set_title(0, "Edit atoms · select atoms in the viewer first")
        # Do not render NGL inside a display:none parent: it creates a 0×0
        # canvas that remains blank when the parent is subsequently revealed.
        # Attach the viewer only when the first structure is ready.
        self.geometry_panel = ipw.VBox()
        self.summary.value = "<p>No molecule selected. Import a structure or load the example to begin.</p>"
        super().__init__([self.importers, self.message, self.summary, self.geometry_panel])

    def _load_example(self, _=None):
        self.xyz.value = services.NO_XYZ
        self.set_atoms(services.parse_xyz(services.NO_XYZ))

    def set_atoms(self, atoms, source_uuid="", imported=None):
        self.source_uuid = source_uuid
        self.imported = copy.deepcopy(imported)
        self._active_importer = imported.get("kind") if imported else None
        self.ready = True
        self._original = atoms.copy()
        self._set_geometry(atoms)
        self.message.value = ""

    def _set_geometry(self, atoms):
        self._updating = True
        try:
            self.atoms = atoms.copy()
            self.editor.structure = atoms.copy()
            self.viewer.structure = atoms.copy()
            if not self.geometry_panel.children:
                self.geometry_panel.children = [self.viewer, self.constraint_panel, self.editing]
            self.editor.selection = []
            self.constraints.geometry_changed(atoms)
            text = f"{atoms.get_chemical_formula()} · {len(atoms)} atoms"
            if any(atoms.pbc):
                text += " · Periodic input: select the desired molecular fragment and explicitly treat it as isolated before submission."
            if self.source_uuid:
                text += " · Imported from AiiDA; any edits will be recorded as a new structure."
            self.summary.value = f"<p><b>{html.escape(text)}</b></p>"
            self.revision += 1
        finally:
            self._updating = False

    def _error(self, exc):
        self.message.value = f"<p style='color:#a02020'>{html.escape(str(exc))}</p>"

    def _upload(self, change):
        if not change["new"]:
            return
        try:
            file = change["new"][0]
            content = bytes(file["content"])
            self.set_atoms(structure_io.read_file(file["name"], content), imported={"kind": "file", "filename": file["name"], "content": content})
        except Exception as exc:
            self._error(exc)

    def _import_xyz(self, _=None):
        try:
            self.set_atoms(services.parse_xyz(self.xyz.value), imported={"kind": "file", "filename": "geometry.xyz", "content": self.xyz.value.encode()})
        except Exception as exc:
            self._error(exc)

    def _from_cdxml(self, change):
        if change["new"] is None and self._active_importer == "cdxml":
            self.ready = False
            self.revision += 1
            self._error("CDXML settings changed. Click Create model and review the new geometry before continuing.")
        if change["new"] is not None:
            try:
                self.set_atoms(change["new"], imported=structure_io.snapshot_cdxml(self.cdxml, change["new"]))
            except Exception as exc:
                self._error(exc)

    def _from_smiles(self, change):
        if change["new"] is not None:
            self.set_atoms(change["new"], imported={"kind": "file", "filename": "molecule.smi", "content": self.smiles.smiles.value.encode()})

    def _edited(self, change):
        if not self._updating and change["new"] is not None:
            self._set_geometry(change["new"])

    def _reset(self, _=None):
        if self._original is not None:
            self._set_geometry(self._original)

    def _isolate(self, _=None):
        atoms = self.atoms.copy()
        atoms.pbc = False
        self._set_geometry(atoms)

    def _search(self, offset):
        try:
            page = structure_io.search_structures(self.query.value.strip(), offset=offset)
            self._search_offset = offset
            self.matches.options = [(f"{r['formula']} · {r['label'] or 'Structure'} · {r['uuid'][:8]}", r["uuid"]) for r in page["rows"]]
            self.matches.value = None
            self.previous.disabled = offset == 0
            self.next.disabled = not page["has_more"]
            self.message.value = "" if page["rows"] else "<p>No matching structures.</p>"
        except Exception as exc:
            self._error(exc)

    def _use_selected(self, _=None):
        if self.matches.value:
            self._load_uuid(self.matches.value)

    def _load_uuid(self, uuid):
        try:
            self.set_atoms(structure_io.load_structure(uuid), source_uuid=uuid)
        except Exception as exc:
            self._error(exc)

    def xyz_text(self):
        handle = io.StringIO()
        ase.io.write(handle, self.atoms, format="xyz")
        return handle.getvalue()

    def mark_stored(self, uuid):
        self.source_uuid = uuid
        self.imported = None

    def close(self):
        for link in getattr(self, "_links", []):
            link.unlink()
        for name in ("cdxml", "smiles", "editor", "viewer", "constraints"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.close()
        super().close()
