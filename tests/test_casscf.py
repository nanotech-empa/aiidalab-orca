"""Scientific objectives, saved-orbital checks, and explicit GUI submission."""
from copy import deepcopy

from aiida import orm
from aiida.common import CodeRunMode
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process
import pytest

from aiida_empa_orca import artifacts, casscf, common_orbitals
from test_casci import common_reference, electronic_source, reference_data


SPACE = {'electrons': 3, 'orbitals': [6, 7, 8]}


def objective():
    return {'mode': 'state_average', 'states': [
        {'multiplicity': 2, 'weights': [2, 1]}, {'multiplicity': 4, 'weights': [1]}]}


def native_output(settings, *, frozen=False, shift=0):
    prefix = ('MaxMacroIter 1 detected >>> CAS-CI.\nFINAL ORBITALS:\n'
              ' Active Orbitals ... unchanged\n Internal Orbitals ... unchanged\n'
              ' External Orbitals ... unchanged\n' if frozen else
              '---- THE CAS-SCF GRADIENT HAS CONVERGED ----\n'
              '---- DOING ONE FINAL ITERATION FOR PRINTING ----\n')
    prefix += ('Guess MOs are being read from file: ' + ('aiida.gbw' if frozen else 'reference.gbw') + '\n'
               'Input Geometry matches current geometry\nInput basis set matches current basis set\n')
    prefix += ('Number of active electrons ... 3\nNumber of active orbitals ... 3\n'
               'Total number of electrons ... 15\nActive 6 - 8 ( 3 orbitals)\nCI-PROBLEM SOLVED\n')
    for i, b in enumerate(settings['states']):
        prefix += f'BLOCK {i} WEIGHT= {sum(b["weights"]):.4f}\n Multiplicity ... {b["multiplicity"]}\n'
        prefix += ''.join(f' ROOT={r} WEIGHT= {w:.6f}\n' for r, w in enumerate(b['weights'])) + '\n'
    prefix += ' PrintLevel ... 1\n'
    for i, b in enumerate(settings['states']):
        prefix += f'CAS-SCF STATES FOR BLOCK {i} MULT= {b["multiplicity"]} NROOTS= {len(b["weights"])}\n'
        prefix += ''.join(f'ROOT {r}: E= {-100 + i + r / 10 + shift:.12f} Eh\n' for r in range(len(b['weights'])))
    return prefix + 'ORCA TERMINATED NORMALLY\n'


def test_explicit_state_weights_are_global_not_equal_multiplicity_weights():
    s = casscf.casscf_settings(objective(), reference_data(), SPACE)
    assert [b['weights'] for b in s['states']] == [[.5, .25], [.25]]
    text = casscf.casscf_input(reference_data(), SPACE, objective())
    assert 'mult 2,4\n nroots 2,1\n bweight 0.75,0.25' in text
    assert 'weights[0] = 0.5,0.25' in text
    assert 'PBE' not in text and 'Opt ' not in text
    assert '* xyzfile 0 2' in text and 'ActOrbs NatOrbs' in text
    assert text.index('!') < text.index('%casscf')
    frozen = casscf.casscf_input(reference_data(), SPACE, objective(), readback=True)
    assert 'maxiter 1' in frozen and '%moinp "aiida.gbw"' in frozen
    assert 'ActOrbs unchanged' in frozen
    equal = {'mode': 'state_average', 'states': [{'multiplicity': 2, 'weights': [1] * 6}]}
    normalized = casscf.casscf_settings(equal, reference_data(), SPACE)
    assert casscf.casscf_settings(normalized, reference_data(), SPACE) == normalized


