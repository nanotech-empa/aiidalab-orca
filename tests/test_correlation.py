"""Reference identity, complete corrections and incompatible-route guards."""
from copy import deepcopy

import pytest

from aiida_empa_orca import casscf, correlation
from test_casci import reference_data
from test_casscf import native_output, objective, SPACE


def reference():
    ref = reference_data()
    return ref | {'kind': 'CASSCF', 'preparation': casscf.PREPARATION,
                  'optimized_active_space': SPACE,
                  'casscf_settings': casscf.casscf_settings(objective(), ref, SPACE)}


def nevpt_text():
    ref = reference()
    native = native_output(ref['casscf_settings'], frozen=True).replace('aiida.gbw', 'reference.gbw')
    native = native.replace('ORCA TERMINATED NORMALLY', '')
    text = ('Program Version 6.1.1\n Number of Electrons NEL .... 15\n' + native +
            '< NEVPT2  >\n Last frozen orbital ... 1\n Orbitals ... canonical for each state\n'
            'NEVPT2 Results\n')
    expected = []
    # Deliberately print the higher-spin block first, and give the scalar
    # final energy an unrelated value: only labelled per-state tables count.
    for mult, root, energy in [(4, 0, -99.), (2, 0, -100.), (2, 1, -99.9)]:
        text += (f'MULT {mult}, ROOT {root}\nTotal Energy Correction : dE = -0.2\n'
                 f'Reference Energy : E0 = {energy}\nTotal Energy (E0+dE) : E = {energy - .2}\n')
        expected.append({'charge': 0, 'multiplicity': mult, 'root': root, 'energy_hartree': energy,
                         'averaging_weight': .5 if (mult, root) == (2, 0) else .25})
    return text + 'FINAL SINGLE POINT ENERGY -999\nORCA TERMINATED NORMALLY\n', {'states': expected}


def mp2_text():
    return '''Program Version 6.1.1
Hartree-Fock type HFTyp .... RHF
Total Charge Charge .... 0
Multiplicity Mult .... 1
Number of Electrons NEL .... 10
SCF CONVERGED AFTER 11 CYCLES
Total Energy : -75.0 Eh
ORCA MP2
Freezing NCore=2 chemical core electrons
RI-MP2 CORRELATION ENERGY: -0.2 Eh
MP2 TOTAL ENERGY: -75.2 Eh
FINAL SINGLE POINT ENERGY -75.2
ORCA TERMINATED NORMALLY
'''


def test_inputs_keep_hf_and_active_space_routes_separate():
    ref = reference()
    mp2 = correlation.correlation_input(ref['settings'], {'method': 'RI-MP2'})
    assert 'UHF' in mp2 and 'RI-MP2' in mp2
    assert all(word not in mp2 for word in ('PBE', 'MOREAD', 'NoIter', '%casscf'))
    nevpt = correlation.correlation_input(ref['settings'], {'method': 'SC-NEVPT2'}, ref)
    assert 'PTMethod SC_NEVPT2' in nevpt and 'CanonStep canonical' in nevpt
    assert 'ActOrbs unchanged' in nevpt and 'maxiter 1' in nevpt
    assert '%moinp "reference.gbw"' in nevpt and 'FrozenCore FC_ELECTRONS' in nevpt
    with pytest.raises(ValueError, match='integral model'):
        correlation.settings({'method': 'SC-NEVPT2', 'auxiliary_basis': 'def2-TZVP/C'},
                             ref['settings'], ref['casscf_settings'])
    with pytest.raises(ValueError):
        correlation.correlation_input(ref['settings'], {'method': 'SC-NEVPT2'})


def test_mp2_reports_reference_correction_and_total_from_fresh_hf():
    electronic = reference_data()['settings'] | {'multiplicity': 1}
    result = correlation.parse_result(mp2_text(), electronic, {'method': 'RI-MP2'}, 10)
    assert result['states'][0]['reference_energy_hartree'] == -75
    assert result['states'][0]['correction_hartree'] == -.2
    assert result['states'][0]['energy_hartree'] == -75.2
    assert result['model']['frozen_core_electrons'] == 2
    assert not result['provides_transition_amplitudes'] and not result['dyson_compatible']


@pytest.mark.parametrize('before,after', [
    ('HFTyp .... RHF', 'HFTyp .... RKS'),
    ('SCF CONVERGED AFTER', 'SCF NOT CONVERGED AFTER'),
    ('Freezing NCore=2', 'Freezing NCore=3'),
    ('-75.2\nORCA', '-75.1\nORCA'),
    ('Total Energy : -75.0', 'Total Energy : -74.9'),
    ('ORCA TERMINATED NORMALLY', 'Segmentation fault\nORCA TERMINATED NORMALLY'),
])
def test_mp2_rejects_wrong_reference_native_failure_and_energy_accounting(before, after):
    with pytest.raises(ValueError):
        correlation.parse_result(mp2_text().replace(before, after),
            reference_data()['settings'] | {'multiplicity': 1}, {'method': 'RI-MP2'}, 10)


