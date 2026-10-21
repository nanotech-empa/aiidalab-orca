"""Import review and result data; retain UUIDs, never ORM instances."""
import io

from aiida import orm
from aiida.engine import submit
from ase.io import write

from aiida_empa_orca.fixed_orbitals import FixedOrbitalsImportWorkChain
from aiida_empa_orca.fixed_orbitals_data import PROCESS, checked_manifest
from aiida_empa_orca.reference import reference_settings


def prepare_import(structure_uuid, source_remote_uuid, manifest, settings, code_uuid, export_uuid, helper_uuid):
    structure, remote = orm.load_node(structure_uuid), orm.load_node(source_remote_uuid)
    if not isinstance(structure, orm.StructureData) or not isinstance(remote, orm.RemoteData):
        raise ValueError('Select an explicit structure and external remote folder')
    if any(orm.load_code(u).computer.uuid != remote.computer.uuid for u in (code_uuid,export_uuid,helper_uuid)):
        raise ValueError('Import and future ORCA calculations must use the external folder computer')
    return dict(structure_uuid=str(structure.uuid), source_remote_uuid=str(remote.uuid),
                manifest=checked_manifest(manifest), settings=reference_settings(settings),
                code_uuid=str(code_uuid), export_uuid=str(export_uuid), helper_uuid=str(helper_uuid))


def submit_import(plan, label):
    plan = prepare_import(plan['structure_uuid'], plan['source_remote_uuid'], plan['manifest'], plan['settings'],
                          plan['code_uuid'], plan['export_uuid'], plan['helper_uuid'])
    b = FixedOrbitalsImportWorkChain.get_builder()
    b.structure, b.source_remote = orm.load_node(plan['structure_uuid']), orm.load_node(plan['source_remote_uuid'])
    b.source_manifest, b.settings = orm.Dict(dict=plan['manifest']), orm.Dict(dict=plan['settings'])
    b.code, b.export_code, b.storage_code = (orm.load_code(plan[k]) for k in ('code_uuid','export_uuid','helper_uuid'))
    b.storage_policy = orm.Dict(dict={'mode':'remote','threshold_mb':0,'stash_directory':''})
    b.metadata.label = label
    b.metadata.description = 'Explicit import of external frozen-CASCI orbitals; original files are unchanged.'
    node = submit(b)
    node.base.extras.set('aiidalab_orca', {'version':'0.1.0','view':'imported_fixed_orbitals'})
    return str(node.uuid)


def result(uuid):
    n = orm.load_node(uuid)
    if n.process_type != PROCESS:
        raise ValueError('Select an external fixed-orbital import workflow')
    data = dict(uuid=str(n.uuid), label=n.label, state=n.process_state.value, finished=n.is_terminated,
        successful=n.is_finished_ok, scientific_success=n.is_finished_ok, exit_message=n.exit_message,
        settings=n.inputs.settings.get_dict(), optimized=False, single_point=False, imported_reference=True,
        source_description=n.inputs.source_manifest.get_dict()['description'],
        reports=[r.message for r in orm.Log.collection.get_logs_for(n)], warnings=[], calculations=[])
    if n.is_finished_ok:
        atoms = n.outputs.structure.get_ase()
        xyz = io.StringIO(); write(xyz, atoms, format='xyz')
        ref = n.outputs.orbital_reference.get_dict()
        data.update(structure_uuid=str(n.outputs.structure.uuid), symbols=atoms.get_chemical_symbols(),
            positions=atoms.positions.tolist(), xyz=xyz.getvalue(), active_space=ref['active_space'],
            warnings=['Imported fixed spatial orbitals from an external CASCI calculation. '
                      'New CASCI/Dyson results are recorded separately; no new DFT reference was computed.'])
    return data
