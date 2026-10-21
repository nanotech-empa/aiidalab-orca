"""Operation-local ORM access for QRO/UNO inspection and cube requests."""
from pathlib import PurePosixPath

from aiida import orm
from aiida.engine import submit

from aiida_empa_orca import orbital_inspection as backend
from aiida_empa_orca.artifacts import resolve_electronic
from aiida_empa_orca.orbitals import cube_parameters, validate_cube_outputs
from .property_services import helper_code, tool_codes
from aiida_empa_orca.fixed_orbitals_data import PROCESS as IMPORT_PROCESS


def common_node(uuid):
    node = orm.load_node(uuid)
    if node.process_type not in ('aiida.workflows:empa_orca.common_orbitals', IMPORT_PROCESS) or not node.is_finished_ok:
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


def submit_catalog(common_uuid, export_uuid, force=False):
    node = common_node(common_uuid)
    if not export_uuid:
        raise ValueError('Configure and select the ORCA export code on this computer in Code setup')
    b = backend.OrbitalCatalogWorkChain.get_builder()
    b.orbital_reference, b.source_remote = node.outputs.orbital_reference,node.outputs.remote_folder
    b.storage_policy, b.storage_code = node.inputs.storage_policy,orm.load_code(helper_code(node.inputs.code.computer.uuid))
    b.export_code = orm.load_code(export_uuid)
    b.force_recompute = orm.Bool(force)
    b.metadata.label = 'Inspect common spatial orbitals'
    return str(submit(b).uuid)


def review_cubes(common_uuid, catalog_uuid, kind, parameters, selected_codes):
    node, data = common_node(common_uuid),orm.load_node(catalog_uuid).get_dict()
    if data['orbital_reference_uuid'] != str(node.outputs.orbital_reference.uuid):
        raise ValueError('Inspect the selected common reference first')
    p = cube_parameters(parameters)
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
            'codes':code_ids,'action':'reuse' if reuse else 'compute','reuse_uuid':reuse}


def submit_cubes(plan):
    node = common_node(plan['common_uuid'])
    b = backend.CommonOrbitalCubesWorkChain.get_builder()
    b.orbital_reference, b.source_remote = node.outputs.orbital_reference,node.outputs.remote_folder
    b.catalog, b.orbital_kind = orm.load_node(plan['catalog_uuid']),orm.Str(plan['kind'])
    b.parameters = orm.Dict(dict=plan['parameters'])
    b.storage_policy = node.inputs.storage_policy
    for key,value in plan['codes'].items():
        b[key] = orm.load_code(value)
    b.metadata.label = f'{plan["kind"]} orbital cubes'
    return str(submit(b).uuid)


def cube_runs(common_uuid, kind):
    node = common_node(common_uuid)
    result = []
    for uuid in backend.runs(node.outputs.orbital_reference.uuid,backend.CUBES_PROCESS):
        run = orm.load_node(uuid)
        if run.inputs.orbital_kind.value == kind:
            result.append((f'{run.ctime:%Y-%m-%d %H:%M} · {run.process_state.value} · {str(uuid)[:8]}',str(uuid)))
    return result
