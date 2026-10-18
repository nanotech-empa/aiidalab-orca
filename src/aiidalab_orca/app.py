"""Geometry submission, search, and results using short-lived ORM services."""

import asyncio
import html

import ipywidgets as ipw

from .configuration import GeometrySettings
from . import services, structure_io
from .history import HistoryWidget, inspect_run
from .viewer import show_result


# Classic Notebook auto-scrolls tall outputs as widgets expand. Scope this to
# the app's containing output, including existing notebook copies; retain the
# normal scroll behavior of lists, text fields and other notebook outputs.
_APP_STYLE = """<style>
.output_scroll:has(.aiidalab-orca-app) {
    height: auto !important;
    max-height: none !important;
    overflow: visible !important;
    box-shadow: none !important;
}
</style>"""


class OrcaApp(ipw.VBox):
    def __init__(self):
        # The notebook loads its profile before constructing the app. Import
        # shared widgets only then, avoiding their automatic-profile fallback.
        from .structures import StructureWidget
        from .steps import GeometryStep
        from aiidalab_widgets_base import WizardAppWidget

        self._structure_confirmed = False
        self._settings_confirmed = False
        self._submitted = False
        self.review = None
        self.process_uuid = None
        self._poll_task = None
        style = {"description_width": "150px"}
        width = ipw.Layout(width="460px")
        self.structure = StructureWidget()
        self.optimize = ipw.Checkbox(value=True, description="Optimize geometry")
        self.mode_hint = ipw.HTML()
        self.science = GeometrySettings()
        # Keep familiar control names for the surrounding wizard and tests.
        for key in ("method", "basis", "charge", "multiplicity", "convergence", "max_steps", "max_scf"):
            setattr(self, key, getattr(self.science, key))
        self.nprocs = ipw.BoundedIntText(value=2, min=1, max=128, description="Processes", style=style, layout=width)
        self.memory = ipw.BoundedIntText(value=2048, min=256, max=1000000, description="Total memory (MB)", style=style, layout=width)
        self.wallclock = ipw.BoundedIntText(value=30, min=1, max=10080, description="Wall time (minutes)", style=style, layout=width)
        self.code = ipw.Dropdown(options=services.codes(), description="ORCA code", style=style, layout=width)
        self.force = ipw.Checkbox(value=False, description="Recompute even if a compatible result is available", layout=ipw.Layout(width="auto"))
        self.label = ipw.Text(value="Molecular calculation", description="Run label", style=style, layout=width)
        self.review_button = ipw.Button(description="Review calculation", button_style="primary", icon="list", disabled=True, layout=ipw.Layout(width="auto"))
        self.review_button.on_click(self._review)
        self.plan_html = ipw.HTML("Review the settings to see whether this step will run or reuse a result.")
        self.submit_button = ipw.Button(description="Submit", button_style="success", icon="play", disabled=True)
        self.submit_button.on_click(self._submit)
        self.status = ipw.HTML()
        self.error = ipw.HTML()
        self.result_box = ipw.VBox()
        refresh = ipw.Button(description="Refresh status", icon="refresh")
        refresh.on_click(lambda _: self._refresh())
        self.use_final = ipw.Button(description="Use final geometry", icon="cubes", disabled=True, layout=ipw.Layout(width="auto"))
        self.use_final.on_click(lambda _: self.use_geometry(self.process_uuid))
        self.copy = ipw.Button(description="Copy settings", icon="copy", disabled=True)
        self.copy.on_click(lambda _: self.copy_settings(self.process_uuid))
        self.science_message = ipw.HTML()
        self.resource_message = ipw.HTML()
        self.settings_summary = ipw.HTML()
        self.resource_hint = ipw.HTML()
        self.next_step = ipw.Button(description="Confirm structure", button_style="success", icon="check", disabled=True, layout=ipw.Layout(width="auto"))
        self.next_step.on_click(self._confirm_structure)
        self.confirm_settings = ipw.Button(description="Confirm settings", button_style="success", icon="check", disabled=True, layout=ipw.Layout(width="auto"))
        self.confirm_settings.on_click(self._confirm_settings)
        back_structure = ipw.Button(description="Back to structure", icon="arrow-left", layout=ipw.Layout(width="auto"))
        back_structure.on_click(lambda _: setattr(self.steps, "selected_index", 0))
        back_settings = ipw.Button(description="Back to settings", icon="arrow-left", layout=ipw.Layout(width="auto"))
        back_settings.on_click(lambda _: setattr(self.steps, "selected_index", 1))
        from .storage import WavefunctionStorage
        self.wavefunction_storage = WavefunctionStorage()
        storage_panel = ipw.Accordion(children=[self.wavefunction_storage], selected_index=0)
        storage_panel.set_title(0, "Wavefunction storage")
        self.resource_controls = ipw.VBox([self.code, self.nprocs, self.memory, self.wallclock, self.force, storage_panel])
        self.structure_step = GeometryStep([self.structure, self.next_step], "Select a molecule to begin.")
        self.settings_step = GeometryStep([
            self.settings_summary, self.optimize, self.mode_hint, self.science, self.science_message,
            ipw.HBox([back_structure, self.confirm_settings]),
        ], "Confirm the molecular structure in step 1 to configure this calculation.")
        self.resources_step = GeometryStep([
            self.label, self.resource_controls, self.resource_hint, self.resource_message,
            ipw.HBox([back_settings, self.review_button]), self.plan_html, self.submit_button,
        ], "Confirm the calculation settings in step 2 to review resources and submit.")
        self.steps = WizardAppWidget([
            ("Select structure", self.structure_step),
            ("Configure calculation", self.settings_step),
            ("Resources, review and submit", self.resources_step),
        ], show_header=False)
        edit_copy = ipw.Button(description="Edit a copy of these inputs", icon="copy", layout=ipw.Layout(width="auto"))
        edit_copy.on_click(self._edit_copy)
        self.submitted_notice = ipw.VBox([
            ipw.HTML("<p>These inputs have been submitted. Follow progress in <b>Results</b>, or edit a copy to prepare another calculation.</p>"), edit_copy,
        ])
        self.draft_panel = ipw.VBox([self.steps])
        self.history = HistoryWidget(self.load_run, self.use_geometry, self.copy_settings)
        self.pages = ipw.Tab(children=[self.draft_panel, self.history,
                                      ipw.VBox([ipw.HBox([refresh, self.use_final, self.copy]), self.status,
                                                self.result_box])])
        for i, title in enumerate(["New calculation", "Search calculations", "Results"]):
            self.pages.set_title(i, title)
        self.pages.observe(self._page_changed, names="selected_index")
        super().__init__([
            ipw.HTML(_APP_STYLE + "<div style='border-left:5px solid #237b98;padding:10px 20px;background:#f5f7fa'><h2 style='margin:0'>ORCA · Molecular analysis</h2><p>Geometry, orbitals, electronic states and vibrational spectroscopy with AiiDA provenance.</p></div>"),
            self.error, self.pages,
        ], layout=ipw.Layout(max_width="1100px"))
        self.add_class("aiidalab-orca-app")
        self.structure.observe(self._structure_changed, names="revision")
        self.optimize.observe(self._settings_changed, names="value")
        self.science.observe(self._settings_changed, names="revision")
        self.structure.constraints.observe(self._settings_changed, names="revision")
        for widget in [self.nprocs, self.memory, self.wallclock, self.code, self.force, self.label]:
            widget.observe(self._invalidate, names="value")
        self.wavefunction_storage.observe(self._invalidate, names="revision")
        self.optimize.observe(self._optimization_changed, names="value")
        self._update_steps()

    def _settings(self):
        values = self.science.values()
        if self.optimize.value:
            values["constraints"] = self.structure.constraints.values()
        values.update(nprocs=self.nprocs.value, memory_mb=self.memory.value,
                      wallclock_seconds=self.wallclock.value * 60)
        return values

    def _show_error(self, exc):
        self.error.value = f"<p style='color:#a02020'><b>{html.escape(str(exc))}</b></p>"

    def _invalidate(self, _=None):
        self.review = None
        self.submit_button.disabled = True
        self.plan_html.value = "<p>Review the calculation to see which data will be reused and which steps will run.</p>"
        self.error.value = ""
        self.resource_message.value = ""
        self._update_steps()

    def _structure_changed(self, _=None):
        self.science.set_molecule(self.structure.atoms)
        self._structure_confirmed = False
        self._settings_changed()

    def _settings_changed(self, _=None):
        self._settings_confirmed = False
        self.science_message.value = ""
        self._invalidate()

    def _update_steps(self):
        state = self.structure_step.State
        ready = self.structure.ready and self.structure.atoms is not None
        self.next_step.disabled = not ready or self._submitted
        self.confirm_settings.disabled = not self._structure_confirmed or self._submitted
        self.review_button.disabled = not self._settings_confirmed or self._submitted
        self.structure_step.update(state.SUCCESS if self._structure_confirmed else
                                   state.CONFIGURED if ready else state.READY, True)
        self.settings_step.update(state.SUCCESS if self._settings_confirmed else
                                  state.READY if self._structure_confirmed else state.INIT,
                                  self._structure_confirmed)
        self.resources_step.update(state.SUCCESS if self._submitted else
                                   state.CONFIGURED if self.review else
                                   state.READY if self._settings_confirmed else state.INIT,
                                   self._settings_confirmed)
        self.resource_hint.value = "<p>Local execution. ORCA uses 75% of the total memory budget divided by the process count. The local scheduler does not enforce a hard memory limit.</p>"
        self.mode_hint.value = ("<p>Optimize the atomic positions and compute the final electronic energy.</p>"
                                if self.optimize.value else
                                "<p><b>Single-point SCF:</b> compute the energy and wavefunction at the supplied coordinates. "
                                "Atoms remain fixed; geometry convergence, constraints and geom parameters are unused.</p>")
        if ready:
            atoms = self.structure.atoms
            self.settings_summary.value = f"<p><b>{html.escape(atoms.get_chemical_formula())}</b> · {len(atoms)} atoms. Review charge and spin multiplicity for this molecule.</p>"
            if self.optimize.value and self.structure.constraints.rows:
                self.settings_summary.value += ("<p><b>Geometry constraints (edit in Select structure):</b></p>"
                                                + self.structure.constraints.summary.value)

    def _confirm_structure(self, _=None):
        if self._submitted or not self.structure.ready or self.structure.atoms is None:
            return
        self._structure_confirmed = True
        self._update_steps()
        self.steps.selected_index = 1
        self.error.value = ""

    def _confirm_settings(self, _=None):
        if self._submitted or not self._structure_confirmed:
            return
        try:
            services.validate_configuration(self.structure.atoms, self._settings(), self.optimize.value)
        except ValueError as exc:
            self.science_message.value = f"<p style='color:#a02020'><b>{html.escape(str(exc))}</b></p>"
            return
        self._settings_confirmed = True
        self.science_message.value = ""
        self._update_steps()
        self.steps.selected_index = 2

    def _edit_copy(self, _=None):
        self._submitted = False
        self.draft_panel.children = [self.steps]
        self._structure_changed()
        self.pages.selected_index = 0
        self.steps.selected_index = 0

    def _optimization_changed(self, change):
        self.science.set_optimization_enabled(change["new"])

    def _page_changed(self, change):
        if change["new"] == 1:
            self.history.refresh()
        for view in self.result_box.children:
            if hasattr(view, 'set_active'):
                view.set_active(change['new'] == 2)

    def _review(self, _=None):
        if self._submitted:
            return
        self._invalidate()
        try:
            if self.structure.atoms is None:
                raise ValueError("Import a molecular structure or load an example before reviewing the calculation.")
            if not self.structure.ready:
                raise ValueError("Create and review the updated molecular model before submitting.")
            if not self._structure_confirmed or not self._settings_confirmed:
                raise ValueError("Confirm the structure and calculation settings before reviewing.")
            self.review = services.prepare(
                self.structure.xyz_text(), self.structure.source_uuid, self._settings(),
                self.code.value, self.optimize.value, self.force.value,
                atoms=self.structure.atoms, imported=self.structure.imported, storage=self.wavefunction_storage.values(self.code.value),
            )
            self.structure.mark_stored(self.review["structure_uuid"])
            plan = self.review["plan"]
            actions = ({"compute": "Run a new geometry optimization", "reuse": "Reuse a compatible stored optimization"}
                       if self.optimize.value else
                       {"compute": "Run a single-point SCF calculation", "reuse": "Reuse a compatible electronic state"})
            action = actions[plan["action"]]
            s = self.review["settings"]
            body = f"<h3>{action}</h3>"
            body += f"<p>{self.review['formula']} · charge {s['charge']} · multiplicity {s['multiplicity']}</p>"
            from .viewer import settings_details, input_details
            if self.review.get("storage"):
                policy = self.review["storage"]["policy"]
                body += (f"<p>Wavefunction preservation: retrieve bundles up to {policy['threshold_mb']:g} MiB; "
                         f"stash larger bundles under <code>{html.escape(policy['stash_directory'])}</code>.</p>")
            body += settings_details(s, single_point=not self.optimize.value)
            body += input_details(self.review["input_files"], "Review generated ORCA input")
            if plan["source_uuid"]:
                available = ("Stored coordinates and history are available; no wavefunction is required for this operation."
                             if self.optimize.value else "The electronic results and required orbital/density files are available.")
                body += f"<p>{available}</p><details><summary>Source workflow</summary><code>{plan['source_uuid']}</code></details>"
            if plan["unavailable"]:
                body += ("<p>A matching previous result lacks required data. This step must be recomputed with calculation caching bypassed.</p>"
                         if plan["action"] == "compute" else
                         "<p>Some matching results lack required data. The available source above will be reused.</p>")
                body += "<ul>" + "".join(f"<li>{html.escape(x['uuid'])}: {html.escape(x['reason'])}</li>" for x in plan["unavailable"]) + "</ul>"
            if self.force.value:
                body += "<p>Forced recomputation: manual reuse and calculation caching will be bypassed.</p>"
            body += f"<details><summary>Geometry provenance</summary><p>{html.escape(self.review['source_description'])}</p></details>"
            self.plan_html.value = body
            self.submit_button.disabled = False
            self._update_steps()
            self.steps.selected_index = 2
            self.error.value = ""
            self.resource_message.value = ""
        except Exception as exc:
            self.review = None
            self.submit_button.disabled = True
            self.resource_message.value = f"<p style='color:#a02020'><b>{html.escape(str(exc))}</b></p>"

    def _submit(self, _=None):
        if self.review is None:
            return
        self.submit_button.disabled = True
        try:
            self.process_uuid = services.submit_plan(self.review, self.label.value)
            self.review = None
            self._submitted = True
            self._update_steps()
            self.draft_panel.children = [self.submitted_notice]
            self.pages.selected_index = 2
            self.error.value = ""
            self.refresh_status()
            self._start_polling()
        except Exception as exc:
            self.submit_button.disabled = self.review is None
            self._show_error(exc)

    def load_run(self, uuid):
        try:
            inspect_run(uuid)
            self.process_uuid = uuid
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
        state = ("Converged" if data["optimized"] or data.get("single_point") else "Completed") if data["successful"] else data["state"].capitalize()
        identifier = (f"<details><summary>Workflow identifier</summary><code>{self.process_uuid}</code></details>"
                      if not data.get('scientific_success', data['successful']) else '')
        self.status.value = f"<h3>{html.escape(data['label'])}</h3><p><b>{state}</b></p>" + identifier
        self.copy.disabled = False
        self.use_final.disabled = "structure_uuid" not in data
        old = self.result_box.children
        for widget in old:
            if hasattr(widget, 'set_active'):
                widget.set_active(False)
        if data["finished"]:
            if data.get("scientific_success", data["successful"]):
                self.result_box.children = [show_result(data)]
                self.result_box.children[0].set_active(self.pages.selected_index == 2)
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
            if self._submitted:
                self._edit_copy()
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
            if self._submitted:
                self._edit_copy()
            s = data["settings"]
            self.science.set_values(s)
            self.structure.constraints.set_values(s.get("constraints", []))
            self.structure.constraints.require_confirmation("Settings copied. Check the constraint atom numbers and targets against the current geometry.")
            if s.get("constraints"):
                self.structure.constraint_panel.selected_index = 0
            self.nprocs.value = s["nprocs"]
            self.memory.value = s["memory_mb"]
            self.wallclock.value = (s["wallclock_seconds"]+59)//60
            self.optimize.value = data["optimize"]
            self.force.value = False
            self.code.value = data["code_uuid"] if data["code_uuid"] in dict(self.code.options).values() else None
            self.pages.selected_index = 0
            self.steps.selected_index = 1 if self._structure_confirmed and not s.get("constraints") else 0
            self._settings_changed()
            self.error.value = "<p>Settings copied. Review them against the molecule currently shown in Molecular structure.</p>"
            if self.code.value is None:
                self.error.value += "<p>The original code is unavailable. Select an ORCA code in Resources, review and submit.</p>"
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
    if getattr(widget, '_orca_tree_closed', False):
        return
    widget._orca_tree_closed = True
    if hasattr(widget, 'set_active'):
        widget.set_active(False)
    for child in getattr(widget, "children", ()):
        close_widget_tree(child)
    widget.close()
