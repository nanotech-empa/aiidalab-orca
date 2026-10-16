"""Operation-local AiiDA access for numerical maps and persistent figures."""
from aiida import orm
from aiida.engine import submit
from aiida.common.constants import AIIDA_FLOAT_PRECISION

from aiida_empa_orca.maps import DysonMapsCalculation, MapFigureCalculation, MAP_PROCESS, FIGURE_PROCESS, selected_cubes
from aiida_empa_orca.maps_data import map_parameters, figure_style
from aiida_empa_orca.rendering import calcjob_options
from .render_services import render_source
from .casci_services import progress


def stored_values(value):
    """Match the documented attribute precision without storing temporary nodes."""
    if isinstance(value, dict):
        return {key: stored_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stored_values(item) for item in value]
    return float(f'{value:.{AIIDA_FLOAT_PRECISION}g}') if isinstance(value, float) else value


def history(source_uuid, label, process_type):
    query = orm.QueryBuilder().append(orm.Data, filters={'uuid': str(source_uuid)}, tag='source').append(
        orm.CalcJobNode, with_incoming='source', edge_filters={'label': label}, tag='run',
        filters={'process_type': process_type}, project=['uuid', 'label', 'ctime'])
    return [(f'{title} · {date:%Y-%m-%d %H:%M} · {str(uuid)[:8]}', str(uuid))
            for uuid, title, date in query.order_by({'run': {'ctime': 'desc'}}).all()]


def map_history(cube_uuid):
    manifest = orm.load_node(cube_uuid).outputs.manifest
    return history(manifest.uuid, 'source_manifest', MAP_PROCESS)


def source_data(cube_uuid):
    node = orm.load_node(cube_uuid)
    manifest = node.outputs.manifest
    producer = manifest.creator
    if producer is None or producer.process_type != 'aiida.calculations:empa_orca.dyson_cubes' or not producer.is_finished_ok:
        raise ValueError('Select completed Dyson amplitude cubes')
    return dict(manifest_uuid=str(manifest.uuid), manifest=manifest.get_dict(),
                transitions_uuid=str(producer.inputs.transitions.uuid), table=producer.inputs.transitions.get_dict())


def prepare_maps(cube_uuid, parameters, code_uuid):
    data = source_data(cube_uuid)
    # Match AiiDA's attribute serialization before exact provenance comparison.
    p = stored_values(map_parameters(parameters))
    cubes = selected_cubes(data['manifest'], data['table'], p)
    if not code_uuid:
        raise ValueError('Configure ORCA Dyson tools on the cube computer')
    plan = dict(cube_uuid=str(cube_uuid), parameters=p, code_uuid=str(code_uuid), action='compute')
    # Numerical maps are durable; reuse them before checking expendable cubes.
    for _, uuid in map_history(cube_uuid):
        run = orm.load_node(uuid)
        if (run.is_finished_ok and run.inputs.parameters.get_dict() == p and str(run.inputs.code.uuid) == str(code_uuid)
                and 'maps' in run.outputs and 'map_metadata' in run.outputs):
            run.outputs.maps.get_array('intensity')
            return dict(plan, action='reuse', reuse_uuid=uuid)
    locations = [render_source(cube_uuid, c['filename'], 'full') for c in cubes]
    if len({(r['kind'], r['uuid']) for r in locations}) != 1:
        raise ValueError('Selected amplitude cubes must share a full-resolution source')
    return dict(plan, location=locations[0])


def submit_maps(plan):
    checked = prepare_maps(plan['cube_uuid'], plan['parameters'], plan['code_uuid'])
    if checked['action'] == 'reuse':
        return checked['reuse_uuid']
    data = source_data(plan['cube_uuid'])
    b = DysonMapsCalculation.get_builder()
    b.code = orm.load_code(plan['code_uuid'])
    b.source_manifest = orm.load_node(data['manifest_uuid'])
    b.transitions = orm.load_node(data['transitions_uuid'])
    b.parameters = orm.Dict(dict=checked['parameters'])
    b['source_'+checked['location']['kind']] = orm.load_node(checked['location']['uuid'])
    b.metadata.options = calcjob_options(b.source_manifest.creator.outputs.remote_folder, seconds=3600)
    b.metadata.disable_cache = True
    b.metadata.label = 'Constant-height Dyson '+checked['parameters']['kind']+' maps'
    return str(submit(b).uuid)


def map_result(uuid):
    node = orm.load_node(uuid)
    if not node.is_finished_ok or node.process_type != MAP_PROCESS:
        raise ValueError('Select successful numerical maps')
    return dict(metadata=node.outputs.map_metadata.get_dict(), maps_uuid=str(node.outputs.maps.uuid),
                figures=history(node.outputs.maps.uuid, 'maps', FIGURE_PROCESS))


def submit_figure(map_uuid, settings, code_uuid):
    node = orm.load_node(map_uuid)
    if not node.is_finished_ok or node.process_type != MAP_PROCESS:
        raise ValueError('Compute numerical maps before rendering')
    p = stored_values(figure_style(settings))
    for _, uuid in history(node.outputs.maps.uuid, 'maps', FIGURE_PROCESS):
        old = orm.load_node(uuid)
        if old.is_finished_ok and old.inputs.settings.get_dict() == p and str(old.inputs.code.uuid) == str(code_uuid):
            for key in ('png', 'pdf'):
                with old.outputs[key].open(mode='rb') as handle:
                    if not handle.read(8):
                        raise ValueError('Empty stored figure')
            return str(uuid)
    b = MapFigureCalculation.get_builder()
    b.code = orm.load_code(code_uuid)
    b.maps, b.map_metadata = node.outputs.maps, node.outputs.map_metadata
    b.settings = orm.Dict(dict=p)
    b.metadata.options = calcjob_options(node.outputs.remote_folder)
    b.metadata.disable_cache = True
    b.metadata.label = 'Dyson maps · shared intensity scale'
    return str(submit(b).uuid)


def figure_result(uuid):
    node = orm.load_node(uuid)
    if node.process_type != FIGURE_PROCESS or not node.is_finished_ok:
        raise ValueError('Select a successful map figure')
    images = {}
    for key in ('png', 'pdf'):
        with node.outputs[key].open(mode='rb') as handle:
            images[key] = handle.read()
    return dict(images=images, settings=node.inputs.settings.get_dict(),
                png_uuid=str(node.outputs.png.uuid), pdf_uuid=str(node.outputs.pdf.uuid))
