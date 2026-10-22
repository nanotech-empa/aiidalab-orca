"""Independent numerical-map and figure CalcJobs with immutable provenance."""
import json
from pathlib import PurePosixPath

import numpy as np
from aiida import common, engine, orm
from aiida.parsers import Parser

from .artifacts import remote_files
from .dyson import script, run_code
from .maps_data import map_parameters, figure_style

MAP_PROCESS = 'aiida.calculations:empa_orca.dyson_maps'
KONDO_MAP_PROCESS = 'aiida.calculations:empa_orca.kondo_maps'
FIGURE_PROCESS = 'aiida.calculations:empa_orca.map_figure'


def selected_cubes(manifest, table, parameters):
    p = map_parameters(parameters)
    kondo = 'channel_ids' in p
    ids = p['channel_ids' if kondo else 'transition_ids']
    rows = {r['id']: r for r in table['channels' if kondo else 'transitions']}
    if not set(ids) <= rows.keys():
        raise ValueError('Selected transitions are absent from the Dyson table')
    result = []
    for identifier in ids:
        candidates = [c for c in manifest['cubes'] if c.get('kind') == ('kondo' if kondo else 'dyson') and
                      c.get('channel_id' if kondo else 'transition_id') == identifier]
        if len(candidates) != 1:
            raise ValueError('Generate the individual amplitude cube for '+identifier+'; a precomputed intensity blend cannot be extrapolated')
        cube = candidates[0]
        if PurePosixPath(cube['filename']).name != cube['filename']:
            raise ValueError('Invalid recorded cube filename')
        result.append(cube)
    return result


