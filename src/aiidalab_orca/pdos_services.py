"""Operation-local orbital-character services. Durable state contains UUIDs only."""
from aiida import engine, orm
from aiida_empa_orca.orbital_inspection import variants
from aiida_empa_orca.pdos import PROCESS, validate_arrays
from aiida_empa_orca.pdos_workflow import available_codes, character_builder

from . import property_services


def context(source_uuid):
    node = orm.load_node(source_uuid)
    if node.process_type in ('aiida.workflows:empa_orca.common_orbitals', 'aiida.workflows:empa_orca.casscf') and node.is_finished_ok:
        ref = node.outputs.orbital_reference.get_dict()
        return {'source_uuid': str(node.uuid), 'remote_uuid': str(node.outputs.remote_folder.uuid),
                'structure_uuid': str(node.inputs.structure.uuid), 'charge': ref['charge'],
                'multiplicity': ref['source_multiplicity'], 'sets': variants(ref),
                'automatic_status': node.outputs.pdos_status.get_dict() if 'pdos_status' in node.outputs else {}}
    node = property_services.source_node(source_uuid)
    settings = node.inputs.settings.get_dict()
    return {'source_uuid': str(node.uuid), 'remote_uuid': str(property_services.source_remote(node).uuid),
            'structure_uuid': str(node.outputs.structure.uuid), 'charge': settings['charge'],
            'multiplicity': settings['multiplicity'], 'sets': {'SCF': 'aiida.gbw'},
            'automatic_status': node.outputs.pdos_status.get_dict() if 'pdos_status' in node.outputs else {}}


def codes(source_uuid):
    info = context(source_uuid)
    computer_uuid = orm.load_node(info['remote_uuid']).computer.uuid
    return available_codes(computer_uuid)


def runs(source_uuid, kind):
    return orm.QueryBuilder().append(orm.Dict, filters={
        'attributes.source_uuid': str(source_uuid), 'attributes.kind': kind}, tag='identity').append(
            orm.CalcJobNode, with_incoming='identity', edge_filters={'label': 'identity'},
            filters={'process_type': PROCESS}, tag='job', project=['uuid']).order_by(
                {'job': {'ctime': 'desc'}}).all(flat=True)


def result(uuid):
    node = orm.load_node(uuid)
    if not node.is_finished_ok or node.process_type != PROCESS:
        raise ValueError('Select a completed orbital-character CalcJob')
    arrays = {name: node.outputs.character.get_array(name) for name in node.outputs.character.get_arraynames()}
    metadata = node.outputs.metadata.get_dict()
    validate_arrays(metadata, arrays)
    return {'uuid': str(node.uuid), 'metadata_uuid': str(node.outputs.metadata.uuid),
            'arrays_uuid': str(node.outputs.character.uuid), 'metadata': metadata, 'arrays': arrays}


def latest(source_uuid, kind):
    for uuid in runs(source_uuid, kind):
        node = orm.load_node(uuid)
        if node.is_finished_ok:
            return result(uuid)
    return None


def builder(source_uuid, kind, export_uuid, helper_uuid, memory_gib=8, *, wallclock_seconds=1800):
    return character_builder(context(source_uuid), kind, export_uuid, helper_uuid, memory_gib,
                             wallclock_seconds=wallclock_seconds)


def submit(source_uuid, kind, export_uuid, helper_uuid, force=False, memory_gib=8, *, wallclock_seconds=1800):
    if not force:
        old = latest(source_uuid, kind)
        if old:
            return old['uuid']
    return str(engine.submit(builder(source_uuid, kind, export_uuid, helper_uuid, memory_gib,
                                     wallclock_seconds=wallclock_seconds)).uuid)
