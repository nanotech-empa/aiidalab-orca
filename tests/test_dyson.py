"""State compatibility, spin-component conventions and explicit durable reuse."""
from copy import deepcopy
import itertools
import math

import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.engine import ProcessState,run_get_node

from aiida_empa_orca import dyson
from aiida_empa_orca.dyson_data import (compatible,selection,checked_ci,spectrum,spin_factor,
                                       weighted_table,blend_weight,blend_options)
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401


def dataset(charge=0,mult=2):
    return {'method':'CASCI','geometry_mode':'fixed','orbital_reference_uuid':'reference',
            'structure_uuid':'structure','active_space':{'electrons':3,'orbitals':[6,7,8]},
            'model':{'integral_transform':'RI','auxiliary_basis':'def2-SVP/C'},
            'states':[{'charge':charge,'multiplicity':mult,'root':r,'energy_hartree':-10.+.1*r} for r in range(2)]}


@pytest.mark.parametrize('key,value',[('orbital_reference_uuid','other'),('structure_uuid','other'),
    ('active_space',{'electrons':3,'orbitals':[5,6,7]}),('model',{'auxiliary_basis':'AutoAux'}),('method','CASSCF')])
def test_incompatible_states_do_not_silently_share_a_spectrum(key,value):
    initial,final = dataset(),dataset(1,1)
    final[key] = value
    with pytest.raises(ValueError):compatible(initial,final)


def test_transition_selection_requires_one_electron_and_spin_allowed_existing_roots():
    initial = dataset()
    for final in (dataset(),dataset(1,5),dataset(2,1)):
        with pytest.raises(ValueError):compatible(initial,final)
    selected = selection({'initial_root':1,'final_roots':{'a':[1,0]}},initial,{'a':dataset(1,3)})
    assert selected['final_roots']['a'] == [0,1]
    for changes in ({'initial_root':2},{'final_roots':{'a':[0,0]}},{'final_roots':{'a':[9]}},
                    {'max_missing_ci_norm':float('nan')}):
        with pytest.raises(ValueError):selection(selected|changes,initial,{'a':dataset(1,3)})


def test_truncated_ci_is_measured_without_renormalizing_or_accepting_bad_spin():
    assert checked_ci({'[20u]':.8,'[02u]':.5},3,3,2) == pytest.approx(.89)
    for ci in ({'[20d]':1.},{'[22u]':1.},{'[20u]':float('nan')},{'[20u]':1.1},{}):
        with pytest.raises(ValueError):checked_ci(ci,3,3,2)


def table():
    return {'initial_state':{'multiplicity':2},'transitions':[
        {'id':'rem','energy_ev':-2.,'strength':.8,'side':'removal','final_multiplicity':1},
        {'id':'add','energy_ev':1.,'strength':.4,'side':'addition','final_multiplicity':3}]}


def test_spectral_area_hwhm_shift_and_branch_selection():
    omega = np.linspace(-1000,1000,200001)
    data = spectrum(table(),omega,.04)
    assert np.trapezoid(data['removal'],omega) == pytest.approx(math.pi*.8,rel=3e-5)
    peak = spectrum(table(),[-2.,-1.96],.04,side='removal')['total']
    assert peak[1] == pytest.approx(peak[0]/2)
    shifted = spectrum(table(),[-1.],.04,side='removal',shift=1.)
    assert shifted['total'][0] == pytest.approx(20.)
    assert shifted['addition'][0] == 0
    with pytest.raises(ValueError):spectrum(table(),omega,0)


