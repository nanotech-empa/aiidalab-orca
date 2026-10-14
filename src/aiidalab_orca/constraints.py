"""Geometry constraints using the shared molecular viewer's atom selection."""

import html
from math import isfinite
import re

import ipywidgets as ipw
import traitlets as tl
from aiidalab_widgets_base.utils import list_to_string_range, string_range_to_list

from aiida_empa_orca.constraints import describe_constraints, normalize_constraints, validate_constraints

TYPES = [("Freeze xyz", "xyz"), ("Freeze x", "x"), ("Freeze y", "y"), ("Freeze z", "z"),
         ("Freeze xy", "xy"), ("Freeze xz", "xz"), ("Freeze yz", "yz"),
         ("Distance", "distance"), ("Angle", "angle"), ("Dihedral", "dihedral")]


class ConstraintEditor(ipw.VBox):
    revision = tl.Int()

    def __init__(self, viewer):
        self.viewer = viewer
        self.rows = []
        self.atoms = None
        self._needs_confirmation = False
        self.body = ipw.VBox()
        self.message = ipw.HTML()
        self.summary = ipw.HTML("<p>No constraints.</p>")
        self.add = ipw.Button(description="Add constraint", icon="plus", layout=ipw.Layout(width="auto"))
        self.add.on_click(lambda _: self.append())
        self.freeze = ipw.Button(description="Freeze selected atoms", icon="lock", layout=ipw.Layout(width="auto"))
        self.freeze.on_click(self._freeze_selection)
        self.confirm = ipw.Button(description="Confirm constraints for this geometry", icon="check", layout=ipw.Layout(width="auto", display="none"))
        self.confirm.on_click(self._confirm)
        super().__init__([
            ipw.HTML("<p>Used when optimizing the geometry. Atom numbers start at <b>1</b>, as in the viewer. "
                     "Select atoms above or type their numbers. Frozen coordinates keep their starting values. "
                     "Distances use Å; angles and dihedrals use degrees. Leave the target blank to keep its starting value.</p>"),
            ipw.HBox([self.freeze, self.add], layout=ipw.Layout(flex_flow="row wrap")),
            self.body, self.summary, self.message, self.confirm,
        ])

    def append(self, value=None):
        kind = ipw.Dropdown(options=TYPES, layout=ipw.Layout(width="155px"))
        indices = ipw.Text(placeholder="Atoms, e.g. 1 3..5", layout=ipw.Layout(width="180px"))
        target = ipw.Text(placeholder="Starting value", layout=ipw.Layout(width="180px"), style={"description_width": "20px"})
        current = ipw.HTML(layout=ipw.Layout(width="180px"))
        use = ipw.Button(description="Use selected atoms", icon="crosshairs", layout=ipw.Layout(width="auto"))
        remove = ipw.Button(icon="trash", tooltip="Remove constraint", layout=ipw.Layout(width="40px"))
        row = ipw.HBox([kind, indices, target, current, use, remove], layout=ipw.Layout(flex_flow="row wrap"))
        if value:
            kind.value = value.get("components", "xyz") if value["kind"] == "cartesian" else value["kind"]
            indices.value = " ".join(str(i+1) for i in value["atoms"])
            target.value = str(value["value"]) if "value" in value else ""
        self.rows.append((row, kind, indices, target, current))

        def update_type(_=None):
            internal = kind.value in ("distance", "angle", "dihedral")
            target.disabled = not internal
            target.description = "Å" if kind.value == "distance" else "°" if internal else ""
            target.layout.visibility = "visible" if internal else "hidden"
            indices.placeholder = "Atoms, e.g. 1 3..5" if not internal else {
                "distance": "Atoms, e.g. 1 2", "angle": "Atoms, e.g. 1 2 3", "dihedral": "Atoms, e.g. 1 2 3 4",
            }[kind.value]
            indices.tooltip = "For angles the middle atom is the vertex; for dihedrals the middle pair is the axis. Atom order matters."
            self._changed()

        def from_selection(_):
            if not self.viewer.selection:
                self.message.value = "<p>Select atoms in the viewer first.</p>"
                return
            indices.value = (list_to_string_range(self.viewer.selection) if kind.value not in ("distance", "angle", "dihedral")
                             else " ".join(str(i+1) for i in self.viewer.selection))

        def delete(_):
            self.rows.remove((row, kind, indices, target, current))
            self.body.children = [entry[0] for entry in self.rows]
            for control in row.children:
                control.close()
            row.close()
            if not self.rows:
                self._needs_confirmation = False
                self.message.value = ""
            self._changed()

        kind.observe(update_type, names="value")
        indices.observe(self._changed, names="value")
        target.observe(self._changed, names="value")
        use.on_click(from_selection)
        remove.on_click(delete)
        self.body.children = [entry[0] for entry in self.rows]
        update_type()

    def _freeze_selection(self, _=None):
        if not self.viewer.selection:
            self.message.value = "<p>Select atoms in the viewer first.</p>"
            return
        self.append({"kind": "cartesian", "atoms": list(self.viewer.selection), "components": "xyz"})

    def _row_constraint(self, kind, indices, target_text=""):
        text = indices.value.strip()
        internal = kind.value in ("distance", "angle", "dihedral")
        if not text:
            raise ValueError("Enter atom numbers for each constraint or remove the empty row")
        # Use the shared parser for Cartesian ranges. Internal-coordinate
        # order must be preserved, so accept explicit ordered numbers only.
        if internal:
            if not re.fullmatch(r"[1-9][0-9]*(?:\s+[1-9][0-9]*)*", text):
                raise ValueError("Enter ordered atom numbers for a distance, angle or dihedral")
            atoms = [int(i)-1 for i in text.split()]
        else:
            for token in text.split():
                if not re.fullmatch(r"[1-9][0-9]*(?:\.\.[1-9][0-9]*)?", token):
                    raise ValueError("Use atom numbers such as 1 3..5")
                if ".." in token and int(token.split("..")[0]) > int(token.split("..")[1]):
                    raise ValueError("Atom ranges must increase, for example 3..5")
                if self.atoms is not None and int(token.split("..")[-1]) > len(self.atoms):
                    raise ValueError(f"This molecule has atoms 1 to {len(self.atoms)}")
            atoms, valid = string_range_to_list(text)
            if not valid:
                raise ValueError("Use atom numbers such as 1 3..5")
        item = {"kind": kind.value if internal else "cartesian", "atoms": atoms}
        if internal and target_text.strip():
            try:
                item["value"] = float(target_text)
            except ValueError as exc:
                raise ValueError("Enter a numerical constraint target or leave it blank") from exc
        elif not internal:
            item["components"] = kind.value
        return item

    def _measure(self, kind, indices):
        """Measure the ordered row in the current geometry, without PBC."""
        if self.atoms is None:
            return "Current: select a molecule"
        item = normalize_constraints([self._row_constraint(kind, indices)])[0]
        if max(item["atoms"]) >= len(self.atoms):
            raise ValueError("An atom number is outside the current molecule")
        method = {"distance": self.atoms.get_distance, "angle": self.atoms.get_angle,
                  "dihedral": self.atoms.get_dihedral}[item["kind"]]
        value = method(*item["atoms"], mic=False)
        if not isfinite(value):
            raise ValueError("This coordinate is undefined in the current geometry")
        if item["kind"] == "dihedral":
            value = (value + 180) % 360 - 180
        return f"Current: {value:.4f} Å" if item["kind"] == "distance" else f"Current: {value:.2f}°"

    def values(self, require_confirmation=True):
        values = [self._row_constraint(kind, indices, target.value)
                  for _, kind, indices, target, _ in self.rows]
        values = normalize_constraints(values)
        if values and require_confirmation and self._needs_confirmation:
            raise ValueError("Check and confirm constraints for the current geometry in Select structure")
        return values

    def _changed(self, _=None):
        for _, kind, indices, _, current in self.rows:
            internal = kind.value in ("distance", "angle", "dihedral")
            current.layout.display = "" if internal else "none"
            if internal:
                try:
                    current.value = f"<span>{html.escape(self._measure(kind, indices))}</span>"
                except (ValueError, ZeroDivisionError, IndexError):
                    current.value = "<span>Current: unavailable — check atoms/geometry</span>"
        try:
            descriptions = describe_constraints(self.values(require_confirmation=False))
            self.summary.value = "<p>" + "<br>".join(html.escape(line) for line in descriptions or ["No constraints."]) + "</p>"
        except ValueError as exc:
            self.summary.value = f"<p>{html.escape(str(exc))}</p>"
        self.confirm.layout.display = "" if self._needs_confirmation else "none"
        self.revision += 1

    def geometry_changed(self, atoms):
        self.atoms = atoms.copy()
        if self.rows:
            self.require_confirmation("Geometry changed. Check the atom numbers and targets before confirming constraints.")

    def require_confirmation(self, message):
        self._needs_confirmation = bool(self.rows)
        self.message.value = f"<p><b>{html.escape(message)}</b></p>" if self.rows else ""
        self._changed()

    def _confirm(self, _=None):
        try:
            if self.atoms is None:
                raise ValueError("Select a molecule first")
            validate_constraints(self.atoms, self.values(require_confirmation=False))
        except ValueError as exc:
            self.message.value = f"<p style='color:#a02020'>{html.escape(str(exc))}</p>"
            return
        self._needs_confirmation = False
        self.message.value = "<p>Constraints checked for the current geometry.</p>"
        self._changed()

    def set_values(self, values):
        for row, *_ in self.rows:
            for child in row.children:
                child.close()
            row.close()
        self.rows = []
        self.body.children = []
        self._needs_confirmation = False
        self.message.value = ""
        for value in normalize_constraints(values):
            self.append(value)
        self._changed()

    def close(self):
        for row, *_ in getattr(self, "rows", []):
            for child in row.children:
                child.close()
            row.close()
        super().close()
