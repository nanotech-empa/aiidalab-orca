"""Await an existing DMRG study and recover a scheduler timeout once."""
from aiida import engine, orm
from .dmrg import file_sha256
from .dmrg_storage import checkpoint_node
from .dmrg_workchain import DmrgConvergenceWorkChain


def confirmed_timeout(workflow_exit, calcjob_exit, scheduler_error):
    return workflow_exit == 402 and calcjob_exit == 310 and 'DUE TO TIME LIMIT' in scheduler_error


@engine.calcfunction
def recovery_manifest(previous_report, interrupted_outputs, checkpoint_states, request):
    """Explicitly link the failed run and completed restart checkpoint."""
    return orm.Dict(dict=request.get_dict())


class DmrgTimeoutRecoveryWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('previous_workflow_uuid', valid_type=orm.Str)
        spec.input('current_remote_folder', valid_type=orm.RemoteData)
        spec.input('wallclock_seconds', valid_type=orm.Int, default=lambda: orm.Int(72*3600))
        spec.output('convergence', valid_type=orm.Dict, required=False)
        spec.output('final_results', valid_type=orm.Dict, required=False)
        spec.output('states', valid_type=(orm.FolderData, orm.RemoteData), required=False)
        spec.exit_code(401, 'ERROR_NOT_TIMEOUT', message='Existing study needs inspection; no timeout continuation was submitted.')
        spec.exit_code(402, 'ERROR_CONTINUATION', message='The longer continuation did not establish convergence; inspect retained outputs.')
        spec.outline(cls.await_previous, cls.decide,
            engine.if_(cls.needs_recovery)(cls.submit_recovery, cls.inspect_recovery), cls.results)

    def await_previous(self):
        identifier = self.inputs.previous_workflow_uuid.value
        previous = orm.load_node(identifier)
        source = self.inputs.current_remote_folder.creator
        if (previous.process_type != 'aiida.workflows:empa_orca.dmrg_convergence' or
                source is None or source.caller is None or str(source.caller.uuid) != identifier or
                file_sha256(source.inputs.hamiltonian) != file_sha256(previous.inputs.hamiltonian) or
                not 8*3600 < self.inputs.wallclock_seconds.value <= 72*3600):
            return self.exit_codes.ERROR_NOT_TIMEOUT
        self.ctx.previous_uuid = identifier
        self.ctx.source_uuid = str(source.uuid)
        self.ctx.replacement_uuid = None
        self.node.base.extras.set('dmrg_recovery_progress', {'phase': 'awaiting-existing-study',
            'previous_workflow_uuid': identifier, 'current_calcjob_uuid': str(source.uuid),
            'wallclock_seconds': self.inputs.wallclock_seconds.value, 'qpu_jobs_submitted': 0})
        return engine.ToContext(_engine_previous=previous)

    def decide(self):
        self.ctx.pop('_engine_previous', None)
        previous = orm.load_node(self.ctx.previous_uuid)
        source = orm.load_node(self.ctx.source_uuid)
        if previous.is_finished_ok:
            self.ctx.result_uuid = self.ctx.previous_uuid
            self.node.base.extras.set('dmrg_recovery_progress', {'phase': 'existing-study-succeeded',
                'previous_workflow_uuid': self.ctx.previous_uuid, 'qpu_jobs_submitted': 0})
            return
        current = previous.base.extras.get('dmrg_progress', {}).get('current', {})
        if (current.get('uuid') != self.ctx.source_uuid or current.get('phase') != 'target' or
                previous.exit_status != 402 or source.exit_status != 310 or 'retrieved' not in source.outputs):
            return self.exit_codes.ERROR_NOT_TIMEOUT
        try:
            error = source.outputs.retrieved.base.repository.get_object_content('_scheduler-stderr.txt')
        except OSError:
            return self.exit_codes.ERROR_NOT_TIMEOUT
        if not confirmed_timeout(previous.exit_status, source.exit_status, error):
            return self.exit_codes.ERROR_NOT_TIMEOUT
        self.ctx.should_recover = True

    def needs_recovery(self):
        return self.ctx.get('should_recover', False)

    def submit_recovery(self):
        previous = orm.load_node(self.ctx.previous_uuid)
        interrupted = orm.load_node(self.ctx.source_uuid)
        adopted = {'validation': {}, 'target': {}}
        for record in previous.base.extras.get('dmrg_progress')['completed']:
            source = orm.load_node(record['uuid'])
            if source.exit_status not in [0, 311] or 'results' not in source.outputs:
                return self.exit_codes.ERROR_NOT_TIMEOUT
            adopted[record['phase']][str(record['bond_dimension'])] = str(source.uuid)
        if not adopted['target']:
            return self.exit_codes.ERROR_NOT_TIMEOUT
        last_bond = max(int(bond) for bond in adopted['target'])
        parent = orm.load_node(adopted['target'][str(last_bond)])
        parent_checkpoint = checkpoint_node(parent)
        plan = previous.inputs.plan.get_dict()
        plan['wallclock_seconds'] = self.inputs.wallclock_seconds.value
        builder = DmrgConvergenceWorkChain.get_builder()
        for name in ['code', 'validation_hamiltonian', 'validation_reference', 'hamiltonian', 'comparator']:
            if name in previous.inputs:
                builder[name] = previous.inputs[name]
        builder.plan = orm.Dict(dict=plan)
        builder.existing_runs = recovery_manifest(previous.outputs.convergence,
            interrupted.outputs.retrieved, parent_checkpoint,
            orm.Dict(dict=dict(adopted, recovery={'previous_workflow_uuid': self.ctx.previous_uuid,
                'interrupted_calcjob_uuid': self.ctx.source_uuid, 'restart_parent_calcjob_uuid': str(parent.uuid),
                'interrupted_checkpoint_used': False, 'only_wallclock_cap_changed': True,
                'qpu_jobs_submitted': 0})))
        builder.clean_workdirs = previous.inputs.clean_workdirs
        builder.metadata.label = previous.label + ' — timeout continuation'
        builder.metadata.description = ('Waited for the original workflow to terminate. '
            'Confirmed a Slurm time-limit failure; adopts completed results and preserves all old nodes. '
            'Same native code and numerical settings; longer scheduler allowance only.')
        builder.metadata.call_link_label = 'continuation'
        child = self.submit(builder)
        self.ctx.replacement_uuid = str(child.uuid)
        self.ctx.result_uuid = str(child.uuid)
        self.node.base.extras.set('dmrg_recovery_progress', {'phase': 'longer-continuation',
            'previous_workflow_uuid': self.ctx.previous_uuid,
            'replacement_workflow_uuid': str(child.uuid), 'restart_parent_calcjob_uuid': str(parent.uuid),
            'wallclock_seconds': plan['wallclock_seconds'], 'qpu_jobs_submitted': 0})
        return engine.ToContext(_engine_continuation=child)

    def inspect_recovery(self):
        self.ctx.pop('_engine_continuation', None)

    def results(self):
        node = orm.load_node(self.ctx.result_uuid)
        for name in ['convergence', 'final_results', 'states']:
            if name in node.outputs:
                self.out(name, node.outputs[name])
        if not node.is_finished_ok:
            return self.exit_codes.ERROR_CONTINUATION
