"""Exchange checked against explicit spin-flip Fock-space matrix elements."""
from copy import deepcopy
import math
import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io.cube import write_cube
from ase.units import Bohr

from aiida_empa_orca.kondo_data import exchange
from aiida_empa_orca.maps_data import compute_maps, map_parameters
from test_dyson import act, lower, vector, projections


def table():
    def row(name, side, coefficients, mult=1):
        return dict(id=name, side=side, final_multiplicity=mult, final_charge=1 if side == 'removal' else -1,
                    final_state_uuid=name, final_root=0, energy_ev=-2. if side == 'removal' else 3.,
                    active_coefficients=coefficients, active_indices=[0], strength=sum(x*x for x in coefficients))
    return dict(initial_state_uuid='initial', orbital_reference_uuid='common',
                initial_state=dict(multiplicity=2, charge=0), active_space=dict(electrons=1, orbitals=[0]),
                strength_convention='highest_ms_component',
                transitions=[row('rem', 'removal', [1.]), row('add', 'addition', [1.])])


def test_single_level_anderson_limit_and_explicit_mu_sign():
    data = exchange(table(), {})
    assert data['exchange_over_v2_inv_ev'][0][0] == pytest.approx(2/2+2/3)
    assert exchange(table(), {'chemical_potential_ev': 1.})['exchange_over_v2_inv_ev'][0][0] == pytest.approx(2/1+2/4)
    ph = table()
    ph['transitions'][1]['energy_ev'] = 2.
    assert exchange(ph, {})['channels'][0]['exchange_over_v2_inv_ev'] == pytest.approx(8/4)  # 8/U, U=4.
    assert data['stability_interval_ev'] == [-3., 2.]


@pytest.mark.parametrize('initial,mi,final,mf,create', [
    ({'u0':1.},2,{'20':1.},1,True),
    ({'u0':1.},2,{'uu':1.},3,True),
    ({'2u':1.},2,{'uu':1.},3,False),
    ({'2u':1.},2,{'ud':2**-.5,'du':-2**-.5},1,False),
    ({'uu':1.},3,{'u0':1.},2,False),
    ({'uu':1.},3,{'2u':1.},2,True),
    ({'uu0':1.},3,{'uuu':1.},4,True),
    ({'2uu':1.},3,{'uuu':1.},4,False),
])
def test_exchange_spin_factor_against_independent_virtual_spin_flip(initial, mi, final, mf, create):
    iv, fv = ({vector(k):v for k,v in values.items()} for values in (initial, final))
    spin = (mi-1)/2
    low = lower(iv)
    intermediate = projections(fv, mf)[0 if mf < mi else 1]
    norb = len(next(iter(iv)))//2
    def dot(a, b):
        return sum(c*b.get(bits, 0.) for bits,c in a.items())
    component_spin = (0 if mf > mi else 1) if create else (0 if mf < mi else 1)
    d = np.array([dot(act(iv, 2*i+component_spin, create), fv) for i in range(norb)])
    first = np.array([dot(act(iv, 2*i+(1 if create else 0), create), intermediate) for i in range(norb)])
    second = np.array([dot(act(intermediate, 2*i+(0 if create else 1), not create), low) for i in range(norb)])
    exact = (-1 if create else 1) * 2/math.sqrt(2*spin) * np.outer(second, first)
    factor = 1/spin if mf < mi else -1/(spin+.5)
    assert np.linalg.norm(d) > 0
    assert np.allclose(exact, factor*np.outer(d, d), atol=1e-14)


@pytest.mark.parametrize('mutation', ['singlet', 'nonpositive_gap', 'one_charge_only', 'spin_forbidden', 'weighted', 'norm'])
def test_invalid_physical_inputs_fail(mutation):
    t = table()
    if mutation == 'singlet':t['initial_state']['multiplicity'] = 1
    if mutation == 'nonpositive_gap':t['transitions'][0]['energy_ev'] = .1
    if mutation == 'one_charge_only':t['transitions'].pop()
    if mutation == 'spin_forbidden':t['transitions'][0]['final_multiplicity'] = 4
    if mutation == 'weighted':t['strength_convention'] = 'unpolarized'
    if mutation == 'norm':t['transitions'][0]['strength'] = .5
    with pytest.raises(ValueError):exchange(t, {})


