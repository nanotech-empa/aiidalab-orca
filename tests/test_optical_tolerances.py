"""Explicit response controls, reviewed identity and unchanged acceptance limits."""

from copy import deepcopy

import pytest

from aiida_empa_orca import native_logs, optical
from aiidalab_orca import optical as ui, optical_services as service
from test_optical_families import FAILED, SETTINGS, electronic
from test_reference import electronic_source  # noqa: F401


def converged_synthetic():
    return FAILED.read_text().replace('*** CONVERGENCE OF ENERGIES REACHED ***',
        'Maximum residual norm : 0.00000001\n*** CONVERGENCE OF RESIDUAL NORM REACHED ***')


def test_default_settings_and_inputs_keep_historical_native_tolerances():
    old = optical.settings(SETTINGS, electronic())
    explicit_none = optical.settings(SETTINGS | {'etol': None, 'rtol': None}, electronic())
    assert old == explicit_none and 'etol' not in old and 'rtol' not in old
    text = optical.optical_input(electronic(), explicit_none)
    assert 'ETol' not in text and 'RTol' not in text
    explicit = optical.optical_input(electronic(), SETTINGS | {'etol': 1e-12, 'rtol': 2.5e-7})
    assert 'ETol 1e-12' in explicit and 'RTol 2.5e-07' in explicit


@pytest.mark.parametrize('key', ['etol', 'rtol'])
@pytest.mark.parametrize('value', [0, -1, True, '1e-12', float('nan'), float('inf')])
def test_invalid_explicit_tolerances_are_rejected(key, value):
    with pytest.raises(ValueError, match='finite positive'):
        optical.settings(SETTINGS | {key: value}, electronic())


def test_native_tolerances_must_match_review_for_every_family():
    values = SETTINGS | {'etol': 1e-12, 'rtol': 2.5e-7}
    text = converged_synthetic().replace('residual ... 1.000e-06', 'residual ... 2.500e-07')
    text = text.replace('energies ... 1.000e-06', 'energies ... 1.000e-12')
    data = optical.parse_result(text, electronic(), values, expected_electrons=2)
    assert len(data['states']) == 6
    assert all(c == {'residual': 1e-8, 'tolerance': 2.5e-7, 'energy_tolerance': 1e-12}
               for c in data['checks']['response_solves'])
    for kind in ('residual', 'energies'):
        old = '2.500e-07' if kind == 'residual' else '1.000e-12'
        # Change only the last family's printed tolerance.
        first, last = text.rsplit(kind + ' ... ' + old, 1)
        with pytest.raises(ValueError, match='differs from the reviewed tolerance'):
            optical.parse_result(first + kind + ' ... 1.000e-03' + last, electronic(), values)
    failed = FAILED.read_text().replace('residual ... 1.000e-06', 'residual ... 2.500e-07')
    failed = failed.replace('energies ... 1.000e-06', 'energies ... 1.000e-12')
    with pytest.raises(ValueError, match='native residual tolerance'):
        optical.parse_result(failed, electronic(), values)


def test_printed_tolerance_rounding_never_weakens_the_requested_residual_limit():
    text = converged_synthetic().replace('Maximum residual norm : 0.00000001',
                                         'Maximum residual norm : 0.00000099995')
    with pytest.raises(ValueError, match='native residual tolerance'):
        optical.parse_result(text, electronic(), SETTINGS | {'rtol': .9999e-6})


def test_review_identity_and_builder_keep_resources_and_retention(electronic_source, configured_orca_tools):
    uid, _ = electronic_source()
    values = {'method': 'TDDFT', 'nto': False, 'etol': 1e-12, 'rtol': 2.5e-7,
              'nprocs': 2, 'memory_mb': 2048, 'wallclock_seconds': 600}
    policy = {'mode': 'remote', 'maxsizeoutput': 5*1024**2}
    reviewed = service.review(uid, values, native_output_policy=policy)
    builder = service.builder(reviewed)
    assert builder.settings.get_dict() == reviewed['settings']
    assert builder.native_output_policy.get_dict() == policy
    assert builder.metadata.options.resources == {'num_machines': 1, 'num_mpiprocs_per_machine': 2}
    assert builder.metadata.options.max_memory_kb == 2097152
    assert builder.metadata.options.max_wallclock_seconds == 600
    assert 'ETol 1e-12' in reviewed['input'] and 'RTol 2.5e-07' in reviewed['input']
    changed = deepcopy(reviewed)
    changed['settings']['etol'] = 1e-11
    with pytest.raises(ValueError, match='changed'):
        service.builder(changed)


