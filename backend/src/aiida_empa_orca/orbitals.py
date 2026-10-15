"""Small orbital/spin-density workflow using existing electronic data and cubehandler."""

import json
from importlib.resources import files
from pathlib import PurePosixPath

from aiida import common, engine, orm
from aiida.parsers import Parser

from .artifacts import ELECTRONIC_FILES, resolve_electronic, storage_builder, storage_policy, stash_options

PROCESS_TYPE = 'aiida.workflows:empa_orca.orbitals'


def cube_parameters(values):
    p = dict(values)
    if set(p)-{'orbitals','spin_density','grid_points','retention','stash_directory'}:
        raise ValueError('Unknown cube option')
    orbitals = p.get('orbitals', [])
    if not isinstance(orbitals, list) or any(not isinstance(pair, (list, tuple)) or len(pair)!=2 or
            type(pair[0]) is not int or pair[0] not in (0,1) or type(pair[1]) is not int or pair[1]<0 for pair in orbitals):
        raise ValueError('Select orbitals as [spin 0/1, zero-based orbital index]')
    orbitals = [list(pair) for pair in sorted(set(map(tuple, orbitals)))]
    spin = p.get('spin_density', False)
    if type(spin) is not bool or not (orbitals or spin):
        raise ValueError('Select at least one orbital or spin density')
    grid = p.get('grid_points', 80)
    if type(grid) is not int or not 40 <= grid <= 256:
        raise ValueError('Choose 40–256 grid points along each axis')
    if len(orbitals)>64:
        raise ValueError('Select at most 64 orbitals per property calculation')
    retention = p.get('retention', 'stash')
    if retention not in ('stash','leave','delete'):
        raise ValueError('Full cubes must be stashed, retained, or deleted')
    stash = p.get('stash_directory','')
    if retention=='stash':
        storage_policy({'stash_directory':stash})
    return {'orbitals': orbitals, 'spin_density': spin, 'grid_points': grid,
            'retention': retention, 'stash_directory': stash}


def attach_source(builder, location):
    key = {'repository':'source_repository', 'stash':'source_stash', 'remote':'source_folder'}[location['kind']]
    builder[key] = orm.load_node(location['uuid'])
    builder.electronic_manifest = orm.Dict(dict={'files':location['files']})


class OrbitalCubesCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('plot_code', valid_type=orm.AbstractCode)
        spec.input('cubehandler_code', valid_type=orm.AbstractCode)
        spec.input('source_repository', valid_type=orm.FolderData, required=False)
        spec.input('source_stash', valid_type=orm.RemoteStashFolderData, required=False)
        spec.input('source_folder', valid_type=orm.RemoteData, required=False)
        spec.input('electronic_manifest', valid_type=orm.Dict)
        spec.input('parameters', valid_type=orm.Dict)
        spec.input('metadata.options.parser_name', default='empa_orca.orbital_cubes')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('manifest', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_CUBES', message='Cube generation/reduction failed; inspect plot.log and driver.log.')

    def prepare_for_submission(self, folder):
        p = cube_parameters(self.inputs.parameters.get_dict())
        computer = self.inputs.code.computer
        if any(self.inputs[k].computer.uuid != computer.uuid for k in ('plot_code','cubehandler_code')):
            raise ValueError('ORCA tools, ORCA plot and cubehandler codes must use the same computer')
        keys = [k for k in ('source_repository','source_stash','source_folder') if k in self.inputs]
        if len(keys)!=1:
            raise ValueError('Exactly one verified electronic source is required')
        info = common.CalcInfo()
        info.local_copy_list, info.remote_copy_list = [], []
        if keys[0]=='source_repository':
            source = self.inputs.source_repository
            info.local_copy_list = [(source.uuid,'electronic/'+name,name) for name in ELECTRONIC_FILES]
        else:
            source = self.inputs[keys[0]]
            if source.computer.uuid != computer.uuid:
                raise ValueError('Remote electronic files must be on the computation computer')
            base = (PurePosixPath(source.target_basepath)/'electronic' if keys[0]=='source_stash'
                    else PurePosixPath(source.get_remote_path()))
            info.remote_copy_list = [(computer.uuid,str(base/name),name) for name in ELECTRONIC_FILES]
        request = {'parameters':p, 'files':self.inputs.electronic_manifest.get_dict()['files'],
                   'plot_executable':str(self.inputs.plot_code.filepath_executable),
                   'cubehandler_executable':str(self.inputs.cubehandler_code.filepath_executable)}
        with folder.open('request.json','w') as handle:
            json.dump(request, handle)
        with folder.open('plot_cubes.py','w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('scripts/plot_cubes.py').read_text())
        expected_stash = stash_options(p['stash_directory'], 'full_cubes') if p['retention']=='stash' else {}
        if dict(self.inputs.metadata.options.get('stash', {})) != expected_stash:
            raise ValueError('Stash options do not match the selected cube retention policy')
        code = common.CodeInfo()
        code.code_uuid = self.inputs.code.uuid
        code.cmdline_params = ['plot_cubes.py']
        code.stdout_name, code.join_files = 'driver.log', True
        info.codes_info = [code]
        info.retrieve_list = ['previews','manifest.json','plot.log','driver.log']
        return info


class OrbitalCubesParser(Parser):
    def parse(self, **kwargs):
        try:
            report = json.loads(self.retrieved.base.repository.get_object_content('manifest.json'))
            parameters = cube_parameters(self.node.inputs.parameters.get_dict())
            expected = len(parameters['orbitals']) + int(parameters['spin_density'])
            if len(report['cubes'])!=expected:
                raise ValueError('Incomplete cube output')
            for cube in report['cubes']:
                with self.retrieved.base.repository.open('previews/'+cube['filename'],mode='rb') as handle:
                    if not handle.read(32):
                        raise ValueError('Empty preview')
            if report['retention']=='stash' and 'remote_stash' not in self.node.outputs:
                raise ValueError('No full-resolution cube stash')
            self.out('manifest', orm.Dict(dict=report))
        except (OSError, KeyError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CUBES


def validate_cube_outputs(node):
    if not node.is_finished_ok:
        raise ValueError('Property calculation is not complete')
    report = node.outputs.manifest.get_dict()
    for cube in report['cubes']:
        with node.outputs.retrieved.base.repository.open('previews/'+cube['filename'],mode='rb') as handle:
            if not handle.read(32):
                raise ValueError('Preview is missing')
    if report['retention']!='delete':
        from .artifacts import remote_files
        remote = node.outputs.remote_stash if report['retention']=='stash' else node.outputs.remote_folder
        base = remote.target_basepath if report['retention']=='stash' else remote.get_remote_path()
        remote_files(remote.computer, str(PurePosixPath(base)/'full_cubes'),
                     names=[c['filename'] for c in report['cubes']],
                     expected={c['filename']:c['full']['size_bytes'] for c in report['cubes']})
    return report


class OrbitalsWorkChain(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        for key, typ in {'source_retrieved':orm.FolderData, 'source_remote':orm.RemoteData,
                         'structure':orm.StructureData,'reference_settings':orm.Dict,'parameters':orm.Dict,
                         'storage_policy':orm.Dict, 'python_code':orm.AbstractCode,'orca_code':orm.AbstractCode,
                         'plot_code':orm.AbstractCode,'cubehandler_code':orm.AbstractCode}.items():
            spec.input(key,valid_type=typ)
        spec.input('regenerate_reference',valid_type=orm.Bool,default=lambda:orm.Bool(False))
        spec.input('reuse_uuid',valid_type=orm.Str,required=False)
        spec.output('manifest',valid_type=orm.Dict)
        spec.output('retrieved',valid_type=orm.FolderData)
        spec.output('remote_folder',valid_type=orm.RemoteData)
        spec.output('remote_stash',valid_type=orm.RemoteStashFolderData,required=False)
        spec.output('electronic_source',valid_type=orm.RemoteData,required=False)
        spec.outline(cls.setup, engine.if_(cls.needs_execution)(
            engine.if_(cls.needs_reference)(cls.run_reference,cls.inspect_reference),
            cls.preserve,cls.inspect_storage,cls.run_cubes,cls.inspect_cubes),cls.results)
        spec.exit_code(400,'ERROR_INPUT',message='Invalid property inputs; see the workflow report.')
        spec.exit_code(401,'ERROR_SOURCE',message='Electronic files are unavailable. Review the regeneration plan.')
        spec.exit_code(402,'ERROR_REFERENCE',message='The replacement SCF failed.')
        spec.exit_code(403,'ERROR_STORAGE',message='Wavefunction preservation failed.')
        spec.exit_code(404,'ERROR_CUBES',message='Cube generation, reduction or retention failed.')

    def setup(self):
        try:
            self.ctx.parameters = cube_parameters(self.inputs.parameters.get_dict())
            storage_policy(self.inputs.storage_policy.get_dict())
            computer=self.inputs.python_code.computer
            if any(self.inputs[k].computer.uuid!=computer.uuid for k in ('plot_code','cubehandler_code','orca_code')):
                raise ValueError('Select all codes on the same computer')
            if self.inputs.source_remote.computer.uuid!=computer.uuid:
                raise ValueError('The electronic reference must be on the selected computer')
            producer = self.inputs.source_retrieved.creator
            if producer is None or producer.outputs.remote_folder.uuid != self.inputs.source_remote.uuid:
                raise ValueError('The retrieved output and electronic folder must have the same producer')
            from aiida.common import LinkType
            from .reference import PROCESS_TYPE as REFERENCE_PROCESS, GEOMETRY_PROCESS, reference_signature
            expected = reference_signature(self.inputs.structure, self.inputs.reference_settings.get_dict(), self.inputs.orca_code.uuid)
            matching = False
            for triple in self.inputs.source_retrieved.base.links.get_incoming(link_type=LinkType.RETURN).all():
                candidate = triple.node
                if candidate.process_type not in (REFERENCE_PROCESS, GEOMETRY_PROCESS):
                    continue
                if 'structure' in candidate.outputs and 'code' in candidate.inputs:
                    signature = reference_signature(candidate.outputs.structure, candidate.inputs.settings.get_dict(), candidate.inputs.code.uuid)
                    matching |= signature == expected
            if not matching:
                raise ValueError('The reference settings and geometry do not match the producing workflow')
            from .levels import orbital_levels
            levels = orbital_levels(self.inputs.source_retrieved.base.repository.get_object_content('aiida.out'))
            selected = self.ctx.parameters
            available = {(v['spin'], v['index']) for c in levels['channels'] for v in c}
            if any(tuple(pair) not in available for pair in selected['orbitals']):
                raise ValueError('Requested orbital is absent from the stored ORCA level table')
            if selected['spin_density'] and not levels['spin_polarized']:
                raise ValueError('Spin density requires an unrestricted reference')
            self.ctx.regenerate=False
            self.ctx.source_uuid=str(self.inputs.source_remote.uuid)
            if 'reuse_uuid' in self.inputs:
                source=orm.load_node(self.inputs.reuse_uuid.value)
                if (source.process_type!=PROCESS_TYPE or source.inputs.source_retrieved.uuid!=self.inputs.source_retrieved.uuid or
                        cube_parameters(source.inputs.parameters.get_dict())!=self.ctx.parameters or
                        any(source.inputs[role+'_code'].uuid!=self.inputs[role+'_code'].uuid
                            for role in ('python','plot','cubehandler'))):
                    raise ValueError('The reviewed property source does not match')
                validate_cube_outputs(source)
                return
            try:
                resolve_electronic(self.inputs.source_remote)
            except (FileNotFoundError,ValueError):
                if not self.inputs.regenerate_reference.value:
                    return self.exit_codes.ERROR_SOURCE
                self.ctx.regenerate=True
        except (ValueError,OSError,RuntimeError,KeyError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INPUT

    def needs_execution(self):
        return 'reuse_uuid' not in self.inputs

    def needs_reference(self):
        return self.ctx.regenerate

    def run_reference(self):
        from .reference import get_reference_builder
        builder=get_reference_builder(self.inputs.structure,self.inputs.reference_settings.get_dict(),self.inputs.orca_code)
        return engine.ToContext(reference=self.submit(builder))

    def inspect_reference(self):
        if not self.ctx.reference.is_finished_ok:
            return self.exit_codes.ERROR_REFERENCE
        self.ctx.source_uuid=str(self.ctx.reference.outputs.remote_folder.uuid)

    def preserve(self):
        try:
            remote=orm.load_node(self.ctx.source_uuid)
            self.ctx.location=resolve_electronic(remote)
            if self.ctx.location['kind']!='remote':
                return
            return engine.ToContext(storage=self.submit(storage_builder(remote,self.inputs.python_code,self.inputs.storage_policy.get_dict())))
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_STORAGE

    def inspect_storage(self):
        if 'storage' in self.ctx and not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE
        try:
            self.ctx.location=resolve_electronic(orm.load_node(self.ctx.source_uuid))
            if self.ctx.location['kind']=='remote':
                return self.exit_codes.ERROR_STORAGE
        except (OSError,ValueError,RuntimeError,KeyError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_STORAGE

    def run_cubes(self):
        builder=OrbitalCubesCalculation.get_builder()
        builder.code=self.inputs.python_code
        builder.plot_code=self.inputs.plot_code
        builder.cubehandler_code=self.inputs.cubehandler_code
        builder.parameters=orm.Dict(dict=self.ctx.parameters)
        attach_source(builder,self.ctx.location)
        from .rendering import calcjob_options
        builder.metadata.options=calcjob_options(self.inputs.source_remote,seconds=3600)
        if self.ctx.parameters['retention']=='stash':
            builder.metadata.options.stash=stash_options(self.ctx.parameters['stash_directory'], 'full_cubes')
        builder.metadata.disable_cache=True  # Explicit reuse checks files, including retained/stashed full cubes.
        return engine.ToContext(cubes=self.submit(builder))

    def inspect_cubes(self):
        try:
            validate_cube_outputs(self.ctx.cubes)
        except (ValueError,OSError,RuntimeError,KeyError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_CUBES

    def results(self):
        source=orm.load_node(self.inputs.reuse_uuid.value) if 'reuse_uuid' in self.inputs else self.ctx.cubes
        for name in ('manifest','retrieved','remote_folder','remote_stash'):
            if name in source.outputs:
                self.out(name,source.outputs[name])
        self.out('electronic_source', source.outputs.electronic_source if 'reuse_uuid' in self.inputs
                 else orm.load_node(self.ctx.source_uuid))
