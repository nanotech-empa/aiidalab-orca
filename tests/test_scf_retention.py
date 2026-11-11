"""SCF collection keeps validation, spin levels and bounded geometry history."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import compact_scf, native_logs
from aiida_empa_orca.calculation import SinglePointCalculation, OptimizationCalculation
from aiida_empa_orca.levels import orbital_levels
from aiida_empa_orca.parser import reference_summary
from aiida_empa_orca.input import preview_input
from aiida_empa_orca.reference import single_point_parameters
from aiida_empa_orca.settings import orca_parameters
from test_properties import TABLE
from test_reference import OUTPUT


def source(tmp_path, monkeypatch, *, optimized=False, suffix='', oversized=False):
    root = tmp_path / 'native_output'
    root.mkdir()
    # The omitted body may be arbitrarily large; cclib receives the intact file.
    text = OUTPUT + TABLE + ('native full body\n' * 200000) + suffix
    original = root / 'aiida.out'
    original.write_text(text)
    received = []
    data = {'natom': 2, 'nmo': 3, 'nbasis': 3, 'charge': 0, 'mult': 2,
            'atomnos': [7, 8], 'scfenergies': [-3529.8], 'metadata': {'success': True},
            'mocoeffs': ['large wavefunction content'], 'aooverlaps': ['large matrix']}
    def read(path):
        received.append(path)
        assert path == str(original)
        return SimpleNamespace(getattributes=lambda: data)
    monkeypatch.setattr('aiida_orca.parsers.cclib.ccio.ccread', read)
    (tmp_path / 'compact_scf.py').write_text(Path(compact_scf.__file__).read_text())
    if optimized:
        for name in ('aiida.xyz', 'aiida_trj.xyz'):
            (tmp_path / name).write_text('2\nframe\nN 0 0 0\nO 0 0 1.15\n')
        if oversized:
            (tmp_path / 'aiida_trj.xyz').write_bytes(b'X' * (compact_scf.LIMITS['aiida_trj.xyz'] + 1))
    protocol = 'optimization-v1' if optimized else 'scf-v1'
    record = native_logs.collect_output({'protocol': protocol, 'policy': {'mode': 'remote'}}, tmp_path)
    return original, text, record, received


@pytest.mark.parametrize('optimized', [False, True])
def test_remote_reader_gets_full_output_but_only_compact_data_is_published(tmp_path, monkeypatch, optimized):
    original, text, record, received = source(tmp_path, monkeypatch, optimized=optimized)
    native_logs.validate_manifest(record)
    assert received == [str(original)] and original.read_text() == text
    summary = (tmp_path / 'aiida.out').read_text()
    assert len(summary) < 2000
    assert orbital_levels(summary, 3) == orbital_levels(text, 3)
    assert reference_summary(summary) == reference_summary(text)
    data = json.loads((tmp_path / 'scf_results.json').read_text())
    assert 'mocoeffs' not in data and 'aooverlaps' not in data
    assert data['compact_output']['omitted_fields'] == ['aooverlaps', 'mocoeffs']
    assert data['nmo'] == 3 and data['mult'] == 2
    if optimized:
        assert (tmp_path / 'aiida_trj.xyz').read_bytes() == (original.parent / 'aiida_trj.xyz').read_bytes()


def test_late_scf_failure_is_not_hidden_by_compaction(tmp_path, monkeypatch):
    source(tmp_path, monkeypatch, suffix='SCF NOT CONVERGED\n')
    with pytest.raises(ValueError, match='convergence'):
        reference_summary((tmp_path / 'aiida.out').read_text())


def test_oversized_geometry_history_stays_remote_and_cannot_pass(tmp_path, monkeypatch):
    original, _, record, _ = source(tmp_path, monkeypatch, optimized=True, oversized=True)
    with pytest.raises(ValueError, match='budget'):
        native_logs.validate_manifest(record)
    assert (original.parent / 'aiida_trj.xyz').is_file()
    assert not (tmp_path / 'aiida_trj.xyz').exists()


def test_staged_collector_loads_sibling_without_cwd_on_python_path(tmp_path):
    directory = tmp_path / 'native_output'
    directory.mkdir()
    (directory / 'aiida.out').write_text(OUTPUT)
    (tmp_path / 'compact_output.py').write_text(Path(native_logs.__file__).read_text())
    (tmp_path / 'compact_scf.py').write_text(
        "def collect(root, protocol, limit):\n"
        "    path = root / 'scf_results.json'\n"
        "    path.write_text('{}')\n"
        "    return [], [path]\n")
    (tmp_path / 'native_output_request.json').write_text(json.dumps({
        'protocol': 'scf-v1', 'policy': {'mode': 'remote'}}))
    # Like the installed orca-tools launcher, runpy does not add the script
    # directory to sys.path. -I also excludes the working directory/PYTHONPATH.
    result = subprocess.run([sys.executable, '-I', '-c',
        'import runpy,sys; runpy.run_path(sys.argv[1], run_name="__main__")',
        str(tmp_path / 'compact_output.py')], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert 'complete' in result.stdout
    native_logs.validate_manifest(json.loads((tmp_path / native_logs.MANIFEST).read_text()))


@pytest.mark.parametrize('calculation,protocol', [(SinglePointCalculation, 'scf-v1'),
                                                 (OptimizationCalculation, 'optimization-v1')])
@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_native_input_and_execution_are_preserved(aiida_profile, aiida_localhost, aiida_manager, calculation, protocol, mode):
    from ase import Atoms
    from aiida_empa_orca.artifacts import stash_options
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/configured/orca').store()
    b = calculation.get_builder()
    b.code = b.compact_code = code
    b.structure = orm.StructureData(ase=Atoms('NO', positions=[[0, 0, 0], [0, 0, 1.3]]))
    values = {'multiplicity': 2, 'nprocs': 1, 'memory_mb': 1024}
    params = orca_parameters(values) if protocol == 'optimization-v1' else single_point_parameters(values)
    b.parameters, b.maxcore_mb = orm.Dict(dict=params), orm.Int(768)
    b.native_output_policy = orm.Dict(dict={'mode': mode, 'stash_directory': '/chosen/stash'})
    b.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    if mode == 'stash':
        b.metadata.options.stash = stash_options('/chosen/stash', 'native_output')
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            expected = preview_input(b.structure, values, single_point=protocol == 'scf-v1')
            for name, content in expected.items():
                with folder.open(name) as handle:
                    assert handle.read() == content
            assert info.codes_info[0].cmdline_params == ['aiida.inp']
            assert info.codes_info[0].stdout_name == 'native_output/aiida.out'
            assert info.codes_info[1].cmdline_params == ['compact_output.py']
            assert 'scf_results.json' in info.retrieve_list
            assert not any(name.endswith(('.gbw', '.densities', '.hess', '.property.txt')) for name in info.retrieve_list)
    finally:
        process.close()