@pytest.mark.parametrize('change', [
    {'charge': 1}, {'mode': 'state_average'}, {'maxiter': 1}, {'gtol': .01},
    {'states': [{'multiplicity': 1, 'weights': [1]}]},
    {'states': [{'multiplicity': 2, 'weights': [float('nan')]}]},
    {'states': [{'multiplicity': 2, 'weights': [-1, 2]}]},
    {'states': [{'multiplicity': 2, 'weights': [0, 0]}]},
    {'states': [{'multiplicity': 2, 'weights': [1, 1]}]},
    {'states': [{'multiplicity': 2, 'weights': [1]}, {'multiplicity': 2, 'weights': [1]}]},
])
def test_incompatible_objectives_are_blocked_before_submission(change):
    with pytest.raises(ValueError):
        casscf.casscf_settings(change, reference_data(), SPACE)


def test_state_specific_excited_root_does_not_mean_an_average():
    s = casscf.casscf_settings({'states': [{'multiplicity': 2, 'weights': [0, 0, 3]}]}, reference_data(), SPACE)
    assert s['mode'] == 'state_specific' and s['states'][0]['weights'] == [0, 0, 1]


def test_each_final_root_must_survive_saved_orbital_readback():
    ref = reference_data()
    s = casscf.casscf_settings(objective(), ref, SPACE)
    optimized, frozen = native_output(s), native_output(s, frozen=True)
    result = casscf.verified_result(optimized, frozen, ref, SPACE, s)
    assert result['method'] == 'CASSCF' and len(result['states']) == 3
    assert result['readback_max_error_hartree'] == 0
    assert [r['averaging_weight'] for r in result['states']] == [.5, .25, .25]
    cases = [
        (optimized.replace('THE CAS-SCF GRADIENT HAS CONVERGED', 'ENERGY CONVERGED'), frozen),
        (optimized, native_output(s, frozen=True, shift=2e-7)),
        (optimized, frozen.replace('ROOT 1:', 'MISSING ROOT 1:').replace('MISSING ROOT', 'missing')),
        (optimized, frozen.replace('Active Orbitals ... unchanged', 'Active Orbitals ... natural')),
        (optimized.replace('ORCA TERMINATED NORMALLY', ''), frozen),
        (optimized.replace('ROOT=0 WEIGHT= 0.500000', 'ROOT=0 WEIGHT= 0.400000'), frozen),
        (optimized.replace('reference.gbw', 'another.gbw'), frozen),
    ]
    for first, second in cases:
        with pytest.raises(ValueError):
            casscf.verified_result(first, second, ref, SPACE, s)


def test_calcjob_runs_two_native_inputs_without_retrieving_full_wavefunctions(common_reference, aiida_manager):
    ref_uuid, remote_uuid, code_uuid, _ = common_reference
    b = casscf.CasscfCalculation.get_builder()
    b.orbital_reference, b.code = orm.load_node(ref_uuid), orm.load_code(code_uuid)
    b.compact_code = b.code
    b.structure = orm.load_node(b.orbital_reference.get_dict()['structure_uuid'])
    b.active_space, b.settings = orm.Dict(dict=SPACE), orm.Dict(dict=objective())
    common_orbitals.attach_orbital(b, artifacts.resolve_electronic(orm.load_node(remote_uuid), names=['aiida.qro']), 'aiida.qro')
    b.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 1}
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            assert info.codes_run_mode == CodeRunMode.SERIAL
            assert [c.cmdline_params for c in info.codes_info] == [['aiida.inp'], ['verify.inp'], ['compact_output.py']]
            assert [c.stdout_name for c in info.codes_info[:2]] == ['native_output/aiida.out', 'native_output/verify.out']
            assert 'aiida.gbw' not in info.retrieve_list and 'verify.out' in info.retrieve_list
    finally:
        process.close()


def test_casscf_reference_is_natural_and_never_a_ks_energy_catalog():
    from aiida_empa_orca.orbital_inspection import variants
    ref = reference_data() | {'preparation': casscf.PREPARATION, 'kind': 'CASSCF', 'filename': 'aiida.gbw'}
    assert variants(ref) == {'CASSCF': 'aiida.gbw'}


