"""External frozen orbitals retain their identity through native CASCI and UI."""
from copy import deepcopy
import hashlib
import io
import json

import ipywidgets as ipw
import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import fixed_orbitals as backend, casci, orbital_inspection
from aiida_empa_orca.fixed_orbitals_data import CALCULATION, PROCESS, checked_manifest, check_export
from test_reference import electronic_source  # noqa: F401


TEXT = '''Your calculation utilizes the basis: def2-SVP
Number of basis functions ... 28
Number of active electrons ... 3
Number of active orbitals ... 3
Total number of electrons ... 15
Active 6 - 8 ( 3 orbitals)
CI-PROBLEM SOLVED
MaxMacroIter 1 detected >>> CAS-CI. Check your FINAL ORBITAL options!
FINAL ORBITALS:
Active Orbitals ... unchanged
Internal Orbitals ... unchanged
External Orbitals ... unchanged
CAS-SCF STATES FOR BLOCK 0 MULT= 2 NROOTS= 1
ROOT 0: E= -129.1234567890 Eh
Spin-Determinant CI Printing
ORCA TERMINATED NORMALLY
'''


@pytest.fixture
def registered_import(entry_points):
    for group, cls in [('calculations',backend.FixedOrbitalsImportCalculation),
                       ('workflows',backend.FixedOrbitalsImportWorkChain), ('parsers',backend.FixedOrbitalsImportParser)]:
        if not entry_points.eps_select(f'aiida.{group}', name='empa_orca.import_fixed_orbitals'):
            entry_points.add(cls, f'aiida.{group}:empa_orca.import_fixed_orbitals')


@pytest.fixture
def external_reference(electronic_source, registered_import):
    def make(text=TEXT):
        uuid, directory = electronic_source()
        original = orm.load_node(uuid)
        settings = original.inputs.settings
        rows = []
        for role, name, content in [('gbw','mol.gbw',b'original frozen orbitals'),
                                    ('input','input.inp',b'! def2-SVP MOREAD NoIter'),
                                    ('output','out.out',text.encode())]:
            (directory/name).write_bytes(content)
            rows.append(dict(role=role,name=name,size_bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
        manifest = dict(files=rows,active_space={'electrons':3,'orbitals':[6,7,8]},nroots=1,
                        energies_hartree=[-129.123456789],description='External NO frozen-CASCI reference; fixture author')
        request = dict(manifest=manifest,settings=settings.get_dict(),atomic_numbers=[7,8],positions=[[0,0,0],[0,0,1.3]])
        molecule = dict(Atoms=[dict(ElementNumber=z,NuclearCharge=z,Coords=p,Basis=[{'fixture':True}])
                              for z,p in zip(request['atomic_numbers'],request['positions'])],
                        CoordinateUnits='Angs',Charge=0,Multiplicity=2,
                        MolecularOrbitals={'EnergyUnit':'Eh','MOs':[dict(Occupancy=occ,MOCoefficients=row)
                            for row,occ in zip(np.eye(28).tolist(),[2.]*6+[1.]*3+[0.]*19)]},
                        **{'S-Matrix':np.eye(28).tolist()})
        report = check_export(molecule,request) | {'source_manifest':manifest}
        helper = orm.InstalledCode(label='import-helper',computer=original.inputs.code.computer,
                                   filepath_executable='/bin/true').store()
        calc = orm.CalcJobNode(process_type=CALCULATION, computer=original.inputs.code.computer)
        for name,value in {'structure':original.inputs.structure,'settings':settings,
                           'code':helper,
                           'source_manifest':orm.Dict(dict=manifest).store()}.items():
            calc.base.links.add_incoming(value,link_type=LinkType.INPUT_CALC,link_label=name)
        calc.store()
        folder = orm.FolderData()
        for name,content in {'source.out':text,'source.inp':'! def2-SVP MOREAD NoIter','export.log':'ORCA_2JSON\n',
                             'import_manifest.json':json.dumps(report)}.items():
            folder.base.repository.put_object_from_filelike(io.StringIO(content),name)
        folder.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='retrieved');folder.store()
        remote = orm.RemoteData(computer=original.inputs.code.computer,remote_path=str(directory))
        remote.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='remote_folder');remote.store()
        (directory/'aiida.gbw').write_bytes(b'original frozen orbitals')
        parser = backend.FixedOrbitalsImportParser(calc)
        error = parser.parse()
        if error:
            return error,None,None,None,None
        reference = parser.outputs['orbital_reference']
        reference.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='orbital_reference');reference.store()
        calc.set_process_state(ProcessState.FINISHED);calc.set_exit_status(0)
        run = orm.WorkChainNode(process_type=PROCESS)
        for name,value in {'structure':original.inputs.structure,'settings':settings,'code':original.inputs.code,
                'source_remote':remote,'source_manifest':orm.Dict(dict=manifest).store(),
                'storage_code':helper,'storage_policy':orm.Dict(dict={'mode':'remote','threshold_mb':0,'stash_directory':''}).store()}.items():
            run.base.links.add_incoming(value,link_type=LinkType.INPUT_WORK,link_label=name)
        run.label = 'Imported NO fixed orbitals';run.store()
        for name,value in {'orbital_reference':reference,'structure':original.inputs.structure,'remote_folder':remote,'retrieved':folder}.items():
            value.base.links.add_incoming(run,link_type=LinkType.RETURN,link_label=name)
        run.set_process_state(ProcessState.FINISHED);run.set_exit_status(0)
        return None,str(run.uuid),request,molecule,str(original.inputs.code.uuid)
    return make


