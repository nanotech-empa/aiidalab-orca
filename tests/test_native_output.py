"""Compact native output preserves validation while full data stays off-repository."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest
from aiida import orm
from aiida.common import CodeRunMode
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import casci, native_logs
from aiida_empa_orca.artifacts import stash_options
from test_casci import common_reference, output, reference_data, workchain_builder  # noqa: F401
from test_reference import electronic_source  # noqa: F401


def native_file(root, text=None):
    directory = root / native_logs.DIRECTORY
    directory.mkdir()
    path = directory / 'aiida.out'
    path.write_text(output() if text is None else text)
    return path


def collect(root, policy=None):
    return native_logs.collect_output({'protocol': 'casci-v1', 'policy': policy or {'mode': 'remote'}}, root)


def parse(text):
    ref = reference_data()
    space = {'electrons': 3, 'orbitals': [6, 7]}
    return casci.parse_states(text, ref, space, casci.casci_settings({'nroots': 2}, ref, space))


def test_large_native_output_is_preserved_with_a_small_equivalent_summary(tmp_path):
    text = output().replace('Spin-Determinant CI Printing\n',
                           'Spin-Determinant CI Printing\n' + '   [20u]   0.0000012345\n' * 200000)
    path = native_file(tmp_path, text)
    property_bytes = b'full property output\n' * 100000
    (tmp_path / 'aiida.property.txt').write_bytes(property_bytes)
    record = collect(tmp_path)
    summary = (tmp_path / 'aiida.out').read_bytes()
    native_logs.validate_summary(record, summary)
    assert len(summary) < 2000
    assert parse(summary.decode()) == parse(text)
    assert path.read_text() == text
    assert record['files'][0]['sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert record['files'][0]['size_bytes'] == len(text.encode())
    assert not (tmp_path / 'aiida.property.txt').exists()
    assert (path.parent / 'aiida.property.txt').read_bytes() == property_bytes
    assert (tmp_path / 'native_output_tail.txt').stat().st_size <= native_logs.TAIL_LIMIT


@pytest.mark.parametrize('suffix', [
    'WARNING: CI-ITERATIONS NOT CONVERGED!\n',
    'CAS-SCF STATES FOR BLOCK 0 MULT= 2 NROOTS= 2\nROOT 0: E= -120.0 Eh\n',
    'Number of active electrons ... 1\n',
])
def test_compaction_keeps_late_scientific_failure_markers(tmp_path, suffix):
    native_file(tmp_path, output() + suffix)
    collect(tmp_path)
    with pytest.raises(ValueError):
        parse((tmp_path / 'aiida.out').read_text())


def test_summary_checksum_mismatch_is_rejected(tmp_path):
    native_file(tmp_path)
    record = collect(tmp_path)
    with pytest.raises(ValueError, match='checksum'):
        native_logs.validate_summary(record, (tmp_path / 'aiida.out').read_bytes() + b'changed')


def test_budget_exhaustion_never_becomes_a_truncated_success(tmp_path, monkeypatch):
    path = native_file(tmp_path)
    original = path.read_bytes()
    monkeypatch.setattr(native_logs, 'SUMMARY_LIMIT', 100)
    record = collect(tmp_path)
    assert (tmp_path / 'aiida.out').stat().st_size <= 100
    with pytest.raises(ValueError, match='budget'):
        native_logs.validate_manifest(record)
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match='budget'):
        native_logs.read_state_summary(io.StringIO(output()))


def test_one_huge_line_is_not_loaded_and_remains_remote(tmp_path):
    text = 'X' * (native_logs.LINE_LIMIT + 100) + '\n' + output()
    path = native_file(tmp_path, text)
    record = collect(tmp_path)
    assert record['files'][0]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='line exceeding'):
        native_logs.validate_manifest(record)


def test_collector_runs_as_a_standalone_staged_worker(tmp_path):
    native_file(tmp_path)
    (tmp_path / 'compact_output.py').write_text(Path(native_logs.__file__).read_text())
    (tmp_path / 'native_output_request.json').write_text(json.dumps({
        'protocol': 'casci-v1', 'policy': {'mode': 'remote'}}))
    run = subprocess.run([sys.executable, 'compact_output.py'], cwd=tmp_path,
                         capture_output=True, text=True, check=True)
    assert 'complete' in run.stdout
    native_logs.validate_manifest(json.loads((tmp_path / native_logs.MANIFEST).read_text()))


@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_new_casci_runs_collect_on_the_calculation_computer(common_reference, aiida_manager, mode):  # noqa: F811
    b = workchain_builder(common_reference)
    b.native_output_policy = orm.Dict(dict={'mode': mode, 'stash_directory': '/chosen/stash'})
    process = instantiate_process(aiida_manager.get_runner(), b)
    captured = []

    def capture(child):
        captured.append(child)
        return orm.CalcJobNode().store()

    process.submit = capture
    try:
        assert process.setup() is None
        assert process.should_stash_wavefunction() == (mode == 'stash')
        process.run_casci()
        child = instantiate_process(aiida_manager.get_runner(), captured[0])
        try:
            with SandboxFolder() as folder:
                info = child.prepare_for_submission(folder)
                assert info.codes_run_mode == CodeRunMode.SERIAL
                assert info.codes_info[0].cmdline_params == ['aiida.inp']
                assert info.codes_info[0].stdout_name == 'native_output/aiida.out'
                assert info.codes_info[1].code_uuid == str(b.storage_code.uuid)
                assert info.codes_info[1].cmdline_params == ['compact_output.py']
                assert info.retrieve_list == ['aiida.out', native_logs.MANIFEST,
                                              'native_output_tail.txt', 'compact_output.log']
                assert 'aiida.property.txt' not in info.retrieve_list
                assert open(folder.get_abs_path('aiida.inp')).read() == casci.casci_input(
                    b.orbital_reference.get_dict(), b.active_space.get_dict(), b.settings.get_dict())
                if mode == 'stash':
                    assert dict(child.inputs.metadata.options.stash) == stash_options('/chosen/stash', 'native_output')
                else:
                    assert not child.inputs.metadata.options.get('stash')
        finally:
            child.close()
    finally:
        process.close()


@pytest.mark.parametrize('bad', [{'mode': 'retrieve'}, {'mode': 'stash'},
                               {'mode': 'stash', 'stash_directory': '/tmp/../escape'}])
def test_full_file_policy_has_no_retrieval_escape(bad):
    with pytest.raises(ValueError):
        native_logs.output_policy(bad)
