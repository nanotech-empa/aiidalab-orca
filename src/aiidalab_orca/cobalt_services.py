"""Plain-data services for independent CoPc valence and Co 2p workflows."""
from aiida import orm
from aiida.engine import submit
from aiida_empa_orca import cobalt_xps as co
from aiida_empa_orca.cobalt_workchains import CobaltValenceWorkChain,CobaltXpsWorkChain,matching_spectrum,available_calculation
from aiida_empa_orca.artifacts import resolve_electronic
from .property_services import source_node,source_remote,helper_code,wavefunction_status


def reference_info(source_uuid):
    n=source_node(source_uuid)
    co.validate_copc(n.outputs.structure,n.inputs.settings.get_dict())
    return {'source_uuid':str(source_uuid),'model':co.model_settings(),
            'cobalt_atoms':[i for i,z in enumerate(n.outputs.structure.get_ase().numbers) if z==27]}


def valence_runs(source_uuid):
    n=source_node(source_uuid)
    rows=orm.QueryBuilder().append(orm.FolderData,filters={'uuid':n.outputs.retrieved.uuid},tag='source').append(
        orm.WorkChainNode,with_incoming='source',edge_filters={'label':'source_retrieved'},tag='run',
        filters={'process_type':co.VALENCE_PROCESS},project=['uuid','ctime','attributes.process_state','attributes.exit_status']).order_by(
        {'run':{'ctime':'desc'}}).all()
    return [{'uuid':str(u),'date':d.isoformat(),'state':('failed ('+str(exit_status)+')') if s=='finished' and exit_status else s,
             'success':s=='finished' and exit_status==0} for u,d,s,exit_status in rows]


def prepare_valence(source_uuid,model=None,force=False):
    reference_info(source_uuid)
    n=source_node(source_uuid)
    model=co.model_settings(model)
    return {'source_uuid':str(source_uuid),'model':model,'force':bool(force),
        'geometry_uuid':str(n.outputs.structure.uuid),'preview':co.input_text(n.outputs.structure,'avas',model),
        'description':'Co 3d AVAS and explicit d/pi character checks, then SA-CASSCF(9,6): five Co d orbitals plus the highest inactive ligand pi orbital; 70 doublets and 20 quartets. Frozen geometry; cc-pwCVTZ on Co, cc-pVTZ on other atoms. The orbital set is checked before the Co 2p step.'}


def submit_valence(plan):
    n=source_node(plan['source_uuid'])
    if str(n.outputs.structure.uuid)!=plan['geometry_uuid']:raise ValueError('The reviewed geometry changed')
    co.validate_copc(n.outputs.structure,n.inputs.settings.get_dict())
    b=CobaltValenceWorkChain.get_builder()
    b.structure,b.settings,b.code=n.outputs.structure,n.inputs.settings,n.inputs.code
    b.source_retrieved,b.source_remote=n.outputs.retrieved,source_remote(n)
    b.storage_code=orm.load_code(helper_code(n.inputs.code.computer.uuid))
    b.storage_policy=orm.Dict(dict=wavefunction_status(plan['source_uuid'])['policy'])
    b.model,b.force_recompute=orm.Dict(dict=co.model_settings(plan['model'])),orm.Bool(plan['force'])
    b.metadata.label='CoPc · Co 2p preparation · SA-CASSCF(9,6)'
    node=submit(b)
    node.base.extras.set('aiidalab_orca',{'version':'0.1.0','view':'cobalt_valence','source_uuid':plan['source_uuid']})
    return str(node.uuid)


