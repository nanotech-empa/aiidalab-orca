"""Separate, reusable orbital preparation and Co 2p multiplet workflows."""
from aiida import engine,orm
from . import cobalt_xps as co
from .artifacts import resolve_electronic,storage_builder
from .common_orbitals import CommonOrbitalsWorkChain,attach_orbital,options,validate_source
from .reference import ArtifactUnavailable


def valence_restart_source(structure,code,reference,retrieved,folder,model):
    """Validate the unchanged producing calculation before reusing its orbitals."""
    parent=reference.creator
    if (parent is None or parent.process_type!=co.CALC_PROCESS or parent.inputs.stage.value!='valence'
            or parent.outputs.reference.uuid!=reference.uuid
            or parent.outputs.retrieved.uuid!=retrieved.uuid
            or parent.outputs.remote_folder.uuid!=folder.uuid
            or parent.inputs.structure.uuid!=structure.uuid or parent.inputs.code.uuid!=code.uuid):
        raise ValueError('Restart reference, geometry and orbital files must share their verified producing calculation')
    previous=co.model_settings(parent.inputs.model.get_dict());current=co.model_settings(model)
    if any(previous[k]!=current[k] for k in ('basis','cobalt_basis','auxiliary_basis')):
        raise ValueError('Valence reconvergence requires the same orbital and auxiliary basis sets')
    co.validated_calculation(parent)
    return resolve_electronic(folder,names=['aiida.gbw'])


def report_failure(workchain,node):
    workchain.report('Calculation '+str(node.uuid)+' failed: '+(node.exit_message or 'native validation failed'))
    for entry in orm.Log.collection.get_logs_for(node):
        if entry.levelname in ('ERROR','CRITICAL'):workchain.report(entry.message)


def available_calculation(parent_uuid,stage,model,code_uuid):
    query=orm.QueryBuilder().append(orm.Dict,filters={'uuid':str(parent_uuid)},tag='parent').append(
        orm.CalcJobNode,with_incoming='parent',edge_filters={'label':'parent_reference'},
        filters={'process_type':co.CALC_PROCESS,'attributes.process_state':'finished','attributes.exit_status':0},
        tag='run',project=['uuid']).order_by({'run':{'ctime':'desc'}})
    for uid in query.all(flat=True):
        n=orm.load_node(uid)
        if n.inputs.stage.value!=stage or co.model_identity(n.inputs.model.get_dict())!=co.model_identity(model) or str(n.inputs.code.uuid)!=str(code_uuid):continue
        try:
            co.validated_calculation(n)
            resolve_electronic(n.outputs.remote_folder,names=['aiida.gbw'])
        except (KeyError,OSError,ValueError):continue
        return str(uid)
    return None


def matching_spectrum(valence_uuid,model,code_uuid):
    """Reuse spectrum data without requiring its no-longer-needed GBW."""
    rows=orm.QueryBuilder().append(orm.Dict,filters={'uuid':str(valence_uuid)},tag='ref').append(
        orm.WorkChainNode,with_incoming='ref',edge_filters={'label':'valence_reference'},
        filters={'process_type':co.SPECTRUM_PROCESS,'attributes.process_state':'finished','attributes.exit_status':0},
        tag='run',project=['uuid']).order_by({'run':{'ctime':'desc'}}).all(flat=True)
    for uid in rows:
        node=orm.load_node(uid)
        if co.model_identity(node.inputs.model.get_dict())!=co.model_identity(model) or str(node.inputs.code.uuid)!=str(code_uuid):continue
        producer=node.outputs.spectrum.creator
        try:co.validated_calculation(producer)
        except (ValueError,KeyError,OSError):continue
        return str(producer.uuid)
    return None


