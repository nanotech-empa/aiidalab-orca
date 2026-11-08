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
    text = ('Program Version 6.1.1\n Number of Electrons NEL .... 15\nPT2 = SC-NEVPT2\n' + native +
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


def dlpno_text():
    text, expected = nevpt_text()
    text = '| 3> ! def2-SVP def2-SVP/C MOREAD NoIter NormalPNO\n' + text.replace(
        'PT2 = SC-NEVPT2', 'PT2 = DLPNO-NEVPT2')
    block = '''DLPNO-NEVPT2 SETTINGS
TCutPNO: 1.000e-08
TCutDO: 1.000e-02
TCutMKN: 1.000e-03
Energy convergence tolerance ... 1.000e-07
Residual convergence tolerance ... 5.000e-07
LMP2-Iter= 0: ELMP2= -0.2 DE= -3.5e-03 RMAX= 3.4e-03
LMP2-Iter= 1: ELMP2= -0.2 DE= 6.9e-10 RMAX= 5.3e-08 => CONVERGED
DLPNO-NEVPT2 Results
'''
    return text.replace('NEVPT2 Results\n', block * 3 + 'NEVPT2 Results\n'), expected


@pytest.mark.parametrize('method', correlation.NEVPT_METHODS)
def test_contractions_have_explicit_native_identity_and_keep_energy_only_results(method):
    text, expected = dlpno_text() if method == 'DLPNO-NEVPT2' else nevpt_text()
    text = text.replace('PT2 = SC-NEVPT2', 'PT2 = ' + method)
    ref = reference()
    values = {'method': method}
    data = correlation.parse_result(text, ref['settings'], values, 15, ref, expected)
    assert data['method'] == method and not data['dyson_compatible']
    assert data['model']['local_approximation'] == (method == 'DLPNO-NEVPT2')
    native = correlation.correlation_input(ref['settings'], values, ref)
    assert ('CanonStep canonical' in native) == (method == 'SC-NEVPT2')
    assert ('NormalPNO' in native) == (method == 'DLPNO-NEVPT2')
    with pytest.raises(ValueError, match='native perturbation method'):
        correlation.parse_result(text.replace('PT2 = ' + method, 'PT2 = unsupported'),
                                 ref['settings'], values, 15, ref, expected)


@pytest.mark.parametrize('before,after', [
    ('=> CONVERGED', ''),
    ('RMAX= 5.3e-08', 'RMAX= 5.3e-04'),
    ('DE= 6.9e-10', 'DE= 6.9e-05'),
    ('NormalPNO', 'TightPNO'),
    ('TCutPNO: 1.000e-08', 'TCutPNO: 0'),
    ('Residual convergence tolerance ... 5.000e-07', 'Residual convergence tolerance ... 0'),
    ('DLPNO-NEVPT2 Results', 'Missing class summary'),
])
def test_dlpno_checks_every_amplitude_solve_and_preserves_preset_evidence(before, after):
    text, expected = dlpno_text()
    ref = reference()
    with pytest.raises(ValueError):
        correlation.parse_result(text.replace(before, after, 1), ref['settings'],
                                 {'method': 'DLPNO-NEVPT2'}, 15, ref, expected)


@pytest.mark.parametrize('warning', [
    'WARNING: Koopmans matrices have at least one negative eigenvalue (-2.026741e-01)',
    'WARNING: Denominator is negative for DEpsilon ITUV i=2 mu=1 : -344.1 < 0',
])
def test_native_normal_termination_does_not_hide_intruder_state_warnings(warning):
    text, expected = nevpt_text()
    ref = reference()
    with pytest.raises(ValueError, match='intruder-state'):
        correlation.parse_result(text.replace('NEVPT2 Results', warning + '\nNEVPT2 Results'),
            ref['settings'], {'method': 'SC-NEVPT2'}, 15, ref, expected)


def test_pno_presets_do_not_leak_into_other_methods():
    ref = reference()
    for method in ('RI-MP2', 'SC-NEVPT2', 'FIC-NEVPT2'):
        with pytest.raises(ValueError, match='Unknown'):
            correlation.settings({'method': method, 'pno_preset': 'TightPNO'},
                                 ref['settings'], ref['casscf_settings'])
    with pytest.raises(ValueError, match='NormalPNO or TightPNO'):
        correlation.settings({'method': 'DLPNO-NEVPT2', 'pno_preset': 'LoosePNO'},
                             ref['settings'], ref['casscf_settings'])


def caspt2_text():
    text, expected = nevpt_text()
    text = text.replace('PT2 = SC-NEVPT2', 'PT2 = CASPT2').replace('< NEVPT2  >', '< CASPT2  >')
    text = text.replace('NEVPT2 Results', 'CASPT2 Results')
    text = text.replace('Total Energy (E0+dE)', 'Reference Weight : W0 = 0.9\nTotal Energy (E0+dE)')
    echo = '| 23> CASPT2_ishift 0.0\n| 24> CASPT2_rshift 0.0\n| 25> CASPT2_IPEAshift 0.0\n'
    shifts = 'CASPT2 Real Levelshift ... 0.00e+00\nCASPT2 Im. Levelshift ... 0.00e+00\nCASPT2 IPEA Levelshift ... 0.00e+00\n'
    solvers = ''
    for row in expected['states']:
        solvers += f'MULT {row["multiplicity"]}, ROOT {row["root"]}\n'
        for kind in ['IJAB', 'ITAB', 'IJTA', 'TUAB', 'IJTU', 'ITAU', 'TUVA', 'ITUV']:
            solvers += f'smallest energy denominator {kind} = 0.237441258\n'
        solvers += '''CASPT2-D Energy = -999.0
Iter EPT2 EHylleraas residual norm Time
1 -0.2 -0.2 0.03 0.0
2 -0.2 -0.2 0.00000288 0.0
CASPT2 calculation converged in 2 iterations
'''
    text = echo + text.replace('< CASPT2  >', '< CASPT2  >\n' + shifts)
    return text.replace('CASPT2 Results', solvers + 'CASPT2 Results'), expected


def test_caspt2_preserves_diagnostics_and_does_not_use_the_diagonal_energy():
    text, expected = caspt2_text()
    ref = reference()
    data = correlation.parse_result(text, ref['settings'], {'method': 'CASPT2'}, 15, ref, expected)
    assert len(data['states']) == 3 and data['checks']['caspt2_states_converged'] == 3
    assert data['states'][0]['energy_hartree'] == -100.2
    assert data['states'][0]['reference_weight'] == .9
    assert data['states'][0]['caspt2_iterations'] == 2
    assert data['states'][0]['final_residual_norm'] == 2.88e-6
    assert data['model']['shifts_hartree'] == {key: 0. for key in correlation.CASPT2_SHIFTS}
    assert not data['dyson_compatible'] and not data['provides_transition_amplitudes']
    native = correlation.correlation_input(ref['settings'], {'method': 'CASPT2'}, ref)
    assert 'PTMethod FIC_CASPT2' in native and 'CanonStep' not in native
    assert all(name + ' 0.0' in native for name in correlation.CASPT2_SHIFTS.values())


@pytest.mark.parametrize('before,after', [
    ('CASPT2 calculation converged in 2 iterations', 'CASPT2 did not converge'),
    ('2 -0.2 -0.2 0.00000288 0.0', '2 -0.2 -0.2 nan 0.0'),
    ('2 -0.2 -0.2 0.00000288 0.0', '2 -0.2 -0.2 -1 0.0'),
    ('smallest energy denominator ITUV = 0.237441258', 'smallest energy denominator ITUV = -0.2'),
    ('Reference Weight : W0 = 0.9', 'Reference Weight : W0 = 1.1'),
    ('Reference Weight : W0 = 0.9', 'missing reference weight'),
    ('CASPT2 Real Levelshift ... 0.00e+00', 'CASPT2 Real Levelshift ... 1.00e-01'),
    ('PT2 = CASPT2', 'PT2 = CASPT2-K'),
])
def test_caspt2_rejects_native_success_without_complete_consistent_diagnostics(before, after):
    text, expected = caspt2_text()
    ref = reference()
    with pytest.raises(ValueError):
        correlation.parse_result(text.replace(before, after, 1), ref['settings'],
                                 {'method': 'CASPT2'}, 15, ref, expected)


def test_caspt2_checks_exact_shift_input_and_native_print_rounding():
    text, expected = caspt2_text()
    ref = reference()
    changed = text.replace('CASPT2_ishift 0.0', 'CASPT2_ishift 0.123456').replace(
        'CASPT2 Im. Levelshift ... 0.00e+00', 'CASPT2 Im. Levelshift ... 1.23e-01')
    data = correlation.parse_result(changed, ref['settings'],
        {'method': 'CASPT2', 'imaginary_shift_hartree': .123456}, 15, ref, expected)
    assert data['model']['shifts_hartree']['imaginary_shift_hartree'] == .123456
    with pytest.raises(ValueError, match='shift input'):
        correlation.parse_result(changed, ref['settings'], {'method': 'CASPT2'}, 15, ref, expected)


@pytest.mark.parametrize('value', [-.1, float('nan'), float('inf'), True, '0.1'])
def test_caspt2_shift_validation_rejects_invalid_inputs(value):
    ref = reference()
    with pytest.raises(ValueError, match='finite nonnegative'):
        correlation.settings({'method': 'CASPT2', 'imaginary_shift_hartree': value},
                             ref['settings'], ref['casscf_settings'])


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
        panel.nevpt.value = 'DLPNO-NEVPT2'
        assert panel.pno.layout.display == '' and panel.submit.disabled
        panel.pno.value = 'TightPNO'
        assert panel._values()['pno_preset'] == 'TightPNO'
        panel.nevpt.value = 'FIC-NEVPT2'
        assert panel.pno.layout.display == 'none'
        assert 'pno_preset' not in panel._values()
        panel.nevpt.value = 'CASPT2'
        assert panel.caspt2_settings.layout.display == ''
        assert panel._values()['ipea_shift_hartree'] == 0
        panel.imaginary_shift.value = .1
        assert panel.plan is None and panel.submit.disabled
        assert panel._values()['imaginary_shift_hartree'] == .1
        panel.nevpt.value = 'SC-NEVPT2'
        assert panel.caspt2_settings.layout.display == 'none'
        assert 'imaginary_shift_hartree' not in panel._values()
        panel.prepare.click()
        assert calls == ['prepare']
    finally:
        panel.close()
