"""Operation-local AiiDA access for independent site-resolved XPS."""

import numpy as np
from aiida import orm
from aiida.engine import submit

from aiida_empa_orca.artifacts import resolve_electronic
from aiida_empa_orca.xps import (
    PROCESS_TYPE, XpsWorkChain, core_runs, matching_sites, site_signature, validated_site, validate_reference,
)
from .property_services import helper_code, source_node, source_remote, wavefunction_status
from aiida_empa_orca.xps_multiplets import PROCESS_TYPE as MULTIPLET_PROCESS, XpsMultipletsWorkChain


def reference_info(source_uuid):
    source = source_node(source_uuid)
    settings = validate_reference(source.outputs.structure, source.inputs.settings.get_dict())
    atoms = source.outputs.structure.get_ase()
    return {'settings': settings, 'atoms': [
        {'index': i, 'symbol': symbol, 'position': atoms.positions[i].tolist()}
        for i, symbol in enumerate(atoms.get_chemical_symbols()) if symbol in ('C', 'N', 'O', 'F', 'Co')]}


def runs(source_uuid):
    source = source_node(source_uuid)
    query = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': source.outputs.retrieved.uuid}, tag='source').append(
        orm.WorkChainNode, with_incoming='source', edge_filters={'label': 'source_retrieved'}, tag='run',
        filters={'process_type': {'in': [PROCESS_TYPE, MULTIPLET_PROCESS]}}, project=['uuid', 'label', 'ctime', 'attributes.process_state', 'attributes.exit_status'])
    result=[]
    for u,label,date,state,exit_status in query.order_by({'run':{'ctime':'desc'}}).all():
        node=orm.load_node(u)
        caller=node.caller
        if caller is not None and caller.process_type==MULTIPLET_PROCESS:
            continue  # The two spin branches belong to one app-level calculation.
        result.append({'uuid':str(u),'label':label,'date':date.isoformat(),'state':f'failed ({exit_status})' if state=='finished' and exit_status else state})
    return result


def prepare(source_uuid, atom_indices, *, force_recompute=False, solver='auto'):
    info = reference_info(source_uuid)
    allowed = {a['index'] for a in info['atoms']}
    selected = list(atom_indices)
    if not selected or len(set(selected)) != len(selected) or any(type(i) is not int or i not in allowed for i in selected):
        raise ValueError('Select one or more C/N/O/F/Co atoms for 1s ionization')
    source = source_node(source_uuid)
    if solver == 'auto':
        solver = 'freeze_release' if 27 in source.outputs.structure.get_ase().numbers else 'standard'
    if solver not in ('standard', 'freeze_release'):
        raise ValueError('Choose a supported DeltaSCF convergence strategy')
    previous = {} if force_recompute else matching_sites(source.outputs.structure, info['settings'],
                                                         source.inputs.code.uuid, source.outputs.retrieved.uuid)
    plan = {'source_uuid': str(source_uuid), 'atom_indices': selected, 'force_recompute': bool(force_recompute), 'solver':solver,
            'signatures': [site_signature(source.outputs.structure, info['settings'], source.inputs.code.uuid,
                                         source.outputs.retrieved.uuid, i) for i in selected],
            'reuse': {str(i): previous[i] for i in selected if i in previous},
            'missing': [i for i in selected if i not in previous], 'warnings': [], 'regenerate_reference': False}
    plan['open_shell'] = info['settings']['multiplicity'] == 2
    if plan['open_shell']:
        beta = {} if force_recompute else matching_sites(source.outputs.structure, info['settings'],
            source.inputs.code.uuid, source.outputs.retrieved.uuid, 'beta')
        plan['beta_signatures'] = [site_signature(source.outputs.structure, info['settings'], source.inputs.code.uuid,
            source.outputs.retrieved.uuid, i, 'beta') for i in selected]
        plan['branch_reuse'] = {'alpha': {str(i): previous[i] for i in selected if i in previous},
                               'beta': {str(i): beta[i] for i in selected if i in beta}}
        plan['reuse'] = {str(i): previous[i] for i in selected if i in previous and i in beta}
        plan['missing'] = [i for i in selected if i not in previous or i not in beta]
        plan['warnings'].append('Two raw UKS branches per atom; the singlet energy is an approximate two-state spin-projection estimate. Intensities are schematic.')
    plan['helper_uuid'] = helper_code(source.inputs.code.computer.uuid)
    plan['storage_policy'] = wavefunction_status(source_uuid)['policy']
    if plan['missing']:
        prepared = False
        for uuid in core_runs(source.outputs.retrieved.uuid, source.inputs.code.uuid):
            try:
                resolve_electronic(orm.load_node(uuid).outputs.remote_folder, names=['aiida.gbw'])
                prepared = True
                break
            except (FileNotFoundError, ValueError, KeyError):
                continue
        if not prepared:
            try:
                resolve_electronic(source_remote(source), names=['aiida.gbw'])
            except (FileNotFoundError, ValueError):
                plan['regenerate_reference'] = True
                plan['warnings'].append('The required wavefunction is missing. The fixed-geometry SCF will be recomputed with caching disabled before core preparation.')
    return plan


