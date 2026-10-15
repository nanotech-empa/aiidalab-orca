"""Short-lived provenance and file access for rendered cube images."""
from pathlib import PurePosixPath
from datetime import datetime, timezone
from uuid import uuid4, UUID
import json

from aiida import orm
from aiida.engine import submit
from aiidalab_widgets_empa.cube_views import render_settings_from_view
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


def submit_render(property_uuid, filename, quality, settings, *, view_name=None):
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
    builder.metadata.label = f'{view_name + " · " if view_name else ""}{filename} · {quality} render'
    builder.metadata.disable_cache = True
    return str(submit(builder).uuid)


def renders(property_uuid, filename=None):
    node = orm.load_node(property_uuid)
    query = orm.QueryBuilder().append(orm.Dict, filters={'uuid':node.outputs.manifest.uuid}, tag='manifest').append(
        orm.CalcJobNode, with_incoming='manifest', edge_filters={'label':'source_manifest'}, tag='render',
        filters={'process_type':'aiida.calculations:empa_orca.cube_render'}, project=['uuid','ctime'])
    result=[]
    for uuid, date in query.order_by({'render':{'ctime':'desc'}}).all():
        run=orm.load_node(uuid)
        if filename is None or run.inputs.filename.value == filename:
            result.append((f'{run.label} · {date:%Y-%m-%d %H:%M} · {run.process_state.value} · {str(uuid)[:8]}',str(uuid)))
    return result


# Mutable user annotations, separate from the manifest's scientific attributes.
# Each view has its own key so saving one cannot overwrite another browser's views.
_VIEW_PREFIX = 'aiidalab_orca_cube_view_'


def _view_key(identifier):
    return _VIEW_PREFIX + str(UUID(identifier))


def saved_views(property_uuid):
    manifest = orm.load_node(property_uuid).outputs.manifest
    records = [value for key, value in manifest.base.extras.all.items() if key.startswith(_VIEW_PREFIX)]
    return sorted(records, key=lambda value: (value['name'].casefold(), value['id']))


def saved_view(property_uuid, identifier):
    manifest = orm.load_node(property_uuid).outputs.manifest
    record = manifest.base.extras.get(_view_key(identifier), None)
    if record is None:
        raise ValueError('This saved visualization was removed; refresh the list')
    return record


def save_view(property_uuid, filename, quality, name, visualization, identifier=None):
    node = orm.load_node(property_uuid)
    manifest = node.outputs.manifest
    source_cube(manifest.get_dict(), filename)
    if not name.strip():
        raise ValueError('Give this visualization a name')
    if quality not in ('preview', 'full'):
        raise ValueError('Select preview or full-resolution cubes')
    if visualization.get('version') != 1:
        raise ValueError('Unsupported visualization version')
    render_settings(render_settings_from_view(visualization))
    # Detach mutable UI dictionaries and reject nonfinite/nonserializable values.
    visualization = json.loads(json.dumps(visualization, allow_nan=False))
    if identifier is not None:
        saved_view(property_uuid, identifier)
    identifier = identifier or str(uuid4())
    record = dict(id=identifier, name=name.strip(), filename=filename, quality=quality,
                  visualization=visualization, updated_at=datetime.now(timezone.utc).isoformat())
    record['label'] = f'{record["name"]} · {filename} · {"full resolution" if quality == "full" else "preview"}'
    manifest.base.extras.set(_view_key(identifier), record)
    return identifier


def remove_view(property_uuid, identifier):
    saved_view(property_uuid, identifier)
    orm.load_node(property_uuid).outputs.manifest.base.extras.delete(_view_key(identifier))


def render_saved_views(property_uuid, identifiers):
    """Submit each saved snapshot independently; report unavailable sources per view."""
    submitted, errors = [], []
    for identifier in dict.fromkeys(identifiers):
        name = identifier
        try:
            record = saved_view(property_uuid, identifier)
            name = record['name']
            uuid = submit_render(property_uuid, record['filename'], record['quality'],
                                 render_settings_from_view(record['visualization']), view_name=name)
            submitted.append({'name': name, 'uuid': uuid})
        except Exception as exc:
            errors.append({'name': name, 'message': str(exc)})
    return {'submitted': submitted, 'errors': errors}


def result(uuid, *, include_image=True):
    node=orm.load_node(uuid)
    result={'state':node.process_state.value, 'finished':node.is_terminated, 'success':node.is_finished_ok,
            'filename':node.inputs.filename.value,
            'message':node.exit_message or ''}
    if node.is_finished_ok:
        if include_image:
            with node.outputs.image.open(mode='rb') as handle:
                result['image']=handle.read()
    elif node.is_terminated and 'retrieved' in node.outputs:
        try:
            result['message']+='\n'+node.outputs.retrieved.base.repository.get_object_content('render.log')[-4000:]
        except FileNotFoundError:
            pass
    return result
