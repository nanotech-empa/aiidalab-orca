"""Small CASCI export, Dyson-transition and optional cube CalcJobs/WorkChains."""
import hashlib
import json
from importlib.resources import files
from pathlib import PurePosixPath

from aiida import common, engine, orm
from aiida.parsers import Parser

from .artifacts import remote_files, resolve_electronic, stash_options, storage_policy
from .dyson_data import selection, blend_options
from .orbitals import cube_parameters, validate_cube_outputs
from .rendering import calcjob_options

EXPORT_PROCESS = 'aiida.workflows:empa_orca.dyson_export'
DYSON_PROCESS = 'aiida.workflows:empa_orca.dyson'
CUBES_PROCESS = 'aiida.workflows:empa_orca.dyson_cubes'


def state_source(state):
    calc = state.creator
    if (calc is None or calc.process_type != 'aiida.calculations:empa_orca.casci' or
            not calc.is_finished_ok or calc.outputs.state_energies.uuid != state.uuid):
        raise ValueError('Select state energies produced by a successful CASCI CalcJob')
    return calc


def previous(input_uuid, label, process_type):
    return orm.QueryBuilder().append(orm.Dict,filters={'uuid':str(input_uuid)},tag='data').append(
        orm.WorkChainNode,with_incoming='data',edge_filters={'label':label},tag='run',
        filters={'process_type':process_type},project=['uuid']).order_by({'run':{'ctime':'desc'}}).all(flat=True)