def test_basis_rotation_covariance_and_ferromagnetic_channel():
    t = table()
    t['active_space']['orbitals'] = [0, 1]
    for row in t['transitions']:
        row['active_indices'] = [0, 1]
        row['active_coefficients'] = [1., 0.]
    high = deepcopy(t['transitions'][1])
    high.update(id='triplet', final_multiplicity=3, active_coefficients=[0., 1.])
    t['transitions'].append(high)
    result = exchange(t, {})
    assert [r['coupling'] for r in result['channels']] == ['AFM', 'FM']
    angle = .37
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    for row in t['transitions']:
        row['active_coefficients'] = (rotation @ row['active_coefficients']).tolist()
    changed = exchange(t, {})
    assert np.allclose(changed['exchange_over_v2_inv_ev'], rotation @ result['exchange_over_v2_inv_ev'] @ rotation.T)
    assert np.allclose([r['exchange_over_v2_inv_ev'] for r in changed['channels']],
                       [r['exchange_over_v2_inv_ev'] for r in result['channels']])


def test_published_rounded_etri_reduced_amplitudes_follow_equation_8():
    fixture = json.loads((Path(__file__).parent/'fixtures/kondo/etri-tabulated.json').read_text())
    t = table()
    t['initial_state']['multiplicity'] = 3
    t['active_space'] = dict(electrons=6, orbitals=list(range(6)))
    t['transitions'] = []
    expected = np.zeros((6,6))
    for i, multiplet in enumerate(fixture['multiplets']):
        reduced = np.array(multiplet['reduced_amplitudes'])
        addition = multiplet['side'] == 'addition'
        # Eq. 8 in reduced-matrix-element convention, S0=1, Sc=1/2.
        expected += np.outer(reduced, reduced) / multiplet['printed_cost_ev'] / (1.5 if addition else 1.)
        component = reduced * (np.sqrt(2/3) if addition else 1.)
        t['transitions'].append(dict(id=multiplet['id'], side=multiplet['side'], final_root=i,
            final_state_uuid=multiplet['id'], final_charge=-1 if addition else 1, final_multiplicity=2,
            energy_ev=multiplet['printed_cost_ev']*(1 if addition else -1),
            active_coefficients=component.tolist(), active_indices=list(range(6)), strength=float(component @ component)))
    result = exchange(t, {'chemical_potential_ev':0.})  # Printed costs already include reported mu.
    assert np.allclose(result['exchange_over_v2_inv_ev'], expected, atol=1e-14)
    assert sum(r['coupling'] == 'AFM' for r in result['channels']) == 4


def test_channel_maps_are_squared_normalized_amplitudes_without_exchange_or_spin_weights(tmp_path):
    path = tmp_path/'ko.cube'
    with path.open('w') as handle:
        write_cube(handle, Atoms('H', positions=[[0,0,0]], cell=[8,8,8]),
                   data=np.full((12,12,12), .4), origin=[-3,-4,-2])
    from test_maps import parameters
    p = parameters()
    p.pop('transition_ids');p.pop('spin_convention')
    p['channel_ids'] = ['ko_1']
    k = exchange(table(), {})
    a, metadata = compute_maps({'ko_1':path}, k, p)
    assert np.allclose(a['intensity'][0], .16/Bohr**3, rtol=2e-6)
    assert metadata['sources'][0]['intensity_multiplier'] == 1
    assert metadata['observable'] == 'kondo_channel_intensity'
    assert 'NRG' in metadata['model']
    with pytest.raises(ValueError):map_parameters(p | {'spin_convention':'unpolarized'})
    with pytest.raises(ValueError):map_parameters(p | {'kind':'blend'})


def test_reopening_channels_selects_the_first_stored_cube(monkeypatch):
    from aiidalab_orca import kondo as ui
    data = exchange(table(), {})
    monkeypatch.setattr(ui.service, 'history', lambda _: [('Stored channels', 'run')])
    monkeypatch.setattr(ui.service, 'progress', lambda _: dict(finished=True, success=True))
    monkeypatch.setattr(ui.service, 'result', lambda _: dict(channels_uuid='channels', data=data))
    monkeypatch.setattr(ui.service, 'cube_history', lambda _: [('Stored cubes', 'cubes')])
    monkeypatch.setattr(ui, 'property_result', lambda _: dict(finished=True, successful=True,
        manifest=dict(cubes=[dict(filename='kondo_ko_1.cube')])))
    selected = []
    monkeypatch.setattr(ui.KondoChannels, '_show_cube', lambda self, _=None: selected.append(self.cube.value))
    widget = ui.KondoChannels('table', 'tools', 'cubehandler')
    assert widget.cube.value == 'kondo_ko_1.cube'
    assert selected == ['kondo_ko_1.cube']
    widget.close()
