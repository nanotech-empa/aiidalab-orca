"""Operation-local ORM access for QRO/UNO inspection and cube requests."""
from pathlib import PurePosixPath

from aiida import orm
from aiida.engine import submit

from aiida_empa_orca import orbital_inspection as backend
from aiida_empa_orca.artifacts import resolve_electronic, native_retention
from aiida_empa_orca.orbitals import cube_parameters, validate_cube_outputs
from aiida_empa_orca.rendering import helper_resources
from .property_services import helper_code, tool_codes


def common_node(uuid):
    node = orm.load_node(uuid)
    if node.process_type not in ('aiida.workflows:empa_orca.common_orbitals', 'aiida.workflows:empa_orca.casscf') or not node.is_finished_ok:
        raise ValueError('Select a completed common-orbital preparation')
    return node


def codes(common_uuid):
    node = common_node(common_uuid)
    result = tool_codes(node.inputs.code.computer.uuid)
    # This utility must be registered on the same computer, just like orca_plot.
    result['export'] = []
    for uuid in orm.QueryBuilder().append(orm.InstalledCode,project=['uuid']).all(flat=True):
        code = orm.load_code(uuid)
        if code.computer.uuid == node.inputs.code.computer.uuid and (
                PurePosixPath(code.filepath_executable).name == 'orca_2json' or
                code.default_calc_job_plugin == 'empa_orca.orbital_catalog'):
            result['export'].append((f'{code.label}@{code.computer.label}',str(uuid)))
    return result


def catalog(common_uuid):
    node = common_node(common_uuid)
    for uuid in backend.runs(node.outputs.orbital_reference.uuid):
        run = orm.load_node(uuid)
        if run.is_finished_ok:
            return {'uuid':str(run.outputs.catalog.uuid),'data':run.outputs.catalog.get_dict(),
                    'reference_uuid':str(node.outputs.orbital_reference.uuid),'workflow_uuid':str(uuid)}
    return None


def catalog_builder(common_uuid, export_uuid, force=False, *, resources=None):
    node = common_node(common_uuid)
    if not export_uuid:
        raise ValueError('Configure and select the ORCA export code on this computer in Code setup')
    b = backend.OrbitalCatalogWorkChain.get_builder()
    b.orbital_reference, b.source_remote = node.outputs.orbital_reference,node.outputs.remote_folder
    b.storage_policy, b.storage_code = node.inputs.storage_policy,orm.load_code(helper_code(node.inputs.code.computer.uuid))
    b.retention_policy = orm.Dict(dict=native_retention(node.outputs.remote_folder))
    b.export_code = orm.load_code(export_uuid)
    b.force_recompute = orm.Bool(force)
    b.catalog_resources = orm.Dict(dict=helper_resources(resources))
    b.metadata.label = 'Inspect common spatial orbitals'
    return b


def submit_catalog(common_uuid, export_uuid, force=False, *, resources=None):
    return str(submit(catalog_builder(common_uuid, export_uuid, force, resources=resources)).uuid)


def review_catalog(common_uuid, export_uuid, force=False, *, resources=None):
    node = common_node(common_uuid)
    if not export_uuid:
        raise ValueError('Select the configured ORCA export code')
    code = orm.load_code(export_uuid)
    helper_uuid = helper_code(node.inputs.code.computer.uuid)
    if code.computer.uuid != node.inputs.code.computer.uuid:
        raise ValueError('Export orbitals on the reference computer')
    budget = helper_resources(resources)
    reuse = None
    if not force:
        for uuid in backend.runs(node.outputs.orbital_reference.uuid):
            old = orm.load_node(uuid)
            if (old.is_finished_ok and str(old.inputs.export_code.uuid) == str(export_uuid)
                    and str(old.inputs.storage_code.uuid) == helper_uuid):
                reuse = str(uuid)
                break
    sets, warnings = [], []
    if reuse:
        sets = list(orm.load_node(reuse).outputs.catalog.get_dict()['sets'])
    else:
        for kind, name in backend.variants(node.outputs.orbital_reference.get_dict()).items():
            try:
                resolve_electronic(node.outputs.remote_folder, names=[name])
                sets.append(kind)
            except (OSError, ValueError, KeyError) as exc:
                warnings.append(kind + ': ' + str(exc))
        if not sets:
            raise ValueError('No orbital files are available; prepare a new reference')
    return {'common_uuid': str(common_uuid), 'export_uuid': str(export_uuid), 'helper_uuid': helper_uuid,
            'reference_uuid': str(node.outputs.orbital_reference.uuid), 'resources': budget,
            'code_label': code.full_label, 'force': bool(force), 'sets': sets, 'warnings': warnings,
            'action': 'reuse' if reuse else 'compute', 'reuse_uuid': reuse}