def export_location(artifact):
    """Check durable/retrieved, native stash, then working directory; do not guess."""
    calc = artifact.creator
    if calc is None or calc.process_type != 'aiida.calculations:empa_orca.dyson_export' or not calc.is_finished_ok:
        raise ValueError('Missing successful Dyson export producer')
    record = artifact.get_dict()
    name = 'retrieved_exports/state.json.gz'
    retrieved = calc.outputs.retrieved
    if name in [str(PurePosixPath(prefix)/name) for prefix,_,names in retrieved.base.repository.walk() for name in names]:
        with retrieved.base.repository.open(name,mode='rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest() != record['sha256']:
                raise ValueError('Stored wavefunction export checksum differs')
        return {'kind':'repository','uuid':str(retrieved.uuid),'path':name}
    name = 'exports/state.json.gz'
    if 'remote_stash' in calc.outputs:
        stash = calc.outputs.remote_stash
        path = str(PurePosixPath(stash.target_basepath)/name)
        try:
            remote_files(stash.computer,str(PurePosixPath(path).parent),names=['state.json.gz'],
                         expected={'state.json.gz':record['size_bytes']})
            return {'kind':'stash','uuid':str(stash.uuid),'path':path}
        except FileNotFoundError:
            pass
    remote = calc.outputs.remote_folder
    path = str(PurePosixPath(remote.get_remote_path())/name)
    remote_files(remote.computer,str(PurePosixPath(path).parent),names=['state.json.gz'],
                 expected={'state.json.gz':record['size_bytes']})
    return {'kind':'remote','uuid':str(remote.uuid),'path':path}


def existing_export(state, export_code, helper_code):
    for uuid in previous(state.uuid,'state_energies',EXPORT_PROCESS):
        run = orm.load_node(uuid)
        if (run.is_finished_ok and run.inputs.code.uuid == export_code.uuid and
                run.inputs.helper_code.uuid == helper_code.uuid and
                run.outputs.artifact.get_dict().get('basis_available') is True):
            try:
                export_location(run.outputs.artifact)
                return str(uuid)
            except FileNotFoundError:
                continue
    return None


def stage(info, source, location, target):
    if location['kind'] == 'repository':
        info.local_copy_list.append((source.uuid,location['path'],target))
    else:
        info.remote_copy_list.append((source.computer.uuid,location['path'],target))


def script(folder, name, request):
    with folder.open('request.json','w') as handle:
        json.dump(request,handle,allow_nan=False)
    with folder.open(name,'w') as handle:
        handle.write(files('aiida_empa_orca').joinpath('scripts/'+name).read_text())


def run_code(uuid, arguments, log):
    code = common.CodeInfo()
    code.code_uuid,code.cmdline_params,code.stdout_name,code.join_files = uuid,arguments,log,True
    return code


class StateExportCalculation(engine.CalcJob):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        for key,typ in {'state_energies':orm.Dict,'helper_code':orm.AbstractCode,'location':orm.Dict,
                        'source':orm.Data,'storage_policy':orm.Dict}.items():
            spec.input(key,valid_type=typ)
        spec.input('metadata.options.parser_name',default='empa_orca.dyson_export')
        spec.input('metadata.options.withmpi',default=False)
        spec.output('artifact',valid_type=orm.Dict)
        spec.exit_code(310,'ERROR_EXPORT',message='Wavefunction export failed; inspect export.log and driver.log.')

    def prepare_for_submission(self,folder):
        calc = state_source(self.inputs.state_energies)
        if any(code.computer.uuid != calc.computer.uuid for code in (self.inputs.code,self.inputs.helper_code)):
            raise ValueError('Export the CASCI wavefunction on its original computer')
        location = self.inputs.location.get_dict()
        info = common.CalcInfo()
        info.local_copy_list,info.remote_copy_list = [(calc.outputs.retrieved.uuid,'aiida.out','aiida.out')],[]
        item = next(row for row in location['files'] if row['name'] == 'aiida.gbw')
        source = self.inputs.source
        if location['uuid'] != str(source.uuid):
            raise ValueError('Electronic location and source differ')
        if location['kind'] == 'repository':
            path = 'electronic/aiida.gbw'
        else:
            if source.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('Export remote files on their storage computer')
            base = PurePosixPath(source.target_basepath)/'electronic' if location['kind'] == 'stash' else PurePosixPath(source.get_remote_path())
            path = str(base/'aiida.gbw')
        stage(info,source,dict(location,path=path),'aiida.gbw')
        policy = storage_policy(self.inputs.storage_policy.get_dict())
        expected_stash = (stash_options(policy['stash_directory'],'exports')
                          if policy.get('mode') != 'remote' else {})
        if dict(self.inputs.metadata.options.get('stash',{})) != expected_stash:
            raise ValueError('Export stash does not match its preservation policy')
        with folder.open('orca.json.conf','w') as handle:
            json.dump({'MOCoefficients':True,'Basisset':True,'1elIntegrals':['S'],'JSONFormats':['json']},handle)
        request = {'identity':self.inputs.state_energies.get_dict(),'state_uuid':str(self.inputs.state_energies.uuid),
                   'file':item,'threshold_mb':0 if policy.get('mode') == 'remote' else policy['threshold_mb'],
                   'positions':calc.inputs.structure.get_ase().positions.tolist(),
                   'atomic_numbers':calc.inputs.structure.get_ase().numbers.tolist()}
        script(folder,'export_dyson.py',request)
        info.codes_info = [run_code(self.inputs.code.uuid,['aiida.gbw','-json'],'export.log'),
                           run_code(self.inputs.helper_code.uuid,['export_dyson.py'],'driver.log')]
        info.codes_run_mode = common.CodeRunMode.SERIAL
        info.retrieve_list = ['artifact.json','retrieved_exports','export.log','driver.log']
        return info


class StateExportParser(Parser):
    def parse(self,**kwargs):
        try:
            data = json.loads(self.retrieved.base.repository.get_object_content('artifact.json'))
            if data['state_uuid'] != str(self.node.inputs.state_energies.uuid):
                raise ValueError('Export identity differs from the requested CASCI states')
            if data['size_bytes'] < 1 or len(data['sha256']) != 64 or not data['ci_norms']:
                raise ValueError('Incomplete export metadata')
            policy = storage_policy(self.node.inputs.storage_policy.get_dict())
            if policy.get('mode') == 'remote':
                if data['retrieved_copy'] or 'remote_stash' in self.node.outputs:
                    raise ValueError('Remote-only export unexpectedly retrieved or stashed its wavefunction')
            elif 'remote_stash' not in self.node.outputs:
                raise ValueError('Native export stash is missing')
            self.out('artifact',orm.Dict(dict=data))
        except (OSError,KeyError,ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_EXPORT


class StateExportWorkChain(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        for key,typ in {'state_energies':orm.Dict,'code':orm.AbstractCode,'helper_code':orm.AbstractCode,
                        'storage_policy':orm.Dict}.items():
            spec.input(key,valid_type=typ)
        spec.input('force_recompute',valid_type=orm.Bool,default=lambda:orm.Bool(False))
        spec.output('artifact',valid_type=orm.Dict)
        spec.outline(cls.setup,engine.if_(cls.needs_execution)(cls.run_export,cls.inspect),cls.results)
        spec.exit_code(400,'ERROR_SOURCE',message='CASCI wavefunction is unavailable; review the recovery plan.')
        spec.exit_code(401,'ERROR_EXPORT',message='CASCI wavefunction export failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            calc = state_source(self.inputs.state_energies)
            storage_policy(self.inputs.storage_policy.get_dict())
            if not self.inputs.force_recompute.value:
                self.ctx.reuse_uuid = existing_export(self.inputs.state_energies,self.inputs.code,self.inputs.helper_code)
            if self.ctx.reuse_uuid:
                self.report('Reusing preserved wavefunction export '+self.ctx.reuse_uuid)
                return
            self.ctx.location = resolve_electronic(calc.outputs.remote_folder,names=['aiida.gbw'])
        except (ValueError,KeyError,OSError,RuntimeError) as exc:
            self.report(str(exc)+'; restore the original export/GBW or explicitly recompute this CASCI sector.')
            return self.exit_codes.ERROR_SOURCE

    def needs_execution(self):
        return self.ctx.reuse_uuid is None

    def run_export(self):
        calc = state_source(self.inputs.state_energies)
        b = StateExportCalculation.get_builder()
        b.state_energies,b.code,b.helper_code,b.storage_policy = (self.inputs.state_energies,self.inputs.code,
                                                                self.inputs.helper_code,self.inputs.storage_policy)
        b.source,b.location = orm.load_node(self.ctx.location['uuid']),orm.Dict(dict=self.ctx.location)
        b.metadata.options = calcjob_options(calc.outputs.remote_folder,seconds=1800)
        policy = storage_policy(self.inputs.storage_policy.get_dict())
        if policy.get('mode') != 'remote':
            b.metadata.options.stash = stash_options(policy['stash_directory'],'exports')
        b.metadata.disable_cache = True
        return engine.ToContext(export=self.submit(b))

    def inspect(self):
        if not self.ctx.export.is_finished_ok:
            return self.exit_codes.ERROR_EXPORT

    def results(self):
        run = orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.export
        self.out('artifact',run.outputs.artifact)


def checked_request(inputs):
    calc = state_source(inputs.initial)
    if calc.computer.uuid != inputs.code.computer.uuid:
        raise ValueError('Use Dyson tools on the CASCI computer')
    finals = {key:value.get_dict() for key,value in inputs.finals.items()}
    if len(finals) > 16:
        raise ValueError('Select at most 16 final charge/spin sectors per calculation')
    for state in inputs.finals.values():
        state_source(state)
        if state.creator.computer.uuid != inputs.code.computer.uuid:
            raise ValueError('Use Dyson tools on the CASCI computer')
    return selection(inputs.selection.get_dict(),inputs.initial.get_dict(),finals)


def same_request(node,inputs,selected):
    return (node.inputs.initial.uuid == inputs.initial.uuid and
            set(node.inputs.finals) == set(inputs.finals) and
            all(node.inputs.finals[k].uuid == v.uuid for k,v in inputs.finals.items()) and
            node.inputs.selection.get_dict() == selected and node.inputs.code.uuid == inputs.code.uuid)


def validate_transitions(node):
    data = node.outputs.transitions.get_dict()
    if not data['transitions']:
        raise ValueError('No transitions were stored')
    for path in ('coefficients.npz','transitions.json'):
        with node.outputs.retrieved.base.repository.open(path,mode='rb') as handle:
            if not handle.read(32):
                raise ValueError('Dyson coefficients or transition table are missing')
    return data


def runtime_settings(values):
    """Execution controls are independent of the physical state selection."""
    if not isinstance(values,dict) or set(values)-{'workers','max_wallclock_seconds'}:
        raise ValueError('Unknown Dyson execution option')
    result = {'workers':1,'max_wallclock_seconds':3600} | values
    if any(type(value) is not int or value < 1 for value in result.values()):
        raise ValueError('Dyson workers and wall time must be positive integers')
    return result


class DysonCalculation(engine.CalcJob):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.input('initial',valid_type=orm.Dict)
        spec.input_namespace('finals',dynamic=True,valid_type=orm.Dict)
        spec.input_namespace('artifacts',dynamic=True,valid_type=orm.Dict)
        spec.input_namespace('sources',dynamic=True,valid_type=orm.Data)
        spec.input('locations',valid_type=orm.Dict)
        spec.input('selection',valid_type=orm.Dict)
        spec.input('runtime',valid_type=orm.Dict,default=lambda:orm.Dict(dict=runtime_settings({})))
        spec.input('metadata.options.parser_name',default='empa_orca.dyson')
        spec.input('metadata.options.withmpi',default=False)
        spec.output('transitions',valid_type=orm.Dict)
        spec.exit_code(310,'ERROR_DYSON',message='Dyson calculation failed; inspect driver.log.')

    def prepare_for_submission(self,folder):
        selected = checked_request(self.inputs)
        runtime = runtime_settings(self.inputs.runtime.get_dict())
        resources = self.inputs.metadata.options.resources
        if resources.get('num_mpiprocs_per_machine',1) != runtime['workers'] or self.inputs.metadata.options.withmpi:
            raise ValueError('Allocate the requested Dyson workers inside one non-MPI CalcJob')
        locations = self.inputs.locations.get_dict()
        info = common.CalcInfo()
        info.local_copy_list,info.remote_copy_list = [],[]
        artifacts = {}
        for key,artifact in self.inputs.artifacts.items():
            expected = self.inputs.initial if key == 'initial' else self.inputs.finals[key]
            if artifact.get_dict()['state_uuid'] != str(expected.uuid):
                raise ValueError('State export and CASCI state identity differ')
            source = self.inputs.sources[key]
            if locations[key]['uuid'] != str(source.uuid):
                raise ValueError('Export source differs from its checked location')
            stage(info,source,locations[key],key+'.json.gz')
            artifacts[key] = artifact.get_dict()
        script(folder,'compute_dyson.py',{'selection':selected,'artifacts':artifacts,'workers':runtime['workers']})
        info.codes_info = [run_code(self.inputs.code.uuid,['compute_dyson.py'],'driver.log')]
        info.retrieve_list = ['transitions.json','coefficients.npz','driver.log']
        return info


class DysonParser(Parser):
    def parse(self,**kwargs):
        try:
            data = json.loads(self.retrieved.base.repository.get_object_content('transitions.json'))
            selected = checked_request(self.node.inputs)
            expected = {(key,r) for key,roots in selected['final_roots'].items() for r in roots}
            if ({(r['sector'],r['final_root']) for r in data['transitions']} != expected or
                    data['initial_state_uuid'] != str(self.node.inputs.initial.uuid)):
                raise ValueError('Incomplete or mismatched Dyson transitions')
            with self.retrieved.base.repository.open('coefficients.npz',mode='rb') as handle:
                import numpy as np
                with np.load(handle,allow_pickle=False) as arrays:
                    if set(arrays.files) != {r['id'] for r in data['transitions']}:
                        raise ValueError('Missing Dyson AO coefficient arrays')
            self.out('transitions',orm.Dict(dict=data))
        except (OSError,KeyError,ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_DYSON


class DysonWorkChain(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.input('initial',valid_type=orm.Dict)
        spec.input_namespace('finals',dynamic=True,valid_type=orm.Dict)
        for key,typ in {'selection':orm.Dict,'code':orm.AbstractCode,'export_code':orm.AbstractCode,
                        'storage_policy':orm.Dict}.items():
            spec.input(key,valid_type=typ)
        spec.input('force_recompute',valid_type=orm.Bool,default=lambda:orm.Bool(False))
        spec.input('runtime',valid_type=orm.Dict,default=lambda:orm.Dict(dict=runtime_settings({})))
        for key,typ in {'transitions':orm.Dict,'retrieved':orm.FolderData,'remote_folder':orm.RemoteData}.items():
            spec.output(key,valid_type=typ)
        spec.outline(cls.setup,engine.if_(cls.needs_execution)(cls.export_states,cls.compute,cls.inspect),cls.results)
        spec.exit_code(400,'ERROR_INPUT',message='Incompatible Dyson states or unavailable prerequisites; see report.')
        spec.exit_code(401,'ERROR_EXPORT',message='State export failed; no electronic calculation was repeated.')
        spec.exit_code(402,'ERROR_DYSON',message='Dyson evaluation failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            self.ctx.selected = checked_request(self.inputs)
            self.ctx.runtime = runtime_settings(self.inputs.runtime.get_dict())
            if self.inputs.export_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('ORCA export and Dyson tools must use the same computer')
            storage_policy(self.inputs.storage_policy.get_dict())
            if not self.inputs.force_recompute.value:
                for uuid in previous(self.inputs.initial.uuid,'initial',DYSON_PROCESS):
                    old = orm.load_node(uuid)
                    if old.is_finished_ok and same_request(old,self.inputs,self.ctx.selected):
                        validate_transitions(old)
                        self.ctx.reuse_uuid = str(uuid)
                        self.report('Reusing durable Dyson coefficients and transition energies from '+str(uuid))
                        return
            # Check every dependency before submitting any new export job.
            for state in [self.inputs.initial,*self.inputs.finals.values()]:
                if not existing_export(state,self.inputs.export_code,self.inputs.code):
                    resolve_electronic(state_source(state).outputs.remote_folder,names=['aiida.gbw'])
        except (ValueError,KeyError,OSError,RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INPUT

    def needs_execution(self):
        return self.ctx.reuse_uuid is None

    def export_states(self):
        pending = {}
        for key,state in {'initial':self.inputs.initial,**dict(self.inputs.finals)}.items():
            b = StateExportWorkChain.get_builder()
            b.state_energies,b.code,b.helper_code,b.storage_policy = (state,self.inputs.export_code,self.inputs.code,self.inputs.storage_policy)
            pending['export_'+key] = self.submit(b)
        return engine.ToContext(**pending)

    def compute(self):
        b = DysonCalculation.get_builder()
        b.code,b.initial,b.selection = self.inputs.code,self.inputs.initial,orm.Dict(dict=self.ctx.selected)
        b.runtime = orm.Dict(dict=self.ctx.runtime)
        for key,state in self.inputs.finals.items():
            b.finals[key] = state
        locations = {}
        for key in ['initial',*self.inputs.finals]:
            export = self.ctx['export_'+key]
            if not export.is_finished_ok:
                return self.exit_codes.ERROR_EXPORT
            artifact = export.outputs.artifact
            location = export_location(artifact)
            b.artifacts[key],b.sources[key] = artifact,orm.load_node(location['uuid'])
            locations[key] = location
        b.locations = orm.Dict(dict=locations)
        b.metadata.options = calcjob_options(state_source(self.inputs.initial).outputs.remote_folder,
                                            seconds=self.ctx.runtime['max_wallclock_seconds'])
        b.metadata.options.resources = {'num_machines':1,'num_mpiprocs_per_machine':self.ctx.runtime['workers']}
        b.metadata.disable_cache = True
        return engine.ToContext(dyson=self.submit(b))

    def inspect(self):
        if not self.ctx.dyson.is_finished_ok:
            return self.exit_codes.ERROR_DYSON

    def results(self):
        run = orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.dyson
        for key in ('transitions','retrieved','remote_folder'):
            self.out(key,run.outputs[key])


class DysonCubesCalculation(engine.CalcJob):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        for key,typ in {'transitions':orm.Dict,'artifact':orm.Dict,'source':orm.Data,'location':orm.Dict,
                        'coefficients':orm.FolderData,'parameters':orm.Dict,'cubehandler_code':orm.AbstractCode}.items():
            spec.input(key,valid_type=typ)
        spec.input('blend',valid_type=orm.Dict,required=False)
        spec.input('metadata.options.parser_name',default='empa_orca.dyson_cubes')
        spec.exit_code(310,'ERROR_CUBES',message='Dyson cube generation or reduction failed.')
        spec.input('metadata.options.withmpi',default=False)
        spec.output('manifest',valid_type=orm.Dict)

    def prepare_for_submission(self,folder):
        calc = self.inputs.transitions.creator
        if (calc is None or calc.process_type != 'aiida.calculations:empa_orca.dyson' or not calc.is_finished_ok or
                calc.outputs.retrieved.uuid != self.inputs.coefficients.uuid or
                calc.inputs.artifacts.initial.uuid != self.inputs.artifact.uuid):
            raise ValueError('Dyson coefficients, transition table and basis export must share their producer')
        if self.inputs.location.get_dict()['uuid'] != str(self.inputs.source.uuid):
            raise ValueError('Basis export source differs from the checked location')
        p = cube_parameters(self.inputs.parameters.get_dict())
        if p['spin_density'] or any(spin != 0 or i >= len(self.inputs.transitions.get_dict()['transitions']) for spin,i in p['orbitals']):
            raise ValueError('Select Dyson transition indices; spin density is a separate property')
        if self.inputs.cubehandler_code.computer.uuid != self.inputs.code.computer.uuid:
            raise ValueError('Run cubehandler on the Dyson cube computer')
        expected = stash_options(p['stash_directory'],'full_cubes') if p['retention'] == 'stash' else {}
        if dict(self.inputs.metadata.options.get('stash',{})) != expected:
            raise ValueError('Cube stash options differ from the selected policy')
        info = common.CalcInfo()
        info.local_copy_list,info.remote_copy_list = [(self.inputs.coefficients.uuid,'coefficients.npz','coefficients.npz')],[]
        stage(info,self.inputs.source,self.inputs.location.get_dict(),'initial.json.gz')
        script(folder,'dyson_cubes.py',{'parameters':p,'artifact':self.inputs.artifact.get_dict(),
            'table':self.inputs.transitions.get_dict(),'cubehandler_executable':str(self.inputs.cubehandler_code.filepath_executable),
            'blend':blend_options(self.inputs.blend.get_dict()) if 'blend' in self.inputs else None})
        info.codes_info = [run_code(self.inputs.code.uuid,['dyson_cubes.py'],'driver.log')]
        info.retrieve_list = ['previews','manifest.json','plot.log','driver.log']
        return info


class DysonCubesParser(Parser):
    def parse(self,**kwargs):
        try:
            report = json.loads(self.retrieved.base.repository.get_object_content('manifest.json'))
            expected = len(self.node.inputs.parameters.get_dict()['orbitals'])+int('blend' in self.node.inputs)
            if len(report['cubes']) != expected:
                raise ValueError('Incomplete Dyson cube output')
            for cube in report['cubes']:
                with self.retrieved.base.repository.open('previews/'+cube['filename'],mode='rb') as handle:
                    if not handle.read(32):
                        raise ValueError('Missing reduced Dyson cube')
            if report['retention'] == 'stash' and 'remote_stash' not in self.node.outputs:
                raise ValueError('Missing full-resolution stash')
            self.out('manifest',orm.Dict(dict=report))
        except (OSError,KeyError,ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CUBES


class DysonCubesWorkChain(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        for key,typ in {'transitions':orm.Dict,'parameters':orm.Dict,'code':orm.AbstractCode,'cubehandler_code':orm.AbstractCode}.items():
            spec.input(key,valid_type=typ)
        for key,typ in {'manifest':orm.Dict,'retrieved':orm.FolderData,'remote_folder':orm.RemoteData,
                        'remote_stash':orm.RemoteStashFolderData}.items():
            spec.output(key,valid_type=typ,required=key != 'remote_stash')
        spec.input('blend',valid_type=orm.Dict,required=False)
        spec.outline(cls.setup,engine.if_(cls.needs_execution)(cls.generate,cls.inspect),cls.results)
        spec.exit_code(400,'ERROR_SOURCE',message='Dyson cube source is unavailable; see report.')
        spec.exit_code(401,'ERROR_CUBES',message='Dyson cube generation or reduction failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            calc = self.inputs.transitions.creator
            if calc is None or calc.process_type != 'aiida.calculations:empa_orca.dyson' or not calc.is_finished_ok:
                raise ValueError('Select successful Dyson transitions')
            p = cube_parameters(self.inputs.parameters.get_dict())
            blend = blend_options(self.inputs.blend.get_dict()) if 'blend' in self.inputs else None
            for uuid in previous(self.inputs.transitions.uuid,'transitions',CUBES_PROCESS):
                old = orm.load_node(uuid)
                if (old.is_finished_ok and old.inputs.parameters.get_dict() == p and old.inputs.code.uuid == self.inputs.code.uuid and
                        old.inputs.cubehandler_code.uuid == self.inputs.cubehandler_code.uuid and
                        (blend_options(old.inputs.blend.get_dict()) if 'blend' in old.inputs else None) == blend):
                    try:
                        validate_cube_outputs(old)
                        self.ctx.reuse_uuid = str(uuid)
                        return
                    except FileNotFoundError:
                        continue
            self.ctx.location = export_location(calc.inputs.artifacts.initial)
        except (ValueError,KeyError,OSError,RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_execution(self):
        return self.ctx.reuse_uuid is None

    def generate(self):
        calc = self.inputs.transitions.creator
        b = DysonCubesCalculation.get_builder()
        b.code,b.cubehandler_code,b.parameters = self.inputs.code,self.inputs.cubehandler_code,self.inputs.parameters
        b.transitions,b.coefficients,b.artifact = self.inputs.transitions,calc.outputs.retrieved,calc.inputs.artifacts.initial
        if 'blend' in self.inputs:
            b.blend = orm.Dict(dict=blend_options(self.inputs.blend.get_dict()))
        b.source,b.location = orm.load_node(self.ctx.location['uuid']),orm.Dict(dict=self.ctx.location)
        b.metadata.options = calcjob_options(calc.outputs.remote_folder,seconds=3600)
        p = cube_parameters(self.inputs.parameters.get_dict())
        if p['retention'] == 'stash':
            b.metadata.options.stash = stash_options(p['stash_directory'],'full_cubes')
        b.metadata.disable_cache = True
        return engine.ToContext(cubes=self.submit(b))

    def inspect(self):
        if not self.ctx.cubes.is_finished_ok:
            return self.exit_codes.ERROR_CUBES

    def results(self):
        run = orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.cubes
        for key in ('manifest','retrieved','remote_folder','remote_stash'):
            if key in run.outputs:
                self.out(key,run.outputs[key])
