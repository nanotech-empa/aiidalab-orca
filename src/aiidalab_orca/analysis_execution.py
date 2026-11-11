"""Read-only busy checks across Dyson/Kondo exports, cubes, maps and figures."""
from aiida import orm

PROCESS_TYPES = ('aiida.workflows:empa_orca.dyson', 'aiida.workflows:empa_orca.dyson_export',
    'aiida.workflows:empa_orca.dyson_cubes', 'aiida.calculations:empa_orca.dyson_maps',
    'aiida.calculations:empa_orca.map_figure', 'aiida.workflows:empa_orca.kondo',
    'aiida.workflows:empa_orca.kondo_cubes', 'aiida.calculations:empa_orca.kondo',
    'aiida.calculations:empa_orca.kondo_reference_cubes', 'aiida.calculations:empa_orca.kondo_cubes',
    'aiida.calculations:empa_orca.kondo_maps')


def process_reference(uuid):
    node=orm.load_node(uuid)
    if 'maps' in node.inputs:
        producer=node.inputs.maps.creator
        return process_reference(producer.uuid) if producer else None
    for name in ('initial','state_energies','transitions','channels'):
        if name in node.inputs:
            return node.inputs[name].get_dict().get('orbital_reference_uuid')
    return None


def assert_idle(reference_uuid):
    if not reference_uuid:return
    uuids=orm.QueryBuilder().append(orm.ProcessNode,
        filters={'process_type':{'in':list(PROCESS_TYPES)},
                 'attributes.process_state':{'!in':['finished','excepted','killed']}},project='uuid').all(flat=True)
    for uuid in uuids:
        if process_reference(uuid)==str(reference_uuid):
            raise ValueError('A Dyson/Kondo analysis stage is still active: '+str(uuid)+'. Wait for completion before another submission.')