def prepare_spectrum(source_uuid,valence_uuid,model=None,force=False):
    reference_info(source_uuid)
    allowed={r['uuid'] for r in valence_runs(source_uuid)}
    if valence_uuid not in allowed:raise ValueError('Choose a Co valence preparation belonging to this geometry reference')
    n=orm.load_node(valence_uuid)
    if not n.is_finished_ok:raise ValueError('Choose a successfully completed Co valence preparation')
    model=co.model_settings(model or n.inputs.model.get_dict())
    source=source_node(source_uuid)
    reuse=None if force else matching_spectrum(n.outputs.reference.uuid,model,source.inputs.code.uuid)
    prepared=None if force else available_calculation(n.outputs.reference.uuid,'spectator',model,source.inputs.code.uuid)
    if not reuse and not prepared:resolve_electronic(n.outputs.remote_folder,names=['aiida.gbw'])
    data=n.outputs.reference.get_dict()
    return {'source_uuid':str(source_uuid),'valence_uuid':str(valence_uuid),'reference_uuid':str(n.outputs.reference.uuid),
        'model':model,'force':bool(force),'reference':data,'reuse_calculation_uuid':reuse,
        'description':'Co 2p RAS-CI(16,10) + SOMF spin-orbit coupling, 376 triplets and 316 singlets. Includes valence ionization and ligand-to-metal charge-transfer configurations. Relative intensities use the explicit 1s-to-2p core-transition approximation from the cited protocol; no continuum electron is computed.'}


def submit_spectrum(plan):
    reviewed=prepare_spectrum(plan['source_uuid'],plan['valence_uuid'],plan['model'],plan['force'])
    if reviewed['reference_uuid']!=plan['reference_uuid']:raise ValueError('The reviewed valence orbitals changed')
    n=orm.load_node(plan['valence_uuid']);source=source_node(plan['source_uuid'])
    b=CobaltXpsWorkChain.get_builder()
    b.structure,b.code=source.outputs.structure,source.inputs.code
    b.helper_code=orm.load_code(helper_code(source.inputs.code.computer.uuid))
    b.storage_policy=orm.Dict(dict=wavefunction_status(plan['source_uuid'])['policy'])
    b.valence_reference,b.valence_folder,b.valence_retrieved=n.outputs.reference,n.outputs.remote_folder,n.outputs.retrieved
    b.model,b.force_recompute=orm.Dict(dict=plan['model']),orm.Bool(plan['force'])
    b.metadata.label='CoPc · Co 2p multiplets · RAS-CI + SOC'
    node=submit(b)
    node.base.extras.set('aiidalab_orca',{'version':'0.1.0','view':'cobalt_xps','source_uuid':plan['source_uuid'],'valence_uuid':plan['valence_uuid']})
    return str(node.uuid)


def spectrum_runs(source_uuid):
    refs=[]
    for row in valence_runs(source_uuid):
        if row['success']:
            node=orm.load_node(row['uuid'])
            refs.append(str(node.outputs.reference.uuid))
    if not refs:return []
    rows=orm.QueryBuilder().append(orm.Dict,filters={'uuid':{'in':refs}},tag='ref').append(
        orm.WorkChainNode,with_incoming='ref',edge_filters={'label':'valence_reference'},tag='run',
        filters={'process_type':co.SPECTRUM_PROCESS},project=['uuid','ctime','attributes.process_state','attributes.exit_status']).order_by(
        {'run':{'ctime':'desc'}}).all()
    return [{'uuid':str(u),'date':d.isoformat(),'state':('failed ('+str(exit_status)+')') if s=='finished' and exit_status else s,
             'success':s=='finished' and exit_status==0} for u,d,s,exit_status in rows]


def result(uuid):
    n=orm.load_node(uuid)
    if n.process_type!=co.SPECTRUM_PROCESS or not n.is_finished_ok:raise ValueError('Choose a completed Co 2p spectrum')
    return co.validated_calculation(n.outputs.spectrum.creator) | {'uuid':str(uuid),'spectrum_uuid':str(n.outputs.spectrum.uuid),
        'valence_reference_uuid':str(n.inputs.valence_reference.uuid),'retrieved_uuid':str(n.outputs.retrieved.uuid)}
