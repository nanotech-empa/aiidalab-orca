"""Geometry submission, search, and results using short-lived ORM services."""

import asyncio
import html

import ipywidgets as ipw

from aiida_empa_orca.settings import BASES, METHODS
from . import services, structure_io
from .history import HistoryWidget, inspect_run
from .viewer import show_result


class OrcaApp(ipw.VBox):
    def __init__(self):
        # The notebook loads its profile before constructing the app. Import
        # shared widgets only then, avoiding their automatic-profile fallback.
        from .structures import StructureWidget

        self.review = None
        self.process_uuid = None
        self._poll_task = None
        style = {"description_width": "150px"}
        width = ipw.Layout(width="460px")
        self.structure = StructureWidget()
        self.optimize = ipw.Checkbox(value=True, description="Optimize geometry")
        self.method = ipw.Dropdown(options=[("M06-2X" if m == "M062X" else m, m) for m in METHODS], value="PBE", description="Method", style=style, layout=width)
        self.basis = ipw.Dropdown(options=BASES, value="def2-SVP", description="Basis", style=style, layout=width)
        self.charge = ipw.IntText(value=0, description="Charge", style=style, layout=width)
        self.multiplicity = ipw.BoundedIntText(value=2, min=1, max=100, description="Multiplicity (2S+1)", style=style, layout=width)
        self.ri = ipw.Checkbox(value=True, description="RI-J / RIJCOSX with def2/J")
        self.convergence = ipw.Dropdown(options=["NormalOpt", "TightOpt"], description="Geometry convergence", style=style, layout=width)
        self.nprocs = ipw.BoundedIntText(value=2, min=1, max=128, description="Processes", style=style, layout=width)
        self.memory = ipw.BoundedIntText(value=2048, min=256, max=1000000, description="Total memory (MB)", style=style, layout=width)
        self.max_steps = ipw.BoundedIntText(value=100, min=1, max=2000, description="Max geometry steps", style=style, layout=width)
        self.max_scf = ipw.BoundedIntText(value=200, min=1, max=2000, description="Max SCF steps", style=style, layout=width)
        self.wallclock = ipw.BoundedIntText(value=30, min=1, max=10080, description="Wall time (minutes)", style=style, layout=width)
        self.code = ipw.Dropdown(options=services.codes(), description="ORCA code", style=style, layout=width)
        self.force = ipw.Checkbox(value=False, description="Recompute even if a compatible result is available")
        self.label = ipw.Text(value="Molecular geometry", description="Run label", style=style, layout=width)
        self.review_button = ipw.Button(description="Review calculation", button_style="primary", icon="list", disabled=True)
        self.review_button.on_click(self._review)
        self.plan_html = ipw.HTML("Review the settings to see whether this step will run or reuse a result.")
        self.submit_button = ipw.Button(description="Submit", button_style="success", icon="play", disabled=True)
        self.submit_button.on_click(self._submit)
        self.status = ipw.HTML()
        self.error = ipw.HTML()
        self.result_box = ipw.VBox()
        refresh = ipw.Button(description="Refresh status", icon="refresh")
        refresh.on_click(lambda _: self._refresh())
        self.run_uuid = ipw.Text(placeholder="Geometry workflow UUID", layout=ipw.Layout(width="100%"))
        load = ipw.Button(description="Load run", icon="folder-open")
        load.on_click(lambda _: self.load_run(self.run_uuid.value.strip()))
        identifiers = ipw.Accordion(children=[ipw.VBox([self.run_uuid, load])], selected_index=None)
        identifiers.set_title(0, "Open a workflow by UUID")
        self.use_final = ipw.Button(description="Use final geometry", disabled=True)
        self.use_final.on_click(lambda _: self.use_geometry(self.process_uuid))
        self.copy = ipw.Button(description="Copy settings", disabled=True)
        self.copy.on_click(lambda _: self.copy_settings(self.process_uuid))
        advanced = ipw.Accordion(children=[ipw.VBox([
            self.ri, self.convergence, self.code, self.nprocs, self.memory,
            self.max_steps, self.max_scf, self.wallclock, self.force,
            ipw.HTML("<p>TightSCF, no dispersion correction. RI-J for PBE; RIJCOSX for HF/hybrids. MaxCore uses 75% of the memory budget divided by the process count. Local direct scheduling does not enforce a hard memory limit.</p>"),
        ])], selected_index=None)
        advanced.set_title(0, "Advanced settings and resources")
        self.next_step = ipw.Button(description="Continue to settings", button_style="primary", disabled=True)
        self.next_step.on_click(lambda _: setattr(self.steps, "selected_index", 1))
        settings_panel = ipw.VBox([self.optimize, self.method, self.basis, self.charge,
                                   self.multiplicity, self.label, advanced, self.review_button])
        self.steps = ipw.Accordion(children=[ipw.VBox([self.structure, self.next_step]), settings_panel,
                                            ipw.VBox([self.plan_html, self.submit_button])], selected_index=0)
        for i, title in enumerate(["1 · Molecular structure", "2 · Calculation settings", "3 · Review and submit"]):
            self.steps.set_title(i, title)
        self.history = HistoryWidget(self.load_run, self.use_geometry, self.copy_settings)
        self.pages = ipw.Tab(children=[self.steps, self.history,
                                      ipw.VBox([ipw.HBox([refresh, self.use_final, self.copy]), self.status,
                                                self.result_box, identifiers])])
        for i, title in enumerate(["New calculation", "Search calculations", "Results"]):
            self.pages.set_title(i, title)
        self.pages.observe(self._page_changed, names="selected_index")
        super().__init__([
            ipw.HTML("<div style='border-left:5px solid #237b98;padding:10px 20px;background:#f5f7fa'><h2 style='margin:0'>ORCA · Molecular geometry</h2><p>Prepare, optimize, and reuse molecular structures with AiiDA provenance.</p></div>"),
            self.error, self.pages,
        ], layout=ipw.Layout(max_width="1100px"))
        self.structure.observe(self._invalidate, names="revision")
        for widget in [self.optimize, self.method, self.basis, self.charge, self.multiplicity,
                       self.ri, self.convergence, self.nprocs, self.memory, self.max_steps,
                       self.max_scf, self.wallclock, self.code, self.force]:
            widget.observe(self._invalidate, names="value")
        self.optimize.observe(self._optimization_changed, names="value")

    def _settings(self):
        return {"method": self.method.value, "basis": self.basis.value, "charge": self.charge.value,
                "multiplicity": self.multiplicity.value, "ri": self.ri.value,
                "optimization": self.convergence.value, "nprocs": self.nprocs.value,
                "memory_mb": self.memory.value, "max_geometry_steps": self.max_steps.value,
                "max_scf_steps": self.max_scf.value, "wallclock_seconds": self.wallclock.value * 60}

    def _show_error(self, exc):
        self.error.value = f"<p style='color:#a02020'><b>{html.escape(str(exc))}</b></p>"

    def _invalidate(self, _):
        self.review = None
        self.next_step.disabled = self.review_button.disabled = not self.structure.ready
        self.submit_button.disabled = True
        self.plan_html.value = "Inputs changed. Review the calculation again before submitting."

    def _optimization_changed(self, change):
        for widget in [self.method, self.basis, self.ri, self.convergence, self.code, self.nprocs,
                       self.memory, self.max_steps, self.max_scf, self.wallclock, self.force]:
            widget.disabled = not change["new"]

    def _page_changed(self, change):
        if change["new"] == 1:
            self.history.refresh()

    def _review(self, _=None):
        try:
            if self.structure.atoms is None:
                raise ValueError("Import a molecular structure or load an example before reviewing the calculation.")
            if not self.structure.ready:
                raise ValueError("Create and review the updated molecular model before submitting.")
            self.review = services.prepare(
                self.structure.xyz_text(), self.structure.source_uuid, self._settings(),
                self.code.value, self.optimize.value, self.force.value,
                atoms=self.structure.atoms, imported=self.structure.imported,
            )
            self.structure.mark_stored(self.review["structure_uuid"])
            plan = self.review["plan"]
            action = {"compute": "Run a new geometry optimization", "reuse": "Reuse a compatible stored optimization", "keep": "Keep the supplied geometry"}[plan["action"]]
            s = self.review["settings"]
            body = f"<h3>{action}</h3><p>{html.escape(self.review['source_description'])}</p>"
            body += f"<p>{self.review['formula']} · charge {s['charge']} · multiplicity {s['multiplicity']}</p>"
            if self.optimize.value:
                body += f"<p>{s['method']}/{s['basis']}</p>"
            if plan["source_uuid"]:
                body += f"<p>Stored coordinates and history are available; no wavefunction is required for this operation.</p><details><summary>Source workflow</summary><code>{plan['source_uuid']}</code></details>"
            if plan["unavailable"]:
                body += "<p>A matching previous result lacks required data. This step must be recomputed with calculation caching bypassed.</p>"
                body += "<ul>" + "".join(f"<li>{html.escape(x['uuid'])}: {html.escape(x['reason'])}</li>" for x in plan["unavailable"]) + "</ul>"
            if self.force.value and self.optimize.value:
                body += "<p>Forced recomputation: manual reuse and calculation caching will be bypassed.</p>"
            self.plan_html.value = body
            self.submit_button.disabled = False
            self.steps.selected_index = 2
            self.error.value = ""
        except Exception as exc:
            self.review = None
            self.submit_button.disabled = True
            self._show_error(exc)

    def _submit(self, _=None):
        if self.review is None:
            return
        self.submit_button.disabled = True
        try:
            self.process_uuid = services.submit_plan(self.review, self.label.value)
            self.review = None
            self.pages.selected_index = 2
            self.run_uuid.value = self.process_uuid
            self.error.value = ""
            self.refresh_status()
            self._start_polling()
        except Exception as exc:
            self._show_error(exc)

    def load_run(self, uuid):
        try:
            inspect_run(uuid)
            self.process_uuid = uuid
            self.run_uuid.value = uuid
            self.pages.selected_index = 2
            self.refresh_status()
            self._start_polling()
            self.error.value = ""
        except Exception as exc:
            self._show_error(exc)

    def _refresh(self):
        try:
            self.refresh_status()
        except Exception as exc:
            self._show_error(exc)

    def refresh_status(self):
        if not self.process_uuid:
            return False
        data = services.result(self.process_uuid)
        state = "Converged" if data["successful"] and data["optimized"] else data["state"].capitalize()
        self.status.value = f"<h3>{html.escape(data['label'])}</h3><p><b>{state}</b></p>"
        self.copy.disabled = False
        self.use_final.disabled = "structure_uuid" not in data
        old = self.result_box.children
        if data["finished"]:
            if data["successful"]:
                self.result_box.children = [show_result(data)]
            else:
                message = data["exit_message"] or "Workflow did not finish successfully"
                details = "\n".join(data["reports"]) + "\n" + data.get("output_tail", "")
                self.result_box.children = [ipw.HTML(f"<p style='color:#a02020'>{html.escape(message)}</p><details><summary>Calculation diagnostics</summary><pre style='max-height:350px;overflow:auto'>{html.escape(details)}</pre></details>")]
        else:
            self.result_box.children = [ipw.HTML("<p>The daemon is processing this run. You can close the notebook and return later.</p>")]
        for widget in old:
            close_widget_tree(widget)
        return data["finished"]

    def _start_polling(self):
        if self._poll_task:
            self._poll_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._poll_task = loop.create_task(self._poll())

    async def _poll(self):
        while self.process_uuid:
            try:
                if self.refresh_status():
                    return
            except Exception as exc:
                self._show_error(exc)
                return
            await asyncio.sleep(5)

    def use_geometry(self, uuid):
        try:
            data = inspect_run(uuid)
            if not data["structure_uuid"]:
                raise ValueError(data["geometry_status"])
            atoms = structure_io.load_structure(data["structure_uuid"])
            # Reveal the structure step before mounting a first-use NGL view.
            self.pages.selected_index = 0
            self.steps.selected_index = 0
            self.structure.set_atoms(atoms, source_uuid=data["structure_uuid"])
            self.optimize.value = False
            self.error.value = "<p>Geometry loaded. Review charge and multiplicity in Calculation settings.</p>"
        except Exception as exc:
            self._show_error(exc)

    def copy_settings(self, uuid):
        try:
            data = inspect_run(uuid)
            s = data["settings"]
            mapping = {"method": self.method, "basis": self.basis, "charge": self.charge,
                       "multiplicity": self.multiplicity, "ri": self.ri, "optimization": self.convergence,
                       "nprocs": self.nprocs, "memory_mb": self.memory, "max_geometry_steps": self.max_steps,
                       "max_scf_steps": self.max_scf}
            for key, widget in mapping.items():
                widget.value = s[key]
            self.wallclock.value = (s["wallclock_seconds"]+59)//60
            self.optimize.value = data["optimize"]
            self.force.value = False
            self.code.value = data["code_uuid"] if data["code_uuid"] in dict(self.code.options).values() else None
            self.pages.selected_index = 0
            self.steps.selected_index = 1
            self._invalidate(None)
            self.error.value = "<p>Settings copied. Review them against the molecule currently shown in Molecular structure.</p>"
            if data["optimize"] and self.code.value is None:
                self.error.value += "<p>The original code is unavailable. Select an ORCA code in Advanced settings.</p>"
        except Exception as exc:
            self._show_error(exc)

    def close(self):
        if getattr(self, "_poll_task", None):
            self._poll_task.cancel()
        if hasattr(self, "structure"):
            self.structure.close()
        super().close()


def close_widget_tree(widget):
    """Dispose owned result widgets when replacing a result view."""
    for child in getattr(widget, "children", ()):
        close_widget_tree(child)
    widget.close()