def test_intensity_blend_uses_amplitudes_without_an_extra_strength():
    row = table()['transitions'][0]
    point = {'mode':'energy','energy_ev':-2.,'eta_ev':.04,'spin_convention':'unpolarized'}
    assert blend_weight(row,2,point) == pytest.approx(25.)  # Not 25 * .8.
    weight = blend_weight(row,2,point|{'mode':'window','lower_ev':-2.04,'upper_ev':-1.96})
    assert weight == pytest.approx(math.pi/2)
    assert blend_weight(row,2,point|{'shift_ev':1.,'energy_ev':-1.}) == pytest.approx(25.)
    with pytest.raises(ValueError):blend_options({'lower_ev':2.,'upper_ev':1.})
    raw = deepcopy(table())
    weighted = weighted_table(raw)
    assert weighted['transitions'][1]['strength'] == pytest.approx(.6)
    assert weighted['transitions'][1]['component_strength'] == .4
    assert weighted['transitions'][1]['spin_factor'] == 1.5
    assert weighted['strength_convention'] == 'unpolarized'
    assert weighted['source_strength_convention'] == 'highest_ms_component'
    assert weighted_table(weighted)['transitions'][1]['strength'] == pytest.approx(.6)
    assert weighted_table(weighted,'highest_ms_component')['transitions'][1]['strength'] == .4
    assert raw['transitions'][1]['strength'] == .4


# Independent spin-ladder/Fock-space reference for the multiplet factors.
def act(vector,p,create=False):
    output = {}
    for bits,c in vector.items():
        if bits[p] != int(not create):continue
        new = bits[:p]+(int(create),)+bits[p+1:]
        output[new] = output.get(new,0.)+c*(-1)**sum(bits[:p])
    return output


def lower(vector):
    output = {}
    for p in range(0,len(next(iter(vector))),2):
        for bits,c in act(act(vector,p),p+1,True).items():
            output[bits] = output.get(bits,0.)+c
    norm = math.sqrt(sum(c*c for c in output.values()))
    return {bits:c/norm for bits,c in output.items() if abs(c)>1e-12}


def projections(vector,mult):
    result = [vector]
    for _ in range(mult-1):result.append(lower(result[-1]))
    return result


def vector(text):
    bits = {'2':(1,1),'u':(1,0),'d':(0,1),'0':(0,0)}
    return tuple(itertools.chain.from_iterable(bits[c] for c in text))


@pytest.mark.parametrize('initial,mi,final,mf,create',[
    ({'20':1.},1,{'u0':1.},2,False),
    ({'u0':1.},2,{'20':1.},1,True),
    ({'u0':1.},2,{'uu':1.},3,True),
    ({'2u':1.},2,{'uu':1.},3,False),
    ({'2u':1.},2,{'ud':2**-.5,'du':-2**-.5},1,False),
    ({'uu':1.},3,{'u0':1.},2,False),
    ({'uu0':1.},3,{'uuu':1.},4,True),
    ({'2uu':1.},3,{'uuu':1.},4,False),
])
def test_spin_factor_matches_explicit_sum_over_all_spin_projections(initial,mi,final,mf,create):
    iv,fv = ({vector(k):v for k,v in values.items()} for values in (initial,final))
    def strength(i,f):
        return sum(sum(c*f.get(bits,0.) for bits,c in act(i,p,create).items())**2 for p in range(len(next(iter(i)))))
    component = strength(iv,fv)
    spin_summed = sum(strength(i,f) for i in projections(iv,mi) for f in projections(fv,mf))/mi
    assert component > 0
    assert spin_summed == pytest.approx(component*spin_factor(mi,mf))
    assert spin_factor(mi,mf,'highest_ms_component') == 1.


def test_dyson_kernel_single_orbital_limit_has_unit_component_strength():
    from dyson_orca_tools.dyson import Dyson
    initial = {'Molecule':{'Multiplicity':1,'S-Matrix':[[1.]],'MolecularOrbitals':{'MOs':[{'Occupancy':1.,'MOCoefficients':[1.]}]}}}
    final = deepcopy(initial);final['Molecule']['Multiplicity'] = 2
    params = {'parameters':{'initial':{'nelc':2,'norb':1,'spin_ci':{'[2]':1.}},
                            'final':{'nelc':1,'norb':1,'spin_ci':{'[u]':1.}}}}
    kernel = Dyson(initial,final,params)
    assert kernel.strength(kernel.dyson_orbital()) == pytest.approx(1.)
    assert spin_factor(1,2)*kernel.strength(kernel.dyson_orbital()) == pytest.approx(2.)


