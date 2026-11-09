"""Durable DMRG calibration, bond refinement and independent ordering check."""
import math
from aiida import engine, orm
from .dmrg import DmrgCalculation, file_sha256
from .dmrg_storage import checkpoint_node

EV = 27.211386245988


def energy_changes(previous, current):
    if len(previous['energies_hartree']) != len(current['energies_hartree']):
        raise ValueError('Different root counts')
    energy = max(abs(a-b) for a, b in zip(previous['energies_hartree'], current['energies_hartree'])) * EV
    gaps = max(abs(a-b) for a, b in zip(previous['excitation_energies_ev'], current['excitation_energies_ev']))
    return {'max_root_energy_change_ev': energy, 'max_gap_change_ev': gaps}


def stable_history(history, tolerance):
    if len(history) < 3 or not all(p.get('sweep_converged', False) for p in history[-3:]):
        return False, []
    changes = [energy_changes(a, b) for a, b in zip(history[-3:-1], history[-2:])]
    return all(max(change.values()) <= tolerance for change in changes), changes


def calibration_errors(energies, reference, plan):
    energy = max(abs(a-b) for a, b in zip(energies, reference))
    gaps = max(abs((a-energies[0])-(b-reference[0])) for a, b in zip(energies, reference))
    observable = plan.get('validation_observable', 'energies')
    metric = energy if observable == 'energies' else gaps
    accepted = metric <= plan['validation_tolerance_hartree']
    if observable == 'gaps':
        accepted &= energy <= plan['validation_absolute_ceiling_hartree']
    return {'reference_max_energy_error_hartree': energy,
            'reference_max_gap_error_hartree': gaps,
            'validation_observable': observable, 'accepted': bool(accepted)}


def validate_plan(value):
    for field in ['validation_bonds', 'target_bonds']:
        values = value.get(field)
        if (not isinstance(values, list) or not values or
                any(type(v) is not int or not 32 <= v <= 8192 for v in values) or
                values != sorted(set(values))):
            raise ValueError('Specify increasing bounded bond dimensions')
    if type(value.get('nroots')) is not int or value.get('nroots') not in [1, 3]:
        raise ValueError('The validated workflow supports one or three singlets')
    observable = value.get('validation_observable', 'energies')
    if observable not in ['energies', 'gaps'] or (observable == 'gaps' and value['nroots'] == 1):
        raise ValueError('Specify an appropriate calibration observable')
    if observable == 'gaps':
        ceiling = value.get('validation_absolute_ceiling_hartree')
        if type(ceiling) not in [int, float] or not math.isfinite(ceiling) or ceiling <= 0:
            raise ValueError('Gap calibration also requires an absolute-energy ceiling')
    for field in ['validation_tolerance_hartree', 'stability_tolerance_ev']:
        number = value.get(field)
        if type(number) not in [int, float] or not math.isfinite(number) or number <= 0:
            raise ValueError('Positive finite convergence tolerances required')
    if value.get('validation_ordering', 'fiedler') not in ['none', 'fiedler']:
        raise ValueError('Unknown calibration ordering')
    if type(value.get('threads', 8)) is not int or not 1 <= value.get('threads', 8) <= 23:
        raise ValueError('Specify 1–23 numerical threads')
    if value.get('logical_cpu_factor', 2) not in [1, 2]:
        raise ValueError('Specify the measured CPU topology factor')
    if type(value.get('max_sweeps', 64)) is not int or not 32 <= value.get('max_sweeps', 64) <= 100:
        raise ValueError('Specify a supported polishing cap')
    for name, default, low, high in [('max_sweep_extensions', 3, 1, 16), ('continuation_sweeps', 32, 32, 100)]:
        if type(value.get(name, default)) is not int or not low <= value.get(name, default) <= high:
            raise ValueError('Invalid fixed-M continuation budget: ' + name)
    return dict(value)


