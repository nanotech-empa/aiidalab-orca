"""Native family numbering is independent of scientific convergence acceptance."""

from pathlib import Path
import re

import pytest

from aiida_empa_orca import optical
from aiida_empa_orca.protocols import protocol_settings


FIXTURES = Path(__file__).parent / 'fixtures' / 'optical'
FAILED = FIXTURES / 'synthetic-full-triplets-energy-stop.out'
SETTINGS = {'method': 'TDDFT', 'nroots': 3, 'triplets': True, 'nto': False}


def electronic():
    return protocol_settings('pbe-v1', {'basis': 'def2-SVP', 'charge': 0, 'multiplicity': 1})


def rows(text=None):
    return optical._excited_states(text or FAILED.read_text(), SETTINGS, False)


def test_synthetic_energy_stop_still_fails_scientific_validation():
    assert FAILED.read_text().startswith('SYNTHETIC PARSER FIXTURE')
    with pytest.raises(ValueError, match='native residual tolerance'):
        optical.parse_result(FAILED.read_text(), electronic(), SETTINGS,
                             expected_electrons=2, expected_energy=-10.0)


def test_synthetic_solver_audit_distinguishes_energy_and_residual_convergence():
    solves = re.split(r'Number of roots to be determined\s*\.{2,}\s*', FAILED.read_text())[1:]
    assert len(solves) == 2
    for solve in solves:
        for criterion in ('residual', 'energies'):
            tolerance = re.search(r'Convergence tolerance for the ' + criterion +
                                  r'\s*\.{2,}\s*(' + optical.NUMBER + ')', solve)
            assert float(tolerance[1]) == 1e-6
    residuals = [re.findall(r'Maximum residual norm\s*:\s*(' + optical.NUMBER + ')', s)
                 for s in solves]
    assert float(residuals[0][-1]) == pytest.approx(1e-8)
    assert float(residuals[1][-1]) == pytest.approx(3e-6)
    assert 'CONVERGENCE OF RESIDUAL NORM REACHED' in solves[0]
    assert 'CONVERGENCE OF RESIDUAL NORM REACHED' not in solves[1]
    assert 'CONVERGENCE OF ENERGIES REACHED' in solves[1]
    final_iteration = solves[1].split('****Iteration 1****')[1]
    assert 'Maximum residual norm' not in final_iteration


def test_synthetic_full_tddft_rows_keep_family_local_roots_and_spin_identity():
    # Inspect only native table syntax. This helper cannot certify convergence.
    states = rows()
    assert set(states) == {f'{family}:{root}' for family in ('singlet', 'triplet')
                           for root in (1, 2, 3)}
    energies = {'singlet': [.11, .21, .31],
                'triplet': [.12, .22, .32]}
    for family, spin in [('singlet', 0), ('triplet', 2)]:
        for root in (1, 2, 3):
            state = states[f'{family}:{root}']
            assert (state['id'], state['family'], state['root'], state['native_state_index']) == (
                f'{family}:{root}', family, root, root)
            assert state['spin_squared'] == spin
            assert state['excitation_hartree'] == energies[family][root-1]
            assert state['nto'] is None
            with pytest.raises(ValueError, match='No qualified NTO'):
                optical.nto_selection({'states': list(states.values())},
                                      {'state_id': state['id'], 'pairs': [1]})


def test_global_tda_numbering_retains_native_indices_and_singlet_ntos():
    text = (FIXTURES / 'pyridine-triplets.out').read_text()
    data = optical.parse_result(text, electronic(), {'triplets': True, 'nto_states': [1, 2, 3]},
                                expected_electrons=42)
    states = {state['id']: state for state in data['states']}
    for root in range(1, 6):
        triplet = states[f'triplet:{root}']
        assert triplet['root'] == root
        assert triplet['native_state_index'] == root + 5
        assert triplet['spin_squared'] == 2
        assert triplet['multiplicity'] == 3
        assert triplet['oscillator_strength'] == 0
        assert triplet['nto'] is None
        singlet = states[f'singlet:{root}']
        assert singlet['native_state_index'] == root
        assert singlet['multiplicity'] == 1
        if root <= 3:
            assert singlet['nto']['filename'] == f'aiida.s{root}.nto'


def test_local_listing_numbers_still_match_spectrum_families_and_singlet_ntos():
    text = (FIXTURES / 'pyridine-triplets.out').read_text()
    values = {'triplets': True, 'nto_states': [1, 2, 3]}
    expected = optical.parse_result(text, electronic(), values, expected_electrons=42)
    prefix, block = text.split('TD-DFT/TDA EXCITED STATES (TRIPLETS)', 1)
    # Synthetic syntax variant only: no energies, residuals, spins or NTOs change.
    block = re.sub(r'^STATE\s+(\d+):',
                   lambda m: f'STATE  {int(m[1])-5}:', block, flags=re.M)
    local = prefix + 'TD-DFT/TDA EXCITED STATES (TRIPLETS)' + block
    actual = optical.parse_result(local, electronic(), values, expected_electrons=42)
    for state in expected['states']:
        if state['family'] == 'triplet':
            state['native_state_index'] -= 5
    assert actual == expected


@pytest.mark.parametrize('old,new', [
    ('STATE 1:', 'STATE 0:'),
    ('STATE 3:', 'STATE 2:'),
    ('STATE 3:', 'STATE 6:'),
    ('STATE 3:', 'REMOVED 3:'),
])
def test_mixed_duplicate_zero_and_missing_native_roots_are_rejected(old, new):
    prefix, block = FAILED.read_text().split('TD-DFT EXCITED STATES (TRIPLETS)', 1)
    damaged = prefix + 'TD-DFT EXCITED STATES (TRIPLETS)' + block.replace(old, new, 1)
    with pytest.raises(ValueError, match='identity|numbering'):
        rows(damaged)


def test_family_numbering_cannot_enable_triplet_nto_requests():
    with pytest.raises(ValueError, match='Triplet NTO generation is not qualified'):
        optical.settings(SETTINGS | {'nto': True, 'nto_family': 'triplet'}, electronic())
