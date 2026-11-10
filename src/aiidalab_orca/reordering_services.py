"""Reviewed orbital-reordering operations; return only UUIDs and plain data."""

from aiida import engine, orm

from aiida_empa_orca import orbital_reordering_job as backend
from aiida_empa_orca.artifacts import resolve_electronic
from aiida_empa_orca.casci import validate_reference
from aiida_empa_orca.native_logs import output_policy
from aiida_empa_orca.orbital_reordering import selection_plan


def references(retrieved_uuid, code_uuid):
    query = orm.QueryBuilder().append(orm.Dict, filters={
        'attributes.preparation': backend.PREPARATION,
        'attributes.source_retrieved_uuid': str(retrieved_uuid)}, tag='reference').append(
            orm.WorkChainNode, with_outgoing='reference', edge_filters={'label': 'orbital_reference'},
            filters={'process_type': backend.PROCESS, 'attributes.process_state': 'finished',
                     'attributes.exit_status': 0}, tag='run', project='uuid')
    return [str(uuid) for uuid in query.order_by({'run': {'ctime': 'desc'}}).all(flat=True)
            if str(orm.load_node(uuid).inputs.code.uuid) == str(code_uuid)]


def review(common_uuid, space, export_uuid, *, resources, native_output_policy):
    from . import casci_services, inspection_services, property_services
    node = inspection_services.common_node(common_uuid)
    ref = casci_services.reference_data(common_uuid)
    validate_reference(node.outputs.orbital_reference, node.outputs.remote_folder)
    catalog = inspection_services.catalog(common_uuid)
    if not catalog or catalog['reference_uuid'] != str(node.outputs.orbital_reference.uuid):
        raise ValueError('Read orbital information for this exact source before reviewing its permutation')
    if ref['kind'] not in catalog['data']['sets']:
        raise ValueError('The selected CAS spatial set is absent from the source catalog')
    selected = catalog['data']['sets'][ref['kind']]
    plan = selection_plan(ref, space, [r['occupation'] for r in selected['levels']],
        source_reference_uuid=str(node.outputs.orbital_reference.uuid), source_file_sha256=selected['sha256'])
    backend.validate_request(ref, plan)
    backend.validate_catalog(orm.load_node(catalog['uuid']), node.outputs.orbital_reference,
                             node.outputs.remote_folder, plan)
    exporter = orm.load_code(export_uuid)
    if exporter.computer.uuid != node.inputs.code.computer.uuid:
        raise ValueError('Choose the ORCA exporter on the source computer')
    helper_uuid = property_services.helper_code(node.inputs.code.computer.uuid)
    retention = output_policy(native_output_policy)
    budget = backend.checked_resources(ref, resources)
    resolve_electronic(node.outputs.remote_folder, names=[ref['filename']])
    reuse, reused_resources, reused_policy = None, None, None
    query = orm.QueryBuilder().append(orm.Dict, filters={'uuid': str(node.outputs.orbital_reference.uuid)}, tag='source').append(
        orm.WorkChainNode, with_incoming='source', edge_filters={'label': 'orbital_reference'},
        filters={'process_type': backend.PROCESS}, tag='run', project='uuid')
    for uuid in query.order_by({'run': {'ctime': 'desc'}}).all(flat=True):
        old = orm.load_node(uuid)
        if (old.inputs.plan.get_dict() == plan and old.inputs.export_code.uuid == exporter.uuid and
                str(old.inputs.storage_code.uuid) == helper_uuid and
                (not old.is_terminated or old.is_finished_ok)):
            if old.is_finished_ok:
                resolve_electronic(old.outputs.remote_folder, names=['aiida.gbw'])
            reuse = str(uuid)
            reused_resources = old.inputs.resources.get_dict()
            reused_policy = old.inputs.native_output_policy.get_dict()
            break
    return {'common_uuid': str(common_uuid), 'space': space, 'catalog_uuid': catalog['uuid'],
            'plan': plan, 'export_uuid': str(export_uuid), 'helper_uuid': helper_uuid,
            'resources': budget, 'native_output_policy': retention,
            'reused_resources': reused_resources, 'reused_policy': reused_policy,
            'reuse_uuid': reuse, 'action': 'reuse' if reuse else 'prepare'}


def builder(plan):
    from .inspection_services import common_node
    current = review(plan['common_uuid'], plan['space'], plan['export_uuid'],
        resources=plan['resources'], native_output_policy=plan['native_output_policy'])
    if current != plan:
        raise ValueError('Source, catalog, mapping, execution or retention changed; review again')
    source = common_node(plan['common_uuid'])
    ref = source.outputs.orbital_reference.get_dict()
    b = backend.OrbitalReorderingWorkChain.get_builder()
    b.structure = orm.load_node(ref['structure_uuid'])
    b.orbital_reference, b.source_remote = source.outputs.orbital_reference, source.outputs.remote_folder
    b.code, b.export_code = source.inputs.code, orm.load_code(plan['export_uuid'])
    b.storage_code = orm.load_code(plan['helper_uuid'])
    b.storage_policy = orm.Dict(dict=backend.compatibility_storage_policy(plan['native_output_policy']))
    b.catalog = orm.load_node(plan['catalog_uuid'])
    b.plan, b.resources = orm.Dict(dict=plan['plan']), orm.Dict(dict=plan['resources'])
    b.native_output_policy = orm.Dict(dict=plan['native_output_policy'])
    b.metadata.label = 'Verified shared orbital permutation · ' + ' '.join(map(str, plan['space']['orbitals']))
    return b


def submit(plan):
    current = review(plan['common_uuid'], plan['space'], plan['export_uuid'],
        resources=plan['resources'], native_output_policy=plan['native_output_policy'])
    if current != plan:
        raise ValueError('The reviewed request changed or is already running; review again')
    if plan['reuse_uuid']:
        return plan['reuse_uuid']
    return str(engine.submit(builder(plan)).uuid)


def prepared_space(uuid):
    node = orm.load_node(uuid)
    if node.process_type != backend.PROCESS or not node.is_finished_ok:
        raise ValueError('The signed orbital permutation has not passed')
    validate_reference(node.outputs.orbital_reference, node.outputs.remote_folder)
    return node.outputs.orbital_reference.get_dict()['reordered_active_space']
