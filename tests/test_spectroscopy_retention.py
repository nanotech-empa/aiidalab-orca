"""Compact spectroscopy retains native numerical results and failure decisions."""

from pathlib import Path
import shutil

import ase.io
import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType, StashMode
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import artifacts, native_logs, optical, vibrations
from aiidalab_orca import optical_services
from test_optical import electronic, native
from test_reference import electronic_source  # noqa: F401

FIXTURES = Path(__file__).parent / 'fixtures' / 'vibrations'


def collect(root, text, protocol, hessian=None):
    (root / 'native_output').mkdir()
    (root / 'native_output/aiida.out').write_text(text)
    if hessian is not None:
        (root / 'aiida.hess').write_text(hessian)
    record = native_logs.collect_output({'protocol': protocol, 'policy': {'mode': 'remote'}}, root)
    return record, (root / 'aiida.out').read_text()


@pytest.mark.parametrize('name,settings', [
    ('pyridine-tda', {}), ('pyridine-full', {'method': 'TDDFT'}),
    ('pyridine-triplets', {'triplets': True}),
])
def test_compact_optics_preserves_all_native_results(tmp_path, name, settings):
    text = native(name).replace('ORCA TERMINATED NORMALLY', 'unrelated detail\n' * 150000 + 'ORCA TERMINATED NORMALLY')
    record, summary = collect(tmp_path, text, 'optical-v1')
    native_logs.validate_manifest(record)
    values = {'nto_states': [1, 2, 3], **settings}
    assert optical.parse_result(summary, electronic(), values) == optical.parse_result(text, electronic(), values)
    assert len(summary) < 20000
    assert (tmp_path / 'native_output/aiida.out').read_text() == text


@pytest.mark.parametrize('before,after', [
    ('ORCA TERMINATED NORMALLY', 'ORCA TERMINATED NORMALLY\npoorly normalized'),
    ('CONVERGENCE OF RESIDUAL NORM REACHED', 'NO CONVERGENCE'),
    ('0.000000068510', '0.001000068510'),
    ('aiida.s2.nto', '../other.s2.nto'),
    ('STATE  5:', 'STATE  4:'),
])
def test_compact_optics_rejects_the_same_native_failures(tmp_path, before, after):
    text = native().replace(before, after)
    _, summary = collect(tmp_path, text, 'optical-v1')
    for sample in (text, summary):
        with pytest.raises(ValueError):
            optical.parse_result(sample, electronic(), {'nto_states': [1, 2, 3]})


def test_compact_hessian_and_log_keep_exact_modes_and_raman_checks(tmp_path):
    text = (FIXTURES / 'h2co.out').read_text()
    hessian = (FIXTURES / 'h2co.hess').read_text()
    atoms = ase.io.read(FIXTURES / 'h2co.xyz')
    record, summary = collect(tmp_path, text, 'vibrations-v1', hessian + '\n$unused\n' + 'irrelevant detail\n' * 100000)
    native_logs.validate_manifest(record)
    compact = (tmp_path / 'aiida.hess').read_text()
    full_arrays, full_summary = vibrations.parse_vibrations(text, hessian, atoms, True)
    arrays, result = vibrations.parse_vibrations(summary, compact, atoms, True)
    assert full_summary == result
    for key, values in full_arrays.items():
        np.testing.assert_array_equal(values, arrays[key])
    assert len(compact) < len(hessian) and '$unused' not in compact
    assert 'irrelevant detail' in (tmp_path / 'native_output/aiida.hess').read_text()
    bad = compact.replace('-1.5630400216E+00', '-9.5630400216E+00')
    with pytest.raises(ValueError):
        vibrations.parse_vibrations(summary, bad, atoms, True)


def test_hessian_budget_failure_preserves_original_and_is_not_accepted(tmp_path, monkeypatch):
    monkeypatch.setitem(native_logs.COMPACT_LIMITS, 'aiida.hess', 100)
    original = (FIXTURES / 'h2co.hess').read_text()
    record, _ = collect(tmp_path, (FIXTURES / 'h2co.out').read_text(), 'vibrations-v1', original)
    assert record['status'] == 'error'
    with pytest.raises(ValueError, match='budget'):
        native_logs.validate_manifest(record)
    assert (tmp_path / 'native_output/aiida.hess').read_text() == original
    assert not (tmp_path / 'aiida.hess').exists()


