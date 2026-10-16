"""Map geometry, analytical vacuum decay, weighting and durable provenance."""
from copy import deepcopy

import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process
from ase import Atoms
from ase.io.cube import write_cube
from ase.units import Bohr

from aiida_empa_orca.maps_data import (default_plane, plane_basis, sample_source, propagate,
                                      compute_maps, map_parameters, draw_maps)
from aiida_empa_orca.maps import DysonMapsCalculation, MAP_PROCESS
from aiidalab_orca import map_services


def parameters():
    return dict(plane=dict(center=[0., 0., 0.], normal=[0., 0., 1.], offset=1.5,
                           width=2., height=3., resolution=32),
                heights_angstrom=[1.5, 5., 7.], kappa_inv_angstrom=1.15,
                padding=0, transition_ids=['a', 'b'], kind='individual', spin_convention='unpolarized')


def test_default_height_is_above_highest_atom_not_center_of_mass():
    p = default_plane([[0, 0, -2], [0, 0, 3]], 4, 5)
    assert p['center'][2] == 3
    assert p['offset'] == 1.5
    assert np.array(p['center'])[2] + p['offset'] == 4.5


@pytest.mark.parametrize('normal', [[0, 0, 1], [1, 0, 0], [.3, -.2, .8]])
def test_map_plane_frame_matches_existing_slice_viewer(normal):
    from aiidalab_widgets_empa.cube import _orthonormal_basis_from_normal
    assert np.allclose(plane_basis(normal), _orthonormal_basis_from_normal(normal))


def test_oblique_source_slice_preserves_cube_origin_and_cell_metric():
    spacing = np.array([[.4, .1, 0], [0, .5, 0], [.1, 0, .6]])
    origin = np.array([4., -3., 2.])
    indexes = np.moveaxis(np.indices((20, 20, 20)), 0, -1)
    xyz = origin + indexes @ spacing
    data = xyz[..., 0] + 2*xyz[..., 1] - .5*xyz[..., 2]
    center = origin + np.array([10, 10, 10]) @ spacing
    plane = parameters()['plane'] | dict(center=center.tolist(), normal=[.3, -.2, .8], offset=.1, width=2., height=2.)
    values, x, y = sample_source(dict(data=data, origin=origin, spacing=spacing), plane)
    n, u, v = plane_basis(plane['normal'])
    xx, yy = np.meshgrid(x, y)
    points = center + .1*n + xx[..., None]*u + yy[..., None]*v
    exact = (points[..., 0]+2*points[..., 1]-.5*points[..., 2])/Bohr**1.5
    assert np.allclose(values, exact, rtol=0, atol=1e-12)
    with pytest.raises(ValueError, match='outside the full cube'):
        sample_source(dict(data=data, origin=origin, spacing=spacing), plane | {'offset': 100.})


def test_fourier_modes_obey_analytical_vacuum_decay():
    size, spacing, distance, kappa = 64, .2, 2.3, 1.15
    x = y = np.arange(size)*spacing
    k = 2*np.pi*3/(size*spacing)
    mode = np.broadcast_to(np.cos(k*x), (size, size))
    result = next(propagate(2+mode, x, y, [distance], kappa))
    exact = 2*np.exp(-kappa*distance)+mode*np.exp(-np.sqrt(k*k+kappa*kappa)*distance)
    assert np.allclose(result, exact, atol=1e-14)
    assert np.allclose(next(propagate(mode, x, y, [0.], kappa, padding=12)), mode, atol=1e-14)


