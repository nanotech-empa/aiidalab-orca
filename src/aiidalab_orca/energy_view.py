"""Choose a solver after inspecting and confirming the same active orbitals."""

import html
import ipywidgets as ipw

from .energy_route import assess_space


class EnergyRoutes(ipw.VBox):
    def __init__(self, reference_uuid, reference, space, open_orca, open_quantum):
        self.reference_uuid = str(reference_uuid)
        self.space = {
            "electrons": space["electrons"],
            "orbitals": list(space["orbitals"]),
        }
        self.choice = ipw.RadioButtons(
            options=[
                ("ORCA CASCI — full selected active space", "orca"),
                ("Quantum-assisted energy levels (simulator or QPU)", "quantum"),
            ],
            value="orca",
            layout=ipw.Layout(width="100%"),
        )
        self.explanation = ipw.HTML()
        self.continue_button = ipw.Button(
            description="Continue with ORCA CASCI",
            button_style="primary",
            icon="arrow-right",
            layout=ipw.Layout(width="auto"),
        )
        self._callbacks = {"orca": open_orca, "quantum": open_quantum}
        self.choice.observe(self._changed, names="value")
        self.continue_button.on_click(lambda _: self._callbacks[self.choice.value]())
        size = assess_space(
            space["electrons"], space["orbitals"], 1 + space["electrons"] % 2
        )
        warning = (
            (
                "<p><b>Larger than the CAS(7,7) learning example.</b> Review circuit depth, "
                "sampling cost and classical post-processing before submitting. Choosing a QPU "
                "does not by itself make a large CAS feasible.</p>"
            )
            if size["large_example"]
            else ""
        )
        index_text = ", ".join(map(str, space["orbitals"]))
        super().__init__(
            [
                ipw.HTML(
                    "<h3>Compute the many-electron energy levels</h3>"
                    f"<p><b>Confirmed CAS({space['electrons']},{len(space['orbitals'])})</b> · "
                    f"ORCA orbital indices (start at 0): {html.escape(index_text)}.</p>"
                    "<p>The prepared spatial orbitals and active-space choice are shared. "
                    "Choose a solver now; you can return and run the other route for comparison.</p>"
                ),
                self.choice,
                self.explanation,
                ipw.HTML(warning),
                self.continue_button,
            ]
        )
        self._changed()

    def _changed(self, _=None):
        if self.choice.value == "orca":
            self.explanation.value = (
                "<p>Choose charge sectors, multiplicities and the number of states, "
                "then review and submit ORCA CASCI. <b>No separate Hamiltonian export is needed.</b> "
                "ORCA computes the required integrals internally.</p>"
            )
            self.continue_button.description = "Continue with ORCA CASCI"
        else:
            self.explanation.value = (
                "<p><b>Export active-space Hamiltonian → prepare circuits → "
                "simulator or real QPU sampling → classical post-processing → energy diagram.</b> "
                "Export computes integrals in the confirmed orbitals; it must not solve the full CASCI problem. "
                "The quantum device supplies samples, rather than energy eigenvalues directly. "
                "PySCF diagonalizes the exported Hamiltonian projected into the sampled product space. "
                "A separate full exported-Hamiltonian solve with PySCF is an optional reference when feasible. "
                "Neither operation runs ORCA CASCI.</p>"
                "<p>Simulator and hardware results are labelled separately. Hardware execution requires "
                "an explicit review of the backend, circuits, shots and budget.</p>"
            )
            self.continue_button.description = (
                "Continue with quantum-assisted calculation"
            )
