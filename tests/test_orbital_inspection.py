"""Spatial-orbital identity, occupation meaning and durable inspection reuse."""
import hashlib
import io
import json
from copy import deepcopy

import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import orbital_inspection as inspection, orbitals, common_orbitals
from aiida_empa_orca.scripts.compact_orbitals import compact_json
from test_casci import common_reference  # shared disposable reference fixture
from test_reference import electronic_source  # noqa: F401


def raw_export(structure,kind='UNO'):
    occupations = [2.]*7+[1.]+[0.]*20
    if kind == 'UNO':
        occupations[6],occupations[8] = 1.98,.02
    atoms = structure.get_ase()
    return {'sets':{kind:{'source_filename':'aiida.'+kind.lower(),'sha256':'abc','size_bytes':12,
        'molecule':{'CoordinateUnits':'Angs','Charge':0,'Multiplicity':2,
                    'Atoms':[{'ElementNumber':int(z),'Coords':position.tolist()} for z,position in zip(atoms.numbers,atoms.positions)],
                    'MolecularOrbitals':{'EnergyUnit':'Eh','MOs':[
                        {'Occupancy':occ,'OrbitalEnergy':-1.+i*.1} for i,occ in enumerate(occupations)]}}}}}


def test_natural_occupations_are_not_integer_reference_occupations(common_reference):
    ref_uuid,_,_,_ = common_reference
    ref = orm.load_node(ref_uuid)
    structure = ref.creator.inputs.structure
    result = inspection.parse_catalog(raw_export(structure),ref.get_dict(),structure)['UNO']
    assert result['occupation_kind'] == 'fractional_natural'
    assert result['levels'][6]['occupation'] == 1.98
    assert result['levels'][8]['occupation'] == .02
    assert all('energy_ev' not in row for row in result['levels'])
    result = inspection.parse_catalog(raw_export(structure,'QRO'),ref.get_dict(),structure)['QRO']
    assert result['occupation_kind'] == 'integer_reference' and result['levels'][7]['occupation'] == 1
    assert 'energy_ev' in result['levels'][7]


@pytest.mark.parametrize('invalid',['count','electrons','geometry','coord_count','coordinate_nan','spin','nonfinite','fractional_qro','set'])
def test_invalid_orbital_catalog_cannot_be_presented_as_reference(common_reference,invalid):
    ref = orm.load_node(common_reference[0])
    structure = ref.creator.inputs.structure
    raw = raw_export(structure,'QRO')
    mol = raw['sets']['QRO']['molecule']
    if invalid == 'count':mol['MolecularOrbitals']['MOs'].pop()
    if invalid == 'electrons':mol['MolecularOrbitals']['MOs'][7]['Occupancy'] = 0.
    if invalid == 'geometry':mol['Atoms'][0]['Coords'][0] += .1
    if invalid == 'coord_count':mol['Atoms'][0]['Coords'].pop()
    if invalid == 'coordinate_nan':mol['Atoms'][0]['Coords'][0] = float('nan')
    if invalid == 'spin':mol['Multiplicity'] = 4
    if invalid == 'nonfinite':mol['MolecularOrbitals']['MOs'][0]['Occupancy'] = float('nan')
    if invalid == 'fractional_qro':mol['MolecularOrbitals']['MOs'][0]['Occupancy'] = 1.9
    if invalid == 'set':raw['sets']['UNO'] = raw['sets'].pop('QRO')
    with pytest.raises(ValueError):inspection.parse_catalog(raw,ref.get_dict(),structure)


def test_compaction_discards_coefficients_without_rounding_occupations():
    text = json.dumps({'Molecule':{'MolecularOrbitals':{'MOs':[
        {'MOCoefficients':[.1]*10000,'Occupancy':1.9997234587415171,'OrbitalEnergy':-.2}]}}},indent=2)
    compact = compact_json(io.StringIO(text))
    mo = compact['Molecule']['MolecularOrbitals']['MOs'][0]
    assert mo['MOCoefficients'] == []
    assert mo['Occupancy'] == 1.9997234587415171
    assert len(json.dumps(compact)) < 200
    with pytest.raises(ValueError,match='Truncated'):
        compact_json(io.StringIO('"MOCoefficients": [\n 1.0,\n'))
    with pytest.raises(ValueError,match='Unexpected'):
        compact_json(io.StringIO('"MOCoefficients": [\n "not a coefficient"\n'))


