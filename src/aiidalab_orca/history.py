"""Calculation search and operation-specific availability, with plain row data."""

import html
from zoneinfo import ZoneInfo

import ipywidgets as ipw
from aiida import orm

from aiida_empa_orca.reuse import PROCESS_TYPE, validate_outputs
from aiida_empa_orca.settings import METHODS
from .structure_io import formula_from_attributes


def search_runs(text="", state="", method="", since=None, until=None, offset=0, limit=15):
    filters = {"process_type": PROCESS_TYPE}
    query = orm.QueryBuilder().append(
        orm.WorkChainNode, filters=filters, tag="run",
        project=["uuid", "label", "ctime", "attributes.process_state", "attributes.exit_status"],
    ).append(orm.StructureData, with_outgoing="run", edge_filters={"label": "structure"},
             project=["attributes"], tag="structure").append(
        orm.Dict, with_outgoing="run", edge_filters={"label": "settings"}, project=["attributes"],
    ).append(orm.Bool, with_outgoing="run", edge_filters={"label": "optimize"}, project=["attributes.value"])
    query.order_by({"run": {"ctime": "desc", "id": "desc"}})
    rows = []
    skipped = 0
    for uuid, label, created, process_state, exit_status, structure, settings, optimized in query.iterall(batch_size=100):
        status = ("succeeded" if exit_status == 0 else "failed") if process_state == "finished" else process_state
        date = created.astimezone(ZoneInfo("Europe/Zurich")).date()
        formula = formula_from_attributes(structure)
        if ((state and state != status) or (method and (not optimized or method != settings["method"]))
                or (since and date < since) or (until and date > until)
                or text.casefold() not in f"{uuid} {label} {formula}".casefold()):
            continue
        if skipped < offset:
            skipped += 1
            continue
        rows.append({"uuid": str(uuid), "label": label, "formula": formula, "state": status,
                     "created": created.astimezone(ZoneInfo("Europe/Zurich")).strftime("%Y-%m-%d %H:%M"),
                     "method": settings["method"], "basis": settings["basis"],
                     "charge": settings["charge"], "multiplicity": settings["multiplicity"], "optimized": optimized})
        if len(rows) > limit:
            break
    return {"rows": rows[:limit], "has_more": len(rows) > limit}


def inspect_run(uuid):
    node = orm.load_node(uuid)
    if not isinstance(node, orm.WorkChainNode) or node.process_type != PROCESS_TYPE:
        raise ValueError("Select an ORCA geometry workflow.")
    data = {"uuid": str(node.uuid), "label": node.label, "settings": node.inputs.settings.get_dict(),
            "input_uuid": str(node.inputs.structure.uuid), "optimize": node.inputs.optimize.value,
            "code_uuid": str(node.inputs.code.uuid) if "code" in node.inputs else None,
            "structure_uuid": None, "geometry_status": "No final geometry yet.",
            "reuse_status": "This run has no completed optimization to reuse."}
    if "structure" in node.outputs:
        try:
            node.outputs.structure.get_ase()
            data["structure_uuid"] = str(node.outputs.structure.uuid)
            data["geometry_status"] = "Final geometry is available."
        except (KeyError, ValueError, OSError) as exc:
            data["geometry_status"] = f"Final geometry cannot be read: {exc}"
    if node.is_finished_ok and data["optimize"]:
        try:
            validate_outputs(node.outputs)
            data["reuse_status"] = "Optimization data are available. Compatibility is checked when you review a new calculation."
        except (KeyError, ValueError, FileNotFoundError) as exc:
            data["reuse_status"] = f"Required optimization data are missing or invalid; this step needs recomputation: {exc}"
        except OSError as exc:
            data["reuse_status"] = f"Availability could not be checked; retry when storage is reachable: {exc}"
    return data


