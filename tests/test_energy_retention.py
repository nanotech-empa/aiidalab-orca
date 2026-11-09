"""Hamiltonians stay external while native checks and worker inputs stay exact."""

import hashlib
import io
import json
import logging
import shutil
from importlib.metadata import EntryPoint
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from aiida import common, engine, orm
from aiida.common import AttributeDict, LinkType

from aiida_empa_orca import energy, energy_files, native_logs
from aiida_empa_orca.energy_storage import stage_hamiltonian
from test_casci import output, reference_data

RAW = b' &FCI NORB=2,NELEC=3,MS2=0,\n ORBSYM=1,1,\n &END\n 1.5 1 1 0 0\n .7 0 0 0 0\n'
SPACE = {'electrons': 3, 'orbitals': [6, 7]}


def native_text():
    return ('Program Version 6.1.1\n#(CSFs) ... 1\n'
            'MaxIter==0 has been chosen - skipping the SCF\n'
            'Input Geometry matches current geometry\nInput basis set matches current basis set\n'
            + output(energies=(-129.1186109230,)))


def compact(root, text=None):
    (root / 'native_output').mkdir()
    (root / 'native_output/aiida.out').write_text(text or native_text())
    (root / 'aiida.fcidump').write_bytes(RAW)
    shutil.copyfile(energy_files.__file__, root / 'compact_energy.py')
    record = native_logs.collect_output({'protocol': 'energy-export-v1', 'policy': {'mode': 'remote', 'maxsizeoutput': 0},
        'energy_export': {'electrons': 3, 'multiplicity': 2}}, root)
    native_logs.validate_manifest(record)
    return record


def parsed(folder, manifest=None, text=None, reference=None):
    repo = orm.FolderData()
    for name, content in {'aiida.out': (text or native_text()).encode(), 'aiida.fcidump': RAW}.items():
        if manifest is None or name != 'aiida.fcidump':
            target = 'aiida_summary.out' if manifest is not None and name == 'aiida.out' else name
            repo.base.repository.put_object_from_filelike(io.BytesIO(content), target)
    if manifest is not None:
        repo.base.repository.put_object_from_file(folder / 'aiida.out', 'aiida.out')
    if manifest is not None:
        repo.base.repository.put_object_from_filelike(io.StringIO(json.dumps(manifest)), 'native_output.json')
    inputs = AttributeDict({'orbital_reference': reference if reference is not None else orm.Dict(dict=reference_data()),
        'active_space': orm.Dict(dict=SPACE), 'settings': orm.Dict(dict={'nroots': 1}),
        'native_output_policy': orm.Dict(dict=manifest['policy'] if manifest else {'mode': 'remote'})})
    if manifest is not None:
        inputs.compact_code = True
    parser = SimpleNamespace(node=SimpleNamespace(inputs=inputs, outputs={}), retrieved=repo,
        logger=logging.getLogger(__name__), exit_codes=SimpleNamespace(ERROR_EXPORT=310), values={})
    parser.out = lambda key, value: parser.values.__setitem__(key, value)
    status = energy.EnergyHamiltonianParser.parse(parser)
    return status, parser.values


def test_streamed_portable_file_matches_existing_header_convention(tmp_path):
    raw = RAW + b' 0.123456789012345 1 1 1 1\n' * 150000
    (tmp_path / 'native_output').mkdir()
    (tmp_path / 'aiida.fcidump').write_bytes(raw)
    original, portable, sector = energy_files.collect(tmp_path, 3, 2)
    expected, expected_sector = energy.portable_fcidump(raw, 3, 2)
    assert original.read_bytes() == raw and portable.read_bytes() == expected
    assert sector == expected_sector


def test_compact_export_keeps_native_metadata_but_not_integral_payload(tmp_path, aiida_profile):
    text = native_text().replace('ORCA TERMINATED NORMALLY', 'large unused native body\n' * 150000 + 'ORCA TERMINATED NORMALLY')
    manifest = compact(tmp_path, text)
    summary = (tmp_path / 'aiida_summary.out').read_text()
    reference = orm.Dict(dict=reference_data())
    old_status, old = parsed(tmp_path, text=text, reference=reference)
    new_status, new = parsed(tmp_path, manifest, summary, reference=reference)
    assert old_status is None and new_status is None
    assert old['native_export'].get_dict() == new['native_export'].get_dict()
    assert isinstance(new['hamiltonian'], orm.Dict)
    with old['hamiltonian'].open(mode='rb') as stream:
        assert new['hamiltonian'].get_dict()['sha256'] == hashlib.file_digest(stream, 'sha256').hexdigest()
    assert len(summary) < 2000
    assert not (tmp_path / 'aiida.fcidump').exists()


@pytest.mark.parametrize('before,after', [
    ('#(CSFs) ... 1', '#(CSFs) ... 2'),
    ('ORCA TERMINATED NORMALLY', 'ORCA TERMINATED NORMALLY\nSCF CONVERGED AFTER 2 CYCLES'),
    ('Input Geometry matches current geometry', 'Different geometry'),
    ('Active Orbitals ... unchanged', 'Active Orbitals ... optimized'),
    ('CI-PROBLEM SOLVED', 'WARNING: CI-ITERATIONS NOT CONVERGED!\nCI-PROBLEM SOLVED'),
])
def test_compaction_keeps_native_rejections(tmp_path, aiida_profile, before, after):
    text = native_text().replace(before, after)
    manifest = compact(tmp_path, text)
    assert parsed(tmp_path, text=text)[0] == 310
    assert parsed(tmp_path, manifest, (tmp_path / 'aiida_summary.out').read_text())[0] == 310


