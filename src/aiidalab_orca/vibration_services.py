"""Operation-local AiiDA access for the molecular spectroscopy section."""

from aiida import orm
from aiida.engine import submit

from aiida_empa_orca.input import render_input
from aiida_empa_orca.vibrations import (
    PROCESS_TYPE, OUTPUTS, VibrationsWorkChain, frequency_parameters,
    optimized_source, signature, validate_result, compatible, UNVERIFIED_GEOMETRY_WARNING,
)
from .property_services import source_node


def runs(source_uuid):
    source = source_node(source_uuid)
    rows = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': source.outputs.retrieved.uuid}, tag='source').append(
        orm.WorkChainNode, with_incoming='source', edge_filters={'label': 'source_retrieved'},
        filters={'process_type': PROCESS_TYPE}, project=['uuid', 'label', 'ctime', 'attributes.process_state'], tag='run')
    return [{'uuid': str(uuid), 'label': label, 'date': date.isoformat(), 'state': state}
            for uuid, label, date, state in rows.order_by({'run': {'ctime': 'desc'}}).all()]


def reference_context(source_uuid):
    """Find exact geometry/electronic-setting matches, independent of resources."""
    from aiida_empa_orca.reuse import PROCESS_TYPE as GEOMETRY_PROCESS
    from aiida_empa_orca.reference import reference_settings
    source = source_node(source_uuid)
    source_settings = reference_settings(source.inputs.settings.get_dict())
    expected = signature(source.outputs.structure, source_settings, source.inputs.code.uuid, False)
    rows = orm.QueryBuilder().append(orm.WorkChainNode, filters={
        'process_type': GEOMETRY_PROCESS, 'attributes.process_state': 'finished',
        'attributes.exit_status': 0}, project=['uuid'], tag='run').order_by({'run': {'ctime': 'desc'}})
    matches = []
    for (uuid,) in rows.iterall():
        node = orm.load_node(uuid)
        if not node.inputs.optimize.value or 'structure' not in node.outputs or 'retrieved' not in node.outputs:
            continue
        settings = node.inputs.settings.get_dict()
        comparison = dict(settings, nprocs=source_settings['nprocs'])
        if signature(node.outputs.structure, comparison, node.inputs.code.uuid, False) != expected:
            continue
        try:
            optimized_source(node.outputs.structure, settings, node.inputs.code, node.outputs.retrieved)
        except (ValueError, KeyError, OSError):
            continue
        matches.append({'uuid': str(uuid), 'label': node.label,
                        'date': node.ctime.strftime('%Y-%m-%d %H:%M UTC')})
    return {'source_uuid': str(source_uuid), 'optimizations': matches}


def prepare(source_uuid, *, raman=True, force_recompute=False, allow_unverified_geometry=False):
    source = source_node(source_uuid)
    structure, settings, code = source.outputs.structure, source.inputs.settings.get_dict(), source.inputs.code
    verified = optimized_source(structure, settings, code, source.outputs.retrieved,
                                allow_unverified_geometry=allow_unverified_geometry)
    plan = {'source_uuid': str(source_uuid), 'raman': bool(raman), 'reuse_uuid': None,
            'signature': signature(structure, settings, code.uuid, raman), 'warnings': [],
            'allow_unverified_geometry': bool(allow_unverified_geometry), 'geometry_verified': verified}
    if not verified:
        plan['warnings'].append(UNVERIFIED_GEOMETRY_WARNING)
    if settings.get('constraints'):
        plan['warnings'].append('The reference was optimized with constraints. Free-molecule frequencies may contain imaginary modes or describe a nonstationary geometry.')
    if not force_recompute:
        query = orm.QueryBuilder().append(orm.WorkChainNode, filters={'process_type': PROCESS_TYPE,
            'attributes.process_state': 'finished', 'attributes.exit_status': 0}, project=['uuid'], tag='run')
        for (uuid,) in query.order_by({'run': {'ctime': 'desc'}}).iterall():
            previous = orm.load_node(uuid)
            try:
                if not compatible(previous, structure, settings, code.uuid, raman):
                    continue
                validate_result(previous)
            except (ValueError, KeyError, OSError) as exc:
                plan['warnings'].append(f'Previous vibrational data unavailable; this step must be repeated: {exc}')
                continue
            plan['reuse_uuid'] = str(uuid)
            break
    params = frequency_parameters(settings, raman)
    from aiida.orm.implementation import clean_value
    from aiida_empa_orca.reference import reference_settings
    resolved = reference_settings(settings)
    plan['input_preview'] = render_input(clean_value(params), int(.75 * resolved['memory_mb'] / resolved['nprocs']), 'aiida.coords.xyz')
    return plan


def submit_plan(plan):
    from aiida.engine.daemon.client import get_daemon_client
    if not get_daemon_client().is_daemon_running:
        raise ValueError('Start the AiiDA daemon before submitting')
    source = source_node(plan['source_uuid'])
    if signature(source.outputs.structure, source.inputs.settings.get_dict(), source.inputs.code.uuid,
                 plan['raman']) != plan['signature']:
        raise ValueError('The reviewed vibrational reference changed')
    builder = VibrationsWorkChain.get_builder()
    builder.structure, builder.settings = source.outputs.structure, source.inputs.settings
    builder.source_retrieved, builder.code = source.outputs.retrieved, source.inputs.code
    builder.raman = orm.Bool(plan['raman'])
    builder.allow_unverified_geometry = orm.Bool(plan.get('allow_unverified_geometry', False))
    if plan['reuse_uuid']:
        previous = orm.load_node(plan['reuse_uuid'])
        validate_result(previous)
        builder.reuse_uuid = orm.Str(plan['reuse_uuid'])
        for name in OUTPUTS:
            builder.reuse[name] = previous.outputs[name]
    builder.metadata.label = source.outputs.structure.get_formula() + (' · IR and Raman' if plan['raman'] else ' · IR')
    node = submit(builder)
    node.base.extras.set('aiidalab_orca', {'version': '0.1.0', 'view': 'vibrations', 'source_uuid': str(source.uuid)})
    return str(node.uuid)


def result(uuid):
    node = orm.load_node(uuid)
    validate_result(node)
    atoms = node.inputs.structure.get_ase()
    return {'uuid': str(uuid), 'data_uuid': str(node.outputs.vibrational_data.uuid),
            'hessian_uuid': str(node.outputs.hessian.uuid), 'summary': node.outputs.summary.get_dict(),
            'symbols': atoms.get_chemical_symbols(), 'positions': atoms.positions.tolist(),
            'settings': node.inputs.settings.get_dict(),
            'arrays': {name: node.outputs.vibrational_data.get_array(name).tolist()
                       for name in node.outputs.vibrational_data.get_arraynames()},
            'hessian_text': node.outputs.hessian.get_content()}
