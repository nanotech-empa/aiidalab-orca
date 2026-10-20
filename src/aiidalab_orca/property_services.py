"""Short-lived AiiDA access for electronic storage and orbital properties."""

from pathlib import Path, PurePosixPath

from aiida import orm
from aiida.engine import submit

from aiida_empa_orca.artifacts import resolve_electronic, storage_policy
from aiida_empa_orca.levels import orbital_levels
from aiida_empa_orca.orbitals import PROCESS_TYPE, OrbitalsWorkChain, cube_parameters, validate_cube_outputs
from aiida_empa_orca.reference import PROCESS_TYPE as SCF_PROCESS, GEOMETRY_PROCESS


def default_stash_directory():
    return str(Path.home()/'orca-stash')


def tool_codes(computer_uuid=None):
    result = {'python':[], 'plot':[], 'cubehandler':[]}
    for (uuid,) in orm.QueryBuilder().append(orm.InstalledCode,project=['uuid']).all():
        code=orm.load_code(uuid)
        if computer_uuid and code.computer.uuid!=computer_uuid:
            continue
        name=Path(code.filepath_executable).name
        role=code.base.extras.get('aiidalab_orca_role', None)
        kind=(role if role in ('plot','cubehandler','python') else
              'python' if code.default_calc_job_plugin=='empa_orca.electronic_storage' or name=='orca-tools' else
              'cubehandler' if code.default_calc_job_plugin=='nanotech_empa.cubehandler' or name=='cubehandler' else
              'plot' if name=='orca_plot' else None)
        if kind:
            result[kind].append((f'{code.label}@{code.computer.label}',str(uuid)))
    return result


def helper_code(computer_uuid):
    """Resolve the configured application runtime, never a generic Python code."""
    choices = tool_codes(computer_uuid)['python']
    if len(choices) != 1:
        raise ValueError('Configure exactly one ORCA tools code on this computer in Code setup.')
    return choices[0][1]


def wavefunction_status(source_uuid):
    from aiida_empa_orca.reference import ArtifactUnavailable
    node = source_node(source_uuid)
    remote = source_remote(node)
    policy = None
    seen = set()
    while str(node.uuid) not in seen:
        seen.add(str(node.uuid))
        if 'storage_policy' in node.inputs:
            policy = node.inputs.storage_policy.get_dict()
            break
        if 'reuse_source' not in node.inputs:
            break
        node = source_node(node.inputs.reuse_source.value)
    result = {'policy': policy or {'threshold_mb':100, 'stash_directory':default_stash_directory()},
              'inherited': policy is not None}
    try:
        location = resolve_electronic(remote)
        result.update(state=location['kind'], path=location.get('path', ''),
                      size_bytes=sum(f['size_bytes'] for f in location['files']))
        if not policy and location.get('storage_uuid'):
            result.update(policy=orm.load_node(location['storage_uuid']).inputs.policy.get_dict(), inherited=True)
    except ArtifactUnavailable as exc:
        result.update(state='unavailable', message=str(exc))
    except (ValueError, FileNotFoundError) as exc:
        result.update(state='missing', message=str(exc))
    return result


def source_node(uuid):
    node=orm.load_node(uuid)
    if (node.process_type not in (SCF_PROCESS,GEOMETRY_PROCESS) or not (node.is_finished_ok or (node.is_finished and node.exit_status == 405)) or
            'retrieved' not in node.outputs or 'output_parameters' not in node.outputs):
        raise ValueError('Select a successful ORCA geometry or SCF calculation')
    return node


def source_remote(node):
    producer=node.outputs.retrieved.creator
    if producer is None or 'remote_folder' not in producer.outputs:
        raise ValueError('No electronic-file provenance was recorded')
    return producer.outputs.remote_folder


def source_tools(uuid):
    node=source_node(uuid)
    return tool_codes(source_remote(node).computer.uuid)


def property_runs(source_uuid):
    node=source_node(source_uuid)
    query=orm.QueryBuilder().append(orm.FolderData,filters={'uuid':node.outputs.retrieved.uuid},tag='source').append(
        orm.WorkChainNode,with_incoming='source',edge_filters={'label':'source_retrieved'},tag='run',
        filters={'process_type':PROCESS_TYPE},project=['uuid','label','attributes.process_state','ctime'])
    return [{'uuid':str(u),'label':label,'state':state,'date':date.isoformat()} for u,label,state,date in
            query.order_by({'run':{'ctime':'desc'}}).limit(50).all()]


