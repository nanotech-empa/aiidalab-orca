"""Reviewed Kondo budgets and serial, non-scientific execution probes."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib

import pytest
from aiida import common, engine, orm
from aiida.common import LinkType
from aiida.engine import ProcessState
from aiida.engine.utils import instantiate_process
from aiida.parsers import Parser

from aiida_empa_orca import kondo as backend
from aiidalab_orca import kondo_services as service, analysis_execution
from test_kondo import table

BUDGET={'memory_mb':2048,'wallclock_seconds':600}


def output(producer,label,node):
    node.base.links.add_incoming(producer,link_type=LinkType.CREATE,link_label=label)
    node.store()
    return node


def finished(node):
    node.set_process_state(ProcessState.FINISHED);node.set_exit_status(0)


@pytest.fixture
def sources(aiida_profile_clean,aiida_localhost,tmp_path):
    code=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/bin/true').store()
    reference=str(orm.Dict(dict={}).store().uuid)
    t=table();t['orbital_reference_uuid']=reference
    state=orm.CalcJobNode(computer=aiida_localhost,process_type='aiida.calculations:empa_orca.casci')
    state.base.links.add_incoming(code,link_type=LinkType.INPUT_CALC,link_label='code');state.store()
    energies=output(state,'state_energies',orm.Dict(dict={'orbital_reference_uuid':reference}))
    remote=output(state,'remote_folder',orm.RemoteData(computer=aiida_localhost,remote_path=str(tmp_path)))
    (tmp_path/'aiida.gbw').write_bytes(b'probe')
    t['initial_state_uuid']=str(energies.uuid);finished(state)
    exporter=orm.CalcJobNode(computer=aiida_localhost,process_type='aiida.calculations:empa_orca.dyson_export')
    exporter.base.links.add_incoming(energies,link_type=LinkType.INPUT_CALC,link_label='state_energies');exporter.store()
    artifact=output(exporter,'artifact',orm.Dict(dict={'state_uuid':str(energies.uuid),
        'source_gbw_sha256':hashlib.sha256(b'probe').hexdigest(),
        'identity':{'orbital_reference_uuid':reference,'active_space':{'orbitals':[0]}}}));finished(exporter)
    dyson=orm.CalcJobNode(computer=aiida_localhost,process_type='aiida.calculations:empa_orca.dyson')
    dyson.base.links.add_incoming(artifact,link_type=LinkType.INPUT_CALC,link_label='artifacts__initial');dyson.store()
    transitions=output(dyson,'transitions',orm.Dict(dict=t))
    output(dyson,'remote_folder',orm.RemoteData(computer=aiida_localhost,remote_path=str(tmp_path/'dyson')));finished(dyson)
    run=orm.CalcJobNode(computer=aiida_localhost,process_type='aiida.calculations:empa_orca.kondo')
    run.base.links.add_incoming(transitions,link_type=LinkType.INPUT_CALC,link_label='transitions');run.store()
    channels=output(run,'channels',orm.Dict(dict=backend.exchange(t,{'chemical_potential_ev':.5})));finished(run)
    return dict(code=str(code.uuid),reference=reference,transitions=str(transitions.uuid),
                channels=str(channels.uuid),remote=str(remote.uuid))


def check_options(builder):
    o=builder.metadata.options
    assert o.resources=={'num_machines':1,'num_mpiprocs_per_machine':1}
    assert o.max_wallclock_seconds==600 and o.max_memory_kb==2097152 and not o.withmpi


def test_reviewed_budgets_reach_all_three_real_native_builders(sources,aiida_manager,monkeypatch):
    monkeypatch.setattr(service,'native_plot_code',lambda _:sources['code'])
    plan=service.prepare(sources['transitions'],.5,sources['code'],resources=BUDGET)
    b=service.channels_builder(plan);assert b.channel_resources.get_dict()==BUDGET
    parent=instantiate_process(aiida_manager.get_runner(),b);captured=[]
    parent.submit=lambda builder:captured.append(builder) or orm.CalcJobNode().store()
    try:
        parent.ctx.parameters=plan['parameters'];parent.compute()
        check_options(captured.pop())
    finally:parent.close()
    values=dict(orbitals=[[0,0]],grid_points=80,retention='leave')
    plan=service.prepare_cubes(sources['channels'],values,sources['code'],sources['code'],
                              resources=BUDGET,reference_resources=BUDGET)
    assert plan['reference_orbitals']==[0]
    b=service.cubes_builder(plan)
    assert b.cube_resources.get_dict()==b.reference_resources.get_dict()==BUDGET
    parent=instantiate_process(aiida_manager.get_runner(),b)
    parent.submit=lambda builder:captured.append(builder) or orm.CalcJobNode().store()
    monkeypatch.setattr(backend,'resolve_electronic',lambda *a,**kw:{'uuid':sources['remote'],
        'kind':'remote','files':[{'name':'aiida.gbw','size_bytes':5}]})
    try:
        parent._prepare_reference()
        native=captured.pop();check_options(native)
        assert native.parameters['retention']=='leave' and native.parameters['grid_points']==80
        assert native.orbital_identity['source_gbw_sha256']==hashlib.sha256(b'probe').hexdigest()
        parent.ctx.native_uuid=None;parent.ctx.location={'uuid':sources['remote'],'kind':'remote'}
        parent.compute();channel=captured.pop();check_options(channel)
        assert channel.parameters['retention']=='leave' and channel.parameters['grid_points']==80
        assert channel.channels.uuid==orm.load_node(sources['channels']).uuid
    finally:parent.close()


@pytest.mark.parametrize('name',['channel_resources','reference_resources','cube_resources'])
def test_invalid_budget_stops_before_any_native_submission(sources,aiida_manager,name):
    if name=='channel_resources':
        b=backend.KondoWorkChain.get_builder();b.transitions=orm.load_node(sources['transitions'])
        b.parameters=orm.Dict(dict={'chemical_potential_ev':.5})
    else:
        b=backend.KondoCubesWorkChain.get_builder();b.channels=orm.load_node(sources['channels'])
        b.parameters=orm.Dict(dict={'orbitals':[[0,0]],'grid_points':80,'retention':'leave'})
        b.cubehandler_code=orm.load_code(sources['code'])
    b.code=orm.load_code(sources['code']);b[name]=orm.Dict(dict={'memory_mb':2048,'wallclock_seconds':0})
    parent=instantiate_process(aiida_manager.get_runner(),b)
    parent.submit=lambda _:pytest.fail('Invalid budget reached native submission')
    try:assert parent.setup().status==400
    finally:parent.close()


class ProbeCalculation(engine.CalcJob):
    @classmethod
    def define(cls,spec):
        super().define(spec);spec.input('fail',valid_type=orm.Bool)
        spec.input('metadata.options.parser_name',default='test.l09_probe')
        spec.output('manifest',valid_type=orm.Dict)
        spec.exit_code(400,'ERROR_PROBE',message='Intentional dummy failure')
    def prepare_for_submission(self,folder):
        code=common.CodeInfo();code.code_uuid=self.inputs.code.uuid
        info=common.CalcInfo();info.codes_info=[code];return info


class ProbeParser(Parser):
    def parse(self,**kwargs):
        if self.node.inputs.fail.value:return self.exit_codes.ERROR_PROBE
        self.out('manifest',orm.Dict(dict={'probe':True}))


class SerialCubesHarness(backend.KondoCubesWorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec);spec.input('fail_reference',valid_type=orm.Bool)
    def setup(self):
        self.ctx.reuse_uuid=None;self.ctx.native_uuid=None
    def _probe(self,budget,fail):
        b=ProbeCalculation.get_builder();b.code=self.inputs.code;b.fail=orm.Bool(fail)
        b.metadata.options={'resources':{'num_machines':1,'num_mpiprocs_per_machine':1},
            'max_memory_kb':budget['memory_mb']*1024,'max_wallclock_seconds':budget['wallclock_seconds'],'withmpi':False}
        return self.submit(b)
    def _prepare_reference(self):
        job=self._probe(self.inputs.reference_resources.get_dict(),self.inputs.fail_reference.value)
        self.ctx.native_uuid=str(job.uuid);return engine.ToContext(native=job)
    def compute(self):
        job=self._probe(self.inputs.cube_resources.get_dict(),False)
        self.ctx.job_uuid=str(job.uuid);return engine.ToContext(finished=job)


@pytest.mark.parametrize('fail',[False,True])
def test_real_outline_waits_for_reference_and_stops_on_error(aiida_profile_clean,aiida_localhost,entry_points,monkeypatch,fail):
    entry_points.add(ProbeCalculation,'aiida.calculations:test.l09_probe')
    entry_points.add(ProbeParser,'aiida.parsers:test.l09_probe')
    entry_points.add(SerialCubesHarness,'aiida.workflows:test.l09_serial')
    monkeypatch.setattr(backend,'native_location',lambda _:{'uuid':'plain-reference','kind':'remote'})
    code=orm.InstalledCode(computer=aiida_localhost,filepath_executable='/bin/true').store()
    b=SerialCubesHarness.get_builder();b.code=b.cubehandler_code=b.plot_code=code
    b.channels=orm.Dict(dict={});b.parameters=orm.Dict(dict={});b.fail_reference=orm.Bool(fail)
    b.reference_resources=orm.Dict(dict=BUDGET);b.cube_resources=orm.Dict(dict=BUDGET)
    _,run=engine.run_get_node(b)
    assert run.exit_status==(401 if fail else 0)
    jobs=sorted(run.called,key=lambda n:n.ctime);assert len(jobs)==(1 if fail else 2)
    for job in jobs:
        assert job.get_option('max_memory_kb')==2097152 and job.get_option('max_wallclock_seconds')==600
    if not fail:assert jobs[0].mtime<=jobs[1].ctime


@pytest.mark.parametrize('process_type,input_name',[
    (backend.PROCESS,'transitions'),(backend.CUBES_PROCESS,'channels'),
    ('aiida.calculations:empa_orca.kondo_reference_cubes','state_energies'),
    ('aiida.calculations:empa_orca.kondo_maps','channels')])
def test_busy_guard_blocks_kondo_stages_for_same_reference(aiida_profile_clean,process_type,input_name):
    ref=str(orm.Dict(dict={}).store().uuid);data=orm.Dict(dict={'orbital_reference_uuid':ref}).store()
    cls=orm.WorkChainNode if process_type.startswith('aiida.workflows') else orm.CalcJobNode
    node=cls(process_type=process_type)
    node.base.links.add_incoming(data,link_type=LinkType.INPUT_WORK if cls is orm.WorkChainNode else LinkType.INPUT_CALC,link_label=input_name)
    node.store();node.set_process_state(ProcessState.RUNNING)
    with pytest.raises(ValueError,match=str(node.uuid)):analysis_execution.assert_idle(ref)
    analysis_execution.assert_idle('other')
    finished(node);analysis_execution.assert_idle(ref)


def test_submission_adapters_recheck_persistent_busy_state(sources,monkeypatch):
    monkeypatch.setattr(service,'native_plot_code',lambda _:sources['code'])
    plan=service.prepare(sources['transitions'],.5,sources['code'],resources=BUDGET)
    cubes=service.prepare_cubes(sources['channels'],{'orbitals':[[0,0]],'grid_points':80,'retention':'leave'},
        sources['code'],sources['code'],resources=BUDGET,reference_resources=BUDGET)
    busy=orm.WorkChainNode(process_type=backend.CUBES_PROCESS)
    busy.base.links.add_incoming(orm.load_node(sources['channels']),link_type=LinkType.INPUT_WORK,link_label='channels')
    busy.store();busy.set_process_state(ProcessState.RUNNING)
    monkeypatch.setattr(service,'submit',lambda _:pytest.fail('Busy source reached submission'))
    with pytest.raises(ValueError,match=str(busy.uuid)):service.submit_channels(plan)
    with pytest.raises(ValueError,match=str(busy.uuid)):service.submit_reviewed_cubes(cubes)


def test_all_budget_edits_invalidate_and_each_submit_consumes_its_review(monkeypatch):
    from aiidalab_orca.kondo import KondoChannels
    monkeypatch.setattr(service,'history',lambda _:[])
    monkeypatch.setattr(service,'prepare',lambda *args,**kw:dict(stability_interval_ev=[-3,2],warnings=[],resources=kw['resources']))
    monkeypatch.setattr(service,'prepare_cubes',lambda *args,**kw:dict(reference_orbitals=[10,11,12],**kw))
    calls=[]
    monkeypatch.setattr(service,'submit_channels',lambda p:calls.append(('channels',deepcopy(p))) or 'channels')
    monkeypatch.setattr(service,'submit_reviewed_cubes',lambda p:calls.append(('cubes',deepcopy(p))) or 'cubes')
    widget=KondoChannels('table','tools','cubehandler')
    monkeypatch.setattr(widget,'_start',lambda *args:None)
    try:
        for field in (widget.channel_budget.memory,widget.channel_budget.walltime):
            widget.review.click();assert not widget.submit.disabled
            field.value=field.value-1;assert widget.plan is None and widget.submit.disabled
        widget.channel_budget.memory.value=2048;widget.channel_budget.walltime.value=10
        widget.review.click();assert '2 GiB' in widget.message.value
        widget.submit.click();widget.submit.click();assert len(calls)==1 and widget.plan is None
        widget.record={'channels_uuid':'channels'};widget.channels.options=[('ko_1',0),('ko_2',1)];widget.channels.value=(0,1)
        assert widget.retention.value=='leave' and widget.grid.value==80
        assert all(w.layout.display!='none' for w in (widget.previous,widget.retention,widget.cube_previous,widget.cube))
        for control in (widget.reference_budget.memory,widget.reference_budget.walltime,widget.cube_budget.memory,widget.cube_budget.walltime):
            widget.cube_review.click();assert not widget.generate.disabled
            control.value=control.value-1;assert widget.cube_plan is None and widget.generate.disabled
            control.value=2048 if control in (widget.reference_budget.memory,widget.cube_budget.memory) else 10
        widget.cube_review.click();assert 'one after the other' in widget.cube_message.value
        widget.generate.click();widget.generate.click();assert [kind for kind,_ in calls]==['channels','cubes']
        assert calls[-1][1]['resources']==calls[-1][1]['reference_resources']==BUDGET
        widget._task=SimpleNamespace()
        widget.review.click();widget.cube_review.click()
        assert widget.plan is None and widget.cube_plan is None
        widget._task=None
    finally:widget._task=None;widget.close()
