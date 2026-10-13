"""Stepwise geometry app. Widget state contains identifiers and plain data only."""

import asyncio
import html

import ipywidgets as ipw

from aiida_empa_orca.settings import BASES, METHODS
from . import services
from .viewer import molecule, show_result


class OrcaApp(ipw.VBox):
    def __init__(self):
        self.review = None
        self.process_uuid = None
        self._poll_task = None
        style = {"description_width": "150px"}
        width = ipw.Layout(width="460px")
        self.xyz = ipw.Textarea(value=services.NO_XYZ, description="XYZ geometry", style=style,
                                layout=ipw.Layout(width="100%", height="160px"))
        self.structure_uuid = ipw.Text(description="AiiDA structure UUID", placeholder="Optional: reuse an existing structure", style=style, layout=width)
        self.upload = ipw.FileUpload(accept=".xyz", multiple=False, description="Upload XYZ")
        self.upload.observe(self._upload, names="value")
        self.preview = ipw.VBox()
        preview_button = ipw.Button(description="Preview geometry", icon="eye")
        preview_button.on_click(self._preview)
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
        self.label = ipw.Text(value="NO doublet geometry", description="Run label", style=style, layout=width)
        self.review_button = ipw.Button(description="Review calculation", button_style="primary", icon="list")
        self.review_button.on_click(self._review)
        self.plan_html = ipw.HTML("Review the settings to see whether this step will run or reuse a result.")
        self.submit_button = ipw.Button(description="Submit", button_style="success", icon="play", disabled=True)
        self.submit_button.on_click(self._submit)
        self.status = ipw.HTML()
        self.error = ipw.HTML()
        self.result_box = ipw.VBox()
        self.runs = ipw.Dropdown(options=[("Select a previous run", "")] + services.recent_runs(),
                                 layout=ipw.Layout(width="100%"))
        self.runs.observe(self._select_run, names="value")
        refresh = ipw.Button(description="Refresh runs / status", icon="refresh", layout=ipw.Layout(width="200px"))
        refresh.on_click(self._refresh)
        self.run_uuid = ipw.Text(placeholder="Or enter a geometry workflow UUID", layout=ipw.Layout(width="100%"))
        load = ipw.Button(description="Load run", icon="folder-open")
        load.on_click(lambda _: self.load_run(self.run_uuid.value.strip()))
        self.use_final = ipw.Button(description="Use final geometry as input", disabled=True, layout=ipw.Layout(width="240px"))
        self.use_final.on_click(self._use_final)
        structure_panel = ipw.VBox([ipw.HTML("<p>Upload or paste one XYZ, or select an existing AiiDA structure by UUID. The example is neutral NO, a doublet.</p>"), self.upload, self.xyz, self.structure_uuid, preview_button, self.preview])
        settings_panel = ipw.VBox([self.optimize, self.method, self.basis, self.charge, self.multiplicity,
                                   self.ri, self.convergence, self.code, self.nprocs, self.memory,
                                   self.max_steps, self.max_scf, self.wallclock, self.force, self.label,
                                   ipw.HTML("<p>Optimization defaults: TightSCF, no dispersion correction. RI-J is used for PBE and RIJCOSX for HF/hybrids. MaxCore uses 75% of the memory budget divided by the process count. Local direct scheduling does not enforce a hard memory limit.</p>"),
                                   self.review_button])
        self.steps = ipw.Accordion(children=[structure_panel, settings_panel,
                                            ipw.VBox([self.plan_html, self.submit_button]),
                                            ipw.VBox([self.runs, ipw.HBox([refresh, load]), self.run_uuid, self.status, self.result_box, self.use_final])], selected_index=0)
        for index, title in enumerate(["1 · Molecular structure", "2 · Calculation settings", "3 · Review and submit", "4 · Results"]):
            self.steps.set_title(index, title)
        super().__init__([ipw.HTML("<div style='border-left:5px solid #237b98;padding:10px 20px;background:#f5f7fa'><h2 style='margin:0'>ORCA · Molecular geometry</h2><p>Prepare, optimize, and reuse molecular structures with AiiDA provenance.</p></div>"), self.error, self.steps], layout=ipw.Layout(max_width="1100px"))
        for widget in [self.xyz, self.structure_uuid, self.optimize, self.method, self.basis, self.charge,
                       self.multiplicity, self.ri, self.convergence, self.nprocs, self.memory,
                       self.max_steps, self.max_scf, self.wallclock, self.code, self.force]:
            widget.observe(self._invalidate, names="value")

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
        self.submit_button.disabled = True
        self.plan_html.value = "Settings changed. Review the calculation again before submitting."

    def _upload(self, change):
        try:
            if change["new"]:
                self.xyz.value = bytes(change["new"][0]["content"]).decode("utf8")
                self.structure_uuid.value = ""
                self._preview()
        except (ValueError, UnicodeError) as exc:
            self._show_error(exc)

    def _preview(self, _=None):
        try:
            if self.structure_uuid.value.strip():
                from aiida import orm
                node = orm.load_node(self.structure_uuid.value.strip())
                if not isinstance(node, orm.StructureData):
                    raise ValueError("Select a StructureData UUID")
                atoms = node.get_ase()
            else:
                atoms = services.parse_xyz(self.xyz.value)
            self.preview.children = [molecule(atoms.get_chemical_symbols(), [atoms.positions.tolist()])]
            self.error.value = ""
        except Exception as exc:
            self._show_error(exc)

    def _review(self, _=None):
        try:
            self.review = services.prepare(self.xyz.value, self.structure_uuid.value, self._settings(),
                                           self.code.value, self.optimize.value, self.force.value)
            plan = self.review["plan"]
            action = {"compute": "Run a new geometry optimization", "reuse": "Reuse a compatible stored optimization", "keep": "Keep the supplied geometry"}[plan["action"]]
            s = self.review["settings"]
            body = f"<h3>{action}</h3><p>{html.escape(self.review['source_description'])}</p>"
            if self.optimize.value:
                body += f"<p>{self.review['formula']} · {s['method']}/{s['basis']} · charge {s['charge']} · multiplicity {s['multiplicity']}</p>"
            if plan["source_uuid"]:
                body += f"<p>Source workflow: <code>{plan['source_uuid']}</code>. Stored coordinates and history are available; no wavefunction is required for this operation.</p>"
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
            self.steps.selected_index = 3
            self.run_uuid.value = self.process_uuid
            self.error.value = ""
            self.refresh_status()
            self._start_polling()
        except Exception as exc:
            self._show_error(exc)
            self.submit_button.disabled = False

    def load_run(self, uuid):
        try:
            services.result(uuid)  # Validate before changing the selected run.
            self.process_uuid = uuid
            self.run_uuid.value = uuid
            self.steps.selected_index = 3
            self.refresh_status()
            self._start_polling()
            self.error.value = ""
        except Exception as exc:
            self._show_error(exc)

    def _select_run(self, change):
        if change["new"]:
            self.load_run(change["new"])

    def _refresh(self, _=None):
        selected = self.runs.value
        options = [("Select a previous run", "")] + services.recent_runs()
        self.runs.options = options
        if selected in dict(options).values():
            self.runs.value = selected
        self.refresh_status()

    def refresh_status(self):
        if not self.process_uuid:
            return False
        data = services.result(self.process_uuid)
        state = "Converged" if data["successful"] and data["optimized"] else data["state"].capitalize()
        self.status.value = f"<p><b>{state}</b> · <code>{self.process_uuid}</code></p>"
        if data["finished"]:
            if data["successful"]:
                self.result_box.children = [show_result(data)]
                self.use_final.disabled = False
            else:
                message = data["exit_message"] or "Workflow did not finish successfully"
                details = "\n".join(data["reports"]) + "\n" + data.get("output_tail", "")
                self.result_box.children = [ipw.HTML(f"<p style='color:#a02020'>{html.escape(message)}</p><pre style='max-height:350px;overflow:auto'>{html.escape(details)}</pre>")]
                self.use_final.disabled = True
        else:
            self.result_box.children = [ipw.HTML("<p>The daemon is processing this run. You can close the notebook and return later.</p>")]
            self.use_final.disabled = True
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

    def _use_final(self, _=None):
        data = services.result(self.process_uuid)
        self.structure_uuid.value = data["structure_uuid"]
        self.optimize.value = False
        self.steps.selected_index = 0
        self._preview()

    def close(self):
        if self._poll_task:
            self._poll_task.cancel()
        super().close()
