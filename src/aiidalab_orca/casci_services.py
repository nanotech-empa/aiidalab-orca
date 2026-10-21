"""Operation-local ORM access for common orbitals and CASCI state energies."""

from aiida import orm
from aiida.engine import submit

from aiida_empa_orca import casci, common_orbitals
from aiida_empa_orca.artifacts import resolve_electronic, storage_policy
from aiida_empa_orca.reference import reference_settings
from .property_services import helper_code, source_node, source_remote, wavefunction_status
from aiida_empa_orca.fixed_orbitals_data import PROCESS as IMPORT_PROCESS


def reference_runs(source_uuid):
    imported = orm.load_node(source_uuid)
    if imported.process_type == IMPORT_PROCESS:
        if not imported.is_finished_ok:
            return []
        data = imported.outputs.orbital_reference.get_dict()
        return [{'uuid':str(imported.uuid), 'reference_uuid':str(imported.outputs.orbital_reference.uuid),
                 'kind':'Imported fixed orbitals', 'n_orbitals':data['n_orbitals'], 'charge':data['charge']}]
    source = source_node(source_uuid)
    choices, seen = [], set()
    for uuid in common_orbitals.matching_references(source.outputs.retrieved.uuid, source.inputs.code.uuid):
        node = orm.load_node(uuid)
        key = str(node.outputs.orbital_reference.uuid)
        if key in seen:
            continue
        seen.add(key)
        data = node.outputs.orbital_reference.get_dict()
        choices.append({'uuid':uuid, 'reference_uuid':key, 'kind':data['kind'],
                        'n_orbitals':data['n_orbitals'], 'charge':data['charge']})
    return choices


def prepare_common(source_uuid, force=False):
    imported = orm.load_node(source_uuid)
    if imported.process_type == IMPORT_PROCESS:
        if force:
            raise ValueError('Re-import the original fixed orbitals to create a new reference; this source has no native SCF to regenerate')
        common_orbitals.reference_location(imported)
        return {'source_uuid':source_uuid, 'action':'reuse', 'reference_uuid':source_uuid, 'unavailable':[]}
    source = source_node(source_uuid)
    unavailable = []
    for row in ([] if force else reference_runs(source_uuid)):
        try:
            common_orbitals.reference_location(orm.load_node(row['uuid']))
            return {'source_uuid':source_uuid, 'action':'reuse', 'reference_uuid':row['uuid'], 'unavailable':unavailable}
        except (FileNotFoundError, KeyError, ValueError) as exc:
            unavailable.append(str(exc))
    resolve_electronic(source_remote(source))
    s = reference_settings(source.inputs.settings.get_dict())
    return {'source_uuid':source_uuid, 'action':'prepare', 'reference_uuid':None,
            'kind':'QRO' if common_orbitals.orbital_filename(s).endswith('qro') else 'restricted',
            'force_recompute':bool(force), 'unavailable':unavailable}


def common_builder(source_uuid, force=False):
    source = source_node(source_uuid)
    b = common_orbitals.CommonOrbitalsWorkChain.get_builder()
    b.structure, b.settings, b.code = source.outputs.structure, source.inputs.settings, source.inputs.code
    b.source_retrieved, b.source_remote = source.outputs.retrieved, source_remote(source)
    b.storage_code = orm.load_code(helper_code(source.inputs.code.computer.uuid))
    b.storage_policy = orm.Dict(dict=wavefunction_status(source_uuid)['policy'])
    b.force_recompute = orm.Bool(force)
    b.metadata.label = source.outputs.structure.get_formula()+' common spatial orbitals'
    return b


def submit_common(plan):
    if plan['action'] == 'reuse':
        common_orbitals.reference_location(orm.load_node(plan['reference_uuid']))
        return plan['reference_uuid']
    return str(submit(common_builder(plan['source_uuid'],plan.get('force_recompute',False))).uuid)


def reference_data(uuid):
    node = orm.load_node(uuid)
    if node.process_type not in (common_orbitals.PROCESS_TYPE, IMPORT_PROCESS) or not node.is_finished_ok:
        raise ValueError('Select completed common-orbital preparation')
    return node.outputs.orbital_reference.get_dict()