def catalog_builder(common_reference):
    ref_uuid,remote_uuid,code_uuid,_ = common_reference
    b = inspection.OrbitalCatalogWorkChain.get_builder()
    b.orbital_reference,b.source_remote = orm.load_node(ref_uuid),orm.load_node(remote_uuid)
    b.export_code = b.storage_code = orm.load_code(code_uuid)
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/tmp/inspection-stash'})
    return b


def test_catalog_reuses_durable_metadata_after_both_source_files_are_lost(common_reference):
    b = catalog_builder(common_reference)
    previous = orm.WorkChainNode(process_type=inspection.CATALOG_PROCESS)
    for name in ('orbital_reference','source_remote','export_code','storage_code','storage_policy'):
        previous.base.links.add_incoming(b[name].store(),link_type=LinkType.INPUT_WORK,link_label=name)
    previous.store()
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.orbital_catalog').store()
    catalog = orm.Dict(dict={'sets':{'QRO':{}}})
    catalog.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='catalog')
    catalog.store()
    catalog.base.links.add_incoming(previous,link_type=LinkType.RETURN,link_label='catalog')
    previous.set_process_state(ProcessState.FINISHED)
    previous.set_exit_status(0)
    (common_reference[-1]/'aiida.qro').unlink()
    outputs,run = run_get_node(catalog_builder(common_reference))
    assert run.is_finished_ok and not run.called_descendants
    assert outputs['catalog'].uuid == catalog.uuid


def test_missing_uno_keeps_qro_inspection_and_reports_regeneration(common_reference,aiida_manager):
    b = catalog_builder(common_reference)
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        assert process.setup() is None
        assert set(process.ctx.locations) == {'QRO'}
        assert any('UNO unavailable' in row.message for row in orm.Log.collection.get_logs_for(process.node))
        process.ctx.locations = {'QRO':{'kind':'repository'}}
        assert process.preserve() is not None  # No redundant preservation jobs.
    finally:process.close()


def test_common_preparation_preserves_uno_alongside_qro(common_reference,aiida_manager,monkeypatch):
    from types import SimpleNamespace
    b = common_orbitals.CommonOrbitalsWorkChain.get_builder()
    ref = orm.load_node(common_reference[0])
    creator = ref.creator
    # Instantiate with the linked original SCF source's genuine inputs.
    source_retrieved = creator.inputs.source_retrieved
    source = source_retrieved.creator
    b.structure,b.settings,b.code = creator.inputs.structure,creator.inputs.settings,creator.inputs.code
    b.source_retrieved,b.source_remote = source_retrieved,source.outputs.remote_folder
    b.storage_code = b.code
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/tmp/inspection-stash'})
    process = instantiate_process(aiida_manager.get_runner(),b)
    def storage(remote,code,policy,*,names):
        captured.extend(names)
        return SimpleNamespace()
    captured=[]
    monkeypatch.setattr(common_orbitals,'storage_builder',storage)
    process.ctx.preparation = creator
    process.submit = lambda _: creator
    try:
        process.preserve()
        assert captured == ['aiida.qro','aiida.uno']
    finally:process.close()


