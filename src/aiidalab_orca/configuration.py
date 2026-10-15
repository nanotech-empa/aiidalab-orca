"""Property settings with protocol defaults and structured expert controls."""

import html
import json

import ipywidgets as ipw
import traitlets as tl

from aiida_empa_orca.protocols import (
    APPROXIMATIONS, GRIDS, OPTIMIZATION, PROTOCOLS, REFERENCES,
    SCF_CONVERGENCE, editable_settings, protocol_overrides, protocol_settings,
)
from aiida_empa_orca.choices import AUXILIARY_BASES, BASES, ECPS, MANUAL_LINKS, METHODS


class ParameterRows(ipw.VBox):
    """Small editable table; values are serialized only when reviewed."""

    revision = tl.Int()

    def __init__(self, elements=False):
        self.elements = elements
        self.rows = []
        self.add = ipw.Button(description="Add element" if elements else "Add parameter", icon="plus", layout=ipw.Layout(width="auto"))
        self.add.on_click(lambda _: self.append())
        self.body = ipw.VBox()
        hint = ("Element · orbital basis · auxiliary basis · ECP (blank: inherit; none: remove). NewGTO does not change an inherited ECP."
                if elements else "Block · parameter · value (number, true/false, or a single ORCA token).")
        super().__init__([ipw.HTML(f"<p>{hint}</p>"), self.body, self.add])

    def _changed(self, _=None):
        self.revision += 1

    def append(self, values=None):
        if self.elements:
            controls = [ipw.Text(placeholder="Element", layout=ipw.Layout(width="85px")),
                        ipw.Combobox(options=BASES, placeholder="Orbital basis", layout=ipw.Layout(width="190px")),
                        ipw.Text(placeholder="Auxiliary basis", layout=ipw.Layout(width="150px")),
                        ipw.Combobox(options=ECPS, placeholder="ECP", ensure_option=False, layout=ipw.Layout(width="150px"))]
        else:
            controls = [ipw.Dropdown(options=["scf", "geom", "method"], layout=ipw.Layout(width="100px")),
                        ipw.Text(placeholder="Parameter, e.g. TolE", layout=ipw.Layout(width="230px")),
                        ipw.Text(placeholder="Value, e.g. 1e-8", layout=ipw.Layout(width="220px"))]
        if values:
            for control, value in zip(controls, values):
                control.value = value
        remove = ipw.Button(icon="trash", tooltip="Remove this override", layout=ipw.Layout(width="40px"))
        row = ipw.HBox([*controls, remove], layout=ipw.Layout(flex_flow="row wrap"))
        self.rows.append((row, controls))
        for control in controls:
            control.observe(self._changed, names="value")
        def delete(_):
            self.rows.remove((row, controls))
            self.body.children = [r for r, _ in self.rows]
            row.close()
            self._changed()
        remove.on_click(delete)
        self.body.children = [r for r, _ in self.rows]
        self._changed()

    def values(self, exclude_blocks=()):
        result = {}
        for _, controls in self.rows:
            values = [c.value.strip() for c in controls]
            if self.elements:
                element, basis, auxiliary, ecp = values
                if not any(values):
                    continue
                if element in result:
                    raise ValueError(f"Repeated element: {element}")
                result[element] = {k: v for k, v in zip(("basis", "auxiliary_basis", "ecp"), (basis, auxiliary, ecp)) if v}
            else:
                block, key, text = values
                if block in exclude_blocks:
                    continue
                if not key and not text:
                    continue
                if not key or not text:
                    raise ValueError("Complete both the parameter name and its value")
                if key.lower() in {k.lower() for k in result.get(block, {})}:
                    raise ValueError(f"Repeated parameter: {block}.{key}")
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    value = text
                result.setdefault(block, {})[key] = value
        return result

    def set_values(self, values):
        for row, _ in self.rows:
            row.close()
        self.rows = []
        self.body.children = []
        if self.elements:
            for element, choices in values.items():
                self.append([element, *[choices.get(k, "") for k in ("basis", "auxiliary_basis", "ecp")]])
        else:
            for block, entries in values.items():
                for key, value in entries.items():
                    self.append([block, key, json.dumps(value) if not isinstance(value, str) else value])
        self._changed()


