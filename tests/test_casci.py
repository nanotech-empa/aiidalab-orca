"""CASCI root energies, shared-orbital provenance, reuse, and diagram signs."""

import io
from itertools import chain, repeat
from copy import deepcopy

import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import casci, common_orbitals, artifacts
from aiida_empa_orca.protocols import protocol_settings
from aiida_empa_orca.reference import reference_settings
from test_reference import electronic_source


def reference_data():
    return {'n_electrons':15,'n_orbitals':28,'charge':0,'source_multiplicity':2,
            'structure_uuid':'geometry','settings':reference_settings(protocol_settings()), 'filename':'aiida.qro',
            'preparation':'moread_noiter_v1'}


def output(mult=2, energies=(-129.1186109230,-128.8005650791)):
    return ('''Number of active electrons ... 3
Number of active orbitals ... 2
Total number of electrons ... 15
Active 6 - 7 ( 2 orbitals)
CI-PROBLEM SOLVED
MaxMacroIter 1 detected >>> CAS-CI. Check your FINAL ORBITAL options!
FINAL ORBITALS:
 Active Orbitals ... unchanged
 Internal Orbitals ... unchanged
 External Orbitals ... unchanged
'''+f'CAS-SCF STATES FOR BLOCK 0 MULT= {mult} NROOTS= {len(energies)}\n'+
        '\n'.join(f'ROOT {i}: E= {energy:.10f} Eh' for i,energy in enumerate(energies))+
        '\nSpin-Determinant CI Printing\nFINAL SINGLE POINT ENERGY -128.959588001086\nORCA TERMINATED NORMALLY\n')


def test_input_keeps_orbitals_and_parity_with_changing_charge():
    ref = reference_data()
    space = casci.active_space({'electrons':3,'orbitals':[6,7]},ref)
    for charge, mult, nel in [(0,2,3),(1,1,2),(1,3,2),(-1,1,4)]:
        text = casci.casci_input(ref,space,{'charge':charge,'multiplicity':mult})
        assert f'nel {nel}\n' in text
        assert 'ActOrbs unchanged' in text and 'IntOrbs unchanged' in text and 'ExtOrbs unchanged' in text
        assert 'maxiter 1' in text and f'* xyzfile {charge} {mult}' in text
        assert 'PBE ' not in text and 'Opt ' not in text
    for values in ({'charge':0,'multiplicity':1}, {'charge':-1,'multiplicity':3},
                   {'charge':1,'multiplicity':3,'nroots':2}, {'charge':2}):
        with pytest.raises(ValueError):
            casci.casci_settings(values,ref,space)
    for values in ({'electrons':2,'orbitals':[6,7]}, {'electrons':3,'orbitals':[5,7]},
                   {'electrons':3,'orbitals':[7,6]}, {'electrons':3,'orbitals':[6,7,40]}):
        with pytest.raises(ValueError):
            casci.active_space(values,ref)


def test_noiter_is_not_overridden_by_inherited_scf_controls():
    params = common_orbitals.preparation_parameters(protocol_settings(overrides={
        'max_scf_steps':200,'block_parameters':{'scf':{'GuessMix':75,'TolE':1e-9}}}))
    assert params['input_blocks']['scf'] == {'tole':1e-9,'MaxIter':0}
    assert 'NoIter' in params['input_keywords'] and 'UNO' in params['input_keywords']


def test_parser_reads_roots_not_state_average_and_requires_fixed_orbitals():
    ref = reference_data()
    space = {'electrons':3,'orbitals':[6,7]}
    settings = casci.casci_settings({'nroots':2},ref,space)
    result = casci.parse_states(output(),ref,space,settings)
    assert [r['energy_hartree'] for r in result['states']] == [-129.118610923,-128.8005650791]
    for bad in (output().replace('ROOT 1:', 'missing'),output().replace('ORCA TERMINATED NORMALLY',''),
                output().replace('Active Orbitals ... unchanged','Active Orbitals ... natural'),
                output().replace('>>> CAS-CI.','CASSCF'), output().replace('MULT= 2','MULT= 4'),
                output().replace('active electrons ... 3','active electrons ... 2'),
                output().replace('Active 6 - 7','Active 5 - 6'),
                output().replace('CI-PROBLEM SOLVED','CI did not converge')):
        with pytest.raises(ValueError):
            casci.parse_states(bad,ref,space,settings)


