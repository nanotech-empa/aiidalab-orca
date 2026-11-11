"""Operation-local AiiDA access for state-pair planning and Dyson results."""
from pathlib import PurePosixPath

from aiida import orm
from aiida.engine import submit

from aiida_empa_orca import dyson as backend
from aiida_empa_orca.dyson_data import selection
from aiida_empa_orca.artifacts import resolve_electronic
from aiida_empa_orca.orbitals import cube_parameters
from aiida_empa_orca.native_logs import output_policy
from .inspection_services import codes as inspection_codes,common_node
from .casci_services import progress  # re-export short-lived monitoring
from aiida_empa_orca.rendering import helper_resources
from .analysis_execution import assert_idle


def codes(common_uuid):
    result = inspection_codes(common_uuid)
    common = common_node(common_uuid)
    computer_uuid = common.inputs.code.computer.uuid
    result['storage_policy'] = common.inputs.storage_policy.get_dict()
    result['dyson'] = []
    for uuid in orm.QueryBuilder().append(orm.InstalledCode,project=['uuid']).all(flat=True):
        node = orm.load_code(uuid)
        if node.computer.uuid == computer_uuid and PurePosixPath(node.filepath_executable).name == 'orca-dyson':
            result['dyson'].append((f'{node.label}@{node.computer.label}',str(uuid)))
    return result


def states(datasets):
    result = []
    for data in datasets:
        node = orm.load_node(data['workflow_uuid'])
        state_uuid = str(node.outputs.state_energies.uuid)
        for row in data['states']:
            result.append(dict(row,state_uuid=state_uuid,workflow_uuid=data['workflow_uuid']))
    return result


def builder(plan):
    common = common_node(plan['common_uuid'])
    b = backend.DysonWorkChain.get_builder()
    b.initial = orm.load_node(plan['initial_uuid'])
    for key,uuid in plan['finals'].items():
        b.finals[key] = orm.load_node(uuid)
    b.selection = orm.Dict(dict=plan['selection'])
    b.code,b.export_code = orm.load_code(plan['codes']['dyson']),orm.load_code(plan['codes']['export'])
    b.storage_policy = common.inputs.storage_policy
    b.export_resources = orm.Dict(dict=helper_resources(plan.get('export_resources')))
    b.runtime = orm.Dict(dict=backend.runtime_settings(plan.get('runtime',{})))
    b.retention_policy = orm.Dict(dict=output_policy(plan.get('retention_policy')))
    b.force_recompute = orm.Bool(plan.get('force',False))
    b.metadata.label = 'CASCI Dyson transitions and spectral weights'
    return b


def review(common_uuid,initial,finals,selected_codes,loss=1e-5,force=False,runtime=None, *, retention_policy=None,export_resources=None):
    if not initial or not finals:
        raise ValueError('Choose an initial state and at least one compatible final state')
    if any(not selected_codes.get(key) for key in ('dyson','export')):
        raise ValueError('Configure ORCA export and ORCA Dyson codes on the calculation computer')
    grouped = {}
    for uuid,root in finals:
        grouped.setdefault(uuid,[]).append(root)
    mapping = {'s'+str(i):uuid for i,uuid in enumerate(sorted(grouped))}
    initial_node = orm.load_node(initial[0])
    selected = selection({'initial_root':initial[1],'final_roots':{key:grouped[uuid] for key,uuid in mapping.items()},
                          'max_missing_ci_norm':loss},initial_node.get_dict(),
                         {key:orm.load_node(uuid).get_dict() for key,uuid in mapping.items()})
    plan = {'common_uuid':common_uuid,'initial_uuid':initial[0],'finals':mapping,'selection':selected,
            'codes':selected_codes,'force':force,'action':'compute','exports':[],
            'retention_policy':output_policy(retention_policy),
            'runtime':backend.runtime_settings({} if runtime is None else runtime),
            'export_resources':helper_resources(export_resources)}
    b = builder(plan)
    if not force:
        for uuid in backend.previous(initial_node.uuid,'initial',backend.DYSON_PROCESS):
            old = orm.load_node(uuid)
            if old.is_finished_ok and backend.same_request(old,b,selected):
                backend.validate_transitions(old)
                return dict(plan,action='reuse',reuse_uuid=str(uuid))
    for uuid in [initial[0],*mapping.values()]:
        state = orm.load_node(uuid)
        old = backend.existing_export(state,orm.load_code(selected_codes['export']),orm.load_code(selected_codes['dyson']))
        if old:
            status = 'Reuse preserved wavefunction export'
        else:
            backend.native_log_location(backend.state_source(state))
            location = resolve_electronic(backend.state_source(state).outputs.remote_folder,names=['aiida.gbw'])
            status = 'Export existing CASCI wavefunction from '+location['kind']
        first = state.get_dict()['states'][0]
        plan['exports'].append({'state_uuid':uuid,'label':f"q={first['charge']:+d}, multiplicity {first['multiplicity']}",'action':status})
    return plan