@engine.calcfunction
def convergence_record(plan, reference, target_hamiltonian, trace, **runs):
    """A provenance-linked numerical verdict, using the original result nodes."""
    data = trace.get_dict()
    data.update(plan=plan.get_dict(), calibration_reference_uuid=str(reference.uuid),
                target_hamiltonian_sha256=file_sha256(target_hamiltonian),
                native_result_uuids={key: str(value.uuid) for key, value in runs.items()},
                rigorous_full_ci_error_bound=False, full_CAS_computed=False,
                qpu_jobs_submitted=0)
    return orm.Dict(dict=data)


@engine.calcfunction
def sweep_convergence_record(settings, trace, **runs):
    return orm.Dict(dict={'settings': settings.get_dict(), **trace.get_dict(),
        'result_uuids': {name: str(node.uuid) for name, node in runs.items()},
        'bond_dimension_convergence_established': False, 'qpu_jobs_submitted': 0})


class DmrgSweepConvergenceWorkChain(engine.WorkChain):
    """Continue a saved one-site checkpoint at exactly one M until accepted."""
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for name, kind in [('code', orm.AbstractCode), ('hamiltonian', orm.SinglefileData),
                ('parent_states', (orm.FolderData, orm.RemoteData)), ('settings', orm.Dict), ('run_options', orm.Dict)]:
            spec.input(name, valid_type=kind)
        spec.input('max_extensions', valid_type=orm.Int, default=lambda: orm.Int(3))
        spec.output('convergence', valid_type=orm.Dict)
        spec.output('results', valid_type=orm.Dict)
        spec.output('states', valid_type=(orm.FolderData, orm.RemoteData))
        spec.exit_code(402, 'ERROR_NATIVE', message='Fixed-M native continuation failed; inspect preserved checkpoint and logs.')
        spec.exit_code(405, 'ERROR_SWEEP_BUDGET', message='Fixed-M extension budget exhausted; checkpoint preserved, M unchanged.')
        spec.outline(cls.setup, engine.while_(cls.needs_sweeps)(cls.run_sweeps, cls.inspect_sweeps), cls.finalize)

    def setup(self):
        if not 1 <= self.inputs.max_extensions.value <= 16:
            raise ValueError('Use one to sixteen explicit sweep extensions')
        parent = self.inputs.parent_states.creator
        if parent is None or parent.exit_status not in [0, 311] or 'results' not in parent.outputs:
            raise ValueError('Use a completed native checkpoint with validated results')
        s = self.inputs.settings.get_dict(); old = parent.inputs.settings.get_dict()
        if any(s[k] != old[k] for k in ['max_bond_dimension', 'nroots', 'ordering']):
            raise ValueError('Fixed-M continuation must preserve M, roots and orbital order')
        r = parent.outputs.results.get_dict()
        if r['hamiltonian_sha256'] != file_sha256(self.inputs.hamiltonian):
            raise ValueError('Continuation Hamiltonian differs')
        self.ctx.current_uuid = str(parent.uuid); self.ctx.history = [self.point(parent)]
        self.ctx.extensions = 0; self.ctx.error = 0; self.ctx.converged = r['sweep_converged']
        self.publish()

    def point(self, node):
        r = node.outputs.results.get_dict()
        return {'calculation_uuid': str(node.uuid), 'result_uuid': str(node.outputs.results.uuid),
            'energies_hartree': r['energies_hartree'], 'sweep_converged': r['sweep_converged'],
            'sweeps_completed': r['sweeps_completed'],
            'last_sweep_max_root_energy_change_hartree': r['last_sweep_max_root_energy_change_hartree']}

    def publish(self):
        self.node.base.extras.set('sweep_progress', {'bond_dimension': self.inputs.settings.get_dict()['max_bond_dimension'],
            'extensions': self.ctx.extensions, 'current_uuid': self.ctx.current_uuid,
            'converged': self.ctx.converged, 'error': self.ctx.error, 'history': list(self.ctx.history),
            'qpu_jobs_submitted': 0})

    def needs_sweeps(self):
        return not self.ctx.error and not self.ctx.converged and self.ctx.extensions < self.inputs.max_extensions.value

    def run_sweeps(self):
        b = DmrgCalculation.get_builder(); b.code = self.inputs.code; b.hamiltonian = self.inputs.hamiltonian
        b.settings = self.inputs.settings
        b.parent_states = (self.inputs.parent_states if self.ctx.extensions == 0 else
                           checkpoint_node(orm.load_node(self.ctx.current_uuid)))
        b.continue_sweeps = orm.Bool(True); b.metadata.options = self.inputs.run_options.get_dict()
        self.ctx.extensions += 1
        b.metadata.label = f'Fixed-M DMRG sweep continuation {self.ctx.extensions}, M={self.inputs.settings.get_dict()["max_bond_dimension"]}'
        b.metadata.call_link_label = f'sweeps_{self.ctx.extensions:02d}'; b.metadata.disable_cache = True
        child = self.submit(b); self.ctx.pending_uuid = str(child.uuid)
        self.node.base.extras.set('pending_sweep_uuid', str(child.uuid))
        return engine.ToContext(_engine_sweeps=child)

    def inspect_sweeps(self):
        self.ctx.pop('_engine_sweeps', None); n = orm.load_node(self.ctx.pending_uuid)
        if n.exit_status not in [0, 311] or 'results' not in n.outputs:
            self.ctx.error = 402; self.publish(); return
        self.ctx.current_uuid = str(n.uuid); self.ctx.history.append(self.point(n))
        self.ctx.converged = n.outputs.results.get_dict()['sweep_converged']; self.publish()

    def finalize(self):
        runs = {f'run_{i:03d}': orm.load_node(p['result_uuid']) for i, p in enumerate(self.ctx.history)}
        trace = orm.Dict(dict={'passed': self.ctx.converged, 'extensions': self.ctx.extensions,
            'history': list(self.ctx.history), 'fixed_m_sweep_policy': True})
        self.out('convergence', sweep_convergence_record(self.inputs.settings, trace, **runs))
        n = orm.load_node(self.ctx.current_uuid); self.out('results', n.outputs.results)
        self.out('states', self.inputs.parent_states if self.ctx.extensions == 0 else checkpoint_node(n))
        if self.ctx.error: return self.exit_codes.ERROR_NATIVE
        if not self.ctx.converged: return self.exit_codes.ERROR_SWEEP_BUDGET


