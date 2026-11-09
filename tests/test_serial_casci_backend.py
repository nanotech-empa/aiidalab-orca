"""Serial batches wait on terminal sector/native jobs and preserve failures."""
import pytest
from aiida import engine,orm,common
from aiida.parsers import Parser
from aiida.engine.utils import instantiate_process
from aiida_empa_orca import casci,casci_batch as backend
from aiidalab_orca import casci_batch as review,casci_services as service
from test_l06_resources import completed_common  # noqa: F401
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401


class ProbeCalculation(engine.CalcJob):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.input('fail',valid_type=orm.Bool)
        spec.input('metadata.options.parser_name',default='test.casci_probe')
        spec.exit_code(400,'ERROR_PROBE',message='Intentional non-scientific failure')
    def prepare_for_submission(self,folder):
        code=common.CodeInfo();code.code_uuid=self.inputs.code.uuid;code.cmdline_params=[]
        info=common.CalcInfo();info.codes_info=[code];return info


class ProbeParser(Parser):
    def parse(self,**kwargs):
        if self.node.inputs.fail.value:return self.exit_codes.ERROR_PROBE


class ProbeSector(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.input('code',valid_type=orm.AbstractCode)
        spec.input('settings',valid_type=orm.Dict)
        spec.input('fail',valid_type=orm.Bool)
        spec.outline(cls.run_probe,cls.inspect)
        spec.exit_code(400,'ERROR_PROBE',message='Intentional non-scientific sector failure')
    def run_probe(self):
        from aiida_empa_orca.common_orbitals import options
        b=ProbeCalculation.get_builder();b.code=self.inputs.code;b.fail=self.inputs.fail
        b.metadata.options=options(self.inputs.settings.get_dict())
        return engine.ToContext(probe=self.submit(b))
    def inspect(self):
        if not self.ctx.probe.is_finished_ok:return self.exit_codes.ERROR_PROBE


@pytest.fixture
def plan(completed_common,entry_points):
    entry_points.add(backend.CasciBatchWorkChain,'aiida.workflows:empa_orca.casci_batch')
    uid,_,_=completed_common
    values={'nroots':1,'auxiliary_basis':'def2-SVP/C','nprocs':2,'memory_mb':2048,'wallclock_seconds':600}
    return review.prepare_batch(uid,3,2,[0,1,-1],[1,2],values,
        native_output_policy={'mode':'remote','maxsizeoutput':5*1024**2})


@pytest.fixture
def probes(entry_points,monkeypatch):
    entry_points.add(ProbeSector,'aiida.workflows:test.casci_sector')
    entry_points.add(ProbeCalculation,'aiida.calculations:test.casci_probe')
    entry_points.add(ProbeParser,'aiida.parsers:test.casci_probe')
    def builder(self,request):
        b=ProbeSector.get_builder();b.code=self.inputs.code;b.settings=orm.Dict(dict=request['settings'])
        b.fail=orm.Bool(self.ctx.get('fail_first',False) and self.ctx.index==0)
        b.metadata.call_link_label=f'sector_{self.ctx.index:04d}'
        return b
    monkeypatch.setattr(backend.CasciBatchWorkChain,'sector_builder',builder)
    return builder


@pytest.mark.parametrize('fail',[False,True])
def test_real_engine_waits_between_all_sector_and_native_jobs(plan,probes,monkeypatch,fail):
    def build(self,request):
        b=probes(self,request);b.fail=orm.Bool(fail and self.ctx.index==0);return b
    monkeypatch.setattr(backend.CasciBatchWorkChain,'sector_builder',build)
    outputs,parent=engine.run_get_node(service.casci_batch_builder(plan))
    assert parent.exit_status==(401 if fail else 0)
    sectors=sorted(parent.called,key=lambda n:n.ctime)
    assert len(sectors)==3
    for first,second in zip(sectors,sectors[1:]):
        assert first.is_terminated and first.mtime<=second.ctime
        assert first.called[0].mtime<=second.called[0].ctime
    jobs=[s.called[0] for s in sectors]
    for job in jobs:
        assert job.get_option('max_wallclock_seconds')==600
        assert job.get_option('max_memory_kb')==2097152
        assert job.get_option('resources')=={'num_machines':1,'num_mpiprocs_per_machine':2}
    rows=outputs['report']['sectors']
    assert [r['success'] for r in rows]==[not fail,True,True]
    assert all(r['finished'] and r['uuid'] for r in rows)
    progress=service.casci_batch_progress(str(parent.uuid))
    assert progress['finished'] and progress['sectors']==rows


def test_submission_error_stops_queue_and_retains_completed_uuid(plan,probes,monkeypatch):
    def build(self,request):
        if self.ctx.index==1:raise RuntimeError('submission unavailable')
        return probes(self,request)
    monkeypatch.setattr(backend.CasciBatchWorkChain,'sector_builder',build)
    outputs,parent=engine.run_get_node(service.casci_batch_builder(plan))
    assert parent.exit_status==401 and len(parent.called)==1
    rows=outputs['report']['sectors']
    assert rows[0]['success'] and rows[0]['uuid']==str(parent.called[0].uuid)
    assert rows[1]['state']=='submission failed' and 'submission unavailable' in rows[1]['message']
    assert rows[2]['state']=='not submitted' and rows[2]['uuid'] is None


def test_actual_sector_builder_keeps_model_retention_and_native_limits(plan,aiida_manager):
    parent=instantiate_process(aiida_manager.get_runner(),service.casci_batch_builder(plan))
    child=None
    try:
        assert parent.setup() is None
        b=parent.sector_builder(parent.inputs.requests.get_list()[0])
        assert b.active_space.get_dict()==plan['active_space']
        assert b.native_output_policy.get_dict()=={'mode':'remote','maxsizeoutput':5*1024**2}
        child=instantiate_process(aiida_manager.get_runner(),b)
        assert child.setup() is None
        assert not child.should_stash_wavefunction()
        native=[];child.submit=lambda b:native.append(b) or orm.CalcJobNode().store()
        child.run_casci();assert len(native)==1
        assert native[0].metadata.options.max_wallclock_seconds==600
        assert native[0].metadata.options.max_memory_kb==2097152
        assert native[0].metadata.options.resources['num_mpiprocs_per_machine']==2
        assert native[0].native_output_policy.get_dict()==b.native_output_policy.get_dict()
    finally:
        if child:child.close()
        parent.close()


def test_reopening_blocks_duplicate_batch_and_reports_queue(plan,aiida_manager):
    parent=instantiate_process(aiida_manager.get_runner(),service.casci_batch_builder(plan))
    try:
        assert service.active_casci_batch(plan['reference_uuid'])==str(parent.node.uuid)
        with pytest.raises(ValueError,match='already active'):service.casci_batch_builder(plan)
        fresh=review.prepare_batch(plan['reference_uuid'],3,2,[0,1],[1,2],
            {'nroots':1,'nprocs':2,'memory_mb':2048,'wallclock_seconds':600})
        assert not fresh['ready'] and fresh['active_batch_uuid']==str(parent.node.uuid)
        status=service.casci_batch_progress(str(parent.node.uuid))
        assert not status['finished'] and all(r['state']=='queued' for r in status['sectors'])
    finally:parent.close()


def test_saved_sectors_are_reused_without_new_native_children(plan):
    from aiida.common import LinkType
    from aiida.engine import ProcessState
    b=service.casci_batch_builder(plan)
    requests=b.requests.get_list()
    for request in requests:
        old=orm.WorkChainNode(process_type=casci.PROCESS_TYPE)
        for key,value in {'orbital_reference':b.orbital_reference,'active_space':b.active_space,
                          'settings':orm.Dict(dict=request['settings']),'code':b.code}.items():
            value.store();old.base.links.add_incoming(value,link_type=LinkType.INPUT_WORK,link_label=key)
        old.store();old.set_process_state(ProcessState.FINISHED);old.set_exit_status(0)
        request.update(action='reuse',uuid=str(old.uuid))
    b.requests=orm.List(list=requests)
    outputs,parent=engine.run_get_node(b)
    assert parent.is_finished_ok and not parent.called_descendants
    assert all(row['state']=='reused' and row['success'] for row in outputs['report']['sectors'])