def submit_dyson(plan):
    if plan['action']!='reuse':
        assert_idle(orm.load_node(plan['initial_uuid']).get_dict().get('orbital_reference_uuid'))
    return str(submit(builder(plan)).uuid)


def runs(initial_uuid,root):
    result = []
    for uuid in backend.previous(initial_uuid,'initial',backend.DYSON_PROCESS):
        node = orm.load_node(uuid)
        if node.inputs.selection.get_dict()['initial_root'] == root:
            result.append((f'{node.ctime:%Y-%m-%d %H:%M} · {node.process_state.value} · {str(uuid)[:8]}',str(uuid)))
    return result


def result(uuid):
    node = orm.load_node(uuid)
    return {'uuid':str(uuid),'data':node.outputs.transitions.get_dict(),'transitions_uuid':str(node.outputs.transitions.uuid)}


def diagram_states(table,context):
    """Display the original source sectors, even after a newer CASCI rerun."""
    if table.get('initial_states'):
        return []  # The diagram currently assumes one initial state.
    uuids = {table['initial_state_uuid']} | {r['final_state_uuid'] for r in table['transitions']}
    source_rows,sectors = [],set()
    for uuid in sorted(uuids):
        data = orm.load_node(uuid).get_dict()
        for row in data['states']:
            sectors.add((row['charge'],row['multiplicity']))
            source_rows.append(dict(row,state_uuid=str(uuid)))
    return [r for r in context if (r['charge'],r['multiplicity']) not in sectors]+source_rows


def submit_cubes(transitions_uuid,parameters,code_uuid,cubehandler_uuid,blend=None,*,resources=None):
    if not code_uuid or not cubehandler_uuid:
        raise ValueError('Configure Dyson and cubehandler codes on the calculation computer')
    b = backend.DysonCubesWorkChain.get_builder()
    b.transitions = orm.load_node(transitions_uuid)
    assert_idle(b.transitions.get_dict().get('orbital_reference_uuid'))
    b.cube_resources = orm.Dict(dict=helper_resources(resources,default_seconds=3600))
    b.parameters = orm.Dict(dict=cube_parameters(parameters, max_orbitals=None))
    b.code,b.cubehandler_code = orm.load_code(code_uuid),orm.load_code(cubehandler_uuid)
    if blend:
        b.blend = orm.Dict(dict=blend)
    b.metadata.label = 'Dyson spectral intensity blend' if blend else 'Dyson orbital cubes'
    return str(submit(b).uuid)


def cube_runs(transitions_uuid):
    result = []
    for uuid in backend.previous(transitions_uuid,'transitions',backend.CUBES_PROCESS):
        node = orm.load_node(uuid)
        result.append((f'{node.ctime:%Y-%m-%d %H:%M} · {node.process_state.value} · {str(uuid)[:8]}',str(uuid)))
    return result


def map_cube_inventory(transitions_uuid):
    """Find one saved/running complete amplitude set, returning only plain values.

    This inspects provenance and retention metadata. Physical file access is
    checked by map review, which can also reuse durable numerical maps.
    """
    table = orm.load_node(transitions_uuid).get_dict()
    required = {row['id'] for row in table['transitions']}
    indices = set(range(len(table['transitions'])))
    result = dict(cube_uuid=None, running_uuid=None, available_count=0)
    for _, uuid in cube_runs(transitions_uuid):
        node = orm.load_node(uuid)
        if node.is_finished_ok:
            manifest = node.outputs.manifest.get_dict()
            if manifest['retention'] == 'delete':
                continue
            available = {row['transition_id'] for row in manifest['cubes'] if row['kind'] == 'dyson'}
            result['available_count'] = max(result['available_count'], len(required & available))
            if required <= available and result['cube_uuid'] is None:
                result['cube_uuid'] = str(uuid)
        elif not node.is_terminated:
            parameters = node.inputs.parameters.get_dict()
            selected = {pair[1] for pair in parameters['orbitals'] if pair[0] == 0}
            if (indices <= selected and parameters['retention'] != 'delete' and
                    result['running_uuid'] is None):
                result['running_uuid'] = str(uuid)
    return result