def submit_plan(plan):
    from aiida.engine.daemon.client import get_daemon_client
    if not get_daemon_client().is_daemon_running:
        raise ValueError('Start the AiiDA daemon before submitting')
    source = source_node(plan['source_uuid'])
    expected = [site_signature(source.outputs.structure, source.inputs.settings.get_dict(), source.inputs.code.uuid,
                               source.outputs.retrieved.uuid, i) for i in plan['atom_indices']]
    if expected != plan['signatures']:
        raise ValueError('The reviewed XPS reference has changed')
    open_shell = source.inputs.settings.get_dict()['multiplicity'] == 2
    if bool(plan.get('open_shell')) != open_shell:
        raise ValueError('The reviewed spin protocol changed')
    if open_shell:
        beta = [site_signature(source.outputs.structure, source.inputs.settings.get_dict(), source.inputs.code.uuid,
            source.outputs.retrieved.uuid, i, 'beta') for i in plan['atom_indices']]
        if beta != plan['beta_signatures']:
            raise ValueError('The reviewed beta branch changed')
    b = (XpsMultipletsWorkChain if open_shell else XpsWorkChain).get_builder()
    b.structure, b.settings, b.code = source.outputs.structure, source.inputs.settings, source.inputs.code
    b.source_retrieved, b.source_remote = source.outputs.retrieved, source_remote(source)
    b.helper_code, b.storage_policy = orm.load_code(plan['helper_uuid']), orm.Dict(dict=plan['storage_policy'])
    b.atom_indices, b.force_recompute = orm.List(list=plan['atom_indices']), orm.Bool(plan['force_recompute'])
    b.solver = orm.Str(plan.get('solver','standard'))
    b.metadata.label = source.outputs.structure.get_formula() + ' · XPS · atoms ' + ', '.join(str(i+1) for i in plan['atom_indices'])
    node = submit(b)
    node.base.extras.set('aiidalab_orca', {'version': '0.1.0', 'view': 'xps', 'source_uuid': str(source.uuid)})
    return str(node.uuid)


def result(uuid):
    node = orm.load_node(uuid)
    if node.process_type not in (PROCESS_TYPE, MULTIPLET_PROCESS):
        raise ValueError('Select an XPS workflow')
    atoms = node.inputs.structure.get_ase()
    sites = []
    for data in (node.outputs.sites.values() if 'sites' in node.outputs else []):
        site = validated_site(data.creator)
        i = site['atom_index']
        component = {'triplet_ms1': 'triplet (HS)', 'broken_symmetry_ms0': 'spin-mixed (BS)'}.get(site.get('spin_assignment'))
        label = f'{atoms[i].symbol}{i+1} · 1s' + (' · '+component if component else '')
        sites.append(site | {'symbol': atoms[i].symbol, 'label': label,
                             'data_uuid': str(data.uuid), 'calculation_uuid': str(data.creator.uuid)})
    return {'uuid': str(uuid), 'sites': sorted(sites, key=lambda s: s['atom_index']),
            'settings': node.inputs.settings.get_dict(), 'structure_uuid': str(node.inputs.structure.uuid),
            'source_uuid': node.base.extras.get('aiidalab_orca', {}).get('source_uuid'),
            'complete': node.is_finished_ok,
            'multiplets': [data.get_dict() | {'data_uuid': str(data.uuid)} for data in node.outputs.multiplets.values()]
                if 'multiplets' in node.outputs else []}


def qe_comparisons(source_uuid):
    """Optional read-only comparison: identical atom order and relative geometry."""
    source = source_node(source_uuid)
    atoms = source.outputs.structure.get_ase()
    rows = []
    query = orm.QueryBuilder().append(orm.WorkChainNode, filters={'process_type': 'aiida.workflows:xspec.xps',
        'attributes.process_state': 'finished', 'attributes.exit_status': 0}, project=['uuid'])
    for (uuid,) in query.iterall():
        node = orm.load_node(uuid)
        other = node.inputs.structure.get_ase()
        if (other.get_chemical_symbols() != atoms.get_chemical_symbols() or
                not np.allclose(other.positions-other.positions[0], atoms.positions-atoms.positions[0], atol=1e-5, rtol=0)):
            continue
        if 'binding_energies' not in node.outputs:
            continue
        sites = []
        mapping = node.outputs.symmetry_analysis_data.get_dict()['equivalent_sites_data']
        for element, shells in node.outputs.binding_energies.get_dict().items():
            for shell, values in shells.items():
                if shell != '1s':
                    continue
                for label, entry in values.items():
                    sites.append({'symbol': element, 'binding_energy_ev': entry['energy'],
                                  'atom_index': mapping[label]['site_index'], 'weight': entry['multiplicity'],
                                  'equivalent_atom_indices': mapping[label]['equivalent_sites_list']})
        rows.append({'uuid': str(uuid), 'label': node.label or 'QE XPS', 'sites': sites})
    return rows