class HistoryWidget(ipw.VBox):
    def __init__(self, view_run, use_geometry, copy_settings):
        self.offset = 0
        self.page_size = 15
        self._view_run = view_run
        self._use_geometry = use_geometry
        self._copy_settings = copy_settings
        self.query = ipw.Text(placeholder="Formula, label, or UUID", layout=ipw.Layout(width="340px"))
        self.state = ipw.Dropdown(options=[("All states", "")] + [(s.capitalize(), s) for s in ["succeeded", "failed", "running", "waiting", "created", "excepted", "killed"]])
        self.method = ipw.Combobox(options=METHODS, placeholder="All methods", ensure_option=False)
        self.since = ipw.DatePicker(description="From")
        self.until = ipw.DatePicker(description="To")
        self.search = ipw.Button(description="Search", icon="search", button_style="primary")
        self.search.on_click(self._search)
        self.rows = ipw.VBox()
        self.message = ipw.HTML()
        self.previous = ipw.Button(description="Previous", disabled=True)
        self.next = ipw.Button(description="Next", disabled=True)
        self.previous.on_click(lambda _: self.refresh(max(0, self.offset-self.page_size)))
        self.next.on_click(lambda _: self.refresh(self.offset+self.page_size))
        self.detail = ipw.HTML()
        self.selected_uuid = None
        self.view = ipw.Button(description="View results", icon="line-chart", disabled=True)
        self.geometry = ipw.Button(description="Use final geometry", icon="cubes", disabled=True, layout=ipw.Layout(width="auto"))
        self.copy = ipw.Button(description="Copy settings", icon="copy", disabled=True)
        self.view.on_click(lambda _: self._view_run(self.selected_uuid))
        self.geometry.on_click(lambda _: self._use_geometry(self.selected_uuid))
        self.copy.on_click(lambda _: self._copy_settings(self.selected_uuid))
        self.lookup_uuid = ipw.Text(placeholder="Geometry workflow UUID", layout=ipw.Layout(width="100%"))
        load = ipw.Button(description="Load run", icon="folder-open", disabled=True)
        load.on_click(lambda _: self._view_run(self.lookup_uuid.value.strip()))
        self.lookup_uuid.observe(lambda change: setattr(load, "disabled", not change["new"].strip()), names="value")
        self.advanced = ipw.Accordion(children=[ipw.VBox([
            ipw.HTML("<p>Open a geometry workflow from this AiiDA database using its UUID.</p>"),
            self.lookup_uuid, load,
        ])], selected_index=None)
        self.advanced.set_title(0, "Advanced search · open by UUID")
        super().__init__([
            ipw.HTML("<h3>Search calculations</h3><p>Find a run, inspect its available data, then choose how to continue.</p>"),
            ipw.HBox([self.query, self.state, self.method, self.search]), ipw.HBox([self.since, self.until]),
            self.message, self.detail, ipw.HBox([self.view, self.geometry, self.copy]),
            self.rows, ipw.HBox([self.previous, self.next]), self.advanced,
        ])

    def _search(self, _=None):
        self.refresh(0)

    def refresh(self, offset=None):
        if offset is not None:
            self.offset = offset
        self.selected_uuid = None
        self.view.disabled = self.geometry.disabled = self.copy.disabled = True
        self.detail.value = ""
        try:
            if self.since.value and self.until.value and self.since.value > self.until.value:
                raise ValueError("The start date must be before the end date.")
            page = search_runs(self.query.value.strip(), self.state.value, self.method.value,
                               self.since.value, self.until.value, self.offset, self.page_size)
            widgets = []
            for row in page["rows"]:
                button = ipw.Button(description="Select", layout=ipw.Layout(width="75px"))
                button.on_click(lambda _, uuid=row["uuid"]: self.select(uuid))
                title = html.escape(row["label"] or "Geometry")
                operation = f"{row['method']}/{row['basis']} optimization" if row["optimized"] else "Kept supplied geometry"
                info = (f"<b>{title}</b> · {row['formula']} · {row['state']}<br>"
                        f"{row['created']} · {operation} · "
                        f"charge {row['charge']}, multiplicity {row['multiplicity']} · {row['uuid'][:8]}")
                widgets.append(ipw.HBox([button, ipw.HTML(info)], layout=ipw.Layout(border_bottom="1px solid #ddd", padding="5px")))
            old_rows = self.rows.children
            self.rows.children = widgets
            for row in old_rows:
                for child in row.children:
                    child.close()
                row.close()
            self.previous.disabled = self.offset == 0
            self.next.disabled = not page["has_more"]
            self.message.value = (f"<p>Showing {self.offset+1}–{self.offset+len(widgets)} · dates in Europe/Zurich</p>" if widgets else "<p>No matching calculations.</p>")
        except Exception as exc:
            self.message.value = f"<p>{html.escape(str(exc))}</p>"

    def select(self, uuid):
        try:
            data = inspect_run(uuid)
            self.selected_uuid = uuid
            self.detail.value = f"<p><b>{html.escape(data['label'] or 'Geometry')}</b><br>{html.escape(data['geometry_status'])}<br>{html.escape(data['reuse_status'])}</p><details><summary>Workflow identifier</summary><code>{uuid}</code></details>"
            self.view.disabled = self.copy.disabled = False
            self.geometry.disabled = not bool(data["structure_uuid"])
        except Exception as exc:
            self.detail.value = html.escape(str(exc))
            self.selected_uuid = None
            self.view.disabled = self.geometry.disabled = self.copy.disabled = True
