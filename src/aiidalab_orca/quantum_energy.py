"""Guided, independently reviewable quantum-assisted energy stages."""

import html
import base64
import io
from math import comb
import ipywidgets as ipw

from . import casci_services, energy_services as service
from .energy_route import assess_space, STAGE_LABELS
from .retention import FullFileRetention, description as retention_description
from .property_services import default_stash_directory


def text_control(label, value):
    return ipw.Text(
        value=value,
        description=label,
        style={"description_width": "initial"},
        layout=ipw.Layout(width="95%"),
    )


def integer_control(label, value, low=1, high=100000):
    return ipw.BoundedIntText(
        value=value,
        min=low,
        max=high,
        description=label,
        style={"description_width": "initial"},
    )


def disclosure(title, children):
    return ipw.Accordion(
        children=[ipw.VBox(children)], titles=[title], selected_index=None
    )


class QuantumEnergy(ipw.VBox):
    def __init__(self, reference_uuid, space):
        self.reference_uuid = str(reference_uuid)
        self.space = {
            "electrons": space["electrons"],
            "orbitals": list(space["orbitals"]),
        }
        self.reference = casci_services.reference_data(self.reference_uuid)
        self._plan = None
        self._operation = None
        self._refreshing = False
        self.model = ipw.Dropdown(
            description="Hamiltonian",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.circuit = ipw.Dropdown(
            description="Prepared circuits",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.samples = ipw.Dropdown(
            description="Samples to analyze",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.prepared = ipw.Dropdown(
            description="Hardware preparation",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.code = ipw.Dropdown(
            description="Worker / computer",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.charge = integer_control(
            "Target charge", self.reference["charge"], -100, 100
        )
        self.mult = integer_control(
            "Minimum multiplicity in solver sector", 1 + space["electrons"] % 2, 1, 100
        )
        self.spin_help = ipw.HTML()
        basis = self.reference["settings"]["basis"]
        self.aux = text_control(
            "Correlation auxiliary basis",
            basis + "/C"
            if basis in ("def2-SVP", "def2-TZVP", "def2-TZVPP")
            else "AutoAux",
        )
        self.full_files = FullFileRetention(directory=default_stash_directory())
        self.times = text_control("Evolution times (Hartree⁻¹)", "1.0")
        self.initial_alpha = text_control(
            "Initial α occupied orbitals (ORCA indices)", ""
        )
        self.initial_beta = text_control(
            "Initial β occupied orbitals (ORCA indices)", ""
        )
        self.randomizations = integer_control("Circuits per time", 4, 1, 100)
        self.groups = integer_control("Excitation groups per circuit", 10, 1, 50)
        self.seed = integer_control("Random seed", 42, 0, 2**32 - 1000)
        self.remove_diagonal = ipw.Checkbox(
            value=True,
            description="Omit occupation-diagonal terms from the sampling generator",
        )
        self.mode = ipw.RadioButtons(
            options=[
                ("Ideal QPU simulator", "simulator"),
                ("Real IBM QPU", "hardware"),
            ],
            value="simulator",
        )
        self.shots = integer_control("Shots per circuit", 1000, 100, 100000)
        self.backend = text_control("IBM backend name", "")
        self.maximum = integer_control("QPU execution limit (s)", 60, 1, 3600)
        self.budget = integer_control("Campaign time budget (s)", 90, 1, 86400)
        self.margin = integer_control("Reserved margin (s)", 30, 0, 3600)
        self.hardware_ok = ipw.Checkbox(
            value=False,
            description="I authorize execution of this reviewed request on real hardware",
        )
        self.roots = integer_control("Energy levels to request", 4, 1, 1000000)
        self.strings = integer_control("Maximum strings per spin", 128, 1, 1024)
        self.dimension = integer_control(
            "Maximum determinant dimension", 100000, 1, 1000000
        )
        self.max_qubits = integer_control("Simulator qubit cap", 20, 2, 24)
        self.processes = integer_control("CPU processes / threads", 2, 1, 64)
        self.memory = ipw.BoundedFloatText(
            value=4,
            min=0.25,
            max=256,
            step=0.25,
            description="Total CPU memory (GiB)",
            style={"description_width": "initial"},
        )
        self.minutes = integer_control("CPU wall time (minutes)", 30, 1, 1440)
        self.review = ipw.HTML()
        self.status = ipw.HTML()
        self.levels = ipw.HTML()
        self.orca = ipw.Dropdown(
            description="Saved ORCA comparison",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.orca_note = ipw.HTML()
        self._orca_context = None
        self.submit_button = ipw.Button(
            description="Submit reviewed stage",
            button_style="success",
            disabled=True,
            icon="play",
            layout=ipw.Layout(width="auto"),
        )
        self.submit_button.on_click(self._submit)
        self.history = ipw.HTML()
        card_refresh = ipw.Button(
            description="Refresh status and saved results",
            icon="refresh",
            layout=ipw.Layout(width="auto"),
        )
        card_refresh.on_click(self._refresh)
        self.review_card = ipw.VBox(
            [
                self.code,
                self.review,
                ipw.HBox([self.submit_button, card_refresh]),
                self.status,
            ]
        )
        self._review_slot = None
        refresh = ipw.Button(
            description="Refresh status and saved results",
            icon="refresh",
            layout=ipw.Layout(width="auto"),
        )
        refresh.on_click(self._refresh)

        def action(label, operation):
            button = ipw.Button(
                description=label,
                button_style="primary",
                icon="list",
                layout=ipw.Layout(width="auto"),
            )
            slot = ipw.VBox()
            button.on_click(lambda _: self._choose(operation, slot))
            return ipw.VBox([button, slot])

        size = assess_space(
            space["electrons"], space["orbitals"], 1 + space["electrons"] % 2
        )
        self.hardware_box = ipw.VBox(
            [
                self.backend,
                self.maximum,
                self.budget,
                self.margin,
                action(
                    "Prepare hardware circuits for review (no QPU job)",
                    "prepare-hardware",
                ),
                self.prepared,
                self.hardware_ok,
            ],
            layout=ipw.Layout(display="none"),
        )
        super().__init__(
            [
                ipw.HTML(
                    "<h3>Quantum-assisted energy levels</h3>"
                    f"<p><b>CAS({space['electrons']},{len(space['orbitals'])})</b> · {size['qubits']} logical qubits. "
                    "The QPU or simulator supplies occupation samples; classical diagonalization extracts energy levels. "
                    "Every numbered stage has a separate review. Opening this workspace submits nothing.</p>"
                    + (
                        "<p><b>Larger than CAS(7,7):</b> review circuit depth, sampling budget, simulator memory and classical "
                        "subspace size. Qubit count alone does not establish feasibility.</p>"
                        if size["large_example"]
                        else ""
                    )
                ),
                refresh,
                self.history,
                disclosure(
                    "CPU resources for the reviewed stages",
                    [
                        self.processes,
                        self.memory,
                        self.minutes,
                        ipw.HTML(
                            "<p>These are per-stage CPU limits. Native export uses the ORCA computer that holds "
                            "the prepared reference; portable circuit and solver stages use the worker selected in their review.</p>"
                        ),
                    ],
                ),
                ipw.HTML(
                    "<h4>1. Export the active-space Hamiltonian</h4><p>Uses the saved orbitals on their ORCA computer. "
                    "No geometry optimization, SCF iteration or full CASCI is requested. The export includes inactive-electron "
                    "and nuclear contributions once. Reuse a completed model below, or review a new export.</p>"
                ),
                disclosure(
                    "Hamiltonian approximation",
                    [
                        self.aux,
                        ipw.HTML(
                            "<p>The auxiliary basis controls the RI integral "
                            "approximation. Change it only with a suitable basis for your elements; use the same setting in ORCA "
                            "CASCI for comparison. Export does not change the orbital basis or optimize the selected orbitals.</p>"
                        ),
                    ],
                ),
                self.full_files,
                action("Review Hamiltonian export", "export"),
                self.model,
                ipw.HTML(
                    "<h4>2. Choose a charge/spin sector and prepare circuits</h4><p>The same Hamiltonian serves these state families; changing this choice does not rerun export.</p>"
                ),
                ipw.HBox([self.charge, self.mult]),
                self.spin_help,
                ipw.HTML(
                    "<p>SqDRIFT builds randomized circuits from the Hamiltonian. "
                    "These initial settings are a learning example, not a converged molecular calculation.</p>"
                ),
                disclosure(
                    "Circuit parameters and guidance",
                    [
                        self.times,
                        self.initial_alpha,
                        self.initial_beta,
                        self.randomizations,
                        self.groups,
                        self.seed,
                        self.remove_diagonal,
                        ipw.HTML(
                            "<p><b>Evolution times:</b> control the sampling evolution; compare times "
                            "when important configurations are missed. <b>Circuits per time:</b> more random draws diversify support "
                            "and increase cost. <b>Groups:</b> more sampled excitations usually deepen each circuit. "
                            "<b>Seed:</b> records reproducibility, not accuracy. Omitting diagonal terms changes the sampling "
                            "generator; all energies still use the original full Hamiltonian. Occupation-dependent rejection filtering is disabled.</p>"
                            "<p><b>Initial occupations:</b> leave both fields blank to fill the lowest-indexed active orbitals "
                            "for each spin. For other state characters or missing symmetry sectors, try another occupation pattern "
                            "and compare the results. Enter original selected ORCA indices, with spaces, commas or ranges such as "
                            "<code>10 12..14</code>. Counts must match the selected solver’s α/β sector. This changes "
                            "the starting determinant, not the CAS orbitals; an arbitrary determinant need not be spin-pure.</p>"
                        ),
                    ],
                ),
                action("Review circuit generation", "generate"),
                self.circuit,
                ipw.HTML("<h4>3. Sample on a simulator or real QPU</h4>"),
                self.mode,
                self.shots,
                self.hardware_box,
                action("Review sampling / retrieve hardware job", "sample"),
                self.samples,
                ipw.HTML(
                    "<h4>4. Solve the QPU/simulator-selected subspace with PySCF</h4><p>Samples select the configurations used by the "
                    "projected solver; sample frequencies are not wavefunction coefficients. Request several roots to obtain "
                    "excited levels as well as the lowest state. PySCF diagonalizes the original exported Hamiltonian projected "
                    "into that sampled product space. Missing configurations can limit accuracy. No ORCA calculation runs here.</p>"
                ),
                self.roots,
                disclosure(
                    "Classical solver and resource limits",
                    [
                        self.strings,
                        self.dimension,
                        self.max_qubits,
                        ipw.HTML(
                            "<p><b>Spin-string limit:</b> controls retained support; "
                            "increase it and sampling to check convergence. The solver uses a Cartesian product of spin strings, "
                            "including combinations not directly observed. <b>Dimension cap:</b> blocks an oversized solve before "
                            "building its state space. Full classical CAS grows combinatorially. The ideal statevector simulator "
                            "uses exponentially growing memory; it models neither device noise nor quantum advantage. "
                            "Review S² for every level: fixing Mₛ alone does not select a unique total spin.</p>"
                        ),
                    ],
                ),
                action("Review sampled-subspace solve (PySCF)", "solve-sampled"),
                disclosure(
                    "Optional reference: full exported Hamiltonian (PySCF)",
                    [
                        ipw.HTML(
                            "<p>PySCF diagonalizes the exported Hamiltonian in the complete selected charge/Mₛ sector. "
                            "This uses no quantum samples and runs no ORCA CASCI. It is a separate CPU reference, "
                            "feasible only for sufficiently small spaces. ORCA CASCI remains available from Choose energy solver.</p>"
                        ),
                        action(
                            "Review full exported Hamiltonian solve (PySCF)",
                            "solve-full",
                        ),
                    ],
                ),
                ipw.VBox(
                    [
                        ipw.HTML(
                            "<h4>Compare with saved ORCA CASCI (display only)</h4>"
                        ),
                        self.orca,
                        self.orca_note,
                    ]
                ),
                self.levels,
            ]
        )
        for control in (
            self.model,
            self.circuit,
            self.samples,
            self.prepared,
            self.charge,
            self.mult,
            self.aux,
            self.times,
            self.initial_alpha,
            self.initial_beta,
            self.randomizations,
            self.groups,
            self.seed,
            self.remove_diagonal,
            self.mode,
            self.shots,
            self.backend,
            self.maximum,
            self.budget,
            self.margin,
            self.hardware_ok,
            self.roots,
            self.strings,
            self.dimension,
            self.max_qubits,
            self.processes,
            self.memory,
            self.minutes,
        ):
            control.observe(self._invalidate, names="value")
        self.full_files.observe(self._invalidate, names='revision')
        self.code.observe(self._review_current, names="value")
        self.mode.observe(
            lambda _: setattr(
                self.hardware_box.layout,
                "display",
                "" if self.mode.value == "hardware" else "none",
            ),
            names="value",
        )
        self.model.observe(lambda _: self._refresh(), names="value")
        self.charge.observe(self._spin_help, names="value")
        self.charge.observe(self._refresh, names="value")
        self.mult.observe(self._spin_help, names="value")
        self.mult.observe(self._refresh, names="value")
        self.orca.observe(self._refresh, names="value")
        self._spin_help()
        self._refresh()

    def _sector(self):
        return {"charge": self.charge.value, "ms2": self.mult.value - 1}

    def _spin_help(self, _=None):
        electrons = (
            self.space["electrons"] - self.charge.value + self.reference["charge"]
        )
        n = len(self.space["orbitals"])
        if not 0 <= electrons <= 2 * n:
            self.spin_help.value = "<p><b>This charge is outside the selected active electron space.</b></p>"
            return
        values = list(
            range(1 + electrons % 2, min(electrons, 2 * n - electrons) + 2, 2)
        )
        prefix = (
            "<b>Choose an allowed multiplicity.</b> "
            if self.mult.value not in values
            else ""
        )
        self.spin_help.value = (
            "<p>"
            + prefix
            + f"{electrons} active electrons at this charge. Allowed multiplicities: "
            + ", ".join(map(str, values))
            + ". This sets Mₛ for sampling/diagonalization; states with that total spin or higher can appear. "
            "Raise it to explore higher-spin families. Electron parity does not identify the physical ground-state spin.</p>"
        )

    def _invalidate(self, _=None):
        self._plan = None
        self.submit_button.disabled = True
        self.review.value = (
            "<p>Review the selected stage after changing its inputs.</p>"
        )

    def _choose(self, operation, slot=None):
        if slot is not None:
            if self._review_slot is not None:
                self._review_slot.children = ()
            slot.children = (self.review_card,)
            self._review_slot = slot
        if operation == "sample":
            operation = (
                "sample-simulator"
                if self.mode.value == "simulator"
                else "sample-hardware"
            )
        self._operation = operation
        rows = service.resources("validate" if operation == "export" else operation)
        self.code.options = [("Choose a configured worker", None)] + [
            (r["label"] + " @ " + r["computer"], r["uuid"]) for r in rows
        ]
        if rows:
            self.code.value = rows[0]["uuid"]
        self._review_current()

    def _review_current(self, _=None):
        self._invalidate()
        if not self._operation:
            return
        if not self.code.value:
            self.review.value = "<p>Configure an energy worker supporting this stage on localhost or your chosen computer. See the quantum-energy setup guide.</p>"
            return
        try:
            resources = {
                "processes": self.processes.value,
                "memory_mb": int(self.memory.value * 1024),
                "wallclock_seconds": self.minutes.value * 60,
            }
            if self._operation == "export":
                self._plan = service.prepare_export(
                    self.reference_uuid,
                    self.space,
                    {
                        "auxiliary_basis": self.aux.value.strip(),
                        "nprocs": resources["processes"],
                        "memory_mb": resources["memory_mb"],
                        "wallclock_seconds": resources["wallclock_seconds"],
                    },
                    self.code.value,
                    native_output_policy=self.full_files.values(),
                )
            else:
                if not self.model.value:
                    raise ValueError("Export and select a validated Hamiltonian first")
                settings = {
                    "generate": lambda: {
                        "times": [
                            float(x) for x in self.times.value.replace(",", " ").split()
                        ],
                        "randomizations": self.randomizations.value,
                        "groups": self.groups.value,
                        "seed": self.seed.value,
                        "remove_diagonal": self.remove_diagonal.value,
                    },
                    "sample-simulator": lambda: {
                        "shots": self.shots.value,
                        "seed": self.seed.value,
                        "max_qubits": self.max_qubits.value,
                    },
                    "prepare-hardware": lambda: {
                        "backend": self.backend.value.strip(),
                        "shots": self.shots.value,
                        "max_execution_seconds": self.maximum.value,
                        "budget_total_seconds": self.budget.value,
                        "budget_margin_seconds": self.margin.value,
                        "seed": self.seed.value,
                    },
                    "sample-hardware": lambda: {
                        "hardware_authorized": self.hardware_ok.value
                    },
                    "solve-full": lambda: {
                        "nroots": self.roots.value,
                        "threads": resources["processes"],
                        "memory_mb": resources["memory_mb"],
                        "max_dimension": self.dimension.value,
                    },
                    "solve-sampled": lambda: {
                        "nroots": self.roots.value,
                        "threads": resources["processes"],
                        "memory_mb": resources["memory_mb"],
                        "max_dimension": self.dimension.value,
                        "string_limit": self.strings.value,
                    },
                }[self._operation]()
                if self._operation == "generate" and (
                    self.initial_alpha.value.strip() or self.initial_beta.value.strip()
                ):
                    from .orbital_selection import parse_orbital_indices

                    for key, control in [
                        ("initial_alpha", self.initial_alpha),
                        ("initial_beta", self.initial_beta),
                    ]:
                        indices = parse_orbital_indices(
                            control.value, self.space["orbitals"]
                        )
                        settings[key] = [
                            self.space["orbitals"].index(i) for i in indices
                        ]
                self._plan = service.prepare_stage(
                    self.model.value,
                    self._operation,
                    settings,
                    self.code.value,
                    sector=self._sector(),
                    circuit_uuid=self.circuit.value
                    if self._operation in ("sample-simulator", "prepare-hardware")
                    else None,
                    sample_uuid=self.samples.value
                    if self._operation == "solve-sampled"
                    else None,
                    prepared_uuid=self.prepared.value
                    if self._operation == "sample-hardware"
                    else None,
                    **resources,
                )
            names = {
                "charge": "Charge",
                "multiplicity": "Multiplicity",
                "nroots": "States to request",
                "nprocs": "CPU processes",
                "memory_mb": "Total CPU memory (MiB)",
                "wallclock_seconds": "CPU wall time (s)",
                "auxiliary_basis": "Correlation auxiliary basis",
                "times": "Evolution times (Hartree⁻¹)",
                "randomizations": "Circuits per evolution time",
                "groups": "Excitation groups per circuit",
                "seed": "Random seed",
                "remove_diagonal": "Remove diagonal terms from sampling generator",
                "initial_alpha": "Initial α occupied orbitals (ORCA indices)",
                "initial_beta": "Initial β occupied orbitals (ORCA indices)",
                "shots": "Shots per circuit",
                "max_qubits": "Simulator qubit cap",
                "threads": "CPU threads",
                "max_dimension": "Classical determinant-space cap",
                "string_limit": "Spin-string cap",
                "backend": "QPU backend",
                "max_execution_seconds": "QPU execution limit (s)",
                "budget_total_seconds": "Campaign budget (s)",
                "budget_margin_seconds": "Budget margin (s)",
                "hardware_authorized": "Real hardware execution authorized",
            }
            if self._operation == "export":
                names["charge"] = "Export reference charge"
                names["multiplicity"] = "Diagnostic multiplicity (export only)"
            display_settings = dict(self._plan["settings"])
            for key in ("initial_alpha", "initial_beta"):
                if key in display_settings:
                    display_settings[key] = [
                        self.space["orbitals"][i] for i in display_settings[key]
                    ]
            rows = "".join(
                '<tr><td style="padding:6px 12px">'
                + html.escape(names[key])
                + '</td><td style="padding:6px 12px">'
                + html.escape(str(value))
                + "</td></tr>"
                for key, value in display_settings.items()
                if key in names
                and not (self._operation == "export" and key == "nroots")
            )
            target = next(
                (
                    label
                    for label, value in self.code.options
                    if value == self.code.value
                ),
                "",
            )
            self.review.value = (
                "<p><b>Review: "
                + html.escape(STAGE_LABELS[self._operation])
                + "</b> · "
                + html.escape(target)
                + ". No calculation has been submitted.</p><table>"
                + rows
                + "</table>"
            )
            if self._operation == 'export':
                self.review.value += '<p>Full files: ' + html.escape(retention_description(self._plan['native_output_policy'])) + '.</p>'
            transfer = self._plan.get('hamiltonian_transfer')
            if transfer:
                self.review.value += ('<p>The Hamiltonian stays outside the AiiDA repository. ' +
                    ('A temporary transfer from ' + html.escape(transfer['source_computer']) +
                     f" to this worker needs {transfer['size_bytes'] / 1024**2:.2f} MiB of local staging space."
                     if transfer['temporary_relay'] else 'It is copied directly on this calculation computer.') + '</p>')
            if self._plan.get("model_description"):
                model = self._plan["model_description"]
                self.review.value += (
                    "<p><b>Selected Hamiltonian:</b> "
                    + f"reference charge {model['charge']:+d}, diagnostic multiplicity {model['multiplicity']}, "
                    + f"CAS({model['active_space']['electrons']},{len(model['active_space']['orbitals'])}), "
                    + html.escape(model["auxiliary_basis"])
                    + ". Export fields above apply only to a new export.</p>"
                )
            if self._plan.get("sector"):
                sector = self._plan["sector"]
                self.review.value += (
                    f"<p><b>Solver sector:</b> charge {sector['charge']:+d}, "
                    f"{self._plan['sector_electrons']} active electrons, "
                    f"Mₛ = {sector['ms2'] / 2:g} (minimum multiplicity {sector['ms2'] + 1}). "
                    "Higher-spin roots may also appear; inspect S².</p>"
                )
            if self._plan.get("hardware_review"):
                hardware = self._plan["hardware_review"]
                self.review.value += (
                    "<p><b>Prepared hardware request:</b> "
                    + html.escape(hardware["backend"])
                    + f", {len(hardware['circuits'])} circuits, {hardware['shots']} shots each, "
                    + f"{hardware['max_execution_seconds']} s execution limit, "
                    + f"{hardware['budget_total_seconds']} s campaign budget. "
                    + "Retrieval resumes this request; it does not create another provider job.</p>"
                )
                self.review.value += (
                    "<p>Compiled circuits: "
                    + f"maximum depth {max(row['depth'] for row in hardware['circuits'])}, "
                    + f"maximum two-qubit gate count {max(row['two_qubit_gates'] for row in hardware['circuits'])}.</p>"
                )
            self.submit_button.disabled = False
            self.submit_button.description = (
                (
                    "Submit reviewed hardware request"
                    if self.hardware_ok.value
                    else "Retrieve existing hardware job only"
                )
                if self._operation == "sample-hardware"
                else "Submit reviewed stage"
            )
        except (ValueError, KeyError, OSError) as exc:
            self.review.value = "<p>" + html.escape(str(exc)) + "</p>"

    def _submit(self, _=None):
        if self._plan is None:
            return
        try:
            plan, self._plan = self._plan, None
            self.submit_button.disabled = True
            uid = service.submit(plan)
            self.review.value = self.review.value.replace(
                "No calculation has been submitted.",
                "This reviewed request has been submitted.",
            )
            self.status.value = (
                "<p>Submitted "
                + html.escape(STAGE_LABELS[plan["operation"]])
                + " · "
                + html.escape(uid)
                + ". Use Refresh status and saved results to inspect progress.</p>"
            )
        except (ValueError, KeyError, OSError) as exc:
            self.status.value = "<p>" + html.escape(str(exc)) + "</p>"

    def _refresh(self, _=None):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            self._refresh_contents()
        finally:
            self._refreshing = False

    def _refresh_contents(self):
        def choices(widget, rows, label):
            previous = widget.value
            values = [row["uuid"] for row in rows if row["finished_ok"]]
            widget.options = [("No completed " + label, None)] + [
                (row.get("label", row["uuid"][:8]) + " · " + row["state"], row["uuid"])
                for row in rows
                if row["finished_ok"]
            ]
            widget.value = (
                previous if previous in values else (values[-1] if values else None)
            )

        rows = service.models(self.reference_uuid, self.space)
        choices(self.model, rows, "Hamiltonian")
        status = [
            "Hamiltonian export · "
            + row.get("label", row["uuid"][:8])
            + " · "
            + row["state"]
            for row in rows[-3:]
        ]
        self.history.value = (
            "<p>"
            + (
                "<br>".join(html.escape(text) for text in status)
                if status
                else "No energy stages have been submitted for this active space."
            )
            + "</p>"
        )
        if not self.model.value:
            for widget, label in (
                (self.circuit, "circuits"),
                (self.samples, "samples"),
                (self.prepared, "hardware preparation"),
            ):
                choices(widget, [], label)
            self.orca.options = [("No Hamiltonian selected", None)]
            self.orca.disabled = True
            self.orca_note.value = ""
            self.levels.value = ""
            return
        sector = self._sector()
        circuits = service.stages(self.model.value, "generate", sector=sector)
        choices(self.circuit, circuits, "circuits")
        samples = service.stages(
            self.model.value, "sample-simulator", sector=sector
        ) + service.stages(self.model.value, "sample-hardware", sector=sector)
        samples = [
            r for r in samples if r["result"] and "samples_sha256" in r["result"]
        ]
        choices(self.samples, samples, "samples")
        choices(
            self.prepared,
            service.stages(self.model.value, "prepare-hardware", sector=sector),
            "hardware preparation",
        )
        levels = service.stages(
            self.model.value, "solve-full", sector=sector
        ) + service.stages(self.model.value, "solve-sampled", sector=sector)
        levels.sort(key=lambda row: row["created"])
        for operation in (
            "generate",
            "sample-simulator",
            "prepare-hardware",
            "sample-hardware",
            "solve-full",
            "solve-sampled",
        ):
            for row in service.stages(self.model.value, operation, sector=sector)[-2:]:
                status.append(
                    row.get("label", operation)
                    + " · "
                    + row["state"]
                    + " · "
                    + row["uuid"][:8]
                )
        self.history.value = (
            "<p>" + "<br>".join(html.escape(text) for text in status) + "</p>"
        )
        results = [row["result"] for row in levels if row["result"]]
        latest = {
            result.get("samples_execution_kind") or "full": result for result in results
        }
        results = list(latest.values())
        references = service.orca_comparisons(self.model.value, sector)
        previous = self.orca.value
        context = (self.model.value, sector["charge"], sector["ms2"])
        self.orca.options = [("Do not overlay saved ORCA results", None)] + [
            (row["label"], row["uuid"]) for row in references
        ]
        values = [row["uuid"] for row in references]
        if context != self._orca_context or previous not in values + [None]:
            self.orca.value = values[0] if values else None
        else:
            self.orca.value = previous
        self._orca_context = context
        self.orca.disabled = not references
        self.orca_note.value = (
            "<p>Only completed calculations with the same prepared orbitals, geometry, active space, "
            "charge, ORCA code and integral settings are offered. Selecting one only updates this display; it submits nothing. "
            "Its fixed total spin may differ from other states allowed in the selected Mₛ sector.</p>"
            if references
            else "<p>No compatible saved ORCA CASCI calculation is available for this exact orbital reference, active space, charge and integral model.</p>"
        )
        selected = next(
            (row["result"] for row in references if row["uuid"] == self.orca.value),
            None,
        )
        if selected:
            results.append(selected)
        comparison = (
            "".join(
                self._orca_comparison_table(result, selected)
                for result in results
                if result.get("origin") != "orca_casci"
            )
            if selected
            else ""
        )
        self.levels.value = (
            "".join(self._coverage_notice(result) for result in results)
            + self._diagram(results)
            + comparison
            + "".join(self._level_table(result) for result in results)
        )

    @staticmethod
    def _solver_label(result, multiline=False):
        if result.get("origin") == "orca_casci":
            return (
                "ORCA CASCI"
                + ("\n" if multiline else " — ")
                + f"multiplicity {result['multiplicity']}"
            )
        kind = result.get("samples_execution_kind")
        route = (
            "full exported Hamiltonian"
            if kind is None
            else "QPU-selected subspace"
            if kind == "ibm_hardware"
            else "simulator-selected subspace"
        )
        return ("PySCF\n" if multiline else "PySCF — ") + route

    @staticmethod
    def _coverage_notice(result):
        if result.get("selection") is None:
            return ""
        dimension = result["dimension"]
        native = result.get("native_export", {})
        norb = len(native.get("active_space", {}).get("orbitals", []))
        nelec = result.get("nelec")
        full = comb(norb, nelec[0]) * comb(norb, nelec[1]) if norb and nelec else None
        dynamic = (
            result.get("software", {})
            .get("capabilities", {})
            .get("resource_bounded_roots", False)
        )
        adapter_limit = 1000000 if dynamic else 4
        required = min(
            result["requested_roots"],
            full if full is not None else adapter_limit,
            adapter_limit,
        )
        adapter_note = (
            " This adapter returns at most four levels per solve; additional shots do not raise that solver limit."
            if not dynamic and result["requested_roots"] > 4
            else ""
        )
        limited = result["used_roots"] < required or (
            dimension == 1 and full and full > 1
        )
        span = f"{dimension} of {full}" if full else str(dimension)
        title = "Insufficient sampled space" if limited else "Sampled-space coverage"
        explanation = (
            "The sampled product space cannot supply the requested spectrum. Increase shots, diversify "
            "circuits/times or review initial occupations, then resample and repeat the sampled-space solve. "
            "The Hamiltonian export can be reused."
            if limited
            else "The product space spans the complete selected Mₛ sector."
            if full == dimension
            else "These are projected-space approximations. Check level stability with more sampling and retained configurations."
        )
        return (
            "<div style='padding:12px;border:2px solid "
            + ("#b35b00" if limited else "#7592a0")
            + "'>"
            f"<b>{title}:</b> retained dimension {span}; computed {result['used_roots']} of "
            f"{result['requested_roots']} requested levels. {explanation}{adapter_note}</div>"
        )

    @staticmethod
    def _diagram(results):
        if not results:
            return ""
        from matplotlib.figure import Figure

        figure = Figure(
            figsize=(max(6.5, 3.5 * len(results)), 5.5), layout="constrained"
        )
        axes = figure.subplots()
        zero = min(
            level["energy_hartree"] for result in results for level in result["levels"]
        )
        labels = []
        span = max(
            (level["energy_hartree"] - zero) * 27.211386245988
            for result in results
            for level in result["levels"]
        )
        separation = max(span * 0.045, 0.005)
        highest_label = 0
        for column, result in enumerate(results):
            label = QuantumEnergy._solver_label(result, multiline=True)
            labels.append(label)
            previous = float("-inf")
            for level in sorted(
                result["levels"], key=lambda row: row["energy_hartree"]
            ):
                energy = (level["energy_hartree"] - zero) * 27.211386245988
                label_y = max(energy, previous + separation)
                previous = label_y
                highest_label = max(highest_label, label_y)
                axes.hlines(
                    energy,
                    column - 0.28,
                    column + 0.28,
                    color="#ce7d19"
                    if result.get("origin") == "orca_casci"
                    else "#2461a8"
                    if result["selection"] is None
                    else "#27864d",
                )
                axes.annotate(
                    (
                        f"r{level['root']} · mult {level['multiplicity']}"
                        if result.get("origin") == "orca_casci"
                        else f"r{level['root']} · S²={level['spin_squared']:.3f}"
                    ),
                    xy=(column + 0.28, energy),
                    xytext=(column + 0.33, label_y),
                    fontsize=8,
                    arrowprops={"arrowstyle": "-", "color": "#777", "lw": 0.6}
                    if label_y != energy
                    else None,
                )
        axes.set_xticks(range(len(labels)), labels, fontsize=9)
        axes.set_ylim(-separation, max(highest_label + separation, separation))
        axes.set_ylabel("Energy relative to common lowest level (eV)")
        axes.set_xlim(-0.5, len(labels) - 0.25)
        axes.grid(axis="y", alpha=0.2)
        stream = io.BytesIO()
        figure.savefig(stream, format="svg")
        encoded = base64.b64encode(stream.getvalue()).decode()
        figure.clear()
        return (
            '<h3>Energy levels of the selected Hamiltonian</h3><img style="max-width:100%" src="data:image/svg+xml;base64,'
            + encoded
            + '"><p><a download="energy-levels.svg" href="data:image/svg+xml;base64,'
            + encoded
            + '">Download energy diagram (SVG)</a></p>'
        )

    @staticmethod
    def _orca_comparison_table(result, reference):
        spin = (reference["multiplicity"] - 1) / 2
        levels = sorted(
            [
                level
                for level in result["levels"]
                if abs(level["spin_squared"] - spin * (spin + 1)) < 1e-6
            ],
            key=lambda row: row["energy_hartree"],
        )
        if not levels:
            return "<p>No displayed PySCF level has S² matching the selected ORCA multiplicity. Choose the appropriate saved spin family.</p>"
        paired = list(zip(reference["levels"], levels))
        maximum = max(abs(a["energy_hartree"] - b["energy_hartree"]) for a, b in paired)
        rows = "".join(
            "<tr>"
            + "".join(
                "<td style='padding:6px 12px'>" + html.escape(value) + "</td>"
                for value in [
                    str(i),
                    f"{a['energy_hartree']:.10f}",
                    f"{b['energy_hartree']:.10f}",
                    f"{(b['energy_hartree'] - a['energy_hartree']) * 27.211386245988:.3e}",
                ]
            )
            + "</tr>"
            for i, (a, b) in enumerate(paired)
        )
        return (
            "<h4>Saved ORCA CASCI versus "
            + html.escape(QuantumEnergy._solver_label(result))
            + "</h4>"
            f"<p>{len(paired)} energy-ordered pairs within multiplicity {reference['multiplicity']}; "
            f"largest |ΔE| = {maximum:.3e} Hartree. Total energies are compared without alignment shifts. "
            "Pairing uses the displayed S²; check convergence and spin purity before assigning approximate roots.</p>"
            "<table><tr><th>Pair</th><th>ORCA (Ha)</th><th>PySCF (Ha)</th><th>PySCF − ORCA (eV)</th></tr>"
            + rows
            + "</table>"
        )

    @staticmethod
    def _level_table(result):
        levels = result["levels"]
        if result.get("origin") == "orca_casci":
            rows = "".join(
                f"<tr><td style='padding:6px 12px'>{row['root']}</td><td>{row['energy_hartree']:.10f}</td></tr>"
                for row in levels
            )
            return (
                "<h4>" + html.escape(QuantumEnergy._solver_label(result)) + "</h4>"
                "<p>Existing saved calculation; no new job. All columns in the diagram share one energy zero. "
                "ORCA labels show its declared spin multiplicity.</p><table><tr><th>Root</th><th>Total energy (Ha)</th></tr>"
                + rows
                + "</table>"
            )
        zero = min(row["energy_hartree"] for row in levels)
        rows = "".join(
            "<tr>"
            + "".join(
                '<td style="padding:6px 12px">' + html.escape(str(value)) + "</td>"
                for value in (
                    row["root"],
                    f"{row['energy_hartree']:.10f}",
                    f"{(row['energy_hartree'] - zero) * 27.211386245988:.6f}",
                    f"{row['spin_squared']:.6f}",
                )
            )
            + "</tr>"
            for row in levels
        )
        warning = (
            (
                "<p><b>Spin contamination detected.</b> These approximate selected-space levels do not yet "
                "define pure-spin CASCI multiplets. Increase and diversify sampling and the retained support; "
                "inspect convergence before interpreting gaps.</p>"
            )
            if not result.get("spin_expectation_consistent")
            else ""
        )
        return (
            "<h4>"
            + html.escape(QuantumEnergy._solver_label(result))
            + "</h4>"
            + warning
            + "<p>"
            + f"Requested {result['requested_roots']} levels; computed {result['used_roots']} in a space of dimension {result['dimension']}. "
            + "Energy zero: lowest state in this table; the diagram uses a shared zero. Fixed-Mₛ roots may have different total spins. "
            "A quantized S² expectation alone is not a general certificate of higher-spin purity.</p><table><tr><th>Root</th><th>Total energy (Ha)</th><th>Relative energy (eV)</th><th>S²</th></tr>"
            + rows
            + "</table>"
        )