@pytest.mark.parametrize('bad', ['geometry','charge','spin','ecp','overlap','active_norm','occupations'])
def test_import_rejects_incompatible_actual_wavefunctions(external_reference,bad):
    _,_,request,molecule,_ = external_reference()
    m = deepcopy(molecule)
    if bad == 'geometry':m['Atoms'][1]['Coords'][2] += .01
    if bad == 'charge':m['Charge'] = 1
    if bad == 'spin':m['Multiplicity'] = 4
    if bad == 'ecp':m['Atoms'][0]['NuclearCharge'] = 5
    if bad == 'overlap':m['S-Matrix'][0][1] = .1
    if bad == 'active_norm':m['MolecularOrbitals']['MOs'][6]['MOCoefficients'][6] = .9
    if bad == 'occupations':m['MolecularOrbitals']['MOs'][0]['Occupancy'] = 1.
    with pytest.raises(ValueError):check_export(m,request)


@pytest.mark.parametrize('old,new', [('unchanged','natural'),('def2-SVP','def2-TZVP'),
                                    ('-129.1234567890','-129.1134567890'),('ORCA TERMINATED NORMALLY','incomplete')])
def test_import_requires_verified_frozen_source_output(external_reference,old,new):
    error,*_ = external_reference(TEXT.replace(old,new))
    assert error.status == 310


@pytest.mark.parametrize('error', [AttributeError('public_blob'), PermissionError('SSH unavailable')])
def test_imported_results_remain_accessible_when_storage_probe_fails(external_reference, monkeypatch, error):
    from aiida_empa_orca import common_orbitals
    from aiidalab_orca import history, services, casci_services

    _, uuid, *_ = external_reference()

    def inaccessible(*args, **kwargs):
        raise error

    monkeypatch.setattr(common_orbitals, 'reference_location', inaccessible)
    widget = history.HistoryWidget(lambda _: None, lambda _: None, lambda _: None)
    try:
        widget.select(uuid)
        assert widget.selected_uuid == uuid and not widget.view.disabled
        assert 'could not be checked' in widget.detail.value
        assert 're-import' not in widget.detail.value
        assert services.result(uuid)['imported_reference']
        with pytest.raises(type(error), match=str(error)):
            casci_services.prepare_casci(uuid, 3, 3, {'multiplicity': 2, 'tprintwf': 1e-9})
    finally:
        widget.close()


def test_import_is_searchable_and_native_casci_keeps_the_imported_basis(external_reference,monkeypatch):
    _,uuid,request,molecule,code_uuid = external_reference()
    from aiidalab_orca import services, casci_services, history, viewer
    from aiidalab_orca.app import close_widget_tree
    data = services.result(uuid)
    assert data['imported_reference'] and not data['single_point'] and not data['optimized']
    assert 'levels' not in data and data['active_space'] == request['manifest']['active_space']
    assert history.search_runs(text='Imported NO',kind='imported')['rows'][0]['uuid'] == uuid
    assert 'Imported fixed orbitals are available' in history.inspect_run(uuid)['reuse_status']
    assert casci_services.reference_runs(uuid)[0]['uuid'] == uuid
    plan = casci_services.prepare_casci(uuid,3,3,{'multiplicity':2,'tprintwf':1e-9})
    assert plan['active_space']['orbitals'] == [6,7,8]
    assert 'TPrintWF 1e-09' in plan['input'] and 'ActOrbs unchanged' in plan['input']
    assert casci_services.casci_builder(plan).code.uuid == code_uuid
    reference = orm.load_node(uuid).outputs.orbital_reference
    assert casci.validate_reference(reference,orm.load_node(uuid).outputs.remote_folder)['imported']
    assert orbital_inspection.variants(reference.get_dict()) == {'fixed':'aiida.gbw'}
    raw = {'sets':{'fixed':{'source_filename':'aiida.gbw','molecule':molecule,'sha256':'a'*64,'size_bytes':100}}}
    levels = orbital_inspection.parse_catalog(raw,reference.get_dict(),orm.load_node(uuid).outputs.structure)
    assert levels['fixed']['occupation_kind'] == 'source_casci_diagonal'
    assert all('energy_ev' not in row for row in levels['fixed']['levels'])
    monkeypatch.setattr(viewer,'molecule',lambda *args:ipw.Label('Geometry'))
    view = viewer.show_result(data)
    try:
        panel = view.tabs.show_section('states')
        assert panel.reference.value == uuid
        assert panel.electrons.value == 3 and panel.norb.value == 3
        assert panel.threshold.value == 1e-9
        assert 'Imported fixed-orbital reference' in view.children[0].value
        assert 'Frozen CASCI source' in view.children[0].value and 'reported orbital generator' in view.children[0].value
    finally:
        close_widget_tree(view)