def test_gui_override_is_explicit_reviewed_and_invalidated(monkeypatch):
    monkeypatch.setattr(service, 'defaults', lambda _: {'nprocs': 2, 'memory_mb': 2048, 'wallclock_seconds': 600})
    monkeypatch.setattr(service, 'runs', lambda _: [])
    def review(uid, values, force, *, native_output_policy):
        settings = optical.settings(values, electronic())
        return {'settings': settings, 'reuse_uuid': None, 'execution': 'test-code',
                'native_output_policy': native_output_policy,
                'input': optical.optical_input(electronic(), settings)}
    monkeypatch.setattr(service, 'review', review)
    monkeypatch.setattr(service, 'submit', lambda *_: pytest.fail('This test submits no calculation'))
    panel = ui.OpticalExcitations('synthetic-reference')
    try:
        assert not panel.explicit_tolerances.value and panel.etol.disabled and panel.rtol.disabled
        panel._review()
        assert 'no overrides' in panel.review_text.value
        panel.explicit_tolerances.value = True
        assert panel.plan is None and panel.submit.disabled
        assert not panel.etol.disabled and not panel.rtol.disabled
        panel._review()
        assert 'ETol = 1e-12 Ha' in panel.review_text.value and 'RTol = 2.5e-07' in panel.review_text.value
        assert panel.plan['settings']['nprocs'] == 2
        assert panel.plan['settings']['memory_mb'] == 2048
        assert panel.plan['settings']['wallclock_seconds'] == 600
        for control, changed in [(panel.etol, 1e-11), (panel.rtol, 2e-7)]:
            initial = control.value
            control.value = changed
            assert panel.plan is None and panel.submit.disabled and not panel.review_text.value
            control.value = initial
            assert panel.plan is None and panel.submit.disabled
            panel._review()
        panel.explicit_tolerances.value = False
        assert panel.plan is None and panel.submit.disabled
        panel._review()
        assert 'etol' not in panel.plan['settings'] and 'rtol' not in panel.plan['settings']
    finally:
        from aiidalab_orca.app import close_widget_tree
        close_widget_tree(panel)


def test_compact_optical_output_retains_tolerances_and_failed_stopping_criterion(tmp_path):
    folder = tmp_path / 'native_output'
    folder.mkdir()
    original = FAILED.read_bytes()
    (folder/'aiida.out').write_bytes(original)
    record = native_logs.collect_output({'protocol': 'optical-v1',
        'policy': {'mode': 'remote', 'maxsizeoutput': 0}}, tmp_path)
    summary = (tmp_path/'aiida_summary.out').read_bytes()
    native_logs.validate_summary(record, summary)
    assert (folder/'aiida.out').read_bytes() == original
    assert b'Convergence tolerance for the energies' in summary
    assert b'CONVERGENCE OF ENERGIES REACHED' in summary
    with pytest.raises(ValueError, match='native residual tolerance'):
        optical.parse_result(summary.decode(), electronic(), SETTINGS)


def test_compact_output_can_verify_explicit_native_tolerances(tmp_path):
    folder = tmp_path / 'native_output'
    folder.mkdir()
    text = converged_synthetic().replace('residual ... 1.000e-06', 'residual ... 2.500e-07')
    text = text.replace('energies ... 1.000e-06', 'energies ... 1.000e-12')
    (folder/'aiida.out').write_text(text)
    record = native_logs.collect_output({'protocol': 'optical-v1',
        'policy': {'mode': 'remote', 'maxsizeoutput': 0}}, tmp_path)
    summary = (tmp_path/'aiida_summary.out').read_bytes()
    native_logs.validate_summary(record, summary)
    values = SETTINGS | {'etol': 1e-12, 'rtol': 2.5e-7}
    assert optical.parse_result(summary.decode(), electronic(), values) == optical.parse_result(text, electronic(), values)