def casci_state(common_reference,charge=0,mult=2):
    ref_uuid,remote_uuid,code_uuid,_ = common_reference
    ref,remote = orm.load_node(ref_uuid),orm.load_node(remote_uuid)
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.casci',computer=remote.computer)
    calc.base.links.add_incoming(ref,link_type=LinkType.INPUT_CALC,link_label='orbital_reference')
    calc.store()
    data = dataset(charge,mult)
    data['orbital_reference_uuid'] = ref_uuid
    state = orm.Dict(dict=data)
    state.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='state_energies');state.store()
    folder = orm.FolderData().store()
    folder.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='retrieved')
    out = orm.RemoteData(computer=remote.computer,remote_path='/lost/casci')
    out.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='remote_folder');out.store()
    calc.set_process_state(ProcessState.FINISHED);calc.set_exit_status(0)
    return state,code_uuid


def test_lost_casci_wavefunction_reports_recovery_and_does_not_submit_scf(common_reference):
    state,code_uuid = casci_state(common_reference)
    b = dyson.StateExportWorkChain.get_builder()
    b.state_energies = state
    b.code = b.helper_code = orm.load_code(code_uuid)
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/tmp/dyson-stash'})
    _,run = run_get_node(b)
    assert run.exit_status == 400 and not run.called_descendants
    assert any('explicitly recompute this CASCI sector' in entry.message for entry in orm.Log.collection.get_logs_for(run))


@pytest.mark.parametrize("cache_enabled",[False,True])
def test_durable_dyson_results_reuse_before_any_wavefunction_availability_check(common_reference,cache_enabled):
    import io
    state,code_uuid = casci_state(common_reference)
    final,_ = casci_state(common_reference,1,1)
    b = dyson.DysonWorkChain.get_builder()
    b.initial = state
    b.finals.f = final
    b.code = b.export_code = orm.load_code(code_uuid)
    selected = {'initial_root':0,'final_roots':{'f':[0]},'max_missing_ci_norm':1e-5}
    b.selection = orm.Dict(dict=selected)
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/tmp/dyson-stash'})
    previous = orm.WorkChainNode(process_type=dyson.DYSON_PROCESS)
    for name,node in [('initial',state),('finals__f',final),('selection',b.selection.store()),('code',b.code)]:
        previous.base.links.add_incoming(node,link_type=LinkType.INPUT_WORK,link_label=name)
    previous.store()
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.dyson').store()
    data = orm.Dict(dict={'transitions':[{'id':'f_r0','energy_ev':-1.,'strength':1.}]})
    data.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='transitions');data.store()
    folder = orm.FolderData()
    for name in ('coefficients.npz','transitions.json'):
        folder.base.repository.put_object_from_filelike(io.BytesIO(b'preserved numerical result '*4),name)
    folder.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='retrieved');folder.store()
    remote = orm.RemoteData(computer=b.code.computer,remote_path='/lost/dyson')
    remote.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='remote_folder');remote.store()
    for name,node in [('transitions',data),('retrieved',folder),('remote_folder',remote)]:
        node.base.links.add_incoming(previous,link_type=LinkType.RETURN,link_label=name)
    previous.set_process_state(ProcessState.FINISHED);previous.set_exit_status(0)
    assert dyson.same_request(previous,b,selected)
    assert not dyson.same_request(previous,b,selected|{'initial_root':1})
    from aiida.manage.caching import enable_caching,disable_caching
    with (enable_caching() if cache_enabled else disable_caching()):
        output,run = run_get_node(b)
    assert run.is_finished_ok and not run.called_descendants
    assert output['transitions'].uuid == data.uuid



def test_spectral_widget_switches_conventions_and_exports_settings_without_jobs():
    from aiidalab_orca.spectra import SpectralViewer
    value = table()
    for row in value['transitions']:
        row.update(final_charge=1,final_root=0,final_ci_norm=1.)
    widget = SpectralViewer(value)
    try:
        assert widget.spin.value == 'unpolarized'
        assert '0.60000' in widget.transition_table.value
        widget.spin.value = 'highest_ms_component'
        assert '0.40000' in widget.transition_table.value
        widget.shift.value = 2.
        assert widget.blend()['shift_ev'] == 2.
        assert 'Download spectrum CSV' in widget.download.value
        widget.lower.value = widget.upper.value+1
        assert 'increasing energy range' in widget.info.value
    finally:widget.close()


