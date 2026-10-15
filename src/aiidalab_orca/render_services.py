"""Short-lived provenance and file access for rendered cube images."""
from pathlib import PurePosixPath

from aiida import orm
from aiida.engine import submit
from aiida_empa_orca.artifacts import remote_files
from aiida_empa_orca.rendering import CubeRenderCalculation, calcjob_options, render_settings, source_cube


def render_source(property_uuid, filename, quality):
    node = orm.load_node(property_uuid)
    if not node.is_finished_ok:
        raise ValueError('Select a completed cube calculation')
    manifest = node.outputs.manifest.get_dict()
    cube = source_cube(manifest, filename)
    if quality == 'preview':
        with node.outputs.retrieved.base.repository.open('previews/'+filename, mode='rb') as handle:
            if not handle.read(32):
                raise ValueError('The reduced cube is unavailable')
        return {'kind':'repository', 'uuid':str(node.outputs.retrieved.uuid)}
    if quality != 'full':
        raise ValueError('Select preview or full-resolution cubes')
    if manifest['retention'] == 'delete':
        raise ValueError('Full cubes were deleted. Recompute cubes with stash/leave selected, or render the stored preview.')
    source = node.outputs.remote_stash if manifest['retention']=='stash' else node.outputs.remote_folder
    root = source.target_basepath if manifest['retention']=='stash' else source.get_remote_path()
    path = str(PurePosixPath(root)/'full_cubes')
    remote_files(source.computer, path, names=[filename], expected={filename:cube['full']['size_bytes']})
    return {'kind':'stash' if manifest['retention']=='stash' else 'folder', 'uuid':str(source.uuid)}


def submit_render(property_uuid, filename, quality, settings):
    location = render_source(property_uuid, filename, quality)
    p = render_settings(settings)
    node = orm.load_node(property_uuid)
    computer_uuid=node.outputs.remote_folder.computer.uuid
    choices=[]
    for uuid in orm.QueryBuilder().append(orm.InstalledCode,project=['uuid']).all(flat=True):
        candidate=orm.load_code(uuid)
        if candidate.default_calc_job_plugin=='empa_orca.cube_render' and candidate.computer.uuid==computer_uuid:
            choices.append(str(uuid))
    if len(choices)!=1:
        raise ValueError('Configure one cubehandler rendering code on the calculation computer in Code setup.')
    code = orm.load_code(choices[0])
    builder = CubeRenderCalculation.get_builder()
    builder.code = code
    builder.source_manifest = node.outputs.manifest
    builder.filename = orm.Str(filename)
    builder.settings = orm.Dict(dict=p)
    builder['source_'+location['kind']] = orm.load_node(location['uuid'])
    builder.metadata.options = calcjob_options(node.outputs.remote_folder)
    builder.metadata.label = f'{filename} · {quality} render'
    builder.metadata.disable_cache = True
    return str(submit(builder).uuid)


def renders(property_uuid, filename):
    node = orm.load_node(property_uuid)
    query = orm.QueryBuilder().append(orm.Dict, filters={'uuid':node.outputs.manifest.uuid}, tag='manifest').append(
        orm.CalcJobNode, with_incoming='manifest', edge_filters={'label':'source_manifest'}, tag='render',
        filters={'process_type':'aiida.calculations:empa_orca.cube_render'}, project=['uuid','ctime'])
    result=[]
    for uuid, date in query.order_by({'render':{'ctime':'desc'}}).all():
        run=orm.load_node(uuid)
        if run.inputs.filename.value == filename:
            result.append((f'{date:%Y-%m-%d %H:%M} · {run.process_state.value} · {str(uuid)[:8]}',str(uuid)))
    return result


def result(uuid):
    node=orm.load_node(uuid)
    result={'state':node.process_state.value, 'finished':node.is_terminated, 'success':node.is_finished_ok,
            'message':node.exit_message or ''}
    if node.is_finished_ok:
        with node.outputs.image.open(mode='rb') as handle:
            result['image']=handle.read()
    elif node.is_terminated and 'retrieved' in node.outputs:
        try:
            result['message']+='\n'+node.outputs.retrieved.base.repository.get_object_content('render.log')[-4000:]
        except FileNotFoundError:
            pass
    return result
