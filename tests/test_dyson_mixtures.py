"""Population sums preserve physical energies, amplitudes and immutable provenance."""
from copy import deepcopy
import hashlib
import io
import json

import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import dyson
from aiida_empa_orca.dyson_data import spectrum, weighted_table, blend_weight
from aiida_empa_orca.dyson_mixture import mix_tables, cube_source, MIXTURE_PROCESS, checked_sources
from aiida_empa_orca.kondo_data import exchange
from aiidalab_orca import dyson_mixture_services as service
from test_dyson import dataset


def source_table(mult=1, count=2):
    return dict(schema_version=1,orbital_reference_uuid='common',initial_state_uuid='initial_'+str(mult),
        active_space=dict(electrons=2,orbitals=[0,1]),strength_convention='highest_ms_component',
        initial_state=dict(charge=0,multiplicity=mult,root=0,energy_hartree=-10.+(mult-1)*.00005),
        transitions=[dict(id='t'+str(i),side='removal' if i%2==0 else 'addition',
            energy_ev=(-2. if i%2==0 else 1.)+(mult-1)*.001+.03*i,
            strength=.04*(i+1),final_multiplicity=2,final_charge=1 if i%2==0 else -1,
            final_state_uuid='final',final_root=i,final_ci_norm=1.) for i in range(count)])


def test_equal_populations_retain_distinct_poles_and_weight_each_strength_once():
    tables = dict(singlet=source_table(1),triplet=source_table(3))
    before = deepcopy(tables)
    mixture = mix_tables(tables,dict(singlet=.5,triplet=.5))
    omega = np.linspace(-4,4,501)
    actual = spectrum(weighted_table(mixture),omega,.1)['total']
    expected = sum(.5*spectrum(weighted_table(t),omega,.1)['total'] for t in tables.values())
    assert np.allclose(actual,expected,rtol=1e-14,atol=1e-15)
    for row in mixture['transitions']:
        original = next(r for r in tables[row['source']]['transitions'] if r['id']==row['source_transition_id'])
        assert row['energy_ev'] == original['energy_ev']
        assert row['strength'] == original['strength']
        # Raw |D|² already contains Z. Only p, F and the Lorentzian multiply it.
        factor = 2. if row['source']=='singlet' else 1.
        assert blend_weight(row,None,dict(energy_ev=row['energy_ev'])) == pytest.approx(.5*factor/.1)
    twice = weighted_table(weighted_table(mixture))
    assert [r['strength'] for r in twice['transitions']] == [r['strength'] for r in weighted_table(mixture)['transitions']]
    assert tables == before
    with pytest.raises(ValueError,match='one initial spin multiplet'):
        exchange(mixture,{})


@pytest.mark.parametrize('populations', [dict(s=.5,t=.4),dict(s=-.1,t=1.1),dict(s=float('nan'),t=.5),dict(s=True,t=0.)])
def test_invalid_populations_are_not_silently_normalized(populations):
    with pytest.raises(ValueError,match='populations'):
        mix_tables(dict(s=source_table(1),t=source_table(3)),populations)


@pytest.mark.parametrize('change', ['basis','active','charge','duplicate','rerun','weighted'])
def test_mixture_rejects_incompatible_or_duplicate_inputs(change):
    s,t = source_table(1),source_table(3)
    if change=='basis':t['orbital_reference_uuid']='other'
    if change=='active':t['active_space']['orbitals']=[1,2]
    if change=='charge':t['initial_state']['charge']=1
    if change=='duplicate':t=deepcopy(s)
    if change=='rerun':
        t=deepcopy(s);t['initial_state_uuid']='rerun_of_same_state'
    if change=='weighted':t=weighted_table(t)
    with pytest.raises(ValueError):
        mix_tables(dict(s=s,t=t),dict(s=.5,t=.5))


