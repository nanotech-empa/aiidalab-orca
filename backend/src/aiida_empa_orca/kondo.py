"""Independent exchange and cube workflows, with explicit provenance reuse."""
import json

import numpy as np
from aiida import common, engine, orm
from aiida.parsers import Parser

from .dyson import previous, script, run_code, export_location, stage, DysonCubesParser
from .kondo_data import exchange, parameters
from .orbitals import cube_parameters, validate_cube_outputs
from .artifacts import stash_options
from .rendering import calcjob_options

PROCESS = 'aiida.workflows:empa_orca.kondo'
CUBES_PROCESS = 'aiida.workflows:empa_orca.kondo_cubes'


def source(transitions):
    calc = transitions.creator
    if calc is None or not calc.is_finished_ok or calc.process_type != 'aiida.calculations:empa_orca.dyson':
        raise ValueError('Select successful, provenance-linked Dyson transitions')
    return calc


class KondoCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('transitions', valid_type=orm.Dict)
        spec.input('parameters', valid_type=orm.Dict)
        spec.input('metadata.options.parser_name', default='empa_orca.kondo')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('channels', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_KONDO', message='Exchange analysis failed; inspect kondo.log.')

    def prepare_for_submission(self, folder):
        source(self.inputs.transitions)
        table = self.inputs.transitions.get_dict()
        p = parameters(self.inputs.parameters.get_dict(), table)
        exchange(table, p)  # Fail before submission for invalid physics inputs.
        script(folder, 'compute_kondo.py', dict(table=table, parameters=p))
        info = common.CalcInfo()
        info.codes_info = [run_code(self.inputs.code.uuid, ['compute_kondo.py'], 'kondo.log')]
        info.retrieve_list = ['channels.json', 'kondo.log']
        return info


class KondoParser(Parser):
    def parse(self, **kwargs):
        try:
            report = json.loads(self.retrieved.base.repository.get_object_content('channels.json'))
            expected = exchange(self.node.inputs.transitions.get_dict(), self.node.inputs.parameters.get_dict())
            for key in ('observable', 'initial_state_uuid', 'orbital_reference_uuid', 'active_space', 'parameters'):
                if report[key] != expected[key]:
                    raise ValueError('Kondo output identity differs from its input')
            matrix = np.asarray(report['exchange_over_v2_inv_ev'])
            if not np.allclose(matrix, expected['exchange_over_v2_inv_ev'], atol=1e-10, rtol=1e-10):
                raise ValueError('Exchange matrix differs from the selected amplitudes and energies')
            vectors = np.asarray([c['active_coefficients'] for c in report['channels']]).T
            vals = np.asarray([c['exchange_over_v2_inv_ev'] for c in report['channels']])
            if (vectors.shape != matrix.shape or
                    [c['id'] for c in report['channels']] != [c['id'] for c in expected['channels']] or
                    [c['coupling'] for c in report['channels']] != [c['coupling'] for c in expected['channels']] or
                    not np.isfinite(vectors).all() or not np.isfinite(vals).all() or
                    not np.allclose(vectors.T @ vectors, np.eye(len(vals)), atol=1e-8, rtol=0) or
                    not np.allclose(matrix @ vectors, vectors * vals, atol=1e-8, rtol=1e-8)):
                raise ValueError('Invalid exchange eigenchannels')
            self.out('channels', orm.Dict(dict=report))
        except (OSError, KeyError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_KONDO


class KondoWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'transitions': orm.Dict, 'parameters': orm.Dict, 'code': orm.AbstractCode}.items():
            spec.input(key, valid_type=typ)
        spec.input('force_recompute', valid_type=orm.Bool, default=lambda: orm.Bool(False))
        for key, typ in {'channels': orm.Dict, 'retrieved': orm.FolderData, 'remote_folder': orm.RemoteData}.items():
            spec.output(key, valid_type=typ)
        spec.outline(cls.setup, engine.if_(cls.needs_execution)(cls.compute, cls.inspect), cls.results)
        spec.exit_code(400, 'ERROR_SOURCE', message='Unsupported Kondo inputs; see report.')
        spec.exit_code(401, 'ERROR_KONDO', message='Exchange calculation failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            source(self.inputs.transitions)
            table = self.inputs.transitions.get_dict()
            self.ctx.parameters = parameters(self.inputs.parameters.get_dict(), table)
            exchange(table, self.ctx.parameters)
            if not self.inputs.force_recompute.value:
                for uuid in previous(self.inputs.transitions.uuid, 'transitions', PROCESS):
                    old = orm.load_node(uuid)
                    if (old.is_finished_ok and old.inputs.parameters.get_dict() == self.ctx.parameters and
                            old.inputs.code.uuid == self.inputs.code.uuid):
                        old.outputs.channels.get_dict()
                        self.ctx.reuse_uuid = str(uuid)
                        self.report('Reusing stored Kondo eigenchannels; no wavefunction files are needed.')
                        return
        except (ValueError, KeyError, OSError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_execution(self):
        return self.ctx.reuse_uuid is None

    def compute(self):
        b = KondoCalculation.get_builder()
        b.code, b.transitions = self.inputs.code, self.inputs.transitions
        b.parameters = orm.Dict(dict=self.ctx.parameters)
        # Compact durable inputs can be processed on either local or remote tools.
        b.metadata.options = dict(resources={'num_machines': 1, 'num_mpiprocs_per_machine': 1},
                                 max_wallclock_seconds=600, withmpi=False)
        b.metadata.disable_cache = True
        job = self.submit(b)
        self.ctx.job_uuid = str(job.uuid)
        return engine.ToContext(finished=job)

    def inspect(self):
        if not orm.load_node(self.ctx.job_uuid).is_finished_ok:
            return self.exit_codes.ERROR_KONDO

    def results(self):
        run = orm.load_node(self.ctx.reuse_uuid or self.ctx.job_uuid)
        for key in ('channels', 'retrieved', 'remote_folder'):
            self.out(key, run.outputs[key])


def channel_source(channels):
    calc = channels.creator
    if calc is None or not calc.is_finished_ok or calc.process_type != 'aiida.calculations:empa_orca.kondo':
        raise ValueError('Select successful Kondo channels')
    return source(calc.inputs.transitions)


class KondoCubesCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'channels': orm.Dict, 'artifact': orm.Dict, 'source': orm.Data,
                         'location': orm.Dict, 'parameters': orm.Dict, 'cubehandler_code': orm.AbstractCode}.items():
            spec.input(key, valid_type=typ)
        spec.input('metadata.options.parser_name', default='empa_orca.kondo_cubes')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('manifest', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_CUBES', message='Kondo cube generation or reduction failed.')

    def prepare_for_submission(self, folder):
        dyson = channel_source(self.inputs.channels)
        if dyson.inputs.artifacts.initial.uuid != self.inputs.artifact.uuid:
            raise ValueError('Kondo orbitals and AO basis must share the original CASCI reference')
        p = cube_parameters(self.inputs.parameters.get_dict())
        report = self.inputs.channels.get_dict()
        if p['spin_density'] or any(s != 0 or i >= len(report['channels']) for s, i in p['orbitals']):
            raise ValueError('Select existing Kondo channel indices')
        if (self.inputs.cubehandler_code.computer.uuid != self.inputs.code.computer.uuid or
                isinstance(self.inputs.source, (orm.RemoteData, orm.RemoteStashFolderData)) and
                self.inputs.source.computer.uuid != self.inputs.code.computer.uuid):
            raise ValueError('Generate Kondo cubes on the basis/cubehandler computer')
        if self.inputs.location.get_dict()['uuid'] != str(self.inputs.source.uuid):
            raise ValueError('Basis source differs from its checked location')
        expected = stash_options(p['stash_directory'], 'full_cubes') if p['retention'] == 'stash' else {}
        if dict(self.inputs.metadata.options.get('stash', {})) != expected:
            raise ValueError('Cube stash options differ from the selected policy')
        info = common.CalcInfo()
        info.local_copy_list, info.remote_copy_list = [], []
        stage(info, self.inputs.source, self.inputs.location.get_dict(), 'initial.json.gz')
        script(folder, 'dyson_cubes.py', dict(parameters=p, artifact=self.inputs.artifact.get_dict(),
            channels=report, channels_uuid=str(self.inputs.channels.uuid),
            cubehandler_executable=str(self.inputs.cubehandler_code.filepath_executable)))
        info.codes_info = [run_code(self.inputs.code.uuid, ['dyson_cubes.py'], 'driver.log')]
        info.retrieve_list = ['previews', 'manifest.json', 'plot.log', 'driver.log']
        return info


class KondoCubesParser(DysonCubesParser):
    def parse(self, **kwargs):
        try:
            report = json.loads(self.retrieved.base.repository.get_object_content('manifest.json'))
            channels = self.node.inputs.channels.get_dict()['channels']
            selected = self.node.inputs.parameters.get_dict()['orbitals']
            if (report['channels_uuid'] != str(self.node.inputs.channels.uuid) or
                    report['orbital_source']['kind'] != 'Kondo' or
                    report['retention'] != self.node.inputs.parameters.get_dict()['retention'] or
                    {c['channel_id'] for c in report['cubes']} != {channels[i]['id'] for _, i in selected}):
                raise ValueError('Kondo cube manifest differs from its channel source or storage policy')
        except (OSError, KeyError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CUBES
        return super().parse(**kwargs)


class KondoCubesWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'channels': orm.Dict, 'parameters': orm.Dict, 'code': orm.AbstractCode,
                         'cubehandler_code': orm.AbstractCode}.items():
            spec.input(key, valid_type=typ)
        for key, typ in {'manifest': orm.Dict, 'retrieved': orm.FolderData, 'remote_folder': orm.RemoteData,
                         'remote_stash': orm.RemoteStashFolderData}.items():
            spec.output(key, valid_type=typ, required=key != 'remote_stash')
        spec.outline(cls.setup, engine.if_(cls.needs_execution)(cls.compute, cls.inspect), cls.results)
        spec.exit_code(400, 'ERROR_SOURCE', message='Kondo cube source is unavailable; see report.')
        spec.exit_code(401, 'ERROR_CUBES', message='Kondo cubes failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            calc = channel_source(self.inputs.channels)
            p = cube_parameters(self.inputs.parameters.get_dict())
            for uuid in previous(self.inputs.channels.uuid, 'channels', CUBES_PROCESS):
                old = orm.load_node(uuid)
                if (old.is_finished_ok and old.inputs.parameters.get_dict() == p and
                        old.inputs.code.uuid == self.inputs.code.uuid and
                        old.inputs.cubehandler_code.uuid == self.inputs.cubehandler_code.uuid):
                    try:
                        validate_cube_outputs(old)
                        self.ctx.reuse_uuid = str(uuid)
                        return
                    except FileNotFoundError:
                        continue
            self.ctx.location = export_location(calc.inputs.artifacts.initial)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_execution(self):
        return self.ctx.reuse_uuid is None

    def compute(self):
        calc = channel_source(self.inputs.channels)
        b = KondoCubesCalculation.get_builder()
        b.code, b.channels, b.parameters = self.inputs.code, self.inputs.channels, self.inputs.parameters
        b.cubehandler_code = self.inputs.cubehandler_code
        b.artifact = calc.inputs.artifacts.initial
        b.source, b.location = orm.load_node(self.ctx.location['uuid']), orm.Dict(dict=self.ctx.location)
        b.metadata.options = calcjob_options(calc.outputs.remote_folder, seconds=3600)
        p = cube_parameters(self.inputs.parameters.get_dict())
        if p['retention'] == 'stash':
            b.metadata.options.stash = stash_options(p['stash_directory'], 'full_cubes')
        b.metadata.disable_cache = True
        job = self.submit(b)
        self.ctx.job_uuid = str(job.uuid)
        return engine.ToContext(finished=job)

    def inspect(self):
        if not orm.load_node(self.ctx.job_uuid).is_finished_ok:
            return self.exit_codes.ERROR_CUBES

    def results(self):
        run = orm.load_node(self.ctx.reuse_uuid or self.ctx.job_uuid)
        for key in ('manifest', 'retrieved', 'remote_folder', 'remote_stash'):
            if key in run.outputs:
                self.out(key, run.outputs[key])
