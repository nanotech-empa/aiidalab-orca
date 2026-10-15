"""Electronic-file recovery, cube retention, and spin-resolved level contracts."""
import hashlib
import io
import json
import sys

import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process
from ase import Atoms
from ase.io.cube import write_cube

from aiida_empa_orca import artifacts, orbitals, reference
from aiida_empa_orca.levels import orbital_levels, visible_groups
from aiida_empa_orca.scripts import plot_cubes, store_electronic
from test_reference import OUTPUT, electronic_source  # shared disposable provenance fixture

TABLE = '''ORBITAL ENERGIES
SPIN UP ORBITALS
 0 1.0000 -1.0 -27.2114
 1 1.0000 -0.2 -5.4423
 2 0.0000 -0.1 -2.7211
SPIN DOWN ORBITALS
 0 1.0000 -1.0 -27.2114
 1 0.0000 -0.15 -4.0817
 2 0.0000 -0.1 -2.7211
MULLIKEN POPULATION ANALYSIS
'''


def test_energy_range_occupations_and_overlap_are_spin_resolved():
    levels = orbital_levels(TABLE, 3)
    assert levels['complete'] and levels['spin_polarized']
    assert levels['default_range_ev'] == pytest.approx([-6.4423, -3.0817])
    restricted = orbital_levels('ORBITAL ENERGIES\n 0 2.0 -0.2 -5.4\n 1 0.0 -0.1 -2.7\n', 2)
    assert not restricted['spin_polarized']
    assert restricted['default_range_ev'] == pytest.approx([-6.4, -1.7])
    assert not orbital_levels(TABLE, 12)['complete']
    channel = [{'energy_ev': energy} for energy in [-5, -4.999, -4.998, -3]]
    assert [len(g) for g in visible_groups(channel, -6, -2)] == [3, 1]
    assert [len(g) for g in visible_groups(channel, -5.001, -4.997)] == [1, 1, 1]
    with pytest.raises(ValueError):
        visible_groups(channel, 1, 0)
    from aiidalab_orca.levels import EnergyLevels
    widget = EnergyLevels(levels)
    try:
        assert [widget.lower.value, widget.upper.value] == levels['default_range_ev']
        widget.lower.value = -30
        assert 'MO 0' in widget.plot.value
        widget.reset()
        assert widget.lower.value == levels['homo_ev'] - 1
        widget.upper.value = widget.lower.value
        assert 'maximum greater' in widget.error.value
    finally:
        widget.close()


def test_storage_stages_only_small_bundles_and_stash_is_set_before_storage(electronic_source, aiida_manager):
    uuid, _ = electronic_source()
    source = orm.load_node(uuid)
    for threshold, mode in [(100, 'repository'), (0, 'stash')]:
        builder = artifacts.storage_builder(source.outputs.remote_folder, source.inputs.code,
                    {'threshold_mb': threshold, 'stash_directory': '/tmp/orca-test-stash'})
        assert builder.metadata.disable_cache
        process = instantiate_process(aiida_manager.get_runner(), builder)
        try:
            with SandboxFolder() as folder:
                info = process.prepare_for_submission(folder)
                assert ('electronic' in info.retrieve_list) == (mode == 'repository')
                assert json.loads(open(folder.get_abs_path('request.json')).read())['storage'] == mode
                if mode == 'stash':
                    assert process.node.get_option('stash')['source_list'] == ['electronic']
        finally:
            process.close()


def test_preserved_bundle_survives_loss_of_original_scratch(electronic_source, tmp_path, monkeypatch):
    uuid, original = electronic_source()
    source = orm.load_node(uuid)
    work = tmp_path/'preservation'
    work.mkdir()
    (work/'source').symlink_to(original, target_is_directory=True)
    (work/'request.json').write_text(json.dumps({'files': artifacts.ELECTRONIC_FILES,
        'threshold_bytes': 100*1024**2, 'storage': 'repository'}))
    monkeypatch.chdir(work)
    store_electronic.main()
    manifest = json.loads((work/'manifest.json').read_text())
    calc = orm.CalcJobNode(process_type=artifacts.STORAGE_PROCESS)
    calc.base.links.add_incoming(source.outputs.remote_folder, link_type=LinkType.INPUT_CALC, link_label='source_folder')
    calc.store()
    folder = orm.FolderData()
    folder.base.repository.put_object_from_tree(str(work/'electronic'), path='electronic')
    for name, node in {'retrieved': folder, 'manifest': orm.Dict(dict=manifest)}.items():
        node.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label=name)
        node.store()
    calc.set_process_state(ProcessState.FINISHED)
    calc.set_exit_status(0)
    for name in artifacts.ELECTRONIC_FILES:
        (original/name).unlink()  # Only this test's disposable source.
    location = artifacts.resolve_electronic(source.outputs.remote_folder)
    assert location['kind'] == 'repository' and location['storage_uuid'] == str(calc.uuid)
    assert reference.plan_reference(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code)['action'] == 'reuse'
    builder = reference.get_reference_builder(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code)
    builder.storage_policy = orm.Dict(dict={'threshold_mb': 100, 'stash_directory': '/tmp/test-stash'})
    builder.storage_code = source.inputs.code
    outputs, reused = run_get_node(builder)
    assert reused.is_finished_ok and not reused.called_descendants
    assert outputs['electronic_repository'].uuid == folder.uuid
    corrupt = orm.FolderData()
    corrupt.base.repository.put_object_from_filelike(io.BytesIO(b'wrong'), 'electronic/aiida.gbw')
    with pytest.raises(ValueError, match='integrity'):
        artifacts.repository_files(corrupt, manifest)