@pytest.fixture
def native_sources(aiida_localhost):
    def output(calc,node,label):
        node.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label=label)
        return node.store()
    code = orm.InstalledCode(computer=aiida_localhost,filepath_executable='/bin/true').store()
    export = orm.CalcJobNode(computer=aiida_localhost,process_type='aiida.calculations:empa_orca.dyson_export').store()
    payload = b'fixture basis export'
    artifact = output(export,orm.Dict(dict=dict(sha256=hashlib.sha256(payload).hexdigest(),size_bytes=len(payload))),'artifact')
    folder = orm.FolderData()
    folder.base.repository.put_object_from_filelike(io.BytesIO(payload),'retrieved_exports/state.json.gz')
    output(export,folder,'retrieved')
    export.set_process_state(ProcessState.FINISHED);export.set_exit_status(0)
    sources,states = {},[]
    for key,mult in [('s',1),('t',3)]:
        table = source_table(mult,72)
        state_data = dataset(0,mult)
        state_data.update(orbital_reference_uuid=table['orbital_reference_uuid'],active_space=table['active_space'])
        state = orm.Dict(dict=state_data).store()
        table['initial_state_uuid'] = str(state.uuid)
        work = orm.WorkChainNode(process_type=dyson.DYSON_PROCESS)
        work.base.links.add_incoming(state,link_type=LinkType.INPUT_WORK,link_label='initial')
        work.store()
        calc = orm.CalcJobNode(computer=aiida_localhost,process_type='aiida.calculations:empa_orca.dyson')
        calc.base.links.add_incoming(artifact,link_type=LinkType.INPUT_CALC,link_label='artifacts__initial')
        calc.store()
        transitions = output(calc,orm.Dict(dict=table),'transitions')
        stream = io.BytesIO()
        np.savez_compressed(stream,**{r['id']:np.array([np.sqrt(r['strength']),0.]) for r in table['transitions']})
        retrieved = orm.FolderData()
        retrieved.base.repository.put_object_from_filelike(io.BytesIO(stream.getvalue()),'coefficients.npz')
        output(calc,retrieved,'retrieved')
        output(calc,orm.RemoteData(computer=aiida_localhost,remote_path='/unused/native-dyson'),'remote_folder')
        calc.set_process_state(ProcessState.FINISHED);calc.set_exit_status(0)
        transitions.base.links.add_incoming(work,link_type=LinkType.RETURN,link_label='transitions')
        work.set_process_state(ProcessState.FINISHED);work.set_exit_status(0)
        sources[key]=str(transitions.uuid)
        states.append(dict(state_uuid=str(state.uuid),root=0,charge=0,multiplicity=mult,energy_hartree=-10.))
    return dict(sources=sources,states=states,code_uuid=str(code.uuid),artifact_uuid=str(artifact.uuid),basis_uuid=str(folder.uuid))


def test_saved_mixture_provenance_and_complete_cube_submission(aiida_profile,aiida_manager,native_sources):
    f = native_sources
    populations = {uuid:.5 for uuid in f['sources'].values()}
    plan = service.review(populations)
    assert plan['transition_count']==144
    uuid = service.save(plan)
    run = orm.load_node(uuid)
    assert run.is_finished_ok and run.process_type==MIXTURE_PROCESS
    assert {str(link.node.uuid) for link in run.base.links.get_incoming(link_type=LinkType.INPUT_CALC).all()
            if link.link_label!='parameters'} == set(populations)
    transitions = run.outputs.transitions
    assert len(transitions.get_dict()['transitions'])==144
    with run.outputs.retrieved.base.repository.open('coefficients.npz',mode='rb') as handle:
        with np.load(handle,allow_pickle=False) as arrays:
            assert len(arrays.files)==144
            assert np.array_equal(arrays['s0__t0'],[np.sqrt(.04),0.])  # No sqrt(p) or Z rescaling.
    assert uuid in [value for _,value in service.history(f['states'])]
    assert len(service.candidates(f['states']))==2
    source = cube_source(transitions)
    assert source['coefficients_uuid']==str(run.outputs.retrieved.uuid)
    assert source['artifact_uuid']==f['artifact_uuid']

    from aiida_empa_orca.orbitals import cube_parameters
    values = dict(orbitals=[[0,i] for i in range(144)],retention='leave')
    with pytest.raises(ValueError,match='at most 64'):
        cube_parameters(values)  # The unrelated single-particle limit is unchanged.
    b = dyson.DysonCubesCalculation.get_builder()
    b.code=b.cubehandler_code=orm.load_code(f['code_uuid'])
    b.transitions=transitions
    b.coefficients=run.outputs.retrieved
    b.artifact=orm.load_node(f['artifact_uuid'])
    b.source=orm.load_node(f['basis_uuid'])
    b.location=orm.Dict(dict=dyson.export_location(b.artifact))
    b.parameters=orm.Dict(dict=values)
    b.metadata.options.resources=dict(num_machines=1,num_mpiprocs_per_machine=1)
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        with SandboxFolder() as directory:
            info = process.prepare_for_submission(directory)
            with directory.open('request.json') as handle:
                request = json.load(handle)
        assert len(request['parameters']['orbitals'])==144
        assert info.local_copy_list[0][0]==run.outputs.retrieved.uuid
    finally:
        process.close()

    b = dyson.DysonCubesWorkChain.get_builder()
    b.transitions=transitions
    b.parameters=orm.Dict(dict=values)
    b.code=b.cubehandler_code=orm.load_code(f['code_uuid'])
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        assert process.setup() is None
        assert process.ctx.source==source
        assert process.ctx.location['uuid']==f['basis_uuid']
    finally:
        process.close()