class DysonMapsCalculation(engine.CalcJob):
    table_input = 'transitions'
    cube_process = 'aiida.calculations:empa_orca.dyson_cubes'
    parser_name = 'empa_orca.dyson_maps'

    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key in ('source_manifest', cls.table_input, 'parameters'):
            spec.input(key, valid_type=orm.Dict)
        spec.input('source_folder', valid_type=orm.RemoteData, required=False)
        spec.input('source_stash', valid_type=orm.RemoteStashFolderData, required=False)
        spec.input('metadata.options.parser_name', default=cls.parser_name)
        spec.input('metadata.options.withmpi', default=False)
        spec.output('maps', valid_type=orm.ArrayData)
        spec.output('map_metadata', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_MAPS', message='Map calculation failed; inspect maps.log.')

    def prepare_for_submission(self, folder):
        manifest = self.inputs.source_manifest.get_dict()
        producer = self.inputs.source_manifest.creator
        if (producer is None or not producer.is_finished_ok or
                producer.process_type != self.cube_process or
                producer.inputs[self.table_input].uuid != self.inputs[self.table_input].uuid):
            raise ValueError('Cube manifest and transition table must share Dyson provenance')
        p = map_parameters(self.inputs.parameters.get_dict())
        cubes = selected_cubes(manifest, self.inputs[self.table_input].get_dict(), p)
        if ('channel_ids' in p) != (self.table_input == 'channels'):
            raise ValueError('Map observable does not match its orbital source')
        keys = [k for k in ('source_folder', 'source_stash') if k in self.inputs]
        if len(keys) != 1:
            raise ValueError('Provide exactly one full-resolution cube source')
        source = self.inputs[keys[0]]
        output = 'remote_stash' if keys[0] == 'source_stash' else 'remote_folder'
        if output not in producer.outputs or producer.outputs[output].uuid != source.uuid:
            raise ValueError('Cube source does not belong to this manifest producer')
        if source.computer.uuid != self.inputs.code.computer.uuid:
            raise ValueError('Compute maps on the full-cube storage computer')
        root = source.target_basepath if keys[0] == 'source_stash' else source.get_remote_path()
        base = str(PurePosixPath(root)/'full_cubes')
        remote_files(source.computer, base, names=[c['filename'] for c in cubes],
                     expected={c['filename']: c['full']['size_bytes'] for c in cubes})
        info = common.CalcInfo()
        info.local_copy_list, info.remote_copy_list = [], []
        staged = {}
        for j, cube in enumerate(cubes):
            target = f'amplitude_{j}.cube'
            info.remote_copy_list.append((source.computer.uuid, str(PurePosixPath(base)/cube['filename']), target))
            staged[cube['channel_id' if self.table_input == 'channels' else 'transition_id']] = dict(path=target, size_bytes=cube['full']['size_bytes'])
        script(folder, 'dyson_maps.py', dict(parameters=p, table=self.inputs[self.table_input].get_dict(), cubes=staged))
        info.codes_info = [run_code(self.inputs.code.uuid, ['dyson_maps.py'], 'maps.log')]
        info.retrieve_list = ['maps.npz', 'map-metadata.json', 'maps.log']
        return info


class KondoMapsCalculation(DysonMapsCalculation):
    table_input = 'channels'
    cube_process = 'aiida.calculations:empa_orca.kondo_cubes'
    parser_name = 'empa_orca.kondo_maps'


class DysonMapsParser(Parser):
    def parse(self, **kwargs):
        try:
            report = json.loads(self.retrieved.base.repository.get_object_content('map-metadata.json'))
            p = map_parameters(self.node.inputs.parameters.get_dict())
            if report['parameters'] != p:
                raise ValueError('Map output settings differ from the requested plane/spectrum')
            with self.retrieved.base.repository.open('maps.npz', mode='rb') as handle, np.load(handle, allow_pickle=False) as arrays:
                if set(arrays.files) != {'intensity', 'u_angstrom', 'v_angstrom', 'heights_angstrom'}:
                    raise ValueError('Incomplete numerical maps')
                count = len(p['channel_ids' if 'channel_ids' in p else 'transition_ids']) if p['kind'] == 'individual' else 1
                if arrays['intensity'].shape != (len(p['heights_angstrom']), count, p['plane']['resolution'], p['plane']['resolution']):
                    raise ValueError('Unexpected map dimensions')
                node = orm.ArrayData()
                for name in arrays.files:
                    value = arrays[name]
                    if not np.isfinite(value).all():
                        raise ValueError('Nonfinite numerical map')
                    node.set_array(name, value)
                if np.any(arrays['intensity'] < 0) or not np.array_equal(arrays['heights_angstrom'], p['heights_angstrom']):
                    raise ValueError('Invalid intensity or observation heights')
                if not np.isclose(arrays['intensity'].max(), report['maximum'], rtol=1e-12, atol=0):
                    raise ValueError('Map intensity range differs from its report')
            self.out('maps', node)
            self.out('map_metadata', orm.Dict(dict=report))
        except (OSError, KeyError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_MAPS


class MapFigureCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('maps', valid_type=orm.ArrayData)
        spec.input('map_metadata', valid_type=orm.Dict)
        spec.input('settings', valid_type=orm.Dict)
        spec.input('metadata.options.parser_name', default='empa_orca.map_figure')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('png', valid_type=orm.SinglefileData)
        spec.output('pdf', valid_type=orm.SinglefileData)
        spec.exit_code(310, 'ERROR_FIGURE', message='Map figure rendering failed; inspect figure.log.')

    def prepare_for_submission(self, folder):
        producer = self.inputs.maps.creator
        if (producer is None or producer.process_type not in (MAP_PROCESS, KONDO_MAP_PROCESS) or not producer.is_finished_ok or
                producer.outputs.map_metadata.uuid != self.inputs.map_metadata.uuid):
            raise ValueError('Maps and metadata must come from the same successful map CalcJob')
        p = figure_style(self.inputs.settings.get_dict())
        with folder.open('maps.npz', 'wb') as handle:
            np.savez_compressed(handle, **{name: self.inputs.maps.get_array(name) for name in self.inputs.maps.get_arraynames()})
        script(folder, 'render_maps.py', dict(settings=p, metadata=self.inputs.map_metadata.get_dict()))
        info = common.CalcInfo()
        info.codes_info = [run_code(self.inputs.code.uuid, ['render_maps.py'], 'figure.log')]
        info.retrieve_list = ['maps.png', 'maps.pdf', 'figure.log']
        return info


class MapFigureParser(Parser):
    def parse(self, **kwargs):
        try:
            for name, signature in (('png', b'\x89PNG\r\n\x1a\n'), ('pdf', b'%PDF-')):
                with self.retrieved.base.repository.open('maps.'+name, mode='rb') as handle:
                    if handle.read(len(signature)) != signature:
                        raise ValueError('Missing or invalid '+name+' figure')
                    handle.seek(0)
                    self.out(name, orm.SinglefileData(file=handle, filename='maps.'+name))
        except (OSError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_FIGURE