def test_individual_maps_and_blends_keep_absolute_strength_and_spin_weights(tmp_path):
    paths = {}
    for name, amplitude in [('a', np.sqrt(.8)), ('b', -np.sqrt(.4))]:
        paths[name] = tmp_path/(name+'.cube')
        with paths[name].open('w') as handle:
            write_cube(handle, Atoms('H', positions=[[0, 0, 0]], cell=[8, 8, 8]),
                       data=np.full((12, 12, 12), amplitude), origin=[-3, -4, -2])
    table = dict(initial_state={'multiplicity': 2}, transitions=[
        dict(id='a', final_multiplicity=1, energy_ev=-2., strength=.8),
        dict(id='b', final_multiplicity=3, energy_ev=1., strength=.4)])
    p = parameters()
    arrays, metadata = compute_maps(paths, table, p)
    expected = np.array([.8, .4*1.5])/Bohr**3
    assert np.allclose(arrays['intensity'][0, :, 0, 0], expected, rtol=2e-6)
    assert np.allclose(arrays['intensity'][2]/arrays['intensity'][1], np.exp(-2*1.15*2), rtol=1e-12)
    blend = dict(mode='energy', energy_ev=-2., eta_ev=.04, spin_convention='unpolarized')
    blended, report = compute_maps(paths, table, p | dict(kind='blend', blend=blend))
    # Opposite amplitude signs cannot cancel transitions to distinct final states.
    exact = expected[0]*25 + expected[1]*.04/(3**2+.04**2)
    assert blended['intensity'][0, 0, 0, 0] == pytest.approx(exact, rel=2e-6)
    assert metadata['units'] == 'angstrom^-3' and report['units'] == 'angstrom^-3 eV^-1'
    assert metadata['sources'][1]['intensity_multiplier'] == 1.5


@pytest.mark.parametrize('change', [dict(heights_angstrom=[1.]), dict(heights_angstrom=[5., 5.]),
    dict(kappa_inv_angstrom=float('nan')), dict(padding=-1), dict(transition_ids=['a', 'a'])])
def test_invalid_scientific_map_request_is_rejected(change):
    with pytest.raises(ValueError):
        map_parameters(parameters() | change)


def test_figure_preserves_brightness_ratios_with_one_shared_scale(tmp_path, monkeypatch):
    import matplotlib.axes
    original = matplotlib.axes.Axes.imshow
    observed = []
    def capture(self, data, *args, **kwargs):
        observed.append((np.array(data), kwargs['norm']))
        return original(self, data, *args, **kwargs)
    monkeypatch.setattr(matplotlib.axes.Axes, 'imshow', capture)
    data = np.ones((2, 2, 8, 8))
    data[0, 1] *= .1
    data[1] = data[0]*.01
    arrays = dict(intensity=data, u_angstrom=np.linspace(-3, 3, 8),
                  v_angstrom=np.linspace(-3, 3, 8), heights_angstrom=[5, 7])
    draw_maps(arrays, dict(panels=['a', 'b'], units='angstrom^-3'), dict(vmax=1., dpi=72), tmp_path/'map.png', tmp_path/'map.pdf')
    assert len(observed) == 4
    assert all(norm is observed[0][1] for _, norm in observed)
    assert [float(a.max()) for a, _ in observed] == [1., .1, .01, .001]
    assert (tmp_path/'map.png').read_bytes().startswith(b'\x89PNG')
    assert (tmp_path/'map.pdf').read_bytes().startswith(b'%PDF-')


def map_source(aiida_localhost, tmp_path):
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    table = orm.Dict(dict={'initial_state': {'multiplicity': 2}, 'transitions': [
        dict(id='a', final_multiplicity=1), dict(id='b', final_multiplicity=3)]}).store()
    producer = orm.CalcJobNode(computer=aiida_localhost, process_type='aiida.calculations:empa_orca.dyson_cubes')
    producer.base.links.add_incoming(table, link_type=LinkType.INPUT_CALC, link_label='transitions')
    producer.store()
    root = tmp_path/'source'
    (root/'full_cubes').mkdir(parents=True)
    for name in ('a', 'b'):
        (root/'full_cubes'/(name+'.cube')).write_bytes(b'cube')
    manifest = orm.Dict(dict=dict(retention='leave', cubes=[dict(kind='dyson', transition_id=i, filename=i+'.cube', full={'size_bytes': 4}) for i in ('a', 'b')]))
    manifest.base.links.add_incoming(producer, link_type=LinkType.CREATE, link_label='manifest')
    manifest.store()
    remote = orm.RemoteData(computer=aiida_localhost, remote_path=str(root))
    remote.base.links.add_incoming(producer, link_type=LinkType.CREATE, link_label='remote_folder')
    remote.store()
    producer.set_process_state(ProcessState.FINISHED)
    producer.set_exit_status(0)
    return producer, table, code


