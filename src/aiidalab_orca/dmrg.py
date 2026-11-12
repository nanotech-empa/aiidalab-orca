"""Browser-operated native Block2 workspace with explicit review and restart."""

import base64
import html
import io

import ipywidgets as ipw
import matplotlib.pyplot as plt
import numpy as np

from . import dmrg_services as service
from .presentation import data_table


def _integer(label, value, low, high):
    return ipw.BoundedIntText(
        description=label,
        value=value,
        min=low,
        max=high,
        style={"description_width": "initial"},
        layout=ipw.Layout(width="95%"),
    )


class NativeDmrg(ipw.VBox):
    def __init__(self, reference_uuid=None, space=None, open_export=None):
        self.reference_uuid = str(reference_uuid) if reference_uuid else None
        self.space = dict(space) if space else None
        self.plan = None
        self.process_uuid = None
        self.source = ipw.Text(
            description="FCIDUMP / exported-model UUID",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.source.disabled = bool(self.reference_uuid)
        self.upload = ipw.FileUpload(accept=".fcidump,.FCIDUMP", multiple=False)
        use_upload = ipw.Button(
            description="Use uploaded FCIDUMP",
            icon="upload",
            layout=ipw.Layout(width="auto"),
        )
        use_upload.on_click(self._use_upload)
        example = ipw.Button(
            description="Load analytic CAS(2,3) example",
            icon="flask",
            layout=ipw.Layout(width="auto"),
        )
        example.on_click(self._example)
        self.model = ipw.Dropdown(
            description="Saved Hamiltonian export",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.model.observe(self._model_changed, names="value")
        self.code = ipw.Dropdown(
            description="Block2 code / computer",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.roots = ipw.Dropdown(description="Singlet roots", options=[1, 3], value=1)
        self.bond = _integer("Maximum bond dimension M", 32, 32, 8192)
        self.ordering = ipw.Dropdown(
            description="Orbital ordering", options=["none", "fiedler"], value="none"
        )
        self.sweeps = _integer("Maximum sweeps", 32, 32, 100)
        self.threads = _integer("Threads in one native process", 1, 1, 46)
        self.memory = _integer("Block2 stack memory (GB)", 2, 1, 128)
        self.minutes = _integer("Wall time (minutes)", 10, 1, 10080)
        self.output_limit = _integer("Native output retrieval (MiB)", 5, 0, 1024)
        self.parent = ipw.Text(
            description="Native checkpoint calculation UUID",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.continue_sweeps = ipw.Checkbox(
            description="Continue one-site sweeps at the same M",
            value=False,
            indent=False,
        )
        self.recompute = ipw.Checkbox(
            description="Recompute an identical completed request",
            value=False,
            indent=False,
        )
        self.label = ipw.Text(description="Run label", value="Native DMRG · singlets")
        self.review_button = ipw.Button(
            description="Review native DMRG",
            icon="list",
            button_style="primary",
            layout=ipw.Layout(width="auto"),
        )
        self.review_button.on_click(self._review)
        self.submit_button = ipw.Button(
            description="Submit reviewed DMRG",
            icon="play",
            button_style="success",
            disabled=True,
            layout=ipw.Layout(width="auto"),
        )
        self.submit_button.on_click(self._submit)
        self.review = ipw.HTML()
        self.status = ipw.HTML()
        self.results = ipw.VBox()
        self.saved = ipw.Dropdown(
            description="Native DMRG results",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.result_uuid = ipw.Text(
            description="Open native result UUID",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        open_result = ipw.Button(
            description="Open result / refresh",
            icon="refresh",
            layout=ipw.Layout(width="auto"),
        )
        open_result.on_click(self._open_result)
        checkpoint = ipw.Button(
            description="Use this result as checkpoint",
            icon="copy",
            layout=ipw.Layout(width="auto"),
        )
        checkpoint.on_click(self._checkpoint)
        self.saved.observe(self._saved_changed, names="value")
        refresh = ipw.Button(
            description="Refresh codes, exports and history",
            icon="refresh",
            layout=ipw.Layout(width="auto"),
        )
        refresh.on_click(self._refresh)
        source_controls = [self.model, self.source, self.upload, use_upload, example]
        if self.reference_uuid:
            source_controls = [self.model, self.source]
        if open_export:
            export = ipw.Button(
                description="Export the confirmed active-space Hamiltonian",
                icon="arrow-right",
                layout=ipw.Layout(width="auto"),
            )
            export.on_click(lambda _: open_export())
            source_controls.insert(0, export)
        controls = ipw.Accordion(
            children=[
                ipw.VBox(
                    [
                        self.sweeps,
                        self.output_limit,
                        ipw.HTML(
                            "<p>Sweep tolerance is 10⁻⁹ Ha. Davidson tolerance is 10⁻¹⁰ Ha. "
                            "The existing adapter switches from two-site to one-site at sweep 24.</p>"
                        ),
                    ]
                )
            ],
            titles=["Schedule and output retention"],
            selected_index=None,
        )
        super().__init__(
            [
                ipw.HTML(
                    "<h3>Native DMRG · Block2</h3>"
                    "<p>Fixed spatial orbitals, C1 symmetry, even-electron singlets and three or more "
                    "orbitals. This is DMRG-CI, without orbital optimization. No QPU is used.</p>"
                    "<p>Select a validated Hamiltonian export or explicitly upload an FCIDUMP. "
                    "A new job needs its own review. The analytic example tests integration, "
                    "rather than strong correlation or a large active space.</p>"
                ),
                refresh,
                *source_controls,
                self.code,
                self.roots,
                self.bond,
                self.ordering,
                self.threads,
                self.memory,
                self.minutes,
                controls,
                self.parent,
                self.continue_sweeps,
                self.recompute,
                self.label,
                self.review_button,
                self.review,
                self.submit_button,
                self.status,
                ipw.HTML("<h4>Saved results and checkpoints</h4>"),
                self.saved,
                self.result_uuid,
                ipw.HBox([open_result, checkpoint]),
                self.results,
            ]
        )
        for control in [
            self.source,
            self.code,
            self.roots,
            self.bond,
            self.ordering,
            self.sweeps,
            self.threads,
            self.memory,
            self.minutes,
            self.output_limit,
            self.parent,
            self.continue_sweeps,
            self.recompute,
            self.label,
        ]:
            control.observe(self._invalidate, names="value")
        self._refresh()

    def _invalidate(self, _=None):
        self.plan = None
        self.submit_button.disabled = True
        self.review.value = "<p>Review the current settings before submitting.</p>"

    def _message(self, exc):
        self.status.value = '<p class="orca-notice">' + html.escape(str(exc)) + "</p>"

    def _model_changed(self, event):
        if event["new"]:
            self.source.value = str(event["new"])

    def _saved_changed(self, event):
        if event["new"]:
            self.result_uuid.value = str(event["new"])

    def _example(self, _=None):
        self.source.value = service.store_example()
        self._message(
            "Analytic noninteracting CAS(2,3) stored. First three singlets: "
            "−2.0, −1.2, −0.4 Ha. This action submitted no calculation."
        )

    def _use_upload(self, _=None):
        try:
            if len(self.upload.value) != 1:
                raise ValueError("Choose exactly one FCIDUMP file")
            item = self.upload.value[0]
            self.source.value = service.store_upload(item["content"], item["name"])
            self._message(
                "FCIDUMP imported. Review the active space and resources before submitting."
            )
        except (ValueError, OSError, UnicodeError) as exc:
            self._message(exc)

    def _refresh(self, _=None):
        try:
            self._invalidate()
            old = self.code.value
            options = service.codes()
            self.code.options = [("Select a Block2 0.5.4 code", None)] + options
            if old in [value for _, value in options]:
                self.code.value = old
            if self.reference_uuid:
                from . import energy_services

                rows = energy_services.models(self.reference_uuid, self.space)
                self.model.options = [("Select a completed export", None)] + [
                    (row["label"], row["uuid"]) for row in rows if row["finished_ok"]
                ]
            else:
                self.model.options = [
                    ("Use a stored UUID, upload or example below", None)
                ]
            self.saved.options = [
                ("Select a native DMRG result", None)
            ] + service.history()
            if not options:
                self._message(
                    "No verified Block2 0.5.4 code is configured. "
                    "Install and register the released runtime before native acceptance."
                )
        except (ValueError, OSError) as exc:
            self._message(exc)

    def _settings(self):
        return {
            "nroots": self.roots.value,
            "max_bond_dimension": self.bond.value,
            "threads": self.threads.value,
            "memory_gb": self.memory.value,
            "max_sweeps": self.sweeps.value,
            "ordering": self.ordering.value,
            "sweep_tolerance": 1e-9,
            "davidson_tolerance": 1e-10,
        }

    def _review(self, _=None):
        self._invalidate()
        try:
            if self.reference_uuid:
                from . import energy_services

                eligible = [
                    row["uuid"]
                    for row in energy_services.models(self.reference_uuid, self.space)
                    if row["finished_ok"]
                ]
                if self.source.value.strip() not in eligible:
                    raise ValueError(
                        "Select a completed Hamiltonian export for this confirmed reference and active space"
                    )
            self.plan = service.prepare(
                self.source.value.strip(),
                self.code.value,
                self._settings(),
                self.minutes.value * 60,
                parent_uuid=self.parent.value.strip() or None,
                continue_sweeps=self.continue_sweeps.value,
                maxsizeoutput=self.output_limit.value * 1024**2,
                recompute=self.recompute.value,
            )
            plan = self.plan
            params = plan["source"]["parameters"]
            self.review.value = (
                "<p><b>Reviewed native DMRG:</b> "
                f"CAS({params['NELEC']},{params['NORB']}), singlets, "
                f"{plan['settings']['nroots']} root(s), M={plan['settings']['max_bond_dimension']}. "
                f"One process with {plan['settings']['threads']} thread(s) on "
                f"{html.escape(plan['computer'])}. {plan['settings']['memory_gb']} GB native stack allocation, "
                f"{plan['seconds']} s wall time. Block2 also uses memory outside this stack allocation. The local scheduler does not enforce a hard total limit.</p>"
                f"<p>Hamiltonian SHA256: <code>{plan['source']['sha256']}</code>.</p>"
                "<p>MPS checkpoints and full output remain on the calculation computer. "
                "Sweep convergence and bond-dimension convergence are separate. "
                "A native job finishing alone does not establish either.</p>"
                f"<details><summary>Submitted Block2 input</summary><pre>{html.escape(plan['input'])}</pre></details>"
            )
            self.submit_button.disabled = False
            self.status.value = ""
        except (ValueError, OSError, KeyError) as exc:
            self.plan = None
            self._message(exc)

    def _submit(self, _=None):
        if self.plan is None:
            return
        plan, self.plan = self.plan, None
        self.submit_button.disabled = True
        try:
            outcome = service.submit(plan, self.label.value)
            self.process_uuid = outcome["uuid"]
            self.result_uuid.value = self.process_uuid
            self._message(
                (
                    "Reopened identical request: "
                    if outcome["reused"]
                    else "Submitted once: "
                )
                + self.process_uuid
            )
        except (ValueError, OSError, KeyError) as exc:
            self._message(exc)

    def _open_result(self, _=None):
        old, self.results.children = self.results.children, ()
        from .widget_lifecycle import close_widget_tree

        for widget in old:
            close_widget_tree(widget)
        try:
            data = service.result(self.result_uuid.value.strip())
            self.process_uuid = data["uuid"]
            title = ipw.HTML(
                f"<p><b>{html.escape(data['uuid'])}</b> · "
                f"{html.escape(data['state'])} · exit {data['exit_status']} · paused {data['paused']}</p>"
            )
            if not data["results"]:
                self.results.children = [
                    title,
                    ipw.HTML(
                        "<p>No validated native result is available yet. "
                        + html.escape(
                            data["exit_message"]
                            or "Refresh after the native job completes."
                        )
                        + "</p>"
                    ),
                ]
                return
            record = data["results"]
            rows = [
                (
                    i,
                    f"{energy:.12f}",
                    f"{record['excitation_energies_ev'][i]:.9f}",
                    f"{record['density_checks'][i]['trace']:.9f}",
                    ", ".join(f"{value:.9f}" for value in record["density_checks"][i]["natural_occupations"]),
                )
                for i, energy in enumerate(record["energies_hartree"])
            ]
            table = ipw.HTML(
                data_table(
                    [
                        "Root",
                        "Energy (Ha)",
                        "Excitation (eV)",
                        "1-RDM trace",
                        "Natural occupations",
                    ],
                    rows,
                    numeric_columns=(0, 1, 2, 3),
                    label="Native DMRG roots",
                )
            )
            note = ipw.HTML(
                f"<p>Hamiltonian UUID: {html.escape(data['source_uuid'])}. "
                f"SHA256: <code>{html.escape(record['hamiltonian_sha256'])}</code>. "
                f"M={data['settings']['max_bond_dimension']}, ordering "
                f"{html.escape(data['settings']['ordering'])}, "
                f"{data['settings']['threads']} numerical thread(s).</p>"
                f"<p><b>Sweep converged:</b> {record['sweep_converged']}. "
                f"<b>Bond-dimension convergence established:</b> "
                f"{record['bond_dimension_convergence_established']}. "
                "No full-CAS error bound is implied.</p>"
                f"<p>Checkpoint data UUID: {html.escape(data['checkpoint_uuid'] or 'unavailable')}. "
                "Keep its original directory and checksum manifest for restart.</p>"
            )
            energies = np.asarray(data["sweep_energies"])
            fig, ax = plt.subplots(figsize=(7, 3))
            for index in range(energies.shape[1]):
                ax.plot(
                    np.arange(1, len(energies) + 1),
                    energies[:, index],
                    label=f"Root {index}",
                )
            ax.set(xlabel="Completed sweep", ylabel="Energy (Ha)")
            ax.legend()
            fig.tight_layout()
            image = io.BytesIO()
            fig.savefig(image, format="svg")
            plt.close(fig)
            svg = base64.b64encode(image.getvalue()).decode()
            csv = (
                "sweep,"
                + ",".join(f"root_{i}_hartree" for i in range(energies.shape[1]))
                + "\n"
            )
            csv += (
                "\n".join(
                    str(i + 1) + "," + ",".join(f"{x:.14g}" for x in row)
                    for i, row in enumerate(energies)
                )
                + "\n"
            )
            encoded = base64.b64encode(csv.encode()).decode()
            plot = ipw.HTML(
                f'<img style="max-width:100%" src="data:image/svg+xml;base64,{svg}">'
                f'<p><a download="dmrg-sweeps.svg" href="data:image/svg+xml;base64,{svg}">Download sweep plot</a> · '
                f'<a download="dmrg-sweeps.csv" href="data:text/csv;base64,{encoded}">Download sweep energies</a></p>'
            )
            self.results.children = [title, table, note, plot]
        except (ValueError, OSError, KeyError) as exc:
            self.process_uuid = None
            self._message(exc)

    def _checkpoint(self, _=None):
        try:
            data = service.result(self.result_uuid.value.strip())
            if data["exit_status"] not in (0, 311) or not data["checkpoint_uuid"]:
                raise ValueError("Use a completed result with a validated checkpoint")
            self.source.value = data["source_uuid"]
            settings = data["settings"]
            for key, control in [
                ("nroots", self.roots),
                ("max_bond_dimension", self.bond),
                ("ordering", self.ordering),
                ("max_sweeps", self.sweeps),
                ("threads", self.threads),
                ("memory_gb", self.memory),
            ]:
                control.value = settings[key]
            self.parent.value = data["uuid"]
            self.continue_sweeps.value = False
            self._invalidate()
            self._message(
                "Checkpoint selected. Retain or increase M, or explicitly choose fixed-M continuation. "
                "Review before submitting a separate job."
            )
        except (ValueError, OSError, KeyError) as exc:
            self._message(exc)