class DmrgConvergenceWorkChain(engine.WorkChain):
    """Accept old result UUIDs explicitly, then submit all new steps as children."""

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('code', valid_type=orm.AbstractCode)
        spec.input('validation_hamiltonian', valid_type=orm.SinglefileData)
        spec.input('validation_reference', valid_type=orm.Dict)
        spec.input('hamiltonian', valid_type=orm.SinglefileData)
        spec.input('comparator', valid_type=orm.Dict, required=False)
        spec.input('plan', valid_type=orm.Dict)
        spec.input('existing_runs', valid_type=orm.Dict, default=lambda: orm.Dict(dict={}))
        spec.input('clean_workdirs', valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.output('convergence', valid_type=orm.Dict)
        spec.output('final_results', valid_type=orm.Dict, required=False)
        spec.output('states', valid_type=(orm.FolderData, orm.RemoteData), required=False)
        spec.exit_code(401, 'ERROR_INPUT', message='Invalid calibration or refinement inputs.')
        spec.exit_code(402, 'ERROR_NATIVE', message='Native DMRG output needs inspection; dependent submission stopped.')
        spec.exit_code(403, 'ERROR_CALIBRATION', message='The calibration ladder did not reproduce the exact reference.')
        spec.exit_code(404, 'ERROR_REFINEMENT', message='The target ladder did not establish the requested stability.')
        spec.exit_code(405, 'ERROR_SWEEP_BUDGET', message='Fixed-M sweep extensions exhausted; checkpoint preserved, M was not increased.')
        spec.outline(cls.setup, engine.while_(cls.has_work)(cls.dispatch, cls.inspect_result), cls.finalize)

    def setup(self):
        try:
            plan = validate_plan(self.inputs.plan.get_dict())
            reference = self.inputs.validation_reference.get_dict()
            if len(reference['energies_hartree']) < plan['nroots']:
                raise ValueError('Insufficient exact reference roots')
            validation_sha = file_sha256(self.inputs.validation_hamiltonian)
            if reference['hamiltonian_sha256'] != validation_sha:
                raise ValueError('Calibration Hamiltonian differs from its reference')
            target_sha = file_sha256(self.inputs.hamiltonian)
            floor = None
            if 'comparator' in self.inputs:
                comparator = self.inputs.comparator.get_dict()
                if comparator['hamiltonian_sha256'] != target_sha:
                    raise ValueError('Comparator Hamiltonian differs')
                floor = float(comparator['initializer']['cisd_energy_hartree'])
            self.ctx.plan = plan
            self.ctx.reference = reference['energies_hartree'][:plan['nroots']]
            self.ctx.hashes = {'validation': validation_sha, 'target': target_sha, 'ordering': target_sha}
            self.ctx.floor = floor
            self.ctx.phase = 'validation'
            self.ctx.index = 0
            self.ctx.trace = []
            self.ctx.history = []
            self.ctx.cleanup = []
            self.ctx.result_uuids = []
            self.ctx.sweep_parent_uuid = None
            self.ctx.sweep_extensions = 0
            self.ctx.error = 0
            self.ctx.verdict = {'observed_stability_passed': False}
            self.publish()
        except (KeyError, ValueError, TypeError):
            return self.exit_codes.ERROR_INPUT

    def has_work(self):
        return self.ctx.phase != 'done'

    def publish(self):
        # Business state and application progress contain plain data/UUIDs only.
        self.node.base.extras.set('dmrg_progress', {
            'phase': self.ctx.phase, 'current': self.ctx.get('current', {}),
            'completed': list(self.ctx.trace), 'cleanup': list(self.ctx.cleanup),
            'verdict': dict(self.ctx.verdict), 'error': self.ctx.error,
            'sweep_extensions': self.ctx.get('sweep_extensions', 0),
            'sweep_parent_uuid': self.ctx.get('sweep_parent_uuid'),
            'qpu_jobs_submitted': 0})

    def fail(self, code, reason):
        self.ctx.error = code
        self.ctx.verdict.update(reason=reason, observed_stability_passed=False)
        self.ctx.phase = 'done'
        self.publish()

    def dispatch(self):
        phase = self.ctx.phase
        plan = self.ctx.plan
        bonds = plan['validation_bonds'] if phase == 'validation' else plan['target_bonds']
        bond = bonds[self.ctx.index]
        ordering = plan.get('validation_ordering', 'fiedler') if phase == 'validation' else ('none' if phase == 'ordering' else 'fiedler')
        sweep_parent = self.ctx.get('sweep_parent_uuid')
        adopted = None if sweep_parent else self.inputs.existing_runs.get_dict().get(phase, {}).get(str(bond))
        if adopted:
            node = orm.load_node(adopted)
            expected = node.inputs.settings.get_dict()
            if (node.process_type != 'aiida.calculations:empa_orca.dmrg' or
                    expected['max_bond_dimension'] != bond or expected['nroots'] != plan['nroots'] or
                    expected['ordering'] != ordering or file_sha256(node.inputs.hamiltonian) != self.ctx.hashes[phase]):
                self.fail(401, 'Existing calculation does not match the declared step')
                return
        else:
            builder = DmrgCalculation.get_builder()
            builder.code = orm.load_code(str(self.inputs.code.uuid))
            builder.hamiltonian = orm.load_node(str((self.inputs.validation_hamiltonian if phase == 'validation' else self.inputs.hamiltonian).uuid))
            threads = plan.get('threads', 8)
            memory = plan.get('small_memory_gb', 16) if bond <= 512 else (plan.get('medium_memory_gb', 32) if bond <= 2048 else plan.get('large_memory_gb', 64))
            builder.settings = orm.Dict(dict={'nroots': plan['nroots'], 'max_bond_dimension': bond,
                'threads': threads, 'memory_gb': memory,
                'max_sweeps': plan.get('continuation_sweeps', 32) if sweep_parent else plan.get('max_sweeps', 64),
                'ordering': ordering, 'sweep_tolerance': 1e-9, 'davidson_tolerance': 1e-10})
            if sweep_parent:
                builder.parent_states = checkpoint_node(orm.load_node(sweep_parent))
                builder.continue_sweeps = orm.Bool(True)
            elif phase == 'target' and self.ctx.history:
                builder.parent_states = checkpoint_node(orm.load_node(self.ctx.history[-1]['uuid']))
            builder.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1,
                'num_cores_per_mpiproc': threads * plan.get('logical_cpu_factor', 2)}
            builder.metadata.options.queue_name = plan.get('queue', 'debug')
            builder.metadata.options.max_wallclock_seconds = plan.get('wallclock_seconds', 8*3600)
            builder.metadata.options.max_memory_kb = (memory + plan.get('memory_overhead_gb', 8)) * 1024**2
            builder.metadata.options.environment_variables = {'OMP_NUM_THREADS': str(threads),
                'OMP_PLACES': 'cores', 'OMP_PROC_BIND': 'close', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
            builder.metadata.options.prepend_text = 'taskset -pc $$'
            builder.metadata.options.withmpi = False
            builder.metadata.disable_cache = True
            suffix = f'_sweeps_{self.ctx.sweep_extensions:02d}' if sweep_parent else ''
            builder.metadata.call_link_label = f'{phase}_m{bond}' + suffix
            builder.metadata.label = f'DMRG convergence: {phase}, {plan["nroots"]} singlet roots, M={bond}' + suffix
            node = self.submit(builder)
        self.ctx.current = {'phase': phase, 'bond_dimension': bond, 'ordering': ordering,
                            'uuid': str(node.uuid), 'adopted': bool(adopted),
                            'sweep_extension': self.ctx.get('sweep_extensions', 0)}
        self.publish()
        # AiiDA owns this await slot and serializes its process reference.
        # Clear it immediately on resumption, then reload by the saved UUID.
        return engine.ToContext(_engine_wait=node)

    def clean(self, identifier):
        if not self.inputs.clean_workdirs.value:
            return
        node = orm.load_node(identifier)
        if node.outputs.results.get_dict().get('checkpoint_storage') == 'remote':
            self.ctx.cleanup.append({'uuid': identifier, 'scratch_cleaned': False,
                                     'reason': 'Validated MPS checkpoint retained remotely'})
            return
        try:
            node.outputs.retrieved.base.repository.get_object('mps/mps_info.bin')
            node.outputs.remote_folder._clean()
            self.ctx.cleanup.append({'uuid': identifier, 'scratch_cleaned': True,
                                     'retrieved_uuid': str(node.outputs.retrieved.uuid)})
        except Exception as error:
            # Scratch removal is operational; its failure must not erase a
            # valid scientific result or suppress the remaining refinements.
            self.ctx.cleanup.append({'uuid': identifier, 'scratch_cleaned': False,
                                     'error_type': type(error).__name__})

    def inspect_result(self):
        self.ctx.pop('_engine_wait', None)
        if self.ctx.phase == 'done':
            return
        node = orm.load_node(self.ctx.current['uuid'])
        if node.exit_status not in [0, 311] or 'results' not in node.outputs:
            self.fail(402, 'Native calculation failed or its output is invalid')
            return
        result = node.outputs.results.get_dict()
        if result['hamiltonian_sha256'] != self.ctx.hashes[self.ctx.phase]:
            self.fail(402, 'Native Hamiltonian identity changed')
            return
        record = dict(self.ctx.current, exit_status=node.exit_status,
            energies_hartree=result['energies_hartree'], excitation_energies_ev=result['excitation_energies_ev'],
            sweep_converged=result['sweep_converged'], result_uuid=str(node.outputs.results.uuid),
            parent_states_uuid=result.get('parent_states_uuid'))
        self.ctx.trace.append(record)
        self.ctx.result_uuids.append(record['result_uuid'])
        self.report(f'{record["phase"]} M={record["bond_dimension"]}: E0={record["energies_hartree"][0]:.12f} Ha; native checks={record["sweep_converged"]}')
        phase = self.ctx.phase
        plan = self.ctx.plan
        if not result['sweep_converged']:
            extensions = self.ctx.get('sweep_extensions', 0)
            self.ctx.sweep_parent_uuid = str(node.uuid)
            if extensions >= plan.get('max_sweep_extensions', 3):
                self.fail(405, 'Fixed-M sweep extensions exhausted; no increase of M permitted')
                return
            self.ctx.sweep_extensions = extensions + 1
            self.report(f'Sweeps not converged at M={record["bond_dimension"]}; continue the same checkpoint at fixed M.')
            self.clean(record['uuid'])
            self.publish()
            return
        self.ctx.sweep_parent_uuid = None
        self.ctx.sweep_extensions = 0
        # Older in-flight workflows can contain pre-policy, unconverged points.
        # Preserve their trace, but exclude them from a bond-convergence verdict.
        self.ctx.history = [r for r in self.ctx.history if r.get('sweep_converged', False)]
        if phase == 'validation':
            errors = calibration_errors(result['energies_hartree'], self.ctx.reference, plan)
            record.update(errors)
            if errors['accepted'] and result['sweep_converged']:
                self.ctx.verdict['calibration_passed'] = True
                self.ctx.verdict['calibration_observable'] = errors['validation_observable']
                self.ctx.phase = 'target'; self.ctx.index = 0
            else:
                self.ctx.index += 1
                if self.ctx.index == len(plan['validation_bonds']):
                    self.fail(403, 'The exact calibration threshold was not reached')
        elif phase == 'target':
            self.ctx.history.append(record)
            stable, changes = stable_history(self.ctx.history, plan['stability_tolerance_ev'])
            lower = self.ctx.floor is None or result['energies_hartree'][0] <= self.ctx.floor + 1e-6
            if stable and result['sweep_converged'] and lower:
                self.ctx.verdict['successive_changes'] = changes
                self.ctx.phase = 'ordering'
            else:
                self.ctx.index += 1
                if self.ctx.index == len(plan['target_bonds']):
                    self.fail(404, 'The initial refinement ladder did not establish stability')
        else:
            changes = energy_changes(self.ctx.history[-1], record)
            self.ctx.verdict['ordering_changes'] = changes
            if max(changes.values()) <= plan['stability_tolerance_ev'] and result['sweep_converged']:
                self.ctx.verdict.update(observed_stability_passed=True,
                    max_bond_dimension=record['bond_dimension'],
                    energies_hartree=self.ctx.history[-1]['energies_hartree'],
                    excitation_energies_ev=self.ctx.history[-1]['excitation_energies_ev'])
                self.ctx.phase = 'done'
            else:
                self.ctx.phase = 'target'; self.ctx.index += 1
                if self.ctx.index == len(plan['target_bonds']):
                    self.fail(404, 'The independent ordering check did not agree')
        self.clean(record['uuid'])
        self.publish()

    def finalize(self):
        self.ctx.pop('_engine_wait', None)
        records = {f'run_{i:03d}': orm.load_node(identifier) for i, identifier in enumerate(self.ctx.result_uuids)}
        trace = orm.Dict(dict={'passed': self.ctx.verdict.get('observed_stability_passed', False),
            'verdict': dict(self.ctx.verdict), 'runs': list(self.ctx.trace), 'cleanup': list(self.ctx.cleanup),
            'adopted_runs_are_not_reparented': True})
        report = convergence_record(self.inputs.plan, self.inputs.validation_reference,
                                    self.inputs.hamiltonian, trace, **records)
        self.out('convergence', report)
        if self.ctx.history:
            identifier = self.ctx.history[-1]['uuid']
            self.out('final_results', orm.load_node(identifier).outputs.results)
            self.out('states', checkpoint_node(orm.load_node(identifier)))
        if self.ctx.error:
            return {401: self.exit_codes.ERROR_INPUT, 402: self.exit_codes.ERROR_NATIVE,
                    403: self.exit_codes.ERROR_CALIBRATION, 404: self.exit_codes.ERROR_REFINEMENT,
                    405: self.exit_codes.ERROR_SWEEP_BUDGET}[self.ctx.error]
