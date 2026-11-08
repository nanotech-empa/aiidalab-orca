"""Operation-local access for reviewed vertical optics and native NTO previews."""

import hashlib
import json

from aiida import engine, orm
from aiida_empa_orca import optical
from aiida_empa_orca.artifacts import native_retention, resolve_electronic, stash_options, storage_policy
from aiida_empa_orca.native_logs import output_policy
from aiida_empa_orca.common_orbitals import attach_orbital, options
from aiida_empa_orca.orbitals import cube_parameters, validate_cube_outputs
from aiida_empa_orca.rendering import calcjob_options

from .property_services import default_stash_directory, helper_code, source_node, source_remote, tool_codes


def _signature(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, allow_nan=False).encode()).hexdigest()


def defaults(source_uuid):
    source = source_node(source_uuid)
    from aiida_empa_orca.protocols import reference as reference_type
    electronic = source.inputs.settings.get_dict()
    return optical.settings({}, electronic) | {'reference_type': reference_type(electronic)}


def runs(source_uuid):
    source = source_node(source_uuid)
    rows = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': str(source.outputs.retrieved.uuid)}, tag='source').append(
        orm.CalcJobNode, with_incoming='source', edge_filters={'label': 'source_retrieved'}, tag='run',
        filters={'process_type': optical.PROCESS_TYPE}, project=['uuid', 'label', 'ctime', 'attributes.process_state'])
    return [{'uuid': str(uid), 'label': label, 'date': date.isoformat(), 'state': state}
            for uid, label, date, state in rows.order_by({'run': {'ctime': 'desc'}}).all()]


def review(source_uuid, values, force=False, *, native_output_policy=None):
    source = source_node(source_uuid)
    electronic = source.inputs.settings.get_dict()
    effective = optical.settings(values, electronic)
    retention = output_policy(native_output_policy)
    identity = {'source_retrieved_uuid': str(source.outputs.retrieved.uuid), 'settings': effective,
                'structure_uuid': str(source.outputs.structure.uuid), 'code_uuid': str(source.inputs.code.uuid)}
    key = _signature(identity)
    reuse = None
    for row in ([] if force else runs(source_uuid)):
        old = orm.load_node(row['uuid'])
        if (old.inputs.settings.get_dict() == effective and str(old.inputs.code.uuid) == identity['code_uuid']
                and (not old.is_terminated or old.is_finished_ok)):
            reuse = str(old.uuid)
            break
    if reuse is None:
        resolve_electronic(source_remote(source), names=['aiida.gbw'])
    return dict(identity, source_uuid=str(source_uuid), signature=key, force=bool(force),
                native_output_policy=retention,
                reuse_uuid=reuse, action='reuse' if reuse else 'compute',
                input=optical.optical_input(electronic, effective), execution=source.inputs.code.full_label)


def builder(plan):
    checked = review(plan['source_uuid'], plan['settings'], plan['force'],
                     native_output_policy=plan.get('native_output_policy'))
    if any(checked[k] != plan[k] for k in ('signature', 'input', 'code_uuid')):
        raise ValueError('The optical request changed; review it again')
    source = source_node(plan['source_uuid'])
    b = optical.OpticalCalculation.get_builder()
    b.code, b.structure = source.inputs.code, source.outputs.structure
    b.compact_code = orm.load_code(helper_code(source.inputs.code.computer.uuid))
    b.native_output_policy = orm.Dict(dict=checked['native_output_policy'])
    b.electronic_settings, b.settings = source.inputs.settings, orm.Dict(dict=plan['settings'])
    b.source_retrieved, b.source_remote = source.outputs.retrieved, source_remote(source)
    attach_orbital(b, resolve_electronic(source_remote(source), names=['aiida.gbw']), 'aiida.gbw')
    resources = calcjob_options(source_remote(source), seconds=plan['settings']['wallclock_seconds'])
    resources.update(options(plan['settings']))
    b.metadata.options = resources
    if checked['native_output_policy']['mode'] == 'stash':
        b.metadata.options.stash = stash_options(checked['native_output_policy']['stash_directory'], 'native_output')
    b.metadata.disable_cache = True
    b.metadata.label = source.outputs.structure.get_formula() + ' · ' + plan['settings']['method'] + ' · vertical optical excitations'
    return b


def submit(plan):
    checked = review(plan['source_uuid'], plan['settings'], plan['force'],
                     native_output_policy=plan.get('native_output_policy'))
    if checked['signature'] != plan['signature']:
        raise ValueError('The optical request changed; review it again')
    return checked['reuse_uuid'] or str(engine.submit(builder(plan)).uuid)


def result(uuid):
    node = orm.load_node(uuid)
    if node.process_type != optical.PROCESS_TYPE or not node.is_finished_ok:
        raise ValueError('Choose a successfully validated optical calculation')
    return node.outputs.excitations.get_dict() | {'uuid': str(uuid), 'excitations_uuid': str(node.outputs.excitations.uuid)}


def cube_defaults(optical_uuid):
    node = orm.load_node(optical_uuid)
    codes = tool_codes(node.computer.uuid)
    retention = native_retention(node.outputs.remote_folder)
    policy = {'threshold_mb': 0, 'stash_directory': retention.get('stash_directory', default_stash_directory())}
    return {'codes': codes, 'storage_policy': policy}


