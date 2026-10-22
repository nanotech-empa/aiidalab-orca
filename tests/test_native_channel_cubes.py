"""Native orbital combinations preserve signed amplitudes and reject bad grids."""
import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io.cube import read_cube,write_cube

from aiida_empa_orca.scripts.dyson_cubes import native_channels


def request(tmp_path,*,different_origin=False,different_atoms=False):
    grid=np.indices((40,40,40),dtype=float)
    arrays=[np.sin(grid[0]/9),np.cos(grid[1]/7)]
    sources=[]
    for j,data in enumerate(arrays):
        path=tmp_path/f'native_{j}.cube'
        positions=[[.01 if different_atoms and j else 0.,0.,0.]]
        atoms=Atoms('H',positions=positions,cell=[8,9,10])
        with path.open('w') as handle:
            write_cube(handle,atoms,data=data,origin=[.1 if different_origin and j else 0.,0.,0.])
        sources.append(dict(index=j,staged=str(path),size_bytes=path.stat().st_size))
    return dict(parameters=dict(grid_points=40,orbitals=[[0,0],[0,1]]),native_cubes=sources,
        channels=dict(active_space=dict(orbitals=[0,1]),channels=[
            dict(id='ko_1',active_coefficients=[.6,.8]),
            dict(id='ko_2',active_coefficients=[-.8,.6])]))


def test_signed_native_combination_preserves_interference_and_absolute_scale(tmp_path):
    p=request(tmp_path)
    template,rows,arrays,fingerprints=native_channels(p)
    native=[]
    for source in p['native_cubes']:
        with open(source['staged']) as handle:
            native.append(read_cube(handle)['data'])
    assert np.allclose(arrays[0],.6*native[0]+.8*native[1],atol=1e-14)
    assert np.allclose(arrays[1],-.8*native[0]+.6*native[1],atol=1e-14)
    assert not np.allclose(arrays[0]**2,.36*native[0]**2+.64*native[1]**2)
    assert np.allclose(template['origin'],[0,0,0])
    assert [row['index'] for row in fingerprints]==[0,1]
    assert all(len(row['sha256'])==64 for row in fingerprints)
    assert all(Path(source['staged']).exists() for source in p['native_cubes'])


@pytest.mark.parametrize('mutation',['origin','atoms','order','resolution','size','coefficients'])
def test_native_combination_rejects_incompatible_sources(tmp_path,mutation):
    p=request(tmp_path,different_origin=mutation=='origin',different_atoms=mutation=='atoms')
    if mutation=='order':p['native_cubes'].reverse()
    if mutation=='resolution':p['parameters']['grid_points']=80
    if mutation=='size':p['native_cubes'][0]['size_bytes']+=1
    if mutation=='coefficients':p['channels']['channels'][0]['active_coefficients'][0]=float('nan')
    with pytest.raises(ValueError):native_channels(p)


def test_native_reference_submission_binds_checkpoint_and_phase_to_initial_state(aiida_profile,aiida_localhost):
    from aiida import orm
    from aiida.common.folders import SandboxFolder
    from aiida.engine.utils import instantiate_process
    from aiida.manage import get_manager
    from aiida_empa_orca.kondo import KondoReferenceCubesCalculation
    code=orm.InstalledCode(label='native-tools',computer=aiida_localhost,filepath_executable='/bin/true').store()
    state=orm.Dict(dict={'states':[]}).store()
    identity=dict(kind='kondo_reference',initial_state_uuid=str(state.uuid),source_gbw_sha256='a'*64,
                  levels=[dict(index=0)])
    inputs=dict(code=code,plot_code=code,cubehandler_code=code,state_energies=state,
        artifact=orm.Dict(dict=dict(state_uuid=str(state.uuid),source_gbw_sha256='a'*64)),
        orbital_filename=orm.Str('aiida.gbw'),orbital_identity=orm.Dict(dict=identity),
        source_folder=orm.RemoteData(computer=aiida_localhost,remote_path='/tmp/native-reference').store(),
        electronic_manifest=orm.Dict(dict={'files':[dict(name='aiida.gbw',size_bytes=123)]}),
        parameters=orm.Dict(dict=dict(orbitals=[[0,0]],spin_density=False,grid_points=40,retention='leave',stash_directory='')),
        metadata=dict(options=dict(resources={'num_machines':1,'num_mpiprocs_per_machine':1})))
    process=instantiate_process(get_manager().get_runner(),KondoReferenceCubesCalculation,**inputs)
    with SandboxFolder() as folder:
        info=process.prepare_for_submission(folder)
        with folder.open('request.json') as handle:r=json.load(handle)
        assert r['native_reference'] and r['files'][0]['sha256']=='a'*64
        assert r['orbital_identity']['initial_state_uuid']==str(state.uuid)
        assert info.codes_info[0].cmdline_params==['dyson_cubes.py']
        assert info.remote_copy_list[0][1]=='/tmp/native-reference/aiida.gbw'
    inputs['artifact']=orm.Dict(dict=dict(state_uuid='different-state',source_gbw_sha256='a'*64))
    process=instantiate_process(get_manager().get_runner(),KondoReferenceCubesCalculation,**inputs)
    with SandboxFolder() as folder,pytest.raises(ValueError,match='exact initial CASCI'):
        process.prepare_for_submission(folder)
