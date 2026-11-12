"""Saved optical failures retain family identity through the real selector path."""

from types import SimpleNamespace

import pytest
from aiida import orm
from aiida.common.links import LinkType

from aiida_empa_orca import optical
from aiida_empa_orca.protocols import protocol_settings


@pytest.fixture
def saved_runs(aiida_profile_clean, aiida_localhost, monkeypatch):
    from aiidalab_orca import optical_services as service
    retrieved_uuid = str(orm.FolderData().store().uuid)
    monkeypatch.setattr(service, 'source_node', lambda _: SimpleNamespace(
        outputs=SimpleNamespace(retrieved=orm.load_node(retrieved_uuid))))
    identities = {}
    for key, mult, triplets, state, exit_status in [
            ('singlets', 1, False, 'finished', 0),
            ('triplets', 1, True, 'finished', 310),
            ('uks', 2, False, 'waiting', None)]:
        node = orm.CalcJobNode(computer=aiida_localhost, process_type=optical.PROCESS_TYPE)
        node.label = 'Molecule · TDDFT · vertical optical excitations'
        for label, data in [('source_retrieved', orm.load_node(retrieved_uuid)),
                            ('settings', orm.Dict(dict={'method': 'TDDFT'} if key == 'singlets' else
                                                 {'method': 'TDDFT', 'triplets': triplets}).store()),
                            ('electronic_settings', orm.Dict(dict=protocol_settings(
                                overrides={'charge': 0, 'multiplicity': mult})).store())]:
            node.base.links.add_incoming(data, link_type=LinkType.INPUT_CALC, link_label=label)
        node.store()
        node.set_process_state(state)
        if exit_status is not None:
            node.set_exit_status(exit_status)
        identities[key] = str(node.uuid)
    return identities


def test_saved_runs_distinguish_failed_finished_and_response_families(saved_runs):
    from aiidalab_orca import optical_services as service
    rows = {row['uuid']: row for row in service.runs('source')}
    assert rows[saved_runs['singlets']]['display_state'] == 'finished'
    assert rows[saved_runs['singlets']]['families'] == 'singlets'
    assert rows[saved_runs['triplets']]['state'] == 'finished'  # Preserve the raw API state.
    assert rows[saved_runs['triplets']]['display_state'] == 'failed'
    assert rows[saved_runs['triplets']]['families'] == 'singlets + triplets'
    assert rows[saved_runs['uks']]['display_state'] == 'waiting'
    assert rows[saved_runs['uks']]['families'] == 'spin-conserving UKS'


def test_failed_selection_and_refresh_show_failure_without_loading_results(saved_runs, monkeypatch, tmp_path):
    from aiidalab_orca import optical as ui
    from aiidalab_orca import property_services
    monkeypatch.setattr(ui.service, 'defaults', lambda _: {
        'nprocs': 2, 'memory_mb': 2048, 'wallclock_seconds': 600, 'reference_type': 'RKS'})
    monkeypatch.setattr(property_services, 'default_stash_directory', lambda: str(tmp_path))
    monkeypatch.setattr(ui, 'progress', lambda uid: {
        'state': 'finished' if uid != saved_runs['uks'] else 'waiting',
        'finished': uid != saved_runs['uks'], 'success': uid == saved_runs['singlets'],
        'message': 'Optical validation failed', 'reports': ['Response residual criterion failed']})
    monkeypatch.setattr(ui.service, 'result', lambda _: pytest.fail('Failed results must not be loaded'))
    monkeypatch.setattr(ui.service, 'submit', lambda _: pytest.fail('Viewing must not submit'))
    panel = ui.OpticalExcitations('source')
    try:
        panel.saved.value = saved_runs['triplets']
        labels = {uid: label for label, uid in panel.saved.options if uid}
        assert 'singlets + triplets' in labels[saved_runs['triplets']]
        assert labels[saved_runs['triplets']].endswith(' · failed')
        assert '<p>failed · Optical validation failed</p>' in panel.message.value
        assert 'Response residual criterion failed' in panel.message.value
        assert not panel.output.children and panel.submit.disabled
        panel._refresh()
        assert panel.saved.value == saved_runs['triplets']
        assert '<p>failed ·' in panel.message.value
        assert not panel.output.children
    finally:
        panel.close()