def test_open_review_edit_and_submit_are_distinct(monkeypatch):
    from aiidalab_orca import casscf as gui
    calls = []
    monkeypatch.setattr(gui, 'reference_data', lambda _: reference_data())
    monkeypatch.setattr(gui.service, 'history', lambda *a: [])
    def review(uid, space, values, **kwargs):
        calls.append(('review', deepcopy(values)))
        return {'action': 'compute', 'execution': 'orca@test', 'settings': casscf.casscf_settings(values, reference_data(), space),
                'pdos': kwargs['pdos_resources'] | {'ready':True},
                'input': 'native input', 'readback_input': 'readback input'}
    monkeypatch.setattr(gui.service, 'review', review)
    monkeypatch.setattr(gui.service, 'submit', lambda p: calls.append(('submit', p)))
    panel = gui.CasscfOrbitals('ref', SPACE, lambda _: calls.append(('inspect',)))
    try:
        assert calls == [] and panel.submit.disabled
        assert 'Optimize one state: root 0' in panel.intent.value
        assert 'continue with CASCI' in panel.intent.value
        panel.review.click()
        assert len(calls) == 1 and not panel.submit.disabled
        assert 'Then automatic PDOS: 1 process, 2 GiB, up to 10 minutes' in panel.review_text.value
        panel.pdos_wall.value=9
        assert panel.plan is None and panel.submit.disabled
        panel.pdos_wall.value=10
        assert panel.plan is None and panel.submit.disabled
        panel.review.click();panel.pdos_memory.value=3
        assert panel.plan is None and panel.submit.disabled
        panel.pdos_memory.value=2;panel.review.click()
        panel.full_files.mode.value = 'stash'
        assert panel.submit.disabled and panel.plan is None
        panel.full_files.directory.value = '/user/stash'
        panel.review.click()
        assert 'stashed at /user/stash' in panel.review_text.value
        panel.root.value = 1
        assert panel.submit.disabled and panel.plan is None
        assert 'only root 1 drives orbital optimization' in panel.intent.value
        panel.mode.value = 'state_average'
        assert 'Each state retains its own energy' in panel.intent.value
        panel.review.click()
        assert calls[-1][1]['states'][0]['weights'] == [1, 1]
        assert 'Normalized optimization weight' in panel.review_text.value
    finally:
        panel.close()


def test_dyson_goal_offers_shared_casscf_but_not_quantum_state_vectors():
    from aiidalab_orca.energy_view import EnergyRoutes
    calls = []
    panel = EnergyRoutes('ref', {}, SPACE, lambda: calls.append('casci'), lambda: calls.append('quantum'),
                         lambda: calls.append('casscf'), allow_quantum=False)
    try:
        assert 'quantum' not in dict(panel.choice.options).values()
        panel.choice.value = 'casscf'
        assert calls == []
        panel.continue_button.click()
        assert calls == ['casscf']
    finally:
        panel.close()


def test_uncertain_submission_consumes_review_before_contacting_service(monkeypatch):
    from aiidalab_orca import casscf as gui
    monkeypatch.setattr(gui,'reference_data',lambda _:reference_data())
    monkeypatch.setattr(gui.service,'history',lambda *a:[])
    monkeypatch.setattr(gui.service,'review',lambda uid,space,values,**kw:{
        'action':'compute','execution':'test','settings':casscf.casscf_settings(values,reference_data(),space),
        'pdos':kw['pdos_resources']|{'ready':True},'input':'native','readback_input':'readback'})
    calls=[]
    def uncertain(plan):
        calls.append(plan)
        raise RuntimeError('Uncertain response; inspect process history before retrying')
    monkeypatch.setattr(gui.service,'submit',uncertain)
    panel=gui.CasscfOrbitals('ref',SPACE,lambda _:None)
    try:
        panel.review.click();panel.submit.click();panel.submit.click()
        assert len(calls)==1 and panel.plan is None and panel.submit.disabled
        assert 'inspect process history' in panel.message.value
    finally:panel.close()
