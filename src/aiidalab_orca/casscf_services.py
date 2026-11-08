"""Reviewable CASSCF operations; only identifiers/plain data leave this module."""

from aiida import engine, orm
from aiida_empa_orca import casscf
from aiida_empa_orca.artifacts import resolve_electronic
from aiida_empa_orca.casci import signature, validate_reference
from aiida_empa_orca.native_logs import output_policy


def optimized_references(retrieved_uuid, code_uuid):
    query = orm.QueryBuilder().append(orm.Dict, filters={
        'attributes.preparation': casscf.PREPARATION,
        'attributes.source_retrieved_uuid': str(retrieved_uuid)}, tag='reference').append(
            orm.WorkChainNode, with_outgoing='reference', edge_filters={'label': 'orbital_reference'},
            filters={'process_type': casscf.PROCESS_TYPE, 'attributes.process_state': 'finished',
                     'attributes.exit_status': 0}, tag='run', project='uuid')
    return [uuid for uuid in query.order_by({'run': {'ctime': 'desc'}}).all(flat=True)
            if str(orm.load_node(uuid).inputs.code.uuid) == str(code_uuid)]


def review(reference_uuid, space, values, *, force=False, native_output_policy=None):
    from .casci_services import reference_data
    retention = output_policy(native_output_policy)
    node = orm.load_node(reference_uuid)
    ref = reference_data(reference_uuid)
    validate_reference(node.outputs.orbital_reference, node.outputs.remote_folder)
    settings = casscf.casscf_settings(values, ref, space)
    key = signature(node.outputs.orbital_reference.uuid, space, settings, node.inputs.code.uuid)
    reuse = None
    query = orm.QueryBuilder().append(orm.Dict, filters={'uuid': str(node.outputs.orbital_reference.uuid)}, tag='ref').append(
        orm.WorkChainNode, with_incoming='ref', edge_filters={'label': 'orbital_reference'},
        filters={'process_type': casscf.PROCESS_TYPE}, tag='run', project='uuid')
    for uuid in ([] if force else query.order_by({'run': {'ctime': 'desc'}}).all(flat=True)):
        old = orm.load_node(uuid)
        old_key = signature(old.inputs.orbital_reference.uuid, old.inputs.active_space.get_dict(),
                            old.inputs.settings.get_dict(), old.inputs.code.uuid)
        if old_key == key and (not old.is_terminated or old.is_finished_ok):
            if old.is_finished_ok:
                resolve_electronic(old.outputs.remote_folder, names=['aiida.gbw'])
            reuse = str(uuid)
            break
    if not reuse:
        resolve_electronic(node.outputs.remote_folder, names=[ref['filename']])
    return {'reference_uuid': str(reference_uuid), 'active_space': space, 'values': values,
            'native_output_policy': retention,
            'force_recompute': bool(force),
            'settings': settings, 'signature': key, 'reuse_uuid': reuse,
            'action': 'reuse' if reuse else 'compute',
            'code_uuid': str(node.inputs.code.uuid),
            'execution': f'{node.inputs.code.label}@{node.inputs.code.computer.label}',
            'input': casscf.casscf_input(ref, space, settings),
            'readback_input': casscf.casscf_input(ref, space, settings, readback=True)}


def builder(plan):
    current = review(plan['reference_uuid'], plan['active_space'], plan['values'], force=plan.get('force_recompute', False),
                     native_output_policy=plan.get('native_output_policy'))
    if any(current[k] != plan[k] for k in ('signature', 'code_uuid', 'input', 'readback_input')):
        raise ValueError('The CASSCF request changed; review it again')
    node = orm.load_node(plan['reference_uuid'])
    ref = node.outputs.orbital_reference.get_dict()
    b = casscf.CasscfWorkChain.get_builder()
    b.structure = orm.load_node(ref['structure_uuid'])
    b.orbital_reference, b.source_remote = node.outputs.orbital_reference, node.outputs.remote_folder
    b.active_space, b.settings = orm.Dict(dict=plan['active_space']), orm.Dict(dict=plan['settings'])
    b.code, b.storage_code, b.storage_policy = node.inputs.code, node.inputs.storage_code, node.inputs.storage_policy
    b.native_output_policy = orm.Dict(dict=current['native_output_policy'])
    from aiida_empa_orca.pdos_workflow import configure, default_plan
    configure(b, default_plan(node.inputs.code.computer.uuid))
    b.metadata.label = b.structure.get_formula() + ' · ' + ('SA-CASSCF' if plan['settings']['mode'] == 'state_average' else 'CASSCF')
    return b


def submit(plan):
    current = review(plan['reference_uuid'], plan['active_space'], plan['values'], force=plan.get('force_recompute', False),
                     native_output_policy=plan.get('native_output_policy'))
    if current['signature'] != plan['signature']:
        raise ValueError('The request changed; review CASSCF again')
    return current['reuse_uuid'] or str(engine.submit(builder(plan)).uuid)


def results(uuid):
    node = orm.load_node(uuid)
    if node.process_type != casscf.PROCESS_TYPE or not node.is_finished_ok:
        raise ValueError('Select a completed CASSCF reference with passing readback checks')
    return node.outputs.state_energies.get_dict()


def diagnostics(uuid):
    node = orm.load_node(uuid)
    messages = []
    for child in node.called_descendants:
        if child.is_failed:
            messages.append(str(child.uuid) + ': ' + (child.exit_message or 'Calculation failed'))
            messages.extend(entry.message for entry in orm.Log.collection.get_logs_for(child)
                            if entry.levelname in ('ERROR', 'CRITICAL'))
    return list(dict.fromkeys(messages))


def history(reference_uuid, space):
    node = orm.load_node(reference_uuid)
    query = orm.QueryBuilder().append(orm.Dict, filters={'uuid': str(node.outputs.orbital_reference.uuid)}, tag='ref').append(
        orm.WorkChainNode, with_incoming='ref', edge_filters={'label': 'orbital_reference'},
        filters={'process_type': casscf.PROCESS_TYPE}, tag='run', project='uuid')
    rows = []
    for uuid in query.order_by({'run': {'ctime': 'desc'}}).all(flat=True):
        old = orm.load_node(uuid)
        if old.inputs.active_space.get_dict() == space:
            rows.append((old.ctime.strftime('%Y-%m-%d %H:%M') + ' · ' + old.label + ' · ' + old.process_state.value, str(uuid)))
    return rows