@pytest.mark.parametrize('mode', ['stash', 'leave', 'delete'])
def test_full_cubes_are_never_retrieved(aiida_profile, aiida_localhost, aiida_manager, mode):
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable=sys.executable).store()
    b = orbitals.OrbitalCubesCalculation.get_builder()
    b.code = b.plot_code = b.cubehandler_code = code
    b.source_repository = orm.FolderData()
    b.electronic_manifest = orm.Dict(dict={'files': []})
    b.parameters = orm.Dict(dict={'orbitals': [[0, 1]], 'spin_density': False,
        'retention': mode, 'stash_directory': '/tmp/orca-cube-test'})
    b.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    if mode == 'stash':
        b.metadata.options.stash = artifacts.stash_options('/tmp/orca-cube-test', 'full_cubes')
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            assert 'previews' in info.retrieve_list
            assert 'full_cubes' not in info.retrieve_list
            assert not any('gbw' in name for name in info.retrieve_list)
            assert len(info.local_copy_list) == 3
    finally:
        process.close()


@pytest.mark.parametrize('bad_preview', [False, True])
def test_delete_waits_for_valid_reduced_previews(tmp_path, monkeypatch, bad_preview):
    monkeypatch.chdir(tmp_path)
    files = []
    for name in artifacts.ELECTRONIC_FILES:
        (tmp_path/name).write_bytes(b'wavefunction')
        files.append({'name': name, 'size_bytes': 12, 'sha256': hashlib.sha256(b'wavefunction').hexdigest()})
    (tmp_path/'request.json').write_text(json.dumps({'files': files, 'plot_executable': 'plot',
        'cubehandler_executable': 'cubehandler', 'parameters': {'orbitals': [[0, 1]],
        'spin_density': False, 'grid_points': 40, 'retention': 'delete'}}))
    atoms = Atoms('H', positions=[[1, 1, 1]], cell=[5, 5, 5])
    def execute(args, **kwargs):
        if args[0] == 'plot':
            with open('aiida.mo1a.cube', 'w') as handle:
                write_cube(handle, atoms, data=np.ones((10, 10, 10))*.2)
        else:
            assert '--no-low-precision' in args  # No silent amplitude rescaling.
            assert (tmp_path/'full_cubes/orbital_a_0001.cube').exists()
            (tmp_path/'previews').mkdir()
            with open('previews/orbital_a_0001.cube', 'w') as handle:
                if bad_preview:
                    handle.write('truncated cube')
                else:
                    write_cube(handle, atoms, data=np.ones((3, 3, 3))*.2)
    monkeypatch.setattr(plot_cubes.subprocess, 'run', execute)
    if bad_preview:
        with pytest.raises((ValueError, IndexError)):
            plot_cubes.main()
        assert (tmp_path/'full_cubes/orbital_a_0001.cube').exists()
        assert (tmp_path/'aiida.gbw').exists()
    else:
        plot_cubes.main()
        assert not (tmp_path/'full_cubes').exists()
        assert (tmp_path/'previews/orbital_a_0001.cube').exists()
        assert json.loads((tmp_path/'manifest.json').read_text())['cubes'][0]['preview']['maximum'] == pytest.approx(.2)


def test_invalid_storage_and_cube_requests_are_rejected():
    for path in ('', '/', '../stash', '/tmp/../stash'):
        with pytest.raises(ValueError):
            artifacts.storage_policy({'stash_directory': path})
    for values in ({}, {'orbitals': [[2, 0]]}, {'orbitals': [[0, -1]]},
                   {'spin_density': True, 'grid_points': 500}, {'spin_density': True, 'retention': 'unknown'}):
        with pytest.raises(ValueError):
            orbitals.cube_parameters(values)


def test_missing_wavefunction_requires_review_and_regenerates_scf_without_cache(electronic_source, aiida_manager):
    from aiidalab_orca.property_services import prepare_property
    uuid, folder = electronic_source(output=OUTPUT + TABLE)
    source = orm.load_node(uuid)
    policy = {'threshold_mb': 100, 'stash_directory': '/tmp/property-test-stash'}
    parameters = orbitals.cube_parameters({'orbitals': [[0, 1]], 'spin_density': True,
                                           'retention': 'delete'})
    codes = {key: str(source.inputs.code.uuid) for key in ('python', 'plot', 'cubehandler')}
    assert not prepare_property(uuid, parameters, policy, codes)['regenerate_reference']
    (folder/'aiida.gbw').unlink()
    plan = prepare_property(uuid, parameters, policy, codes)
    assert plan['regenerate_reference']
    for approved in (False, True):
        b = orbitals.OrbitalsWorkChain.get_builder()
        b.source_retrieved, b.source_remote = source.outputs.retrieved, source.outputs.remote_folder
        b.structure, b.reference_settings = source.outputs.structure, source.inputs.settings
        b.parameters, b.storage_policy = orm.Dict(dict=parameters), orm.Dict(dict=policy)
        for key in ('python_code', 'plot_code', 'cubehandler_code', 'orca_code'):
            b[key] = source.inputs.code
        b.regenerate_reference = orm.Bool(approved)
        process = instantiate_process(aiida_manager.get_runner(), b)
        try:
            if not approved:
                assert process.setup().status == 401
            else:
                assert process.setup() is None and process.needs_reference()
                captured = []
                def submit(builder):
                    captured.append(builder)
                    return orm.WorkChainNode().store()
                process.submit = submit
                process.run_reference()
                assert captured[0].bypass_cache.value
                assert captured[0].structure.uuid == source.outputs.structure.uuid
        finally:
            process.close()