class CobaltValenceWorkChain(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.expose_inputs(CommonOrbitalsWorkChain)
        spec.input('model',valid_type=orm.Dict)
        for key,kind in {'restart_reference':orm.Dict,'restart_retrieved':orm.FolderData,
                         'restart_folder':orm.RemoteData}.items():spec.input(key,valid_type=kind,required=False)
        for key,kind in {'reference':orm.Dict,'retrieved':orm.FolderData,'remote_folder':orm.RemoteData}.items():spec.output(key,valid_type=kind)
        spec.outline(cls.setup,engine.if_(cls.needs_calculation)(engine.if_(cls.needs_preparation)(cls.common,cls.inspect_common,
            cls.avas,cls.inspect_avas,cls.preserve_avas,cls.check_avas_storage),
            cls.valence,cls.inspect_valence,cls.preserve_valence,cls.check_valence_storage),cls.results)
        spec.exit_code(400,'ERROR_INPUT',message='Unsupported CoPc reference or unavailable source wavefunction.')
        spec.exit_code(401,'ERROR_STAGE',message='Co orbital preparation failed; inspect the native output.')
        spec.exit_code(402,'ERROR_STORAGE',message='Co orbital preservation failed; scientific results remain in the producing calculation.')

    def setup(self):
        self.ctx.reuse_uuid=None
        try:
            co.validate_copc(self.inputs.structure,self.inputs.settings.get_dict())
            self.ctx.model=co.model_settings(self.inputs.model.get_dict())
            if self.ctx.model['protocol']!=co.PROTOCOL:raise ValueError('Use the consistent integration protocol for new orbital preparation')
            validate_source(self.inputs.structure,self.inputs.settings.get_dict(),self.inputs.code,
                self.inputs.source_retrieved,self.inputs.source_remote)
            restart_keys=('restart_reference','restart_retrieved','restart_folder')
            supplied=[k in self.inputs for k in restart_keys]
            if any(supplied) and not all(supplied):raise ValueError('Supply the complete valence restart reference and its producing files')
            if all(supplied):
                self.ctx.restart_location=valence_restart_source(self.inputs.structure,self.inputs.code,
                    self.inputs.restart_reference,self.inputs.restart_retrieved,self.inputs.restart_folder,self.ctx.model)
            if not self.inputs.force_recompute.value:
                rows=orm.QueryBuilder().append(orm.FolderData,filters={'uuid':self.inputs.source_retrieved.uuid},tag='source').append(
                    orm.WorkChainNode,with_incoming='source',edge_filters={'label':'source_retrieved'},
                    filters={'process_type':co.VALENCE_PROCESS,'attributes.process_state':'finished','attributes.exit_status':0},
                    project=['uuid'],tag='run').order_by({'run':{'ctime':'desc'}}).all(flat=True)
                for uid in rows:
                    n=orm.load_node(uid)
                    if (co.model_identity(n.inputs.model.get_dict())!=co.model_identity(self.ctx.model) or n.inputs.code.uuid!=self.inputs.code.uuid):continue
                    try:
                        co.validated_calculation(n.outputs.reference.creator)
                        resolve_electronic(n.outputs.remote_folder,names=['aiida.gbw'])
                    except (ValueError,KeyError,OSError):continue
                    self.ctx.reuse_uuid=str(uid);break
        except (ValueError,KeyError,OSError,ArtifactUnavailable) as exc:
            self.report(str(exc));return self.exit_codes.ERROR_INPUT

    def needs_calculation(self):return self.ctx.reuse_uuid is None
    def needs_preparation(self):return 'restart_reference' not in self.inputs

    def common(self):
        b=CommonOrbitalsWorkChain.get_builder()
        for k,v in self.exposed_inputs(CommonOrbitalsWorkChain).items():b[k]=v
        return engine.ToContext(common=self.submit(b))

    def inspect_common(self):
        if not self.ctx.common.is_finished_ok:return self.exit_codes.ERROR_STAGE

    def launch(self,stage,parent,location):
        reuse=None if self.inputs.force_recompute.value else available_calculation(parent.uuid,stage,self.ctx.model,self.inputs.code.uuid)
        if reuse:
            self.ctx[stage+'_uuid']=reuse;self.ctx[stage+'_reused']=True
            self.report('Reusing '+stage+' from '+reuse);return
        b=co.CobaltStatesCalculation.get_builder()
        b.structure,b.code,b.model=self.inputs.structure,self.inputs.code,orm.Dict(dict=self.ctx.model)
        b.stage,b.parent_reference=orm.Str(stage),parent
        attach_orbital(b,location,'aiida.qro' if stage=='avas' else 'aiida.gbw')
        b.metadata.options=options(self.ctx.model);b.metadata.disable_cache=True
        b.metadata.label='CoPc · '+('Co 3d AVAS inspection' if stage=='avas' else 'SA-CASSCF(9,6) · 70 doublets / 20 quartets')
        self.ctx[stage+'_reused']=False
        return engine.ToContext(**{stage:self.submit(b)})

    def avas(self):
        from .common_orbitals import reference_location
        return self.launch('avas',self.ctx.common.outputs.orbital_reference,reference_location(self.ctx.common))

    def inspect_stage(self,stage):
        if not self.ctx[stage+'_reused']:
            n=self.ctx[stage]
            if not n.is_finished_ok:
                report_failure(self,n);return self.exit_codes.ERROR_STAGE
            self.ctx[stage+'_uuid']=str(n.uuid)

    def inspect_avas(self):return self.inspect_stage('avas')

    def preserve(self,stage):
        if self.ctx[stage+'_reused']:return
        n=orm.load_node(self.ctx[stage+'_uuid'])
        b=storage_builder(n.outputs.remote_folder,self.inputs.storage_code,self.inputs.storage_policy.get_dict(),names=['aiida.gbw'])
        return engine.ToContext(**{stage+'_storage':self.submit(b)})

    def preserve_avas(self):return self.preserve('avas')
    def check_avas_storage(self):
        if not self.ctx.avas_reused and not self.ctx.avas_storage.is_finished_ok:return self.exit_codes.ERROR_STORAGE

    def valence(self):
        if 'restart_reference' in self.inputs:
            self.report('Reconverging the neutral reference from saved valence orbitals; geometry unchanged')
            return self.launch('valence',self.inputs.restart_reference,self.ctx.restart_location)
        n=orm.load_node(self.ctx.avas_uuid)
        return self.launch('valence',n.outputs.reference,resolve_electronic(n.outputs.remote_folder,names=['aiida.gbw']))

    def inspect_valence(self):return self.inspect_stage('valence')
    def preserve_valence(self):return self.preserve('valence')
    def check_valence_storage(self):
        if not self.ctx.valence_reused and not self.ctx.valence_storage.is_finished_ok:return self.exit_codes.ERROR_STORAGE

    def results(self):
        n=orm.load_node(self.ctx.reuse_uuid or self.ctx.valence_uuid)
        for key in ('reference','retrieved','remote_folder'):self.out(key,n.outputs[key])


class CobaltXpsWorkChain(engine.WorkChain):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        for key,kind in {'structure':orm.StructureData,'model':orm.Dict,'code':orm.AbstractCode,
            'helper_code':orm.AbstractCode,'storage_policy':orm.Dict,'valence_reference':orm.Dict,
            'valence_retrieved':orm.FolderData,'valence_folder':orm.RemoteData}.items():spec.input(key,valid_type=kind)
        spec.input('force_recompute',valid_type=orm.Bool,default=lambda:orm.Bool(False))
        for key,kind in {'spectrum':orm.Dict,'retrieved':orm.FolderData,'remote_folder':orm.RemoteData}.items():spec.output(key,valid_type=kind)
        spec.outline(cls.setup,engine.if_(cls.needs_calculation)(cls.prepare_spectator,cls.check_spectator,cls.preserve_spectator,cls.check_spectator_storage,cls.inspect_core,cls.check_core,cls.run_spectrum,
            cls.check_spectrum,cls.preserve,cls.check_storage),cls.results)
        spec.exit_code(400,'ERROR_INPUT',message='Invalid or unavailable Co multireference orbitals.')
        spec.exit_code(401,'ERROR_CORE',message='Co core orbitals could not be verified.')
        spec.exit_code(402,'ERROR_SPECTRUM',message='The Co 2p SOC spectrum failed native calculation or validation.')
        spec.exit_code(403,'ERROR_STORAGE',message='Co 2p results exist, but wavefunction preservation failed.')

    def setup(self):
        self.ctx.reuse_uuid=None
        try:
            self.ctx.model=co.model_settings(self.inputs.model.get_dict())
            parent=self.inputs.valence_reference.creator
            if (parent.process_type!=co.CALC_PROCESS or parent.inputs.stage.value!='valence'
                    or parent.outputs.remote_folder.uuid!=self.inputs.valence_folder.uuid
                    or parent.outputs.retrieved.uuid!=self.inputs.valence_retrieved.uuid
                    or parent.inputs.structure.uuid!=self.inputs.structure.uuid):
                raise ValueError('Co orbital metadata, structure and wavefunction must share their producing calculation')
            if parent.inputs.code.uuid!=self.inputs.code.uuid:
                raise ValueError('The spectrum and neutral reference must use the same ORCA code')
            co.require_consistent_reference(co.validated_calculation(parent),self.ctx.model)
            if not self.inputs.force_recompute.value:
                self.ctx.reuse_uuid=matching_spectrum(self.inputs.valence_reference.uuid,self.ctx.model,self.inputs.code.uuid)
            if not self.ctx.reuse_uuid:
                existing=available_calculation(self.inputs.valence_reference.uuid,'spectator',self.ctx.model,self.inputs.code.uuid)
                if not existing:resolve_electronic(self.inputs.valence_folder,names=['aiida.gbw'])
        except (ValueError,KeyError,OSError,ArtifactUnavailable) as exc:
            self.report(str(exc));return self.exit_codes.ERROR_INPUT

    def needs_calculation(self):return self.ctx.reuse_uuid is None

    def prepare_spectator(self):
        uid=None if self.inputs.force_recompute.value else available_calculation(self.inputs.valence_reference.uuid,'spectator',self.ctx.model,self.inputs.code.uuid)
        self.ctx.spectator_reused=bool(uid)
        if uid:
            self.ctx.spectator_uuid=uid;return
        b=co.CobaltStatesCalculation.get_builder()
        b.structure,b.code,b.model=self.inputs.structure,self.inputs.code,orm.Dict(dict=self.ctx.model)
        b.stage,b.parent_reference=orm.Str('spectator'),self.inputs.valence_reference
        attach_orbital(b,resolve_electronic(self.inputs.valence_folder,names=['aiida.gbw']),'aiida.gbw')
        b.metadata.options=options(self.ctx.model);b.metadata.disable_cache=True
        b.metadata.label='CoPc · neutral doublet natural orbitals · energy-preserving CAS-CI'
        return engine.ToContext(spectator=self.submit(b))

    def check_spectator(self):
        if not self.ctx.spectator_reused:
            if not self.ctx.spectator.is_finished_ok:
                report_failure(self,self.ctx.spectator);return self.exit_codes.ERROR_INPUT
            self.ctx.spectator_uuid=str(self.ctx.spectator.uuid)

    def preserve_spectator(self):
        if self.ctx.spectator_reused:return
        node=orm.load_node(self.ctx.spectator_uuid)
        b=storage_builder(node.outputs.remote_folder,self.inputs.helper_code,self.inputs.storage_policy.get_dict(),names=['aiida.gbw'])
        return engine.ToContext(spectator_storage=self.submit(b))

    def check_spectator_storage(self):
        if not self.ctx.spectator_reused and not self.ctx.spectator_storage.is_finished_ok:return self.exit_codes.ERROR_STORAGE

    def inspect_core(self):
        from .cobalt_core import CobaltCoreCalculation
        b=CobaltCoreCalculation.get_builder()
        b.structure,b.code=self.inputs.structure,self.inputs.helper_code
        spectator=orm.load_node(self.ctx.spectator_uuid)
        b.source_reference,b.source_retrieved=spectator.outputs.reference,spectator.outputs.retrieved
        b.metadata.options=options(self.ctx.model)|{'resources':{'num_machines':1,'num_mpiprocs_per_machine':1}}
        b.metadata.disable_cache=True
        b.metadata.label='Verify native CASSCF Co 1s/2p identities · unchanged wavefunction'
        return engine.ToContext(core=self.submit(b))

    def check_core(self):
        if not self.ctx.core.is_finished_ok:return self.exit_codes.ERROR_CORE

    def run_spectrum(self):
        b=co.CobaltStatesCalculation.get_builder()
        b.structure,b.code,b.model=self.inputs.structure,self.inputs.code,orm.Dict(dict=self.ctx.model)
        spectator=orm.load_node(self.ctx.spectator_uuid)
        b.stage,b.parent_reference=orm.Str('spectrum'),spectator.outputs.reference
        b.core_reference=self.ctx.core.outputs.core_reference
        attach_orbital(b,resolve_electronic(spectator.outputs.remote_folder,names=['aiida.gbw']),'aiida.gbw')
        b.metadata.options=options(self.ctx.model);b.metadata.disable_cache=True
        b.metadata.label='CoPc · Co 2p RAS-CI(16,10) + SOC · 376 triplets / 316 singlets'
        return engine.ToContext(spectrum=self.submit(b))

    def check_spectrum(self):
        if not self.ctx.spectrum.is_finished_ok:
            report_failure(self,self.ctx.spectrum);return self.exit_codes.ERROR_SPECTRUM

    def preserve(self):
        b=storage_builder(self.ctx.spectrum.outputs.remote_folder,self.inputs.helper_code,self.inputs.storage_policy.get_dict(),names=['aiida.gbw'])
        return engine.ToContext(storage=self.submit(b))

    def check_storage(self):
        if not self.ctx.storage.is_finished_ok:return self.exit_codes.ERROR_STORAGE

    def results(self):
        n=orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.spectrum
        self.out('spectrum',n.outputs.reference)
        for key in ('retrieved','remote_folder'):self.out(key,n.outputs[key])