class GeometrySettings(ipw.VBox):
    revision = tl.Int()

    def __init__(self):
        self._loading = False
        self._single_point = False
        self._nuclear_charge = None
        self._updating_spin = False
        style = {"description_width": "160px"}
        width = ipw.Layout(width="490px")
        def dropdown(description, options):
            pairs = [item if isinstance(item, tuple) else (item, item) for item in options]
            return ipw.Dropdown(description=description, options=pairs, style=style, layout=width)
        self.protocol = dropdown("Starting protocol", [(v["label"], k) for k, v in PROTOCOLS.items()])
        apply = ipw.Button(description="Apply defaults", icon="undo", layout=ipw.Layout(width="auto"))
        apply.on_click(self._apply)
        self.method = ipw.Combobox(options=METHODS, value="PBE", description="Method", ensure_option=False, style=style, layout=width)
        self.basis = ipw.Combobox(options=BASES, value="def2-SVP", description="Basis", ensure_option=False, style=style, layout=width)
        self.charge = ipw.IntText(description="Charge", value=0, style=style, layout=width)
        self.multiplicity = ipw.BoundedIntText(description="Multiplicity (2S+1)", value=1, min=1, max=100, style=style, layout=width)
        self.auto_multiplicity = ipw.Checkbox(value=True, description="Use lowest allowed multiplicity", layout=ipw.Layout(width="auto"))
        self.spin_hint = ipw.HTML()
        self.reference = dropdown("Reference type", [("Automatic from spin", "auto"), *REFERENCES[1:]])
        self.approximation = dropdown("RI approximation", [("Automatic from method", "auto"), *APPROXIMATIONS[1:]])
        self.auxiliary_basis = ipw.Combobox(options=AUXILIARY_BASES, value="def2/J", description="Auxiliary basis", style=style, layout=width)
        self.convergence = dropdown("Geometry convergence", OPTIMIZATION)
        self.scf_convergence = dropdown("SCF convergence", SCF_CONVERGENCE)
        self.scf_convergence.value = "TightSCF"
        self.convergence.tooltip = "Convergence thresholds for moving the nuclei; Opt and NormalOpt are equivalent."
        self.scf_convergence.tooltip = "Convergence thresholds for the electronic calculation at each geometry."
        self.grid = dropdown("Integration grid", [("ORCA default", "default"), *GRIDS[1:]])
        self.dispersion = dropdown("Dispersion", [("No extra correction", "default"),
                                                ("D3BJ (Becke–Johnson damping)", "D3BJ"),
                                                ("D3ZERO (zero damping)", "D3ZERO"), ("D4", "D4")])
        self.max_steps = ipw.BoundedIntText(description="Max geometry steps", value=100, min=1, max=2000, style=style, layout=width)
        self.max_scf = ipw.BoundedIntText(description="Max SCF steps", value=200, min=1, max=2000, style=style, layout=width)
        self.elements = ParameterRows(elements=True)
        self.parameters = ParameterRows()
        self.summary = ipw.HTML()
        self.fields = {"method": self.method, "basis": self.basis, "charge": self.charge,
                       "multiplicity": self.multiplicity, "reference": self.reference,
                       "approximation": self.approximation, "auxiliary_basis": self.auxiliary_basis,
                       "optimization": self.convergence, "scf_convergence": self.scf_convergence,
                       "grid": self.grid, "dispersion": self.dispersion,
                       "max_geometry_steps": self.max_steps, "max_scf_steps": self.max_scf}
        advanced = ipw.Accordion(children=[ipw.VBox([
            self.reference, self.approximation, self.auxiliary_basis,
            self.grid, self.dispersion, self.max_steps, self.max_scf,
            ipw.HTML("<h4>Element-specific basis and ECP</h4>"), self.elements,
            ipw.HTML("<h4>Additional scientific parameters</h4>"), self.parameters,
            ipw.HTML("<p>These are expert choices. Check functional, basis, ECP and approximation compatibility in the ORCA manual. Validation checks structure and input consistency; ORCA checks whether the requested model is available. Restricted open-shell, wavefunction import and nested parameter blocks are not part of this geometry milestone.</p>"),
        ])], selected_index=None)
        advanced.set_title(0, "Advanced scientific settings")
        self.optimization_controls = ipw.VBox([
            ipw.HBox([self.protocol, apply], layout=ipw.Layout(flex_flow="row wrap")),
            ipw.HTML("<p>Starting settings for review, not a universal accuracy level. Edit any exposed setting; Apply defaults resets scientific overrides and keeps charge, spin and resources. Method and basis also accept typed ORCA names.</p>"),
            self.method, self.basis, self.scf_convergence, self.convergence,
            ipw.HTML("<p>SCF convergence controls the electronic calculation at each geometry; "
                     "geometry convergence controls when the nuclei stop moving. "
                     "The starting protocols use TightSCF and NormalOpt.</p>"),
            ipw.HTML("<p>ORCA 6.1 reference: " + " · ".join(
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'
                for label, url in MANUAL_LINKS.items()) + "</p>"),
            advanced, self.summary,
        ])
        super().__init__([self.charge, self.multiplicity, self.auto_multiplicity, self.spin_hint, self.optimization_controls])
        self.charge.observe(self._update_spin, names="value")
        self.auto_multiplicity.observe(self._update_spin, names="value")
        self.multiplicity.observe(self._spin_edited, names="value")
        for widget in [self.protocol, *self.fields.values()]:
            widget.observe(self._changed, names="value")
        for widget in [self.elements, self.parameters]:
            widget.observe(self._changed, names="revision")
        self.set_values(protocol_settings(overrides={"multiplicity": 1}), keep_spin_mode=True)

    def set_molecule(self, atoms):
        """Keep only the electron-count input, not an ORM node or geometry."""
        self._nuclear_charge = int(atoms.numbers.sum()) if atoms is not None else None
        self._update_spin()

    def _spin_edited(self, _=None):
        if not self._loading and not self._updating_spin:
            self.auto_multiplicity.value = False

    def _update_spin(self, _=None):
        if self._loading:
            return
        if self._nuclear_charge is None:
            self.spin_hint.value = "<p>The automatic default uses the molecule and charge: 1 for even, 2 for odd electron counts.</p>"
            return
        electrons = self._nuclear_charge - self.charge.value
        if electrons < 1:
            self.spin_hint.value = "<p>The charge leaves fewer than one electron. Review the molecule and charge.</p>"
            return
        lowest = 1 + electrons % 2
        if self.auto_multiplicity.value:
            self._updating_spin = True
            try:
                self.multiplicity.value = lowest
            finally:
                self._updating_spin = False
        mode = "Automatic default" if self.auto_multiplicity.value else "Manual or copied spin retained"
        self.spin_hint.value = (f"<p>{mode}. {electrons} electrons; lowest allowed multiplicity: {lowest}. "
                                "Electron count does not determine the ground-state spin; choose a higher multiplicity when appropriate.</p>")

    def values(self):
        return {"schema_version": 2, "protocol": self.protocol.value,
                **{key: widget.value for key, widget in self.fields.items()},
                "element_settings": self.elements.values(),
                "block_parameters": self.parameters.values(exclude_blocks=("geom",) if self._single_point else ())}

    def set_optimization_enabled(self, enabled):
        self._single_point = not enabled
        # The original controls share a Layout; replace it for these two only.
        self.convergence.layout = ipw.Layout(width="490px", display="" if enabled else "none")
        self.max_steps.layout = ipw.Layout(width="490px", display="" if enabled else "none")
        self._changed()

    def _changed(self, _=None):
        if self._loading:
            return
        try:
            overrides = protocol_overrides(self.values())
            if self._single_point:
                for key in ("optimization", "max_geometry_steps"):
                    overrides.pop(key, None)
            text = ", ".join(k.replace("_", " ") for k in overrides) if overrides else "none"
            self.summary.value = f"<p><b>Changes from protocol:</b> {html.escape(text)}</p>"
        except ValueError as exc:
            self.summary.value = f"<p>{html.escape(str(exc))}</p>"
        self.revision += 1

    def set_values(self, settings, *, keep_spin_mode=False):
        s = editable_settings(settings)
        self._loading = True
        try:
            if not keep_spin_mode:
                self.auto_multiplicity.value = False
            self.protocol.value = s["protocol"]
            for key, widget in self.fields.items():
                widget.value = s[key]
            self.elements.set_values(s["element_settings"])
            self.parameters.set_values(s["block_parameters"])
        finally:
            self._loading = False
        self._update_spin()
        self._changed()

    def _apply(self, _=None):
        self.set_values(protocol_settings(self.protocol.value, {
            "charge": self.charge.value, "multiplicity": self.multiplicity.value,
        }), keep_spin_mode=True)
