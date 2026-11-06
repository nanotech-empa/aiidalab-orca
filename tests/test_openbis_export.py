"""ORCA hands a UUID to the common form and never invokes publication."""

from types import SimpleNamespace

import ipywidgets as ipw

from aiidalab_orca.openbis import OpenbisExport


def test_opening_export_passes_only_uuid_to_shared_interface(monkeypatch):
    calls = []
    form = ipw.VBox()
    api = SimpleNamespace(make_export_widget=lambda uid: calls.append(uid) or form)
    monkeypatch.setattr(OpenbisExport, "_api", lambda _: api)
    panel = OpenbisExport("reference-uuid")
    assert calls == ["reference-uuid"]
    assert panel.body.children == (form,)
    panel._load()
    assert calls == ["reference-uuid"]
    assert not hasattr(panel, "results")  # ORCA adds no calculation picker
    panel.close()


def test_connection_failure_is_safe_and_can_be_retried(monkeypatch):
    calls = []
    form = ipw.VBox()

    def make(uid):
        calls.append(uid)
        if len(calls) == 1:
            raise RuntimeError("private authenticated request")
        return form

    monkeypatch.setattr(
        OpenbisExport, "_api", lambda _: SimpleNamespace(make_export_widget=make)
    )
    panel = OpenbisExport("ref")
    assert "private" not in panel.status.value
    assert "ELN connection" in panel.status.value
    assert panel.retry.layout.display == ""
    panel._load()
    assert panel.body.children == (form,)
    assert panel.retry.layout.display == "none"
    assert calls == ["ref", "ref"]
    panel.close()
    panel.close()


def test_installed_app_bridge_does_not_require_package_install(monkeypatch, tmp_path):
    from pathlib import Path
    from aiidalab_orca import openbis

    bridge = tmp_path / "apps/aiidalab-openbis/aiida_openbis/export.py"
    bridge.parent.mkdir(parents=True)
    bridge.write_text(
        "import ipywidgets as ipw\ndef make_export_widget(uid):\n    form=ipw.VBox()\n    form.source_uuid=uid\n    return form\n"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def absent(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(openbis.importlib, "import_module", absent)
    panel = OpenbisExport("ref")
    assert panel._exporter.source_uuid == "ref"
    panel.close()