@pytest.mark.parametrize('filename',['aiida.qro','aiida.uno'])
def test_common_cubes_stage_only_selected_file_and_retrieve_only_previews(common_reference,aiida_manager,filename):
    ref_uuid,remote_uuid,code_uuid,directory = common_reference
    (directory/filename).write_bytes(b'orbitals')
    code = orm.load_code(code_uuid)
    b = orbitals.OrbitalCubesCalculation.get_builder()
    b.code = b.plot_code = b.cubehandler_code = code
    b.source_folder = orm.load_node(remote_uuid)
    b.electronic_manifest = orm.Dict(dict={'files':[{'name':filename,'size_bytes':8}]})
    b.orbital_filename = orm.Str(filename)
    b.orbital_identity = orm.Dict(dict={'kind':'UNO' if filename.endswith('uno') else 'QRO','levels':[]})
    b.parameters = orm.Dict(dict={'orbitals':[[0,7]],'spin_density':False,'retention':'stash','stash_directory':'/tmp/inspection-cubes'})
    b.metadata.options.resources = {'num_machines':1,'num_mpiprocs_per_machine':1}
    from aiida_empa_orca.artifacts import stash_options
    b.metadata.options.stash = stash_options('/tmp/inspection-cubes','full_cubes')
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            request = json.loads(open(folder.get_abs_path('request.json')).read())
        assert info.remote_copy_list == [(code.computer.uuid,str(directory/filename),'aiida.gbw')]
        assert request['files'] == [{'name':'aiida.gbw','source_name':filename,'size_bytes':8}]
        assert 'previews' in info.retrieve_list and 'full_cubes' not in info.retrieve_list
        assert request['orbital_identity']['kind'] in ('QRO','UNO')
    finally:process.close()


def catalog_node(common_reference):
    ref_uuid,remote_uuid,_,directory = common_reference
    ref = orm.load_node(ref_uuid)
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.orbital_catalog')
    calc.base.links.add_incoming(ref,link_type=LinkType.INPUT_CALC,link_label='orbital_reference')
    calc.store()
    selected = {'filename':'aiida.qro','levels':[{'index':i,'occupation':2. if i<7 else 1. if i==7 else 0.} for i in range(28)],
        'size_bytes':(directory/'aiida.qro').stat().st_size,'sha256':hashlib.sha256((directory/'aiida.qro').read_bytes()).hexdigest(),
        'occupation_kind':'integer_reference'}
    catalog = orm.Dict(dict={'source_remote_uuid':remote_uuid,'orbital_reference_uuid':ref_uuid,'sets':{'QRO':selected}})
    catalog.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='catalog')
    return catalog.store()


def test_common_cube_missing_file_and_changed_file_block_execution(common_reference,aiida_manager):
    ref_uuid,remote_uuid,code_uuid,directory = common_reference
    b = inspection.CommonOrbitalCubesWorkChain.get_builder()
    b.orbital_reference,b.source_remote,b.catalog = orm.load_node(ref_uuid),orm.load_node(remote_uuid),catalog_node(common_reference)
    b.orbital_kind = orm.Str('QRO')
    b.storage_code = b.plot_code = b.cubehandler_code = orm.load_code(code_uuid)
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/tmp/inspection-stash'})
    b.parameters = orm.Dict(dict={'orbitals':[[0,7]],'spin_density':False,'retention':'leave'})
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        assert process.setup() is None
        child=[]
        process.submit = lambda builder: child.append(builder) or orm.CalcJobNode().store()
        process.generate()
        assert child[-1].metadata.disable_cache
        assert child[-1].orbital_identity.get_dict()['catalog_uuid'] == str(b.catalog.uuid)
        (directory/'aiida.qro').write_bytes(b'changed orbitals')
        assert process.setup().status == 400
        (directory/'aiida.qro').unlink()
        assert process.setup().status == 400
    finally:process.close()


def test_inspection_widget_distinguishes_sets_and_never_maps_uno_indices_to_qro(monkeypatch):
    from aiidalab_orca import inspection_services as service
    from aiidalab_orca.inspection import OrbitalInspection
    sets = {
        'QRO':{'levels':[{'index':i,'occupation':occ,'energy_ev':-5.+i} for i,occ in enumerate([2.,1.,0.])]},
        'UNO':{'levels':[{'index':i,'occupation':occ} for i,occ in enumerate([1.98,1.,.02])]}}
    record = {'uuid':'catalog','data':{'orbital_reference_uuid':'reference','n_electrons':3,'n_orbitals':3,'sets':sets}}
    monkeypatch.setattr(service,'catalog',lambda _:deepcopy(record))
    monkeypatch.setattr(service,'codes',lambda _:{'export':[],'plot':[],'cubehandler':[]})
    monkeypatch.setattr(service,'cube_runs',lambda *_:[])
    applied=[]
    widget=OrbitalInspection('common',active_indices=[1,2],apply_window=applied.append)
    try:
        assert widget.retention.value == 'stash'
        assert 'reference occ' in widget.orbitals.options[0][0]
        widget.orbitals.value = (0,2)
        widget.use_window.click()
        assert not applied and 'contiguous' in widget.window_message.value
        widget.orbitals.value = (1,2)
        widget.use_window.click()
        assert applied == [[1,2]]
        widget.kind.value = 'UNO'
        assert widget.use_window.disabled
        assert 'natural occ' in widget.orbitals.options[0][0]
        assert all(' eV' not in label for label,_ in widget.orbitals.options)
        assert 'not a one-to-one' in widget.info.value
        widget.set_active_indices([0,1])
        assert all('current CASCI active' not in label for label,_ in widget.orbitals.options)
        # Widget attributes retain serialized data and UUIDs, never ORM nodes.
        assert not any(isinstance(value,orm.Node) for value in vars(widget).values())
    finally:widget.close()