def test_nevpt2_preserves_complete_spin_root_families_and_ignores_the_scalar_average():
    text, expected = nevpt_text()
    ref = reference()
    result = correlation.parse_result(text, ref['settings'], {'method': 'SC-NEVPT2'}, 15, ref, expected)
    assert [(r['multiplicity'], r['root']) for r in result['states']] == [(2, 0), (2, 1), (4, 0)]
    assert [r['energy_hartree'] for r in result['states']] == [-100.2, -100.10000000000001, -99.2]
    assert [r['averaging_weight'] for r in result['states']] == [.5, .25, .25]
    assert result['checks']['reference_readback_max_error_hartree'] == 0


@pytest.mark.parametrize('before,after', [
    ('E0 = -100.0', 'E0 = -100.000001'),
    ('MULT 2, ROOT 1\nTotal', 'MULT 2, ROOT 0\nTotal'),
    ('canonical for each state', 'averaged'),
    ('Active Orbitals ... unchanged', 'Active Orbitals ... natural'),
    ('Input Geometry matches current geometry', 'Input Geometry mismatch'),
    ('ORCA TERMINATED NORMALLY', 'poorly normalized MO\nORCA TERMINATED NORMALLY'),
])
def test_nevpt2_rejects_reference_drift_state_loss_hidden_rotation_and_norm_warnings(before, after):
    text, expected = nevpt_text()
    ref = reference()
    with pytest.raises(ValueError):
        correlation.parse_result(text.replace(before, after), ref['settings'],
                                 {'method': 'SC-NEVPT2'}, 15, ref, expected)


def test_core_policy_is_checked_against_the_native_count():
    electronic = reference_data()['settings'] | {'multiplicity': 1}
    with pytest.raises(ValueError, match='policy'):
        correlation.parse_result(mp2_text(), electronic, {'method': 'RI-MP2', 'frozen_core': False}, 10)
    text, expected = nevpt_text()
    ref = reference()
    result = correlation.parse_result(text.replace('frozen orbital ... 1', 'frozen orbital ... -1'),
        ref['settings'], {'method': 'SC-NEVPT2', 'frozen_core': False}, 15, ref, expected)
    assert result['model']['frozen_core_electrons'] == 0
    none_text = text.replace('Last frozen orbital ... 1', 'Orbital Range Operator 0: 0-8 to 9-20')
    result = correlation.parse_result(none_text, ref['settings'],
        {'method': 'SC-NEVPT2', 'frozen_core': False}, 15, ref, expected)
    assert result['model']['frozen_core_electrons'] == 0
    native = mp2_text().replace('Freezing NCore=2 chemical core electrons',
                               'Orbital Range Operator 0: 0-4 to 5-23')
    result = correlation.parse_result(native, electronic, {'method': 'RI-MP2', 'frozen_core': False}, 10)
    assert result['model']['frozen_core_electrons'] == 0
    with pytest.raises(ValueError, match='count'):
        correlation.parse_result(native.replace('0: 0-4', '0: 1-4'), electronic,
                                 {'method': 'RI-MP2', 'frozen_core': False}, 10)


def test_form_gates_nevpt2_and_requires_review_without_implicit_jobs(monkeypatch):
    from aiidalab_orca import correlation as gui
    calls = []
    monkeypatch.setattr(gui.service, 'casscf_sources', lambda _: [])
    monkeypatch.setattr(gui.service, 'history', lambda *a: [])
    monkeypatch.setattr(gui.service, 'defaults', lambda *a: {
        'nprocs': 1, 'memory_mb': 1024, 'wallclock_seconds': 600, 'auxiliary_basis': 'def2-SVP/C'})
    monkeypatch.setattr(gui.service, 'review', lambda source, method, values, force: {
        'action': 'compute', 'method': method, 'execution': 'orca@test', 'settings': deepcopy(values),
        'reference_summary': {'charge': 0, 'multiplicity': 2}, 'input': 'input'})
    monkeypatch.setattr(gui.service, 'submit', lambda p: calls.append(p))
    panel = gui.CorrelationEnergies('entry', lambda: calls.append('prepare'))
    try:
        assert not calls and panel.submit.disabled
        panel.review.click()
        assert not panel.submit.disabled
        panel.frozen.value = False
        assert panel.submit.disabled and panel.plan is None
        panel.method.value = 'SC-NEVPT2'
        assert panel.form.layout.display == 'none' and panel.submit.disabled
        panel.submit.click()
        assert not calls
        panel.prepare.click()
        assert calls == ['prepare']
    finally:
        panel.close()