def test_manifest_does_not_accept_unbound_paths_or_discontinuous_spaces(external_reference):
    _,_,request,_,_ = external_reference()
    bad = deepcopy(request['manifest']);bad['files'][0]['name']='../mol.gbw'
    with pytest.raises(ValueError):checked_manifest(bad)
    bad = deepcopy(request['manifest']);bad['active_space']['orbitals']=[6,8]
    with pytest.raises(ValueError):checked_manifest(bad)


def test_imported_casci_setup_uses_declared_orca_and_rejects_helper(external_reference,aiida_manager):
    _,uuid,_,_,code_uuid = external_reference()
    from aiidalab_orca import casci_services
    plan = casci_services.prepare_casci(uuid,3,3,{'multiplicity':2})
    builder = casci_services.casci_builder(plan)
    reference = orm.load_node(uuid).outputs.orbital_reference
    assert reference.creator.inputs.code.uuid != code_uuid
    assert casci.reference_orca_code(reference) == code_uuid
    for accepted in (True,False):
        builder.code = orm.load_code(code_uuid) if accepted else reference.creator.inputs.code
        process = instantiate_process(aiida_manager.get_runner(),builder)
        try:
            error = process.setup()
            if accepted:
                assert error is None and process.ctx.location['kind']=='remote'
            else:
                assert error.status == 400
        finally:
            process.close()


def test_import_calcjob_stages_copies_and_never_retrieves_the_large_wavefunction(external_reference,aiida_manager):
    _,uuid,request,_,code_uuid = external_reference()
    n = orm.load_node(uuid)
    b = backend.FixedOrbitalsImportCalculation.get_builder()
    for key in ('structure','settings','source_remote','source_manifest'):
        b[key] = n.inputs[key]
    b.code = b.export_code = orm.load_code(code_uuid)
    b.metadata.options.resources = {'num_machines':1,'num_mpiprocs_per_machine':1}
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            staged = {'gbw':'aiida.gbw','input':'source.inp','output':'source.out'}
            assert info.remote_copy_list == [(n.inputs.code.computer.uuid,
                n.inputs.source_remote.get_remote_path()+'/'+r['name'],staged[r['role']]) for r in request['manifest']['files']]
            assert 'aiida.gbw' not in info.retrieve_list and 'aiida.json' not in info.retrieve_list
            with open(folder.get_abs_path('request.json')) as handle:
                assert json.load(handle)['manifest'] == request['manifest']
    finally:
        process.close()


def test_missing_external_files_do_not_launch_scf_or_an_import(external_reference):
    _,uuid,_,_,code_uuid = external_reference()
    n = orm.load_node(uuid)
    b = backend.FixedOrbitalsImportWorkChain.get_builder()
    for key in ('structure','settings','source_manifest','storage_policy'):
        b[key] = n.inputs[key]
    b.source_remote = orm.RemoteData(computer=n.inputs.code.computer,remote_path='/missing/external/casci')
    b.code = b.export_code = b.storage_code = orm.load_code(code_uuid)
    _,run = run_get_node(b)
    assert run.exit_status == 400 and not run.called_descendants


def test_incompatible_gbw_reports_matching_version_action(aiida_profile_clean):
    calc = orm.CalcJobNode(process_type=CALCULATION).store()
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.StringIO(
        'Your GBWFile is either corrupt or from a different ORCA version!\nUnknown HFTYP'), 'export.log')
    retrieved.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='retrieved');retrieved.store()
    error = backend.FixedOrbitalsImportParser(calc).parse()
    assert error.status == 311 and 'matching ORCA' in error.message


def test_inspection_prefers_source_installation_utilities(external_reference):
    _,uuid,_,_,code_uuid = external_reference()
    from aiidalab_orca.inspection_services import codes
    code = orm.load_code(code_uuid)
    for binary,kind in [('orca_2json','export'),('orca_plot','plot')]:
        orm.InstalledCode(label='other-version',computer=code.computer,filepath_executable='/opt/other/'+binary).store()
        correct = orm.InstalledCode(label='matching-version',computer=code.computer,filepath_executable='/bin/'+binary).store()
        assert codes(uuid)[kind][0][1] == str(correct.uuid)
