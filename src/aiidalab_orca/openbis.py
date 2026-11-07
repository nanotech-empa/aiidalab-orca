"""Hand the entry workflow UUID to the shared openBIS exporter."""

import importlib
import importlib.util
from pathlib import Path

import ipywidgets as ipw

_STYLE = """<style>
.output_scroll:has(.orca-openbis-export) {
    height: auto !important; max-height: none !important;
    overflow: visible !important; box-shadow: none !important;
}
</style>"""


class OpenbisExport(ipw.VBox):
    """Host the common export form; all selection and review live there."""

    def __init__(self, source_uuid):
        self.source_uuid = str(source_uuid)
        self._exporter = None
        self.status = ipw.HTML()
        self.body = ipw.VBox()
        self.retry = ipw.Button(
            description="Retry openBIS connection",
            icon="refresh",
            layout=ipw.Layout(width="auto", display="none"),
        )
        self.retry.on_click(self._load)
        super().__init__(
            [
                ipw.HTML(_STYLE + "<h3>Export to openBIS</h3>"),
                self.status,
                self.retry,
                self.body,
            ]
        )
        self.add_class("orca-openbis-export")
        self._load()

    def _api(self):
        try:
            return importlib.import_module("aiida_openbis.export")
        except ImportError as exc:
            bridge = Path.home() / "apps/aiidalab-openbis/aiida_openbis/export.py"
            if bridge.is_file():
                spec = importlib.util.spec_from_file_location(
                    "_orca_openbis_bridge", bridge
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
            raise ValueError(
                "The ORCA-capable shared openBIS exporter is not installed. "
                "Install the matching aiidalab-openbis component before exporting."
            ) from exc

    def _load(self, _=None):
        if self._exporter is not None:
            return
        self.retry.layout.display = "none"
        try:
            self._exporter = self._api().make_export_widget(self.source_uuid)
            self.body.children = [self._exporter]
            self.status.value = ""
        except Exception:
            # pyBIS exceptions can contain authenticated requests.
            self.status.value = (
                "<p>Could not open the shared openBIS exporter. "
                "Check the openBIS app and ELN connection, then retry.</p>"
            )
            self.retry.layout.display = ""

    def close(self):
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self.retry.on_click(self._load, remove=True)
        if self._exporter is not None:
            self._exporter.close()
        self._exporter = None
        super().close()
