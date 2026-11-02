"""Resource reviews, durable serial exports and cross-stage submission guards."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from aiida import common,engine,orm
from aiida.parsers import Parser
from aiida.engine.utils import instantiate_process
from aiida.engine import ProcessState
from aiida.common import LinkType
from aiida_empa_orca import dyson as backend
from aiidalab_orca import dyson_services,map_services,analysis_execution
from test_dyson import dataset,casci_state
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401
from test_maps import map_source,parameters

BUDGET={'memory_mb':2048,'wallclock_seconds':600}


class ProbeCalculation(engine.CalcJob):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.input('fail',valid_type=orm.Bool)
        spec.input('metadata.options.parser_name',default='test.l08_probe')
        spec.output('artifact',valid_type=orm.Dict)
        spec.output('transitions',valid_type=orm.Dict)
        spec.exit_code(400,'ERROR_PROBE',message='Intentional non-scientific failure')
    def prepare_for_submission(self,folder):
        code=common.CodeInfo();code.code_uuid=self.inputs.code.uuid;code.cmdline_params=[]
        info=common.CalcInfo();info.codes_info=[code];return info


class ProbeParser(Parser):
    def parse(self,**kwargs):
        if self.node.inputs.fail.value:return self.exit_codes.ERROR_PROBE
        self.out('artifact',orm.Dict(dict={'probe':True}))
        self.out('transitions',orm.Dict(dict={'probe':True}))


RealExport=backend.StateExportWorkChain
class ProbeExport(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.expose_inputs(RealExport)
        spec.output('artifact',valid_type=orm.Dict)
        spec.outline(cls.run_native,cls.inspect)
        spec.exit_code(400,'ERROR_PROBE',message='Intentional export failure')
    def run_native(self):
        from aiida_empa_orca.rendering import calcjob_options
        b=ProbeCalculation.get_builder();b.code=self.inputs.code
        b.fail=orm.Bool(self.inputs.state_energies.get_dict().get('probe_fail',False))
        p=self.inputs.export_resources.get_dict()
        b.metadata.options=calcjob_options(SimpleNamespace(creator=None),seconds=p['wallclock_seconds'],memory_mb=p['memory_mb'])
        return engine.ToContext(probe=self.submit(b))
    def inspect(self):
        if not self.ctx.probe.is_finished_ok:return self.exit_codes.ERROR_PROBE
        self.out('artifact',self.ctx.probe.outputs.artifact)


class SerialExportHarness(backend.DysonWorkChain):
    def setup(self):
        self.ctx.reuse_uuid=None
        self.ctx.selected=self.inputs.selection.get_dict()
        self.ctx.runtime=self.inputs.runtime.get_dict()
    def compute(self):
        from aiida_empa_orca.rendering import calcjob_options
        b=ProbeCalculation.get_builder();b.code=self.inputs.code;b.fail=orm.Bool(False)
        p=self.inputs.runtime.get_dict()
        b.metadata.options=calcjob_options(SimpleNamespace(creator=None),seconds=p['max_wallclock_seconds'],memory_mb=p['memory_mb'])
        return engine.ToContext(dyson=self.submit(b))


@pytest.mark.parametrize('fail',[False,True])
def test_real_engine_exports_one_state_at_a_time_before_compute(aiida_profile_clean,aiida_localhost,entry_points,monkeypatch,fail):
    entry_points.add(ProbeCalculation,'aiida.calculations:test.l08_probe')
    entry_points.add(ProbeParser,'aiida.parsers:test.l08_probe')
    entry_points.add(ProbeExport,'aiida.workflows:test.l08_export')
    entry_points.add(SerialExportHarness,'aiida.workflows:test.l08_serial')
    monkeypatch.setattr(backend,'StateExportWorkChain',ProbeExport)
    code=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/bin/true').store()
    b=SerialExportHarness.get_builder();b.code=b.export_code=code
    b.initial=orm.Dict(dict=dataset()|{'probe_fail':fail})
    for key,q,m in [('a',-1,1),('b',-1,3),('c',1,1),('d',1,3)]:b.finals[key]=orm.Dict(dict=dataset(q,m))
    b.selection=orm.Dict(dict={'initial_root':0,'final_roots':{k:[0] for k in ('a','b','c','d')},'max_missing_ci_norm':1e-5})
    b.storage_policy=orm.Dict(dict={'threshold_mb':0,'stash_directory':'/test'})
    b.export_resources=orm.Dict(dict=BUDGET)
    b.runtime=orm.Dict(dict={'workers':1,'memory_mb':2048,'max_wallclock_seconds':600})
    _,node=engine.run_get_node(b)
    assert node.exit_status==(401 if fail else 0)
    exports=sorted([n for n in node.called if isinstance(n,orm.WorkChainNode)],key=lambda n:n.ctime)
    assert len(exports)==(1 if fail else 5)
    for first,second in zip(exports,exports[1:]):assert first.mtime<=second.ctime
    jobs=sorted([n for n in node.called_descendants if isinstance(n,orm.CalcJobNode)],key=lambda n:n.ctime)
    assert len(jobs)==(1 if fail else 6)
    for first,second in zip(jobs,jobs[1:]):assert first.mtime<=second.ctime
    if not fail:assert exports[-1].mtime<=jobs[-1].ctime
    for job in jobs:
        assert job.get_option('max_wallclock_seconds')==600 and job.get_option('max_memory_kb')==2097152
        assert job.get_option('resources')=={'num_machines':1,'num_mpiprocs_per_machine':1}
    assert node.inputs.selection['max_missing_ci_norm']==1e-5


def test_export_and_cube_resource_ports_reach_real_calcjob_builders(common_reference,aiida_manager,monkeypatch):
    state,code_uuid=casci_state(common_reference)
    source=backend.state_source(state)
    code=orm.load_code(code_uuid)
    b=RealExport.get_builder();b.state_energies=state;b.code=b.helper_code=code
    b.storage_policy=orm.Dict(dict={'threshold_mb':0,'stash_directory':'/test'})
    b.export_resources=orm.Dict(dict=BUDGET)
    p=instantiate_process(aiida_manager.get_runner(),b)
    try:
        p.ctx.location={'uuid':common_reference[1]}
        captures=[];p.submit=lambda b:captures.append(b) or orm.CalcJobNode().store()
        p.run_export()
        assert captures[0].metadata.options.max_wallclock_seconds==600
        assert captures[0].metadata.options.max_memory_kb==2097152
        assert captures[0].metadata.options.resources['num_mpiprocs_per_machine']==1
        assert captures[0].retention_policy['mode']=='remote'
    finally:p.close()


def test_cross_stage_guard_blocks_same_reference_until_terminal(aiida_profile_clean):
    reference=str(orm.Dict(dict={}).store().uuid)
    initial=orm.Dict(dict={'orbital_reference_uuid':reference}).store()
    node=orm.WorkChainNode(process_type=backend.DYSON_PROCESS)
    node.base.links.add_incoming(initial,link_type=LinkType.INPUT_WORK,link_label='initial');node.store()
    node.set_process_state(ProcessState.RUNNING)
    with pytest.raises(ValueError,match=str(node.uuid)):analysis_execution.assert_idle(reference)
    analysis_execution.assert_idle('other-reference')
    node.set_process_state(ProcessState.FINISHED);node.set_exit_status(0)
    analysis_execution.assert_idle(reference)


def test_dyson_and_cube_budget_edits_invalidate_reviews_and_preserve_menus(monkeypatch):
    from aiidalab_orca.dyson import DysonStates
    rows=[dict(state_uuid=str(q),root=0,charge=q,multiplicity=2 if q==0 else 1,energy_hartree=-10.+q)
          for q in (0,-1,1)]
    monkeypatch.setattr(dyson_services,'states',lambda _:deepcopy(rows))
    monkeypatch.setattr(dyson_services,'codes',lambda _:{'export':[('export','export')],'dyson':[('tools','tools')],
        'cubehandler':[('cubehandler','cubehandler')],'storage_policy':{}})
    monkeypatch.setattr(dyson_services,'runs',lambda *_:[])
    plans=[]
    def review(*args,**kwargs):
        plans.append(kwargs)
        return {'action':'compute','exports':[],'retention_policy':kwargs['retention_policy']}
    monkeypatch.setattr(dyson_services,'review',review)
    widget=DysonStates('common',[{'reference_charge':0}])
    try:
        assert widget.loss.value==1e-5
        widget.review.click()
        assert plans[-1]['runtime']=={'workers':1,'memory_mb':2048,'max_wallclock_seconds':600}
        assert plans[-1]['export_resources']==BUDGET
        assert 'one at a time' in widget.message.value
        for control,new in [(widget.walltime,9),(widget.export_budget.memory,1024),(widget.export_budget.walltime,9)]:
            widget.review.click();control.value=new
            assert widget.plan is None and widget.submit.disabled
        submitted=[]
        monkeypatch.setattr(dyson_services,'submit_dyson',lambda plan:submitted.append(('dyson',plan)) or 'dyson-job')
        monkeypatch.setattr(dyson_services,'submit_cubes',lambda **kw:submitted.append(('cubes',kw)) or 'cube-job')
        monkeypatch.setattr(widget,'_start',lambda uid,kind:setattr(widget,'_job_uuid',uid))
        widget.review.click();widget.submit.click();widget.submit.click()
        assert [kind for kind,_ in submitted]==['dyson'] and widget.plan is None
        widget._job_uuid=None
        widget.record={'transitions_uuid':'transitions','data':{'transitions':[]}}
        widget.cube_states.options=[('one',0),('two',1)];widget.cube_states.value=(0,1)
        widget.spectrum=SimpleNamespace(blend=lambda:{})
        widget.retention.value='leave'
        assert all(w.layout.display!='none' for w in (widget.initial,widget.export_code,widget.retention,widget.cube))
        widget.cube_review.click()
        assert widget.cube_plan['resources']==BUDGET
        widget.cube_budget.walltime.value=9
        assert widget.cube_plan is None and widget.cube_submit.disabled
        widget.cube_budget.walltime.value=10;widget.cube_review.click()
        widget.cube_submit.click();widget.cube_submit.click()
        assert [kind for kind,_ in submitted]==['dyson','cubes'] and widget.cube_plan is None
        assert widget.loss.value==1e-5
    finally:
        widget.spectrum=None;widget.close()


def test_cube_budget_reaches_real_native_job(common_reference,aiida_manager):
    code=orm.load_code(common_reference[2]);remote=orm.load_node(common_reference[1])
    state,_=casci_state(common_reference)
    producer=orm.CalcJobNode(computer=code.computer,process_type='aiida.calculations:empa_orca.dyson')
    artifact=orm.Dict(dict={}).store()
    producer.base.links.add_incoming(artifact,link_type=LinkType.INPUT_CALC,link_label='artifacts__initial');producer.store()
    transitions=orm.Dict(dict={'orbital_reference_uuid':common_reference[0],'transitions':[{'id':'f_r0'}]})
    coefficients=orm.FolderData()
    for key,node in {'transitions':transitions,'retrieved':coefficients,'remote_folder':orm.RemoteData(computer=code.computer,remote_path='/probe')}.items():
        node.base.links.add_incoming(producer,link_type=LinkType.CREATE,link_label=key);node.store()
    producer.set_process_state(ProcessState.FINISHED);producer.set_exit_status(0)
    b=backend.DysonCubesWorkChain.get_builder();b.transitions=transitions
    b.code=b.cubehandler_code=code
    b.cube_resources=orm.Dict(dict=BUDGET)
    b.parameters=orm.Dict(dict={'orbitals':[[0,0]],'grid_points':80,'retention':'leave'})
    parent=instantiate_process(aiida_manager.get_runner(),b);children=[]
    def capture(b):
        child=instantiate_process(aiida_manager.get_runner(),b);children.append(child);return child.node
    parent.submit=capture
    try:
        from aiida_empa_orca.dyson_mixture import cube_source
        parent.ctx.source=cube_source(transitions)
        parent.ctx.location={'uuid':str(remote.uuid),'kind':'remote'}
        parent.generate()
        assert len(children)==1
        child=children[0].node
        assert child.get_option('max_wallclock_seconds')==600 and child.get_option('max_memory_kb')==2097152
        assert child.get_option('resources')=={'num_machines':1,'num_mpiprocs_per_machine':1}
        assert child.inputs.parameters['retention']=='leave' and not child.get_option('stash')
    finally:
        for child in children:child.close()
        parent.close()


def test_map_and_figure_budgets_reach_actual_calcjobs(aiida_profile_clean,aiida_localhost,aiida_manager,tmp_path):
    import numpy as np
    from aiida_empa_orca.maps import MAP_PROCESS
    cube,table,code=map_source(aiida_localhost,tmp_path)
    before=orm.QueryBuilder().append(orm.ProcessNode).count()
    plan=map_services.prepare_maps(cube.uuid,parameters(),str(code.uuid),resources=BUDGET)
    assert orm.QueryBuilder().append(orm.ProcessNode).count()==before
    b=map_services.maps_builder(plan)
    job=instantiate_process(aiida_manager.get_runner(),b)
    try:
        assert job.node.get_option('max_memory_kb')==2097152 and job.node.get_option('max_wallclock_seconds')==600
        assert job.node.get_option('resources')=={'num_machines':1,'num_mpiprocs_per_machine':1}
        assert b.parameters.get_dict()==map_services.stored_values(parameters())
    finally:job.close()
    # A completed numerical-map source; no calculation or rendering is executed.
    source=orm.CalcJobNode(computer=code.computer,process_type=MAP_PROCESS)
    source.base.links.add_incoming(table,link_type=LinkType.INPUT_CALC,link_label='transitions');source.store()
    arrays=orm.ArrayData();arrays.set_array('intensity',np.ones((1,2,32,32)))
    for key,node in {'maps':arrays,'map_metadata':orm.Dict(dict={'parameters':parameters()}),
                     'remote_folder':orm.RemoteData(computer=code.computer,remote_path=str(tmp_path))}.items():
        node.base.links.add_incoming(source,link_type=LinkType.CREATE,link_label=key);node.store()
    source.set_process_state(ProcessState.FINISHED);source.set_exit_status(0)
    p=map_services.prepare_figure(str(source.uuid),{'vmin':0.,'vmax':1.},str(code.uuid),resources=BUDGET)
    figure=instantiate_process(aiida_manager.get_runner(),map_services.figure_builder(p))
    try:
        assert figure.node.get_option('max_memory_kb')==2097152 and figure.node.get_option('max_wallclock_seconds')==600
        assert figure.node.get_option('resources')=={'num_machines':1,'num_mpiprocs_per_machine':1}
        assert figure.inputs.settings['vmin']==0 and figure.inputs.settings['vmax']==1
    finally:figure.close()


def test_map_figure_review_invalidation_and_duplicate_submit(monkeypatch):
    import ipywidgets as ipw
    import numpy as np
    from ase import Atoms
    from aiidalab_orca import maps as frontend
    source={'table_input':'transitions','table':{'transitions':[{'id':'a'}]},
        'manifest':{'cubes':[{'kind':'dyson','transition_id':'a','filename':'a.cube'}]}}
    monkeypatch.setattr(map_services,'source_data',lambda _:deepcopy(source))
    monkeypatch.setattr(map_services,'map_history',lambda _:[])
    monkeypatch.setattr(frontend,'preview_content',lambda *_:'probe')
    monkeypatch.setattr(frontend,'read_cube',lambda _:{'data':np.ones((5,5,5)),'spacing':np.eye(3),
        'atoms':Atoms('H2',positions=[[0,0,0],[0,0,1]])})
    cut=SimpleNamespace(center_txt=ipw.Text(),normal_txt=ipw.Text(),offset_txt=ipw.Text(),
        width=ipw.FloatText(value=3),height=ipw.FloatText(value=3),res=ipw.IntSlider(value=32,min=1,max=256))
    cut.return_settings=lambda:dict(center=list(map(float,cut.center_txt.value.split())),normal=list(map(float,cut.normal_txt.value.split())),
        offset=float(cut.offset_txt.value),width=cut.width.value,height=cut.height.value,resolution=cut.res.value)
    viewer=SimpleNamespace(slice2d=cut,viewer3d=SimpleNamespace(show_plane_checkbox=ipw.Checkbox()))
    spin=ipw.Dropdown(options=['unpolarized'],value='unpolarized')
    spectrum=SimpleNamespace(spin=spin,blend=lambda:dict(energy_ev=0.,eta_ev=.1))
    calls=[]
    monkeypatch.setattr(map_services,'prepare_maps',lambda *args,**kw:{'action':'compute','resources':kw['resources']})
    monkeypatch.setattr(map_services,'prepare_figure',lambda *args,**kw:{'action':'compute','resources':kw['resources']})
    monkeypatch.setattr(map_services,'submit_maps',lambda plan:calls.append(('maps',plan)) or 'map-job')
    monkeypatch.setattr(map_services,'submit_figure_plan',lambda plan:calls.append(('figure',plan)) or 'figure-job')
    panel=frontend.DysonMaps('cube',viewer,spectrum,'code')
    monkeypatch.setattr(panel,'_start',lambda *args:setattr(panel,'_task',SimpleNamespace(cancel=lambda:None)))
    try:
        panel.review.click();assert panel.plan['resources']==BUDGET
        panel.map_budget.walltime.value=9
        assert panel.plan is None and panel.compute.disabled
        panel.map_budget.walltime.value=10;panel.review.click()
        panel.compute.click();panel.compute.click()
        assert [kind for kind,_ in calls]==['maps'] and panel.plan is None
        panel.map_uuid='map';panel.figure_review.click();assert panel.figure_plan is None
        panel._task=None;panel.figure_review.click();assert panel.figure_plan['resources']==BUDGET
        panel.figure_budget.memory.value=1024
        assert panel.figure_plan is None and panel.render.disabled
        panel.figure_budget.memory.value=2048;panel.figure_review.click();panel.vmax.value=2
        assert panel.figure_plan is None and panel.render.disabled
        panel.figure_review.click();panel.normalization.value='per_panel'
        assert panel.figure_plan is None and panel.render.disabled
        panel.figure_review.click();panel.render.click();panel.render.click()
        assert [kind for kind,_ in calls]==['maps','figure']
        assert panel.figure_plan is None
    finally:
        panel.close();spin.close()
        for value in vars(cut).values():
            if isinstance(value,ipw.Widget):value.close()
        viewer.viewer3d.show_plane_checkbox.close()


def test_serial_export_uuid_handoff_reaches_dyson_budget_without_changing_norm_limit(common_reference,aiida_manager,monkeypatch):
    initial,code_uuid=casci_state(common_reference)
    final,_=casci_state(common_reference,1,1)
    code=orm.load_code(code_uuid);remote=orm.load_node(common_reference[1])
    b=backend.DysonWorkChain.get_builder();b.initial=initial;b.finals.f=final
    b.code=b.export_code=code
    selected={'initial_root':0,'final_roots':{'f':[0]},'max_missing_ci_norm':1e-5}
    b.selection=orm.Dict(dict=selected)
    b.storage_policy=orm.Dict(dict={'threshold_mb':0,'stash_directory':'/test'})
    b.runtime=orm.Dict(dict={'workers':1,'memory_mb':2048,'max_wallclock_seconds':600})
    b.export_resources=orm.Dict(dict=BUDGET)
    parent=instantiate_process(aiida_manager.get_runner(),b);children=[]
    def capture(b):
        child=instantiate_process(aiida_manager.get_runner(),b);children.append(child);return child.node
    parent.submit=capture
    monkeypatch.setattr(backend,'export_location',lambda _:{'uuid':str(remote.uuid),'kind':'remote','files':[]})
    try:
        parent.ctx.reuse_uuid=None;parent.ctx.selected=selected;parent.ctx.runtime=b.runtime.get_dict()
        parent.ctx.export_uuids={}
        for key,state in [('initial',initial),('f',final)]:
            export=orm.WorkChainNode(process_type=backend.EXPORT_PROCESS).store()
            artifact=orm.Dict(dict={'state_uuid':str(state.uuid),'identity':state.get_dict(),
                                   'ci_norms':{'0':1.,'1':1.}}).store()
            artifact.base.links.add_incoming(export,link_type=LinkType.RETURN,link_label='artifact')
            export.set_process_state(ProcessState.FINISHED);export.set_exit_status(0)
            parent.ctx.export_uuids[key]=str(export.uuid)
        parent.compute()
        assert len(children)==1
        job=children[0].node
        assert job.get_option('max_wallclock_seconds')==600 and job.get_option('max_memory_kb')==2097152
        assert job.get_option('resources')=={'num_machines':1,'num_mpiprocs_per_machine':1}
        assert job.inputs.selection.get_dict()==selected
        assert job.inputs.runtime['workers']==1
    finally:
        for child in children:child.close()
        parent.close()