def submit_catalog_plan(plan):
    fresh = review_catalog(plan['common_uuid'], plan['export_uuid'], plan['force'], resources=plan['resources'])
    if fresh != plan:
        raise ValueError('The catalog source or code changed; review again')
    if plan['action'] == 'reuse':
        return plan['reuse_uuid']
    return submit_catalog(plan['common_uuid'], plan['export_uuid'], plan['force'], resources=plan['resources'])


def review_cubes(common_uuid, catalog_uuid, kind, parameters, selected_codes, *, resources=None):
    node, data = common_node(common_uuid),orm.load_node(catalog_uuid).get_dict()
    if data['orbital_reference_uuid'] != str(node.outputs.orbital_reference.uuid):
        raise ValueError('Inspect the selected common reference first')
    p = cube_parameters(parameters)
    budget = helper_resources(resources, default_seconds=3600)
    selected = data['sets'][kind]
    if p['spin_density'] or any(spin != 0 or index >= len(selected['levels']) for spin,index in p['orbitals']):
        raise ValueError('Select spatial orbitals from the displayed set')
    code_ids = {'storage_code':helper_code(node.inputs.code.computer.uuid),
                'plot_code':selected_codes['plot'],'cubehandler_code':selected_codes['cubehandler']}
    if any(not value for value in code_ids.values()):
        raise ValueError('Configure ORCA plot and cubehandler on this computer')
    if any(orm.load_code(value).computer.uuid != node.inputs.code.computer.uuid for value in code_ids.values()):
        raise ValueError('Use codes on the orbital-reference computer')
    reuse = None
    for uuid in backend.runs(node.outputs.orbital_reference.uuid,backend.CUBES_PROCESS):
        old = orm.load_node(uuid)
        if (old.is_finished_ok and backend.same_orbital_set(old.inputs.catalog.get_dict(),data,kind) and old.inputs.orbital_kind.value == kind and
                cube_parameters(old.inputs.parameters.get_dict()) == p and
                all(str(old.inputs[key].uuid) == value for key,value in code_ids.items())):
            try:
                validate_cube_outputs(old)
                reuse = str(uuid)
                break
            except (OSError,ValueError,KeyError):
                pass
    if reuse is None:
        location = resolve_electronic(node.outputs.remote_folder,names=[selected['filename']])
        item = next(row for row in location['files'] if row['name'] == selected['filename'])
        if item['size_bytes'] != selected['size_bytes'] or (item.get('sha256') and item['sha256'] != selected['sha256']):
            raise ValueError('Orbital files changed; read their information again')
    return {'common_uuid':common_uuid,'catalog_uuid':catalog_uuid,'kind':kind,'parameters':p,
            'codes':code_ids,'action':'reuse' if reuse else 'compute','reuse_uuid':reuse, 'resources': budget}


def cubes_builder(plan):
    node = common_node(plan['common_uuid'])
    b = backend.CommonOrbitalCubesWorkChain.get_builder()
    b.orbital_reference, b.source_remote = node.outputs.orbital_reference,node.outputs.remote_folder
    b.catalog, b.orbital_kind = orm.load_node(plan['catalog_uuid']),orm.Str(plan['kind'])
    b.parameters = orm.Dict(dict=plan['parameters'])
    b.preview_resources = orm.Dict(dict=helper_resources(plan.get('resources'), default_seconds=3600))
    b.storage_policy = node.inputs.storage_policy
    b.orbital_retention_policy = orm.Dict(dict=native_retention(node.outputs.remote_folder))
    for key,value in plan['codes'].items():
        b[key] = orm.load_code(value)
    b.metadata.label = f'{plan["kind"]} orbital cubes'
    return b


def submit_cubes(plan):
    return str(submit(cubes_builder(plan)).uuid)


def cube_runs(common_uuid, kind):
    node = common_node(common_uuid)
    result = []
    for uuid in backend.runs(node.outputs.orbital_reference.uuid,backend.CUBES_PROCESS):
        run = orm.load_node(uuid)
        if run.inputs.orbital_kind.value == kind:
            result.append((f'{run.ctime:%Y-%m-%d %H:%M} · {run.process_state.value} · {str(uuid)[:8]}',str(uuid)))
    return result