def test_parser_rejects_ci_warning_despite_solved_marker_and_normal_termination():
    # ORCA 6.1 can print both lines after exhausting its CI iteration budget.
    text = output().replace('CI-PROBLEM SOLVED',
        'WARNING: CI-ITERATIONS NOT CONVERGED!\nCI-PROBLEM SOLVED')
    ref = reference_data()
    space = {'electrons':3,'orbitals':[6,7]}
    settings = casci.casci_settings({'nroots':2},ref,space)
    assert 'ORCA TERMINATED NORMALLY' in text and 'CI-PROBLEM SOLVED' in text
    with pytest.raises(ValueError,match='CI iterations did not converge'):
        casci.parse_states(text,ref,space,settings)


def test_streamed_state_summary_preserves_results_without_reading_ci_body():
    ref = reference_data()
    space = {'electrons':3,'orbitals':[6,7]}
    settings = casci.casci_settings({'nroots':2},ref,space)
    prefix, footer = output().split('Spin-Determinant CI Printing')
    # A one-pass iterator has no read() method and creates no large input string.
    lines = chain(io.StringIO(prefix+'Spin-Determinant CI Printing\n'),
                  repeat(' 0.0123456789  [001122aabb]\n',100_000),io.StringIO(footer))
    summary = casci.read_state_summary(lines)
    assert len(summary) < 2048
    assert casci.parse_states(summary,ref,space,settings) == casci.parse_states(output(),ref,space,settings)


@pytest.mark.parametrize('late', [
    'warning: CI-ITERATIONS NOT CONVERGED!\n',
    'CAS-SCF STATES FOR BLOCK 1 MULT= 2 NROOTS= 2\n',
    'Number of active electrons ... 2\n',
    'Active 5 - 6 ( 2 orbitals)\n',
])
def test_streamed_summary_keeps_late_validation_failures(late):
    ref = reference_data()
    space = {'electrons':3,'orbitals':[6,7]}
    settings = casci.casci_settings({'nroots':2},ref,space)
    text = output()+late
    summary = casci.read_state_summary(io.StringIO(text))
    for candidate in (text,summary):
        with pytest.raises(ValueError):
            casci.parse_states(candidate,ref,space,settings)


def dataset(charge, mult, energies):
    return {'orbital_reference_uuid':'reference', 'structure_uuid':'geometry',
            'active_space':{'electrons':2,'orbitals':[5,6]}, 'method':'CASCI','geometry_mode':'fixed',
            'model':{'integral_transform':'RI','auxiliary_basis':'def2-SVP/C'}, 'reference_charge':0,'states':[{'charge':charge,'multiplicity':mult,'root':root,
              'energy_hartree':energy} for root,energy in enumerate(energies)]}


def test_shared_zero_preserves_spin_gaps_charge_offsets_and_reference_switch():
    # Illustrative offsets, not a molecular benchmark.
    factor = casci.HARTREE_TO_EV
    datasets = [dataset(0,1,[-100]),dataset(0,3,[-100+.3/factor]),
                dataset(1,2,[-100+6/factor]),dataset(-1,2,[-100-2/factor])]
    diagram = casci.energy_diagram(datasets)
    assert diagram['reference_state'] == 'q0:m1:r0'
    assert [r['relative_energy_ev'] for r in diagram['states']] == pytest.approx([0,.3,6,-2])
    shifted = casci.energy_diagram(datasets,'q0:m3:r0')
    assert [r['relative_energy_ev'] for r in shifted['states']] == pytest.approx([-.3,0,5.7,-2.3])
    for field,value in [('orbital_reference_uuid','another'),('structure_uuid','relaxed'),('model',{'integral_transform':'RI','auxiliary_basis':'AutoAux'}),('active_space',{'electrons':4,'orbitals':[4,5,6]})]:
        altered = deepcopy(datasets)
        altered[-1][field] = value
        with pytest.raises(ValueError,match='same geometry'):
            casci.energy_diagram(altered)
    from aiidalab_orca.state_levels import StateEnergyLevels
    widget = StateEnergyLevels(datasets)
    try:
        assert 'Charge +1' in widget.plot.value and 'Multiplicity 3' in widget.plot.value
        assert '0.300000' in widget.table.value
        widget.zero.value = 'q0:m3:r0'
        assert '5.700000' in widget.table.value
        widget.upper.value = widget.lower.value
        assert 'maximum greater' in widget.message.value
    finally:
        widget.close()