@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_native_nto_bundle_is_resolved_without_electronic_retrieval(tmp_path, aiida_profile, aiida_localhost, mode):
    name = 'aiida.s1.nto'
    (tmp_path / name).write_bytes(b'native NTO bytes')
    record, _ = collect(tmp_path, native(), 'optical-v1')
    record['policy'] = {'mode': mode, **({'stash_directory': str(tmp_path)} if mode == 'stash' else {})}
    producer = orm.CalcJobNode(process_type=optical.PROCESS_TYPE).store()
    remote = orm.RemoteData(computer=aiida_localhost,
                            remote_path=str(tmp_path / 'lost-scratch' if mode == 'stash' else tmp_path))
    manifest = orm.Dict(dict=record)
    outputs = {'remote_folder': remote, 'native_output_manifest': manifest}
    if mode == 'stash':
        # The directory has the same layout as an AiiDA stash, independent of
        # the original working-directory path or its continued availability.
        shutil.copytree(tmp_path / 'native_output', tmp_path / 'stash/native_output')
        outputs['remote_stash'] = orm.RemoteStashFolderData(computer=aiida_localhost,
            stash_mode=StashMode.COPY, target_basepath=str(tmp_path / 'stash'), source_list=['native_output'])
    for key, value in outputs.items():
        value.base.links.add_incoming(producer, link_type=LinkType.CREATE, link_label=key)
        value.store()
    producer.set_process_state(ProcessState.FINISHED)
    producer.set_exit_status(0)
    location = artifacts.resolve_electronic(remote, names=[name])
    expected = tmp_path / ('stash/native_output' if mode == 'stash' else 'native_output')
    assert location['kind'] == mode and location['path'] == str(expected)
    selected_source = outputs['remote_stash'] if mode == 'stash' else remote
    assert artifacts.electronic_base(selected_source, [name]) == expected
    assert (tmp_path / 'native_output' / name).is_file() and not (tmp_path / name).exists()
    assert location['files'][0]['sha256']


@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_optical_retention_staging_keeps_scientific_input(electronic_source, aiida_manager, monkeypatch, mode):  # noqa: F811
    uid, _ = electronic_source()
    code_uuid = str(orm.load_node(uid).inputs.code.uuid)
    monkeypatch.setattr(optical_services, 'helper_code', lambda _: code_uuid)
    plan = optical_services.review(uid, {}, True, native_output_policy={'mode': mode, 'stash_directory': '/chosen/stash'})
    builder = optical_services.builder(plan)
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            assert Path(folder.get_abs_path('aiida.inp')).read_text() == plan['input']
            assert info.codes_info[0].stdout_name == 'native_output/aiida.out'
            assert not any(name.endswith(('.nto', '.gbw', '.property.txt')) for name in info.retrieve_list)
    finally:
        process.close()


def test_retention_controls_invalidate_reviews(monkeypatch):
    from aiidalab_orca import optical as optics_ui, vibrations as vibration_ui
    monkeypatch.setattr(optics_ui.service, 'defaults', lambda _: {'nprocs': 1, 'memory_mb': 1024, 'wallclock_seconds': 600})
    monkeypatch.setattr(optics_ui.OpticalExcitations, '_refresh', lambda *_: None)
    monkeypatch.setattr(vibration_ui.VibrationalSpectroscopy, '_refresh', lambda *_: None)
    for panel in (optics_ui.OpticalExcitations('source'), vibration_ui.VibrationalSpectroscopy('source')):
        try:
            panel.plan = {'reviewed': True}
            panel.submit.disabled = False
            panel.full_files.mode.value = 'stash'
            assert panel.plan is None and panel.submit.disabled
        finally:
            from aiidalab_orca.widget_lifecycle import close_widget_tree
            close_widget_tree(panel)