def descriptor_source(computer, root, raw, native):
    """External fixture representing an already accepted native export."""
    native_dir = root / 'native_output'
    native_dir.mkdir()
    (native_dir / 'hamiltonian.fcidump').write_bytes(raw)
    (native_dir / 'aiida.out').write_text('native fixture')
    item = {'name': 'hamiltonian.fcidump', 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    log = {'name': 'aiida.out', 'size_bytes': 14, 'sha256': hashlib.sha256(b'native fixture').hexdigest()}
    manifest = {'schema': native_logs.SCHEMA, 'protocol': 'energy-export-v1', 'directory': 'native_output',
        'status': 'complete', 'policy': {'mode': 'remote'}, 'summary': log, 'files': [log, item]}
    producer = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.energy_hamiltonian').store()
    outputs = {'hamiltonian': orm.Dict(dict={'schema': 'orca_energy_hamiltonian_v1', **item}),
        'native_export': orm.Dict(dict=native), 'native_output_manifest': orm.Dict(dict=manifest),
        'remote_folder': orm.RemoteData(computer=computer, remote_path=str(root))}
    for key, value in outputs.items():
        value.base.links.add_incoming(producer, link_type=LinkType.CREATE, link_label=key)
        value.store()
    producer.set_process_state(engine.ProcessState.FINISHED)
    producer.set_exit_status(0)
    return {key: str(value.uuid) for key, value in outputs.items()}


def test_transient_stage_checks_integrity_and_cleans_failed_transfer(tmp_path, aiida_localhost, aiida_computer_local):
    from aiida.common.folders import SandboxFolder
    source = descriptor_source(aiida_localhost, tmp_path, RAW, {})
    target = aiida_computer_local(label='different-worker')
    with SandboxFolder() as folder:
        info = common.CalcInfo({'local_copy_list': []})
        data = orm.load_node(source['hamiltonian'])
        stage_hamiltonian(info, data, target, folder)
        assert info.provenance_exclude_list == ['hamiltonian.fcidump']
        assert Path(folder.get_abs_path('hamiltonian.fcidump')).read_bytes() == RAW
    (tmp_path / 'native_output/hamiltonian.fcidump').write_bytes(RAW.replace(b'1.5', b'1.6'))
    with SandboxFolder() as folder:
        with pytest.raises(ValueError, match='checksum'):
            stage_hamiltonian(common.CalcInfo({'local_copy_list': []}), data, target, folder)
        assert not Path(folder.get_abs_path('hamiltonian.fcidump')).exists()


@pytest.mark.parametrize('cross_computer', [False, True])
def test_native_worker_executes_external_hamiltonian_without_repository_copy(
    tmp_path, aiida_localhost, aiida_computer_local, aiida_code_installed, monkeypatch, cross_computer,
):
    np = pytest.importorskip('numpy')
    fcidump = pytest.importorskip('pyscf.tools.fcidump')
    from aiida.plugins import entry_point
    source = Path(__file__).resolve().parents[1] / 'quantum-tools/src'
    monkeypatch.syspath_prepend(str(source))
    from quantum_orbital_tools.energy import manifest as worker_manifest
    raw_path = tmp_path / 'fixture.fcidump'
    eri = np.zeros((2,) * 4)
    eri[0, 0, 0, 0], eri[1, 1, 1, 1] = .5, .3
    fcidump.from_integrals(str(raw_path), np.array([[-1., .03], [.03, -.2]]), eri, 2, 2, nuc=.7)
    raw = raw_path.read_bytes()
    native = {'native_csfs': 1, 'not_a_correlated_CASCI_state': True, 'charge': 0, 'multiplicity': 1,
        'active_space': {'electrons': 2, 'orbitals': [0, 1]}, 'diagnostic_energy_hartree': -.8,
        'hamiltonian_sha256': hashlib.sha256(raw).hexdigest()}
    outputs = descriptor_source(aiida_localhost, tmp_path, raw, native)
    worker = aiida_computer_local(label='portable-worker') if cross_computer else aiida_localhost
    original = entry_point.get_entry_point
    def resolve(group, name):
        classes = {'aiida.calculations': 'EnergyStageCalculation', 'aiida.parsers': 'EnergyStageParser'}
        if name == 'empa_orca.energy_stage' and group in classes:
            return EntryPoint(name=name, value='aiida_empa_orca.energy:' + classes[group], group=group)
        return original(group, name)
    monkeypatch.setattr(entry_point, 'get_entry_point', resolve)
    executable = tmp_path / 'quantum-energy'
    executable.write_text('#!' + sys.executable + '\nfrom quantum_orbital_tools.energy import main\nmain()\n')
    executable.chmod(0o755)
    code = aiida_code_installed(computer=worker, filepath_executable=str(executable),
        prepend_text='export PYTHONPATH=' + str(source) + '${PYTHONPATH:+:$PYTHONPATH}')
    code.base.extras.set('quantum_energy_tools', worker_manifest())
    values, node = engine.run_get_node(energy.EnergyStageCalculation, code=code,
        hamiltonian=orm.load_node(outputs['hamiltonian']), native_export=orm.load_node(outputs['native_export']),
        operation=orm.Str('validate'), settings=orm.Dict(dict={}), metadata={'options': {
            'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 1}, 'withmpi': False, 'max_wallclock_seconds': 30}})
    assert node.is_finished_ok, str(orm.Log.collection.get_logs_for(node))
    assert values['result'].get_dict()['passed'] is True
    assert 'hamiltonian.fcidump' not in node.base.repository.list_object_names()
    assert 'hamiltonian.fcidump' not in node.outputs.retrieved.base.repository.list_object_names()