@pytest.fixture
def common_reference(electronic_source):
    source_uuid, directory = electronic_source()
    source = orm.load_node(source_uuid)
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.common_orbitals',computer=source.inputs.code.computer)
    for name, value in {'structure':source.outputs.structure,'code':source.inputs.code,
                        'source_retrieved':source.outputs.retrieved,'settings':source.inputs.settings}.items():
        calc.base.links.add_incoming(value,link_type=LinkType.INPUT_CALC,link_label=name)
    calc.store()
    data = reference_data() | {'structure_uuid':str(source.outputs.structure.uuid)}
    ref = orm.Dict(dict=data)
    remote = orm.RemoteData(computer=source.inputs.code.computer,remote_path=str(directory))
    for key,value in {'orbital_reference':ref,'remote_folder':remote}.items():
        value.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label=key)
        value.store()
    (directory/'aiida.qro').write_bytes(b'common spatial orbitals')
    calc.set_process_state(ProcessState.FINISHED)
    calc.set_exit_status(0)
    return str(ref.uuid),str(remote.uuid),str(source.inputs.code.uuid),directory


def test_calcjob_stages_shared_reference_and_never_retrieves_large_orbitals(common_reference,aiida_manager):
    ref_uuid, remote_uuid, code_uuid, _ = common_reference
    ref, remote, code = orm.load_node(ref_uuid),orm.load_node(remote_uuid),orm.load_code(code_uuid)
    b = casci.CasciCalculation.get_builder()
    b.code,b.orbital_reference = code,ref
    b.structure = orm.load_node(ref.get_dict()['structure_uuid'])
    b.active_space = orm.Dict(dict={'electrons':3,'orbitals':[6,7]})
    b.settings = orm.Dict(dict={'nroots':2})
    common_orbitals.attach_orbital(b,artifacts.resolve_electronic(remote,names=['aiida.qro']),'aiida.qro')
    b.metadata.options.resources = {'num_machines':1,'num_mpiprocs_per_machine':1}
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            assert 'aiida.gbw' not in info.retrieve_list
            assert info.remote_copy_list == [(code.computer.uuid,remote.get_remote_path()+'/aiida.qro','reference.gbw')]
            assert open(folder.get_abs_path('aiida.inp')).read() == casci.casci_input(ref.get_dict(),b.active_space.get_dict(),b.settings.get_dict())
    finally:
        process.close()


def workchain_builder(common_reference):
    ref_uuid,remote_uuid,code_uuid,_ = common_reference
    b = casci.CasciWorkChain.get_builder()
    b.orbital_reference,b.source_remote = orm.load_node(ref_uuid),orm.load_node(remote_uuid)
    b.code = b.storage_code = orm.load_code(code_uuid)
    b.active_space = orm.Dict(dict={'electrons':3,'orbitals':[6,7]})
    b.settings = orm.Dict(dict={'nroots':2})
    b.storage_policy = orm.Dict(dict={'threshold_mb':100,'stash_directory':'/tmp/test-casci-stash'})
    return b


def test_workchain_missing_orbitals_blocks_new_run_and_forced_calc_bypasses_cache(common_reference,aiida_manager):
    b = workchain_builder(common_reference)
    process = instantiate_process(aiida_manager.get_runner(),b)
    try:
        assert process.setup() is None
        captured = []
        def submit(child):
            captured.append(child)
            return orm.CalcJobNode().store()
        process.submit = submit
        process.run_casci()
        assert captured[-1].metadata.disable_cache
        (common_reference[-1]/'aiida.qro').unlink()
        assert process.setup().status == 400
    finally:
        process.close()


