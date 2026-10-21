"""Parallel pair dispatch must preserve serial physics and scheduler accounting."""
from copy import deepcopy
import gzip
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import dyson
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401
from test_dyson import casci_state


def pair_inputs(directory, workers, truncated=False):
    """One-electron initial vector, two singlet addition roots and a vacuum root."""
    directory.mkdir()
    molecule = {'Charge':0,'Multiplicity':2,'Atoms':[{'ElementNumber':1,'Coords':[0.,0.,0.]}],
                'S-Matrix':np.eye(2).tolist(), 'MolecularOrbitals':{'MOs':[
                    {'MOCoefficients':[1.,0.],'Occupancy':.6},
                    {'MOCoefficients':[0.,1.],'Occupancy':.4}]}}
    specs = {
        'initial':(0,2,1,[{'[u0]':np.sqrt(.6),'[0u]':np.sqrt(.4)}]),
        'addition':(-1,1,2,[{'[20]':1.},{'[02]':1.}]),
        'removal':(1,1,0,[{'[00]':1.}]),
    }
    artifacts = {}
    for key,(charge,mult,nel,vectors) in specs.items():
        wavefunction = {'Molecule':deepcopy(molecule)}
        wavefunction['Molecule'].update(Charge=charge,Multiplicity=mult)
        identity = {'active_electrons':nel,'active_space':{'electrons':1,'orbitals':[0,1]},
                    'orbital_reference_uuid':'shared',
                    'states':[dict(charge=charge,multiplicity=mult,root=i,energy_hartree=-10.+i*.1+charge)
                              for i in range(len(vectors))]}
        roots = {str(i):{'coefficients':vector,'norm':sum(v*v for v in vector.values())}
                 for i,vector in enumerate(vectors)}
        if truncated and key == 'addition':
            roots['1']['norm'] = .8
        bundle = dict(state_uuid=key,identity=identity,wavefunction=wavefunction,ci_roots=roots)
        path = directory/(key+'.json.gz')
        with gzip.open(path,'wt') as handle:json.dump(bundle,handle)
        artifacts[key] = dict(state_uuid=key,identity=identity,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    request = {'workers':workers,'artifacts':artifacts,
               'selection':{'initial_root':0,'final_roots':{'addition':[0,1],'removal':[0]},'max_missing_ci_norm':1e-5}}
    (directory/'request.json').write_text(json.dumps(request))


def execute(directory):
    script = str(files('aiida_empa_orca').joinpath('scripts/compute_dyson.py'))
    # Exercise the same runpy entry mechanism as the installed remote runtime.
    return subprocess.run([sys.executable,'-c',
                           'import runpy,sys; runpy.run_path(sys.argv[1],run_name="__main__")',script],
                          cwd=directory,capture_output=True,text=True,timeout=60)


def test_fork_dispatch_preserves_serial_transition_table_and_every_ao_coefficient(tmp_path):
    serial,parallel = tmp_path/'serial',tmp_path/'parallel'
    pair_inputs(serial,1);pair_inputs(parallel,2)
    for directory in (serial,parallel):
        result = execute(directory)
        assert result.returncode == 0,result.stdout+result.stderr
    assert json.loads((serial/'transitions.json').read_text()) == json.loads((parallel/'transitions.json').read_text())
    with np.load(serial/'coefficients.npz') as first,np.load(parallel/'coefficients.npz') as second:
        assert set(first.files) == set(second.files)
        for key in first.files:
            assert np.array_equal(first[key],second[key])


@pytest.mark.parametrize('workers',[1,2])
def test_truncated_parallel_input_fails_without_writing_partial_results(tmp_path,workers):
    path = tmp_path/'run';pair_inputs(path,workers,truncated=True)
    result = execute(path)
    assert result.returncode != 0
    assert 'too truncated' in result.stderr
    assert not (path/'transitions.json').exists()
    assert not (path/'coefficients.npz').exists()


def test_workchain_forwards_workers_and_wall_time_to_one_non_mpi_calcjob(common_reference,aiida_manager,monkeypatch):
    initial,code_uuid = casci_state(common_reference)
    final,_ = casci_state(common_reference,1,1)
    b = dyson.DysonWorkChain.get_builder()
    b.initial,b.finals.f = initial,final
    b.code = b.export_code = orm.load_code(code_uuid)
    b.selection = orm.Dict(dict={'initial_root':0,'final_roots':{'f':[0]},'max_missing_ci_norm':1e-5})
    b.storage_policy = orm.Dict(dict={'mode':'remote','threshold_mb':100,'stash_directory':''})
    b.runtime = orm.Dict(dict={'workers':3,'max_wallclock_seconds':7200,'memory_mb':32768})
    process = instantiate_process(aiida_manager.get_runner(),b)
    source = orm.FolderData().store()
    captured = []
    monkeypatch.setattr(dyson,'export_location',lambda artifact:{'kind':'repository','uuid':str(source.uuid),'path':'state.json.gz'})
    try:
        process.ctx.selected = b.selection.get_dict()
        process.ctx.runtime = b.runtime.get_dict()
        for key,state in [('initial',initial),('f',final)]:
            artifact = orm.Dict(dict={'state_uuid':str(state.uuid)}).store()
            process.ctx['export_'+key] = SimpleNamespace(is_finished_ok=True,outputs=SimpleNamespace(artifact=artifact))
        def submit(child):
            captured.append(child)
            return orm.CalcJobNode().store()
        process.submit = submit
        process.compute()
        assert captured[0].metadata.options.resources['num_mpiprocs_per_machine'] == 3
        assert captured[0].metadata.options.max_wallclock_seconds == 7200
        assert captured[0].metadata.options.max_memory_kb == 32768*1024
        assert captured[0].metadata.options.withmpi is False
        child = instantiate_process(aiida_manager.get_runner(),captured[0])
        try:
            with SandboxFolder() as folder:
                child.prepare_for_submission(folder)
                request = json.loads(Path(folder.get_abs_path('request.json')).read_text())
                assert request['workers'] == 3
        finally:
            child.close()
    finally:
        process.close()


def test_app_reviews_resources_and_remote_only_retention_without_python_selection(monkeypatch):
    from aiidalab_orca import dyson as frontend
    rows = [dict(state_uuid='i',root=0,charge=0,multiplicity=2,energy_hartree=-10.),
            dict(state_uuid='f',root=0,charge=1,multiplicity=1,energy_hartree=-9.)]
    monkeypatch.setattr(frontend.service,'states',lambda _:rows)
    monkeypatch.setattr(frontend.service,'runs',lambda *_:[])
    monkeypatch.setattr(frontend.service,'codes',lambda _:dict(export=[('Export','export')],
        dyson=[('Dyson','dyson')],cubehandler=[],storage_policy={'mode':'remote'},
        runtime={'workers':6,'max_wallclock_seconds':10800,'memory_mb':65536}))
    calls = []
    def review(*args,**kwargs):
        calls.append(kwargs)
        return {'action':'compute','exports':[]}
    monkeypatch.setattr(frontend.service,'review',review)
    widget = frontend.DysonStates('common',[{'reference_charge':0}])
    try:
        widget._review()
        assert calls[0]['runtime'] == {'workers':6,'max_wallclock_seconds':10800,'memory_mb':65536}
        assert widget.retention.value == 'leave' and widget.stash.layout.display == 'none'
        assert 'native stash' not in widget.message.value
        assert 'export calculation directories' in widget.message.value
        widget.workers.value = 2
        assert widget.plan is None and widget.submit.disabled
    finally:
        widget.close()


@pytest.mark.parametrize('values',[{'workers':True},{'workers':0},{'memory_mb':-1},
                                 {'workers':6,'memory_mb':256},{'memory_mb':1024.5}])
def test_invalid_runtime_resources_are_rejected(values):
    with pytest.raises(ValueError):
        dyson.runtime_settings(values)