def source_node_from_optical(optical_uuid):
    """Return only for immediate, same-operation use; never cache this ORM node."""
    node = orm.load_node(optical_uuid)
    for link in node.inputs.source_retrieved.base.links.get_incoming().all():
        if link.node.process_type in ('aiida.workflows:empa_orca.geometry', 'aiida.workflows:empa_orca.reference'):
            return source_node(str(link.node.uuid))
    raise ValueError('No geometry/SCF entry is linked to this optical calculation')


def cube_runs(optical_uuid):
    node = orm.load_node(optical_uuid)
    return orm.QueryBuilder().append(orm.Dict, filters={'uuid': str(node.outputs.excitations.uuid)}, tag='source').append(
        orm.WorkChainNode, with_incoming='source', edge_filters={'label': 'excitations'}, tag='run',
        filters={'process_type': optical.NTO_PROCESS}, project='uuid').order_by({'run': {'ctime': 'desc'}}).all(flat=True)


def review_cubes(optical_uuid, selection, parameters, policy, codes, force=False):
    data = result(optical_uuid)
    state, orbitals = optical.nto_selection(data, selection)
    parameters = cube_parameters(dict(parameters, orbitals=orbitals, spin_density=False))
    policy = storage_policy(dict(policy, threshold_mb=0))
    node = orm.load_node(optical_uuid)
    computer = node.computer.uuid
    codes = dict(codes, helper=helper_code(computer))
    if any(not uid or orm.load_code(uid).computer.uuid != computer for uid in codes.values()):
        raise ValueError('Select ORCA plot and cubehandler on the optical calculation computer')
    signature = _signature({'optical_uuid': str(optical_uuid), 'selection': selection, 'parameters': parameters,
                            'policy': policy, 'codes': codes})
    reuse = None
    for uid in ([] if force else cube_runs(optical_uuid)):
        old = orm.load_node(uid)
        if (old.inputs.selection.get_dict() == selection and old.inputs.parameters.get_dict() == parameters and
                old.inputs.storage_policy.get_dict() == policy and
                all(str(old.inputs[k].uuid) == codes[v] for k, v in
                    [('code', 'helper'), ('plot_code', 'plot'), ('cubehandler_code', 'cubehandler')])):
            if not old.is_terminated:
                reuse = str(uid)
                break
            if old.is_finished_ok:
                try:
                    validate_cube_outputs(old)
                    reuse = str(uid)
                    break
                except (ValueError, OSError):
                    continue
    if reuse is None:
        resolve_electronic(node.outputs.remote_folder, names=[state['nto']['filename']])
    return {'optical_uuid': str(optical_uuid), 'selection': selection, 'parameters': parameters,
            'policy': policy, 'codes': codes, 'force': bool(force), 'signature': signature,
            'reuse_uuid': reuse, 'action': 'reuse' if reuse else 'compute'}


def cube_builder(plan):
    codes = {k: v for k, v in plan['codes'].items() if k != 'helper'}
    checked = review_cubes(plan['optical_uuid'], plan['selection'], plan['parameters'], plan['policy'], codes, plan['force'])
    if checked['signature'] != plan['signature']:
        raise ValueError('The NTO request changed; review it again')
    source = orm.load_node(plan['optical_uuid'])
    b = optical.NtoCubesWorkChain.get_builder()
    b.excitations, b.source_remote = source.outputs.excitations, source.outputs.remote_folder
    b.selection, b.parameters = orm.Dict(dict=plan['selection']), orm.Dict(dict=plan['parameters'])
    b.storage_policy = orm.Dict(dict=plan['policy'])
    b.code, b.plot_code, b.cubehandler_code = [orm.load_code(plan['codes'][k]) for k in ('helper', 'plot', 'cubehandler')]
    b.metadata.label = 'NTO hole/particle previews · ' + plan['selection']['state_id']
    return b


def submit_cubes(plan):
    codes = {k: v for k, v in plan['codes'].items() if k != 'helper'}
    checked = review_cubes(plan['optical_uuid'], plan['selection'], plan['parameters'], plan['policy'], codes, plan['force'])
    if checked['signature'] != plan['signature']:
        raise ValueError('The NTO request changed; review it again')
    return checked['reuse_uuid'] or str(engine.submit(cube_builder(plan)).uuid)


def preview_inventory(optical_uuid):
    """Inspect only stored pair previews, never full remote/stashed cubes."""
    from .optical_data import pair_members
    data = result(optical_uuid)
    states = {r['id']: r for r in data['states']}
    records = []
    for uid in cube_runs(optical_uuid):
        node = orm.load_node(uid)
        selection = node.inputs.selection.get_dict()
        record = {'uuid': str(uid), 'date': node.ctime.isoformat(), 'state_id': selection['state_id'],
                  'pairs': selection['pairs'], 'finished': node.is_terminated, 'success': node.is_finished_ok,
                  'ready_pairs': [], 'members': {}}
        state = states.get(record['state_id'])
        if node.is_finished_ok and state and state['nto']:
            cubes = node.outputs.manifest.get_dict()['cubes']
            for number in record['pairs']:
                members = pair_members(state, number, cubes)
                try:
                    for filename in members.values():
                        with node.outputs.retrieved.base.repository.open('previews/'+filename, mode='rb') as handle:
                            if len(handle.read(32)) < 32:
                                raise ValueError('Empty stored cube preview')
                except (OSError, ValueError):
                    members = {}
                if members:
                    record['ready_pairs'].append(number)
                    record['members'][str(number)] = members
        records.append(record)
    return records