@pytest.mark.parametrize('caching', [False, True])
def test_reuse_of_durable_state_energies_does_not_need_scratch(common_reference,caching):
    b = workchain_builder(common_reference)
    previous = orm.WorkChainNode(process_type=casci.PROCESS_TYPE)
    for name in ('orbital_reference','source_remote','code','storage_code','active_space','settings','storage_policy'):
        value = b[name].store()
        previous.base.links.add_incoming(value,link_type=LinkType.INPUT_WORK,link_label=name)
    previous.store()
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.casci').store()
    text = output()
    ref,space = b.orbital_reference.get_dict(),b.active_space.get_dict()
    state_data = casci.parse_states(text,ref,space,casci.casci_settings(b.settings.get_dict(),ref,space))
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.StringIO(text),'aiida.out')
    for key,value in {'state_energies':orm.Dict(dict=state_data),'retrieved':retrieved,
                      'remote_folder':orm.RemoteData(computer=b.code.computer,remote_path='/tmp/no-longer-here')}.items():
        value.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label=key)
        value.store()
        value.base.links.add_incoming(previous,link_type=LinkType.RETURN,link_label=key)
    previous.set_process_state(ProcessState.FINISHED)
    previous.set_exit_status(0)
    (common_reference[-1]/'aiida.qro').unlink()
    from aiida.manage.caching import enable_caching,disable_caching
    with (enable_caching if caching else disable_caching)(identifier='aiida.calculations:empa_orca.casci'):
        outputs,run = run_get_node(workchain_builder(common_reference))
    assert run.is_finished_ok and not run.called_descendants
    assert outputs['state_energies'].uuid == previous.outputs.state_energies.uuid


def test_storage_accepts_explicit_casci_bundle(common_reference,aiida_manager):
    _,remote_uuid,code_uuid,_ = common_reference
    builder = artifacts.storage_builder(orm.load_node(remote_uuid),orm.load_code(code_uuid),
                {'threshold_mb':100,'stash_directory':'/tmp/casci-stash'},names=['aiida.qro'])
    process = instantiate_process(aiida_manager.get_runner(),builder)
    try:
        with SandboxFolder() as folder:
            import json
            info = process.prepare_for_submission(folder)
            assert json.loads(open(folder.get_abs_path('request.json')).read())['files'] == ['aiida.qro']
            assert 'electronic' in info.retrieve_list
    finally:
        process.close()
    for names in ([],['../aiida.qro'],['aiida.qro','aiida.qro']):
        with pytest.raises(ValueError):
            artifacts.electronic_names(names)


@pytest.mark.parametrize('invalid', ['', 'iterated', 'basis', 'ecp', 'qro'])
def test_preparation_parser_requires_no_scf_and_verified_spatial_reference(common_reference,invalid):
    ref_uuid, _, _, _ = common_reference
    calc = orm.load_node(ref_uuid).creator
    text = '''Guess MOs are being read from file: reference.gbw
Input Geometry matches current geometry (good)
Input basis set matches current basis set (good)
Number of basis functions ... 28
Number of Electrons NEL .... 15
MaxIter==0 has been chosen - skipping the SCF
Quasi-Restricted Orbitals were saved in aiida.qro
ORCA TERMINATED NORMALLY
'''
    if invalid == 'iterated':
        text = text.replace('MaxIter==0 has been chosen - skipping the SCF','SCF CONVERGED AFTER 2 CYCLES')
    if invalid == 'basis':
        text = text.replace('Input basis set matches current basis set','Different basis')
    if invalid == 'ecp':
        text = text.replace('NEL .... 15','NEL .... 5')
    if invalid == 'qro':
        text = text.replace('Quasi-Restricted Orbitals were saved in aiida.qro','UNO only')
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.StringIO(text),'aiida.out')
    retrieved.base.links.add_incoming(calc,link_type=LinkType.CREATE,link_label='retrieved')
    retrieved.store()
    parser = common_orbitals.CommonOrbitalsParser(calc)
    result = parser.parse()
    if invalid:
        assert result.status == 310
    else:
        assert result is None
        assert parser.outputs['orbital_reference'].get_dict()['preparation'] == 'moread_noiter_v1'