def test_cube_comments_preserve_large_payload_and_ase_xyz_order(tmp_path):
    from aiida_empa_orca.scripts.dyson_cubes import cube_comments
    from ase import Atoms
    from ase.io.cube import write_cube,read_cube
    path = tmp_path/'blend.cube'
    atoms = Atoms('H',positions=[[1.,1.,1.]],cell=[4.,4.,4.])
    original = np.arange(64.).reshape(4,4,4)
    with path.open('w') as handle:write_cube(handle,atoms,data=original,origin=[-.5,-.5,-.5],comment='Intensity blend')
    size = path.stat().st_size
    cube_comments(path,second='XYZ data order; spectral intensity')
    assert path.stat().st_size == size
    # Mirror cubehandler's appended scaling note, the source of the regression.
    text = path.read_text().splitlines(keepends=True)
    text[1] = text[1].rstrip()+' Scaling factor: 1.0\n'
    path.write_text(''.join(text))
    with path.open() as handle:parsed = read_cube(handle)
    assert np.array_equal(parsed['data'],original)
    assert np.allclose(parsed['origin'],[-.5,-.5,-.5],atol=1e-6)


def test_fully_occupied_active_orbital_is_not_mistaken_for_an_inactive_core():
    from aiida_empa_orca.dyson_data import fixed_orbital_kernel
    initial = {'Molecule':{'Multiplicity':1,'S-Matrix':np.eye(2).tolist(),
        'MolecularOrbitals':{'MOs':[{'Occupancy':2.,'MOCoefficients':col} for col in np.eye(2).tolist()]}}}
    final = deepcopy(initial);final['Molecule']['Multiplicity'] = 2
    final['Molecule']['MolecularOrbitals']['MOs'][1]['Occupancy'] = 1.
    params = {'parameters':{'initial':{'nelc':2,'norb':1,'spin_ci':{'[2]':1.}},
                            'final':{'nelc':1,'norb':1,'spin_ci':{'[u]':1.}}}}
    kernel = fixed_orbital_kernel(initial,final,params,[1])
    assert kernel.active_slice == slice(1,2)
    assert np.allclose(abs(kernel.dyson_orbital()),[0.,1.])
    assert kernel.strength(kernel.dyson_orbital()) == pytest.approx(1.)


def test_opening_dyson_cube_results_selects_a_preview_and_enforces_spin_rule(monkeypatch):
    from aiidalab_orca import dyson as frontend
    rows = []
    for charge,mult in [(0,1),(1,2),(1,4),(-1,2)]:
        rows.append({'state_uuid':str(charge)+'_'+str(mult),'root':0,'charge':charge,
                     'multiplicity':mult,'energy_hartree':-10. if charge==0 else -9.})
    monkeypatch.setattr(frontend.service,'states',lambda _:deepcopy(rows))
    monkeypatch.setattr(frontend.service,'codes',lambda _:{'export':[],'dyson':[],'cubehandler':[],
        'storage_policy':{'threshold_mb':100,'stash_directory':'/remote/dyson-archive'}})
    monkeypatch.setattr(frontend.service,'runs',lambda *_:[])
    monkeypatch.setattr(frontend,'property_result',lambda _:{'successful':True,'manifest':{'cubes':[{'filename':'dyson_test.cube'}]}})
    viewed=[]
    monkeypatch.setattr(frontend.DysonStates,'_show_cube',lambda self,_=None:viewed.append(self.cube.value))
    widget=frontend.DysonStates('common',[{'reference_charge':0}])
    try:
        assert widget.stash.value == '/remote/dyson-archive'
        assert len(widget.finals.options)==2  # The quartet is spin forbidden from a singlet.
        assert all('multiplicity 2' in label for label,_ in widget.finals.options)
        widget._open_cubes({'new':'completed-cubes'})
        assert widget.cube.value=='dyson_test.cube'
        assert viewed[-1]=='dyson_test.cube'
    finally:widget.close()


def test_duplicate_final_sectors_cannot_double_count_spectral_weight():
    with pytest.raises(ValueError,match='one CASCI calculation'):
        selection({'final_roots':{'first':[0],'duplicate':[1]}},dataset(),
                  {'first':dataset(1,1),'duplicate':dataset(1,1)})
