"""Adapter between the shared assistant and the current ORCA form."""
import copy
import hashlib
import json
from html.parser import HTMLParser
from pathlib import PurePath

import numpy as np

from . import services, structure_io


class _MessageText(HTMLParser):
    """Expose displayed messages as text, without style/markup or attributes."""

    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(value)

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        return " ".join(" ".join(self.parts).split())


class OrcaAssistantAdapter:
    app_id = "orca"

    def __init__(self, app):
        self.app = app
        self.dispatch = lambda callback: callback()
        self._undo = None
        self._after = None

    def _state(self):
        app = self.app
        values = {"app": "orca", "process_uuid": app.process_uuid,
                  "source_uuid": app.structure.source_uuid, "structure_revision": app.structure.revision,
                  "settings": app.science.values(), "optimize": app.optimize.value,
                  "nprocs": app.nprocs.value, "memory_mb": app.memory.value,
                  "wallclock_minutes": app.wallclock.value, "code_uuid": app.code.value,
                  "label": app.label.value, "force_recompute": app.force.value,
                  "submitted": app._submitted, "ready": app.structure.ready,
                  "auto_multiplicity": app.science.auto_multiplicity.value,
                  "storage_revision": app.wavefunction_storage.revision,
                  "constraints_revision": app.structure.constraints.revision,
                  "pdos_enabled": app.pdos_enabled.value, "pdos_memory_gib": app.pdos_memory.value,
                  "pdos_wallclock_minutes": app.pdos_wallclock.value}
        cdxml = app.structure.cdxml
        document = cdxml._cdxml_content
        values["cdxml"] = {
            "uploaded": document is not None,
            "sha256": hashlib.sha256(document).hexdigest() if document is not None else None,
            "fields": {name: widget.value for name, widget in self._cdxml_fields().items()},
        }
        values["revision"] = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        values["cdxml"].update(
            choices=list(cdxml.structure_selector.options),
            can_create_model=not cdxml.create_button.disabled,
            message=_MessageText(cdxml.output_message.value).text(),
            preview_message=_MessageText(cdxml.preview_message.value).text(),
        )
        values["available_codes"] = [{"label": label, "uuid": value} for label, value in app.code.options]
        # Display-only changes must not invalidate an otherwise unchanged draft.
        values["messages"] = self._messages()
        values["review_ready"] = app.review is not None
        values["page"] = app.pages.get_title(app.pages.selected_index) if app.pages.selected_index is not None else None
        values["setup_step"] = app.steps.selected_index
        atoms = app.structure.atoms
        values["geometry"] = None if atoms is None else {
            "formula": atoms.get_chemical_formula(), "atom_count": len(atoms),
            "pbc": atoms.pbc.tolist(), "cell_angstrom": atoms.cell.array.tolist(),
        }
        return values

    def _messages(self):
        app = self.app
        widgets = {"app": app.error, "structure": app.structure.message,
                   "settings": app.science_message, "resources": app.resource_message}
        return {name: text for name, widget in widgets.items()
                if (text := _MessageText(widget.value).text())}

    def _failure(self, fallback):
        messages = self._messages()
        return ValueError("; ".join(f"{name}: {text}" for name, text in messages.items()) or fallback)

    def context(self):
        return self.dispatch(self._state)

    def _require_revision(self, revision):
        if revision != self._state()["revision"]:
            raise ValueError("The form changed while the assistant was thinking. Read it again and preserve the newer edits.")

    def _snapshot(self):
        return copy.deepcopy(self._state())

    def _restore(self, state):
        app = self.app
        app.science.set_values(state["settings"])
        app.science.auto_multiplicity.value = state["auto_multiplicity"]
        for key, widget in self._resource_fields().items():
            widget.value = state[key]

    def _resource_fields(self):
        app = self.app
        return {"optimize": app.optimize, "nprocs": app.nprocs, "memory_mb": app.memory,
                "wallclock_minutes": app.wallclock, "code_uuid": app.code,
                "label": app.label, "force_recompute": app.force}

    def update(self, expected_revision, settings=None, **changes):
        self._require_revision(expected_revision)
        app = self.app
        if app._submitted:
            raise ValueError("These inputs were submitted. Use Edit a copy before changing them.")
        if not app.structure.ready or app.structure.atoms is None:
            raise ValueError("Select a molecular structure first")
        before = self._snapshot()
        fields = self._resource_fields()
        if changes.keys() - fields.keys():
            raise ValueError("Unknown resource setting")
        merged = {**before["settings"], **(settings or {})}
        if (settings or {}).keys() - app.science.fields.keys():
            raise ValueError("Only declared scientific form fields can be edited by this adapter")
        # Check exact values before traitlets can silently clamp bounded widgets.
        for key, value in {**(settings or {}), **changes}.items():
            widget = fields[key] if key in fields else app.science.fields[key]
            if isinstance(widget.value, bool):
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be boolean")
            elif isinstance(widget.value, int):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{key} must be an integer")
                if hasattr(widget, "min") and not widget.min <= value <= widget.max:
                    raise ValueError(f"{key} is outside the form's allowed range")
            if hasattr(widget, "options") and not hasattr(widget, "ensure_option"):
                options = [o[1] if isinstance(o, tuple) else o for o in widget.options]
                if value not in options:
                    raise ValueError(f"Unsupported {key}; choose an available form option")
        services.validate_configuration(app.structure.atoms, merged, changes.get("optimize", app.optimize.value))
        try:
            app.science.set_values(merged)
            for key, value in changes.items():
                fields[key].value = value
            services.validate_configuration(app.structure.atoms, app._settings(), app.optimize.value)
        except Exception:
            self._restore(before)
            raise
        app.pages.selected_index = 0
        # Selecting a structure and preparing its settings should expose the
        # populated form through the same transition as the Next button.
        app._confirm_structure()
        self._undo, self._after = before, self._state()["revision"]
        return {"changed": {"settings": settings or {}, **changes}, "state": self._state()}

    def undo(self, expected_revision):
        self._require_revision(expected_revision)
        if self._undo is None or self._after != expected_revision:
            raise ValueError("Undo is unavailable after subsequent manual edits or submission")
        self._restore(self._undo)
        self._undo = self._after = None
        return self._state()

    def load_structure(self, structure_uuid, expected_revision):
        self._require_revision(expected_revision)
        if self.app._submitted:
            raise ValueError("Use Edit a copy before replacing the submitted structure")
        atoms = structure_io.load_structure(structure_uuid)
        self.app.structure.set_atoms(atoms, source_uuid=structure_uuid)
        self.app.pages.selected_index = 0
        self.app.steps.selected_index = 0
        self._undo = self._after = None
        return self._state()

    def import_smiles(self, smiles, expected_revision):
        """Use the existing GUI builder; no scientific generation algorithm changes."""
        self._require_revision(expected_revision)
        if self.app._submitted:
            raise ValueError("Use Edit a copy before replacing the submitted structure")
        widget = self.app.structure.smiles
        canonical = widget.canonicalize_smiles(smiles)
        widget.output.value = ""
        atoms = widget._mol_from_smiles(canonical)
        if atoms is None:
            raise ValueError(_MessageText(widget.output.value).text() or "SMILES geometry generation failed")
        # Update the same fields and trait callback as Generate molecule in the GUI.
        widget.smiles.value = canonical
        widget.structure = atoms
        self.app.structure.importers.selected_index = 3
        self.app.pages.selected_index = 0
        self.app.steps.selected_index = 0
        self._undo = self._after = None
        from rdkit import Chem
        mol = Chem.MolFromSmiles(canonical)
        return {
            "smiles": canonical,
            "formula": atoms.get_chemical_formula(),
            "formal_charge": Chem.GetFormalCharge(mol),
            "radical_electrons": sum(atom.GetNumRadicalElectrons() for atom in mol.GetAtoms()),
            "unassigned_stereocenters": [index for index, label in Chem.FindMolChiralCenters(mol, includeUnassigned=True) if label == "?"],
            "message": "Generated a starting conformer with the existing GUI builder. Review the geometry, charge and multiplicity before calculation review.",
            "builder_message": _MessageText(widget.output.value).text(),
            "state": self._state(),
        }

    def import_structure(self, filename, content, expected_revision):
        """Populate the same draft and source-file record as File / XYZ upload."""
        self._require_revision(expected_revision)
        if self.app._submitted:
            raise ValueError("Use Edit a copy before replacing the submitted structure")
        suffix = PurePath(filename).suffix.lower()
        if (not filename or PurePath(filename).name != filename
                or "\\" in filename or "\x00" in filename
                or suffix not in {".xyz", ".extxyz", ".cif", ".pdb", ".mol", ".sdf", ".cdxml"}):
            raise ValueError("Supply a filename ending in .xyz, .extxyz, .cif, .pdb, .mol, .sdf or .cdxml, not a path or URL.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Supply complete text structure-file content.")
        data = content.encode("utf-8")
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Structure-file content must be at most 2 MiB.")
        if suffix == ".cdxml":
            from datetime import datetime, timezone
            widget = self.app.structure.cdxml
            widget.file_upload.value = ({
                "name": filename, "type": "application/xml", "size": len(data),
                "content": memoryview(data), "last_modified": datetime.now(timezone.utc),
            },)
            self.app.structure.importers.selected_index = 2
            self.app.pages.selected_index = self.app.steps.selected_index = 0
            self._undo = self._after = None
            if widget._cdxml_content != data or not widget.structure_selector.options:
                raise ValueError("CDXML import failed. " + _MessageText(widget.output_message.value).text())
            return {
                "status": "cdxml_uploaded", "source_sha256": hashlib.sha256(data).hexdigest(),
                "message": "Drawing loaded; inspect CDXML choices/settings, then use orca_prepare_cdxml with create_model=true. Existing geometry has not been replaced yet.",
                "state": self._state(),
            }
        # Parse before editing the form so invalid/partial files preserve its draft.
        atoms = structure_io.read_file(filename, data)
        if not len(atoms) or not np.isfinite(atoms.positions).all() or not np.isfinite(atoms.cell.array).all():
            raise ValueError("Supply a nonempty structure with finite coordinates and cell.")
        self.app.structure.set_atoms(atoms, imported={
            "kind": "file", "filename": filename, "content": data,
        })
        self.app.structure.xyz.value = content if suffix == ".xyz" else ""
        self.app.structure.importers.selected_index = 0
        self.app.pages.selected_index = 0
        self.app.steps.selected_index = 0
        self._undo = self._after = None
        return {
            "filename": filename, "source_sha256": hashlib.sha256(data).hexdigest(),
            "message": "Structure imported into the visible draft. Original file content is retained for calculation review; no geometry optimization or submission has run.",
            "state": self._state(),
        }

    def _cdxml_fields(self):
        widget = self.app.structure.cdxml
        if widget._cdxml_content is None:
            return {}
        return {name: getattr(widget, name) for name in (
            "structure_selector", "nunits", "use_clever_hydrogenation",
            "symmetrize_geometry", "resolve_steric_collisions", "steric_mode",
            "steric_margin_percent",
        )}

    def prepare_cdxml(self, expected_revision, fields=None, create_model=False):
        self._require_revision(expected_revision)
        if self.app._submitted:
            raise ValueError("Use Edit a copy before replacing the submitted structure")
        widget = self.app.structure.cdxml
        if widget._cdxml_content is None:
            raise ValueError("Import a CDXML drawing first.")
        if fields:
            from aiidalab_ai_assistant.forms import FormAdapter
            form = FormAdapter("orca", self._cdxml_fields)
            form.update(form.context()["revision"], fields)
        if create_model:
            if widget.create_button.disabled:
                raise ValueError("CDXML Create model is disabled; inspect its messages and drawing selection.")
            widget.structure = None
            widget._on_button_click()
            if widget.structure is None or not self.app.structure.ready or self.app.structure.message.value:
                raise ValueError("CDXML model was not created. " + _MessageText(widget.output_message.value).text()
                                 + " " + _MessageText(self.app.structure.message.value).text())
        self.app.structure.importers.selected_index = 2
        self.app.pages.selected_index = self.app.steps.selected_index = 0
        self._undo = self._after = None
        return {"status": "model_created" if create_model else "cdxml_settings_updated",
                "state": self._state(), "calculation_run": False}

    def select_process(self, process_uuid):
        def select():
            from .history import inspect_run
            data = inspect_run(process_uuid)
            self.app.load_run(process_uuid)
            if self.app.process_uuid != process_uuid or self.app.error.value:
                raise self._failure("The app could not open this calculation")
            return {"state": self._state(), "calculation": data}
        return self.dispatch(select)

    def review(self, expected_revision):
        self._require_revision(expected_revision)
        self.app._confirm_structure()
        self.app._confirm_settings()
        if not self.app._settings_confirmed:
            raise self._failure("The app could not validate these settings")
        self.app._review()
        if self.app.review is None:
            raise self._failure("The app could not prepare the calculation")
        return {"review": self.app.review, "state": self._state()}

    def submit(self, expected_revision):
        self._require_revision(expected_revision)
        if self.app._submitted or self.app.review is None:
            raise ValueError("Prepare and review the current inputs first")
        self.app._submit()
        if not self.app._submitted:
            raise self._failure("Submission did not complete")
        return {"process_uuid": self.app.process_uuid, "state": self._state()}

    def register(self, registry):
        from aiidalab_ai_assistant.tools import object_schema
        from aiidalab_ai_assistant.structure_editor import StructureEditorTools

        def edit_atoms(atoms):
            if self.app._submitted:
                raise ValueError("Use Edit a copy before changing a submitted structure")
            self.app.structure.editor.structure = atoms
            self._undo = self._after = None

        self.editor_tools = StructureEditorTools(
            self, lambda: self.app.structure.atoms, edit_atoms,
            lambda: self.app.structure.viewer.selection,
        )
        self.editor_tools.register(registry)
        string = {"type": "string"}
        revision = {"expected_revision": string}
        registry.add("orca_get_state", "Read the ORCA form, current page, visible error/validation messages, review readiness, selected process, allowed codes and revision. Inspect this after an operation fails.",
                     object_schema(), self.context)
        def add(name, description, schema, handler, action=False):
            registry.add(name, description, schema, lambda **args: self.dispatch(lambda: handler(**args)), action)
        scientific = {key: {"type": "integer" if isinstance(widget.value, int) else "string"}
                      for key, widget in self.app.science.fields.items()}
        fields = {key: {"type": "boolean" if isinstance(w.value, bool) else "integer" if isinstance(w.value, int) else "string"}
                  for key, w in self._resource_fields().items()}
        add("orca_update_draft", "Populate the visible ORCA fields. Requires a current revision; validates scientific inputs and preserves provenance.",
            object_schema({**revision, "settings": object_schema(scientific), **fields}, ["expected_revision"]), self.update)
        add("orca_undo", "Undo the last assistant form edit if no newer manual edit occurred.",
            object_schema(revision, ["expected_revision"]), self.undo)
        add("orca_load_structure", "Load an existing StructureData UUID into the visible draft, preserving its provenance.",
            object_schema({**revision, "structure_uuid": string}, ["expected_revision", "structure_uuid"]), self.load_structure)
        add("orca_import_smiles", "Generate a starting molecular conformer from an unambiguous or user-confirmed SMILES using the visible Build from SMILES GUI. Does not submit or optimize with ORCA. Resolve uncertain image chemistry before using this tool.",
            object_schema({**revision, "smiles": {"type": "string", "minLength": 1, "maxLength": 5000}}, ["expected_revision", "smiles"]), self.import_smiles)
        add("orca_import_structure", "Import complete XYZ/extXYZ, CIF, PDB, MOL or SDF text through the existing File / XYZ reader, or CDXML through the drawing importer. CDXML needs orca_prepare_cdxml to create its model after checking drawing choices. Use verified web/literature coordinates or supplied content; preserve the source citation in the file comment where supported. At most 2 MiB. Does not read URLs or filesystem paths, optimize, store AiiDA nodes or submit jobs. Read back geometry and review charge/spin.",
            object_schema({**revision, "filename": {"type": "string", "minLength": 1, "maxLength": 200},
                           "content": {"type": "string", "minLength": 1, "maxLength": 2 * 1024 * 1024}},
                          ["expected_revision", "filename", "content"]), self.import_structure)
        add("orca_prepare_cdxml", "Edit the uploaded CDXML fields shown in orca_get_state, optionally invoking the existing Create model control. Generates a starting geometry with original/reviewed drawing provenance, not a quantum optimization. Inspect returned geometry and messages.",
            object_schema({**revision, "fields": {"type": "object"}, "create_model": {"type": "boolean"}},
                          ["expected_revision"]), self.prepare_cdxml)
        registry.add("orca_open_calculation", "Open an ORCA calculation's results and return its structure UUID and metadata.",
            object_schema({"process_uuid": string}, ["process_uuid"]), self.select_process)
        add("orca_review", "Validate and prepare the existing ORCA form. Uses the app's review path, which may store the reviewed structure, but does not submit.",
            object_schema(revision, ["expected_revision"]), self.review)
        add("orca_submit", "Submit the reviewed calculation through the existing app. The user reviews this action before execution.",
            object_schema(revision, ["expected_revision"]), self.submit, action=True)


def create_panel(app):
    try:
        from aiidalab_ai_assistant.forms import panel
    except ModuleNotFoundError as exc:
        if exc.name not in {"aiidalab_ai_assistant", "aiidalab_ai_assistant.forms"}:
            raise
        import ipywidgets as ipw
        return ipw.HTML("AI assistant is optional; install aiidalab-ai-assistant to enable it.")
    return panel(OrcaAssistantAdapter(app))