def test_checked_sources_rejects_different_geometry_even_with_same_orbital_label(aiida_profile,native_sources):
    nodes = {key:orm.load_node(uuid) for key,uuid in native_sources['sources'].items()}
    # Create a distinct immutable state/result instead of editing existing scientific data.
    original=nodes['t'].get_dict()
    altered=orm.load_node(original['initial_state_uuid']).get_dict();altered['structure_uuid']='another-geometry'
    state=orm.Dict(dict=altered).store()
    original['initial_state_uuid']=str(state.uuid)
    calc=orm.CalcJobNode(process_type='aiida.calculations:empa_orca.dyson').store()
    replacement=orm.Dict(dict=original)
    replacement.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='transitions');replacement.store()
    calc.set_process_state(ProcessState.FINISHED);calc.set_exit_status(0)
    with pytest.raises(ValueError,match='geometry'):
        checked_sources(dict(s=nodes['s'],t=replacement),dict(s=.5,t=.5))


def test_population_widget_requires_explicit_values_and_review_before_save(monkeypatch):
    from aiidalab_orca.dyson_mixtures import DysonMixtures
    from aiidalab_orca import dyson_mixtures as frontend
    rows=[dict(uuid='s',label='singlet',multiplicity=1,root=0),dict(uuid='t',label='triplet',multiplicity=3,root=0)]
    monkeypatch.setattr(frontend.service,'candidates',lambda _:rows)
    saved=[]
    monkeypatch.setattr(frontend.service,'history',lambda _: [('stored','mixture')] if saved else [])
    def review(p):
        mix_tables(dict(s=source_table(1),t=source_table(3)),p)
        return dict(populations=p,transition_count=4)
    monkeypatch.setattr(frontend.service,'review',review)
    monkeypatch.setattr(frontend.service,'save',lambda plan:saved.append(plan) or 'mixture')
    opened=[]
    widget=DysonMixtures([],opened.append)
    try:
        widget.results.value=('s','t')
        assert widget.combine.disabled and not saved
        widget._review()
        assert widget.combine.disabled and 'sum to one' in widget.message.value
        widget._equal();widget._review()
        assert not widget.combine.disabled
        widget.weights['s'].value=.4
        assert widget.combine.disabled  # Changing weights invalidates the reviewed plan.
        widget._equal();widget._review();widget._save()
        assert saved[0]['populations']==dict(s=.5,t=.5)
        assert opened==['mixture']
    finally:
        from aiidalab_orca.app import close_widget_tree
        close_widget_tree(widget)


def test_switching_to_mixture_opens_spectrum_and_blocks_single_multiplet_exchange(monkeypatch):
    from aiidalab_orca import dyson as frontend,dyson_mixture_services
    from aiidalab_orca.app import close_widget_tree
    rows=[dict(state_uuid='singlet',root=0,charge=0,multiplicity=1,energy_hartree=-10.)]
    monkeypatch.setattr(frontend.service,'states',lambda _:rows)
    monkeypatch.setattr(frontend.service,'codes',lambda _:dict(export=[],dyson=[('Dyson','code')],cubehandler=[('Cubes','cubes')]))
    monkeypatch.setattr(frontend.service,'runs',lambda *_:[])
    monkeypatch.setattr(frontend.service,'cube_runs',lambda _:[])
    monkeypatch.setattr(dyson_mixture_services,'candidates',lambda _:[])
    monkeypatch.setattr(dyson_mixture_services,'history',lambda _:[('50/50 singlet/triplet','mixture')])
    mixture=mix_tables(dict(s=source_table(1),t=source_table(3)),dict(s=.5,t=.5))
    monkeypatch.setattr(frontend.service,'progress',lambda _:dict(finished=True,success=True))
    monkeypatch.setattr(frontend.service,'result',lambda _:dict(data=mixture,transitions_uuid='combined'))
    widget=frontend.DysonStates('common',[dict(reference_charge=0)])
    try:
        assert widget.source_mode.value=='single' and widget.mixture_panel is None
        widget.source_mode.value='mixture'
        widget.mixture_panel.previous.value='mixture'
        assert widget.record['data']==mixture
        assert widget.spectrum.eta.value==.1
        assert 'Initial population' in widget.spectrum.transition_table.value
        assert 'p × Z × F' in widget.spectrum.selection_info.value
        assert 'Actual transition energies' in widget.result_identity.value
        widget.blend.value=True
        widget.cube_states.value=()  # Complete blend includes tails independently of a preview selection.
        widget._review_cubes()
        assert len(widget.cube_plan['parameters']['orbitals'])==4
        widget.set_view('kondo')
        assert widget.kondo_panel is None
        assert 'one initial spin multiplet' in widget.kondo_box.children[0].value
        widget.source_mode.value='single'
        assert widget.record is None and widget.process_uuid is None
        assert widget.cube.value is None and not widget.download.value
    finally:
        close_widget_tree(widget)
