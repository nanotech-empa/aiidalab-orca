"""Reviewed PDOS budgets reach both automatic and explicit analysis requests."""

from types import SimpleNamespace

from test_reuse import source  # noqa: F401
from test_pdos_widget import widget


def test_pdos_review_builder_and_edit_invalidation(source, monkeypatch):
    from aiida_empa_orca import pdos_workflow
    from aiidalab_orca import services
    from aiidalab_orca.app import OrcaApp

    code = str(source.inputs.code.uuid)
    monkeypatch.setattr(services, 'codes', lambda: [('Test ORCA', code)])
    monkeypatch.setattr(pdos_workflow, 'available_codes', lambda _: {
        'export': [('Test export', code)], 'character': [('Test character', code)]})
    app = OrcaApp()
    try:
        app.structure.example.click()
        app._confirm_structure()
        app.optimize.value = False
        app._confirm_settings()
        app.force.value = True
        app.wallclock.value = 10
        app.pdos_memory.value = 2
        assert app.pdos_wallclock.min == 1
        app.pdos_wallclock.value = 10
        app._review()
        assert app.review is not None, app.resource_message.value
        assert app.review['settings']['wallclock_seconds'] == 600
        assert app.review['pdos']['wallclock_seconds'] == 600
        assert '2 GiB, up to 10 minutes' in app.plan_html.value
        builder = services.reviewed_builder(app.review, 'PDOS time review')
        assert builder.character_wallclock_seconds.value == 600
        assert builder.settings['wallclock_seconds'] == 600
        app.pdos_wallclock.value = 11
        assert app.review is None and app.submit_button.disabled
        app._review()
        assert 'up to 11 minutes' in app.plan_html.value
        assert services.reviewed_builder(app.review, 'Updated PDOS time').character_wallclock_seconds.value == 660
    finally:
        app.close()


def test_manual_pdos_control_and_submission_forward_walltime(monkeypatch):
    from aiidalab_orca import pdos_services
    original_submit = pdos_services.submit
    panel = widget(monkeypatch)
    observed = []

    def capture(*args, **kwargs):
        observed.append((args, kwargs))
        raise ValueError('Stop before creating any job')

    monkeypatch.setattr(pdos_services, 'submit', capture)
    try:
        panel.force.value = True
        panel.memory.value = 2
        panel.wallclock.value = 10
        panel._compute(None)
        assert observed[0][1]['wallclock_seconds'] == 600
        assert observed[0][0][-1] == 2
        assert panel.wallclock.min == 1
    finally:
        panel.close()

    called = []
    monkeypatch.setattr(pdos_services, 'submit', original_submit)
    monkeypatch.setattr(pdos_services, 'builder', lambda *args, **kwargs: called.append(kwargs) or 'builder')
    monkeypatch.setattr(pdos_services.engine, 'submit', lambda _: SimpleNamespace(uuid='test-job'))
    assert pdos_services.submit('source', 'SCF', 'export', 'helper', force=True,
                                memory_gib=2, wallclock_seconds=600) == 'test-job'
    assert called == [{'wallclock_seconds': 600}]