def prepare_property(source_uuid, parameters, policy, codes):
    node=source_node(source_uuid)
    p=cube_parameters(parameters)
    policy=storage_policy(policy)
    remote=source_remote(node)
    codes = dict(codes)
    if not codes.get('python'):
        codes['python'] = helper_code(remote.computer.uuid)
    for key in ('python','plot','cubehandler'):
        if not codes.get(key):
            raise ValueError(f'Select the {key} code')
        if orm.load_code(codes[key]).computer.uuid!=remote.computer.uuid:
            raise ValueError('All property codes must be on the electronic calculation computer')
    levels=orbital_levels(node.outputs.retrieved.base.repository.get_object_content('aiida.out'),
                          node.outputs.output_parameters.get_dict().get('nmo'))
    available={(v['spin'],v['index']) for c in levels['channels'] for v in c}
    if any(tuple(pair) not in available for pair in p['orbitals']):
        raise ValueError('Select orbitals present in the stored level table')
    if p['spin_density'] and not levels['spin_polarized']:
        raise ValueError('The restricted reference does not provide a spin-density channel')
    plan={'source_uuid':source_uuid,'parameters':p,'storage_policy':policy,'codes':dict(codes),
          'action':'compute','reuse_uuid':None,'regenerate_reference':False,'warnings':[]}
    for row in property_runs(source_uuid):
        previous=orm.load_node(row['uuid'])
        if (previous.is_finished_ok and previous.inputs.parameters.get_dict()==p and
                all(str(previous.inputs[role+'_code'].uuid)==codes[role] for role in ('python','plot','cubehandler'))):
            try:
                validate_cube_outputs(previous)
                plan.update(action='reuse',reuse_uuid=row['uuid'])
                return plan
            except (ValueError,OSError,KeyError) as exc:
                plan['warnings'].append(str(exc))
    try:
        location=resolve_electronic(remote)
        plan['electronic_location']=location['kind']
        total=sum(f['size_bytes'] for f in location['files'])
        plan['wavefunction_bytes']=total
        plan['storage_action']=('leave in the calculation directory' if policy.get('mode')=='remote' else
                                'retrieve' if total<=policy['threshold_mb']*1024**2 else 'stash') if location['kind']=='remote' else 'already preserved'
    except (FileNotFoundError,ValueError) as exc:
        plan['regenerate_reference']=True
        plan['warnings'].append(str(exc))
        plan['storage_action']='preserve the regenerated reference'
    return plan


def submit_property(plan):
    from aiida.engine.daemon.client import get_daemon_client
    if not get_daemon_client().is_daemon_running:
        raise ValueError('Start the AiiDA daemon before submitting')
    node=source_node(plan['source_uuid'])
    builder=OrbitalsWorkChain.get_builder()
    builder.source_retrieved=node.outputs.retrieved
    builder.source_remote=source_remote(node)
    builder.structure=node.outputs.structure
    builder.reference_settings=node.inputs.settings
    builder.orca_code=node.inputs.code
    builder.parameters=orm.Dict(dict=plan['parameters'])
    builder.storage_policy=orm.Dict(dict=plan['storage_policy'])
    for role in ('python','plot','cubehandler'):
        builder[role+'_code']=orm.load_code(plan['codes'][role])
    builder.regenerate_reference=orm.Bool(plan['regenerate_reference'])
    if plan['reuse_uuid']:
        builder.reuse_uuid=orm.Str(plan['reuse_uuid'])
    builder.metadata.label=f'{node.outputs.structure.get_formula()} orbitals and spin density'
    run=submit(builder)
    return str(run.uuid)


def property_result(uuid):
    node=orm.load_node(uuid)
    from aiida_empa_orca.orbital_inspection import CUBES_PROCESS
    from aiida_empa_orca.dyson import CUBES_PROCESS as DYSON_CUBES_PROCESS
    from aiida_empa_orca.kondo import CUBES_PROCESS as KONDO_CUBES_PROCESS
    if node.process_type not in (PROCESS_TYPE,CUBES_PROCESS,DYSON_CUBES_PROCESS,KONDO_CUBES_PROCESS):
        raise ValueError('Select an orbital property workflow')
    data={'uuid':str(uuid),'state':node.process_state.value,'finished':node.is_terminated,
          'successful':node.is_finished_ok,'message':node.exit_message or '',
          'reports':[entry.message for entry in orm.Log.collection.get_logs_for(node)]}
    if node.is_finished_ok:
        data['manifest']=node.outputs.manifest.get_dict()
        mode=data['manifest']['retention']
        if mode=='stash':
            data['full_cube_path']=str(PurePosixPath(node.outputs.remote_stash.target_basepath)/'full_cubes')
        elif mode=='leave':
            data['full_cube_path']=str(PurePosixPath(node.outputs.remote_folder.get_remote_path())/'full_cubes')
    return data


def preview_content(uuid, filename):
    node=orm.load_node(uuid)
    if filename not in [c['filename'] for c in node.outputs.manifest.get_dict()['cubes']]:
        raise ValueError('Select one of the recorded preview cubes')
    return node.outputs.retrieved.base.repository.get_object_content('previews/'+filename)