def test_reexported_metadata_reuses_same_orbital_identity():
    original={'orbital_reference_uuid':'reference','sets':{'UNO':{'filename':'aiida.uno','sha256':'digest',
              'size_bytes':100,'levels':[{'index':0,'occupation':1.999}]}}}
    repeated=deepcopy(original)
    assert inspection.same_orbital_set(original,repeated,'UNO')
    repeated['sets']['UNO']['sha256']='changed'
    assert not inspection.same_orbital_set(original,repeated,'UNO')
    repeated=deepcopy(original)
    repeated['orbital_reference_uuid']='different-reference'
    assert not inspection.same_orbital_set(original,repeated,'UNO')
    assert not inspection.same_orbital_set(original,original,'QRO')


def test_missing_uno_in_stashed_pair_does_not_hide_available_qro(common_reference,tmp_path):
    from aiida.common import StashMode
    from aiida_empa_orca import artifacts
    _,remote_uuid,code_uuid,_=common_reference
    root=tmp_path/'stash'
    (root/'electronic').mkdir(parents=True)
    for name in ('aiida.qro','aiida.uno'):
        (root/'electronic'/name).write_bytes(b'orbitals')
    calc=orm.CalcJobNode(process_type=artifacts.STORAGE_PROCESS)
    calc.base.links.add_incoming(orm.load_node(remote_uuid),link_type=LinkType.INPUT_CALC,link_label='source_folder')
    calc.store()
    manifest=orm.Dict(dict={'storage':'stash','files':[{'name':name,'size_bytes':8,'sha256':'digest'} for name in ('aiida.qro','aiida.uno')]})
    stash=orm.RemoteStashFolderData(stash_mode=StashMode.COPY,computer=orm.load_code(code_uuid).computer,
                                   target_basepath=str(root),source_list=['electronic'])
    for key,node in {'manifest':manifest,'remote_stash':stash}.items():
        node.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label=key)
        node.store()
    calc.set_process_state(ProcessState.FINISHED)
    calc.set_exit_status(0)
    (root/'electronic'/'aiida.uno').unlink()  # Only a disposable test stash.
    result=artifacts.resolve_electronic(orm.load_node(remote_uuid),names=['aiida.qro'])
    assert result['kind']=='stash' and [row['name'] for row in result['files']]==['aiida.qro']
    with pytest.raises(FileNotFoundError):
        artifacts.resolve_electronic(orm.load_node(remote_uuid),names=['aiida.uno'])


def test_user_can_regenerate_common_orbitals_without_silent_scf(electronic_source,monkeypatch):
    from aiidalab_orca import casci_services as service
    uuid,_=electronic_source()
    source=orm.load_node(uuid)
    def unexpected_reuse(_):
        raise AssertionError('A forced new reference must not choose an old preparation')
    monkeypatch.setattr(service,'reference_runs',unexpected_reuse)
    monkeypatch.setattr(service,'helper_code',lambda _:str(source.inputs.code.uuid))
    plan=service.prepare_common(uuid,force=True)
    assert plan['action']=='prepare' and plan['force_recompute']
    builder=service.common_builder(uuid,force=True)
    assert builder.force_recompute.value
    assert builder.source_retrieved.uuid==source.outputs.retrieved.uuid
    assert builder.source_remote.uuid==source.outputs.remote_folder.uuid
