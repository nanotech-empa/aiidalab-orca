"""Render cube images on the source computer through a dedicated CalcJob."""
import math
import json
import re
from pathlib import PurePosixPath

from aiida import common, engine, orm
from aiida.parsers import Parser

from .artifacts import remote_files


def render_settings(values):
    p = dict(values)
    if set(p) - {'slice_plane', 'lighting'} != {'orientation', 'iso', 'width', 'height', 'background', 'opacity'}:
        raise ValueError('Incomplete or unknown render settings')
    if len(p['orientation']) != 16 or not all(math.isfinite(v) for v in p['orientation']):
        raise ValueError('A finite 16-element camera matrix is required')
    if not p['iso'] or any(len(pair) != 2 or not math.isfinite(pair[0]) or
                          not re.fullmatch(r'#[0-9a-fA-F]{6}', pair[1]) for pair in p['iso']):
        raise ValueError('Specify finite isovalues and hexadecimal colours')
    if any(type(p[k]) is not int or not 320 <= p[k] <= 4096 for k in ('width', 'height')):
        raise ValueError('Render dimensions must be 320–4096 pixels')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', p['background']) or not 0 <= p['opacity'] <= 1:
        raise ValueError('Invalid background or opacity')
    if 'lighting' in p:
        lighting=p['lighting']
        if (not isinstance(lighting,dict) or set(lighting)!={'ambient','direct','gloss'} or
                any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in lighting.values())):
            raise ValueError('Lighting requires ambient, direct and gloss values between 0 and 1')
    if 'slice_plane' in p:
        plane=p['slice_plane']
        if not isinstance(plane,dict) or set(plane)!={'center','normal','offset','width','height','resolution','vmin','vmax','periodic'}:
            raise ValueError('Incomplete or unknown slicing-plane settings')
        if any(len(plane[key])!=3 or not all(math.isfinite(v) for v in plane[key]) for key in ('center','normal')):
            raise ValueError('Plane center and normal must contain three finite numbers')
        if sum(v*v for v in plane['normal']) < 1e-24:
            raise ValueError('Plane normal must be nonzero')
        if not all(math.isfinite(plane[key]) for key in ('offset','width','height','vmin','vmax')):
            raise ValueError('Plane dimensions and colour limits must be finite')
        if min(plane['width'],plane['height'])<=0 or plane['vmin']>plane['vmax']:
            raise ValueError('Invalid plane dimensions or colour range')
        if type(plane['resolution']) is not int or not 16<=plane['resolution']<=1024 or type(plane['periodic']) is not bool:
            raise ValueError('Invalid plane resolution or boundary setting')
    return p


def source_cube(manifest, filename):
    if PurePosixPath(filename).name != filename:
        raise ValueError('Expected a recorded cube filename')
    for cube in manifest['cubes']:
        if cube['filename'] == filename:
            return cube
    raise ValueError('The selected cube is not in the recorded manifest')


def calcjob_options(source, *, seconds=1800):
    """Inherit scheduler allocation/account details; helper steps are serial."""
    options = {}
    creator = source.creator
    if creator and isinstance(creator, orm.CalcJobNode):
        for key in ('queue_name', 'account', 'qos', 'custom_scheduler_commands'):
            value = creator.get_option(key)
            if value:
                options[key] = value
    options.update(resources={'num_machines': 1, 'num_mpiprocs_per_machine': 1},
                   max_wallclock_seconds=seconds, withmpi=False)
    return options


class CubeRenderCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('source_manifest', valid_type=orm.Dict)
        spec.input('filename', valid_type=orm.Str)
        spec.input('source_repository', valid_type=orm.FolderData, required=False)
        spec.input('source_folder', valid_type=orm.RemoteData, required=False)
        spec.input('source_stash', valid_type=orm.RemoteStashFolderData, required=False)
        spec.input('settings', valid_type=orm.Dict)
        spec.input('metadata.options.parser_name', default='empa_orca.cube_render')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('image', valid_type=orm.SinglefileData)
        spec.exit_code(310, 'ERROR_RENDER', message='Cube rendering failed; inspect render.log.')

    def prepare_for_submission(self, folder):
        p = render_settings(self.inputs.settings.get_dict())
        name = self.inputs.filename.value
        manifest = self.inputs.source_manifest.get_dict()
        cube = source_cube(manifest, name)
        keys = [key for key in ('source_repository', 'source_folder', 'source_stash') if key in self.inputs]
        if len(keys) != 1:
            raise ValueError('Select exactly one cube source')
        source = self.inputs[keys[0]]
        info = common.CalcInfo()
        info.local_copy_list, info.remote_copy_list = [], []
        if keys[0] == 'source_repository':
            info.local_copy_list = [(source.uuid, 'previews/'+name, 'input.cube')]
        else:
            if source.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('Render full cubes on their storage computer')
            root = source.target_basepath if keys[0] == 'source_stash' else source.get_remote_path()
            base = str(PurePosixPath(root)/'full_cubes')
            remote_files(source.computer, base, names=[name], expected={name:cube['full']['size_bytes']})
            info.remote_copy_list = [(source.computer.uuid, str(PurePosixPath(base)/name), 'input.cube')]
        code = common.CodeInfo()
        code.code_uuid = self.inputs.code.uuid
        code.cmdline_params = ['render', 'input.cube', '--orientation', *[str(v) for v in p['orientation']]]
        for value, colour in p['iso']:
            code.cmdline_params += ['--iso', f'{value}:{colour}']
        code.cmdline_params += ['--format', 'png', '--output', 'render.png', '--width', str(p['width']),
                                '--height', str(p['height']), '--background', p['background'], '--opacity', str(p['opacity'])]
        if 'slice_plane' in p:
            with folder.open('slice-plane.json','w') as handle:
                json.dump(p['slice_plane'],handle,allow_nan=False)
            code.cmdline_params += ['--slice-plane','slice-plane.json']
        if 'lighting' in p:
            with folder.open('lighting.json','w') as handle:
                json.dump(p['lighting'],handle,allow_nan=False)
            code.cmdline_params += ['--lighting','lighting.json']
        code.stdout_name, code.join_files = 'render.log', True
        info.codes_info = [code]
        info.retrieve_list = ['render.png', 'render.log']
        return info


class CubeRenderParser(Parser):
    def parse(self, **kwargs):
        try:
            with self.retrieved.base.repository.open('render.png', mode='rb') as handle:
                if handle.read(8) != b'\x89PNG\r\n\x1a\n':
                    raise ValueError('No PNG image was produced')
                handle.seek(0)
                self.out('image', orm.SinglefileData(file=handle, filename='render.png'))
        except (OSError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_RENDER