def prepare_casci(reference_uuid, electrons, norb, values, force=False):
    node = orm.load_node(reference_uuid)
    ref = reference_data(reference_uuid)
    if type(norb) is not int or norb < 1:
        raise ValueError('Choose a positive number of active orbitals')
    start = (ref['n_electrons']-electrons)//2
    space = casci.active_space({'electrons':electrons, 'orbitals':list(range(start,start+norb))}, ref)
    s = casci.casci_settings(values, ref, space)
    expected = casci.signature(node.outputs.orbital_reference.uuid, space, s, node.inputs.code.uuid)
    reuse_uuid = None
    if not force:
        for uuid in casci.existing_calculations(node.outputs.orbital_reference.uuid):
            old = orm.load_node(uuid)
            if not (old.is_finished_ok or (old.is_finished and old.exit_status == 402)):
                continue
            old_settings = casci.casci_settings(old.inputs.settings.get_dict(), ref, old.inputs.active_space.get_dict())
            if casci.signature(node.outputs.orbital_reference.uuid, old.inputs.active_space.get_dict(), old_settings, old.inputs.code.uuid) == expected:
                parsed = casci.parse_states(old.outputs.retrieved.base.repository.get_object_content('aiida.out'), ref, space, s)
                if (parsed['states'] == old.outputs.state_energies.get_dict()['states'] and
                        parsed['model'] == old.outputs.state_energies.get_dict().get('model')):
                    reuse_uuid = str(uuid)
                    break
    if reuse_uuid is None:
        common_orbitals.reference_location(node)
    return {'reference_uuid':reference_uuid, 'active_space':space, 'settings':s,
            'force_recompute':force, 'action':'reuse' if reuse_uuid else 'compute', 'reuse_uuid':reuse_uuid,
            'input':casci.casci_input(ref, space, s)}


def casci_builder(plan):
    node = orm.load_node(plan['reference_uuid'])
    b = casci.CasciWorkChain.get_builder()
    b.orbital_reference, b.source_remote = node.outputs.orbital_reference, node.outputs.remote_folder
    b.active_space, b.settings = orm.Dict(dict=plan['active_space']), orm.Dict(dict=plan['settings'])
    b.code, b.storage_code = node.inputs.code, node.inputs.storage_code
    b.storage_policy = orm.Dict(dict=storage_policy(node.inputs.storage_policy.get_dict()))
    b.force_recompute = orm.Bool(plan['force_recompute'])
    s = plan['settings']
    b.metadata.label = f'CASCI charge {s["charge"]:+d}, multiplicity {s["multiplicity"]}, {s["nroots"]} roots'
    return b


def submit_casci(plan):
    return str(submit(casci_builder(plan)).uuid)


def progress(uuid):
    node = orm.load_node(uuid)
    return {'uuid':str(uuid), 'finished':node.is_terminated, 'success':node.is_finished_ok,
            'state':node.process_state.value, 'process_type':node.process_type, 'message':node.exit_message or '',
            'reports':[entry.message for entry in orm.Log.collection.get_logs_for(node)]}


def results(reference_uuid, electrons, norb, auxiliary_basis=None):
    node = orm.load_node(reference_uuid)
    datasets, seen = [], set()
    for uuid in casci.existing_calculations(node.outputs.orbital_reference.uuid):
        run = orm.load_node(uuid)
        if 'state_energies' not in run.outputs:
            continue
        data_node = run.outputs.state_energies
        if str(data_node.uuid) in seen:
            continue
        seen.add(str(data_node.uuid))
        data = data_node.get_dict()
        if auxiliary_basis is not None and data.get('model',{}).get('auxiliary_basis') != auxiliary_basis:
            continue
        if data['active_space']['electrons'] != electrons or len(data['active_space']['orbitals']) != norb:
            continue
        # For repeated runs of the same sector prefer the newest; never mix
        # two numerical solutions or roots from separate runs of that sector.
        key = (data['states'][0]['charge'], data['states'][0]['multiplicity'])
        if key in seen:
            continue
        seen.add(key)
        datasets.append(dict(data, workflow_uuid=str(uuid)))
    return datasets


def runs(reference_uuid):
    node = orm.load_node(reference_uuid)
    result = []
    for uuid in casci.existing_calculations(node.outputs.orbital_reference.uuid):
        run = orm.load_node(uuid)
        result.append({'uuid':str(uuid), 'label':run.label, 'state':run.process_state.value,
                       'date':run.ctime.isoformat(), 'space':run.inputs.active_space.get_dict(),
                       'settings':run.inputs.settings.get_dict()})
    return result
