"""Reviewed correlation plans; ORM instances stay confined to each operation."""
from aiida import engine, orm
from aiida_empa_orca import correlation
from aiida_empa_orca.artifacts import resolve_electronic
from aiida_empa_orca.common_orbitals import attach_orbital, options
from aiida_empa_orca.casci import signature
from aiida_empa_orca.rendering import calcjob_options

from .property_services import source_node, helper_code
from aiida_empa_orca.native_logs import DIRECTORY, output_policy
from aiida_empa_orca.artifacts import stash_options


def casscf_sources(entry_uuid):
    from .casci_services import reference_runs
    rows = []
    for record in reference_runs(entry_uuid):
        if record['kind'] != 'CASSCF':
            continue
        n = orm.load_node(record['uuid'])
        objective = n.inputs.settings.get_dict()
        title = 'State average' if objective['mode'] == 'state_average' else 'One selected state'
        rows.append((f'{title} · {n.ctime:%Y-%m-%d %H:%M} · {str(n.uuid)[:8]}', str(n.uuid)))
    return rows


def context(source_uuid, method):
    n = orm.load_node(source_uuid)
    if method == 'RI-MP2':
        n = source_node(source_uuid)
        return n.inputs.settings.get_dict(), None
    if (method not in correlation.CAS_METHODS or n.process_type != 'aiida.workflows:empa_orca.casscf'
            or not n.is_finished_ok):
        raise ValueError('Select a verified CASSCF calculation before its correlation correction')
    ref = n.outputs.orbital_reference.get_dict()
    if ref['preparation'] != 'casscf_verified_v1' or ref['readback_max_error_hartree'] > 1e-7:
        raise ValueError('The CASSCF source did not pass saved-orbital verification')
    return ref['settings'], ref


def defaults(source_uuid, method):
    electronic, ref = context(source_uuid, method)
    return correlation.settings({'method': method}, electronic, ref['casscf_settings'] if ref else None)


def history(source_uuid, method):
    n = orm.load_node(source_uuid)
    key = 'source_retrieved' if method == 'RI-MP2' else 'orbital_reference'
    source = n.outputs.retrieved if method == 'RI-MP2' else n.outputs.orbital_reference
    ids = orm.QueryBuilder().append(orm.Data, filters={'uuid': str(source.uuid)}, tag='source').append(
        orm.CalcJobNode, with_incoming='source', edge_filters={'label': key}, tag='run', project='uuid',
        filters={'process_type': correlation.PROCESS_TYPE}).order_by({'run': {'ctime': 'desc'}}).all(flat=True)
    rows = []
    for uid in ids:
        old = orm.load_node(uid)
        settings = old.inputs.settings.get_dict()
        if settings['method'] == method:
            detail = 'chemical core frozen' if settings['frozen_core'] else 'all electrons correlated'
            if method == 'CASPT2':
                detail += (f' · shifts (Ha): real {settings["real_shift_hartree"]:g}, '
                    f'imaginary {settings["imaginary_shift_hartree"]:g}, IPEA {settings["ipea_shift_hartree"]:g}')
            elif method == 'DLPNO-NEVPT2':
                detail += ' · ' + settings['pno_preset']
            rows.append((f'{old.ctime:%Y-%m-%d %H:%M} · {method} · {detail} · {old.process_state.value}', str(uid)))
    return rows


def review(source_uuid, method, values, force=False, *, native_output_policy=None):
    retention = output_policy(native_output_policy)
    electronic, reference = context(source_uuid, method)
    effective = correlation.settings(values | {'method': method}, electronic,
                                     reference['casscf_settings'] if reference else None)
    n = orm.load_node(source_uuid)
    source_key = n.outputs.retrieved.uuid if reference is None else n.outputs.orbital_reference.uuid
    key = signature(source_key, {}, effective, n.inputs.code.uuid)
    reuse = None
    for _, uid in ([] if force else history(source_uuid, method)):
        old = orm.load_node(uid)
        old_key = signature(source_key, {}, old.inputs.settings.get_dict(), old.inputs.code.uuid)
        if old_key == key and (not old.is_terminated or old.is_finished_ok):
            reuse = str(uid)
            break
    if reference and reuse is None:
        resolve_electronic(n.outputs.remote_folder, names=['aiida.gbw'])
    return {'source_uuid': str(source_uuid), 'method': method, 'settings': effective,
            'native_output_policy':retention,
            'helper_uuid':helper_code(n.inputs.code.computer.uuid) if reuse is None else None,
            'reference_summary': ({'active_space': reference['optimized_active_space'],
                'states': n.outputs.state_energies.get_dict()['states']} if reference else
                {'charge': electronic['charge'], 'multiplicity': electronic['multiplicity']}),
            'signature': key, 'force': bool(force), 'code_uuid': str(n.inputs.code.uuid),
            'execution': n.inputs.code.full_label, 'reuse_uuid': reuse,
            'action': 'reuse' if reuse else 'compute',
            'input': correlation.correlation_input(electronic, effective, reference)}


def builder(plan):
    checked = review(plan['source_uuid'], plan['method'], plan['settings'], plan['force'],
                     native_output_policy=plan.get('native_output_policy'))
    if any(checked[key] != plan[key] for key in ('signature', 'input', 'code_uuid')):
        raise ValueError('The correlation request changed; review it again')
    electronic, reference = context(plan['source_uuid'], plan['method'])
    n = orm.load_node(plan['source_uuid'])
    b = correlation.CorrelationCalculation.get_builder()
    b.code = n.inputs.code
    b.compact_code = orm.load_code(checked['helper_uuid'])
    b.native_output_policy = orm.Dict(dict=checked['native_output_policy'])
    b.electronic_settings, b.settings = orm.Dict(dict=electronic), orm.Dict(dict=plan['settings'])
    b.structure = orm.load_node(reference['structure_uuid']) if reference else n.outputs.structure
    if reference:
        b.orbital_reference, b.reference_states, b.source_remote = (
            n.outputs.orbital_reference, n.outputs.state_energies, n.outputs.remote_folder)
        attach_orbital(b, resolve_electronic(n.outputs.remote_folder, names=['aiida.gbw']), 'aiida.gbw')
        remote = n.outputs.remote_folder
    else:
        b.source_retrieved = n.outputs.retrieved
        remote = n.outputs.retrieved.creator.outputs.remote_folder
    opts = calcjob_options(remote, seconds=plan['settings']['wallclock_seconds'])
    opts.update(options(plan['settings']))
    b.metadata.options = opts
    if checked['native_output_policy']['mode'] == 'stash':
        b.metadata.options.stash = stash_options(checked['native_output_policy']['stash_directory'], DIRECTORY)
    b.metadata.disable_cache = True
    b.metadata.label = b.structure.get_formula() + ' · ' + plan['method'] + ' · correlation energies'
    return b


def submit(plan):
    checked = review(plan['source_uuid'], plan['method'], plan['settings'], plan['force'],
                     native_output_policy=plan.get('native_output_policy'))
    if checked['signature'] != plan['signature']:
        raise ValueError('The correlation request changed; review it again')
    return checked['reuse_uuid'] or str(engine.submit(builder(plan)).uuid)


def result(uid):
    n = orm.load_node(uid)
    if not n.is_finished_ok or n.process_type != correlation.PROCESS_TYPE:
        raise ValueError('Select a successfully validated correlation calculation')
    return n.outputs.correlation_energies.get_dict()