def test_map_calcjob_stages_only_full_amplitudes_with_explicit_inputs(aiida_profile, aiida_localhost, aiida_manager, tmp_path):
    producer, table, code = map_source(aiida_localhost, tmp_path)
    b = DysonMapsCalculation.get_builder()
    b.code, b.source_manifest, b.transitions = code, producer.outputs.manifest, table
    b.source_folder, b.parameters = producer.outputs.remote_folder, orm.Dict(dict=parameters())
    b.metadata.options.resources = dict(num_machines=1, num_mpiprocs_per_machine=1)
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
        assert len(info.remote_copy_list) == 2 and not info.local_copy_list
        assert info.codes_info[0].cmdline_params == ['dyson_maps.py']
        assert info.retrieve_list == ['maps.npz', 'map-metadata.json', 'maps.log']
    finally:
        process.close()


@pytest.mark.parametrize('cache_enabled', [False, True])
def test_maps_reuse_without_cubes_or_aiida_caching(aiida_profile, aiida_localhost, tmp_path, cache_enabled):
    from aiida.manage.caching import enable_caching, disable_caching
    producer, table, code = map_source(aiida_localhost, tmp_path)
    run = orm.CalcJobNode(process_type=MAP_PROCESS)
    requested = parameters()
    requested['plane']['center'][2] = 1.2301480982967594
    requested['plane']['width'] = 7.234334019669321
    for key, value in dict(source_manifest=producer.outputs.manifest, transitions=table,
                           parameters=orm.Dict(dict=requested).store(), code=code).items():
        run.base.links.add_incoming(value, link_type=LinkType.INPUT_CALC, link_label=key)
    run.store()
    maps = orm.ArrayData()
    maps.set_array('intensity', np.ones((3, 2, 32, 32)))
    maps.base.links.add_incoming(run, link_type=LinkType.CREATE, link_label='maps')
    maps.store()
    metadata = orm.Dict(dict={'parameters': parameters()})
    metadata.base.links.add_incoming(run, link_type=LinkType.CREATE, link_label='map_metadata')
    metadata.store()
    run.set_process_state(ProcessState.FINISHED)
    run.set_exit_status(0)
    for path in (tmp_path/'source/full_cubes').iterdir():
        path.unlink()
    with enable_caching() if cache_enabled else disable_caching():
        plan = map_services.prepare_maps(producer.uuid, requested, code.uuid)
    assert plan['action'] == 'reuse' and plan['reuse_uuid'] == run.uuid
    altered = deepcopy(parameters())
    altered['plane']['offset'] = 1.6
    altered['heights_angstrom'][0] = 1.6
    with pytest.raises(FileNotFoundError):
        map_services.prepare_maps(producer.uuid, altered, code.uuid)


def test_oblique_parameters_do_not_drift_after_revalidation():
    p = parameters()
    p['plane']['normal'] = [.3, -.2, .8]
    assert map_parameters(map_parameters(p)) == map_parameters(p)


def test_render_progress_clears_old_download_and_restores_controls(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import ipywidgets as ipw
    from aiidalab_orca.maps import DysonMaps
    monkeypatch.setattr(map_services, 'progress', lambda uuid: dict(state='finished', finished=True, success=True))
    holder = SimpleNamespace(compute=ipw.Button(), render=ipw.Button(), review=ipw.Button(),
                             image=ipw.Image(value=b'old'), download=ipw.HTML('old download'),
                             message=ipw.HTML(), plan=None, _refresh_figures=lambda uuid: None)
    holder._poll = lambda uuid, kind: DysonMaps._poll(holder, uuid, kind)
    async def exercise():
        DysonMaps._start(holder, 'figure-uuid', 'figure')
        assert holder.image.value == b'' and holder.download.value == ''
        assert holder.review.disabled and holder.render.disabled
        await holder._task
        assert not holder.review.disabled and not holder.render.disabled
        assert holder.compute.disabled  # A fresh review is required for another numerical map.
    try:
        asyncio.run(exercise())
    finally:
        for name in ('compute', 'render', 'review', 'image', 'download', 'message'):
            getattr(holder, name).close()
