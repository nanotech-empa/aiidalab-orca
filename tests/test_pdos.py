"""Independent sum rules, directional covariance and molecular DOS conventions."""
import numpy as np
import pytest

from aiida_empa_orca.scripts.orbital_character import character
from aiidalab_orca.pdos_data import gaussian_dos, molecular_normal, p_perpendicular


def model(overlap=None, *, uks=False):
    s = np.eye(4) if overlap is None else overlap
    vals, vecs = np.linalg.eigh(s)
    coefficients = (vecs / np.sqrt(vals)) @ vecs.T
    occupations = [1, 1, 1, 0, 1, 1, 0, 0] if uks else [2, 2, 0, 0]
    return {'Molecule': {'Charge': 1 if uks else 2, 'Multiplicity': 2 if uks else 1,
        'HFTyp': 'UHF' if uks else 'RHF', 'CoordinateUnits': 'Angs', 'S-Matrix': s.tolist(),
        'Atoms': [{'Idx': 0, 'ElementLabel': 'C', 'ElementNumber': 6, 'NuclearCharge': 6,
                   'Coords': [0., 0., 0.]}],
        'MolecularOrbitals': {'EnergyUnit': 'Eh', 'OrbitalLabels': ['0C   1s', '0C   1px', '0C   1py', '0C   1pz'],
            'MOs': [{'Occupancy': o, 'OrbitalEnergy': (i % 4) * .1,
                     'MOCoefficients': coefficients[:, i % 4].tolist()} for i, o in enumerate(occupations)]}}}


def test_symmetric_lowdin_recovers_orthogonal_reference_with_nonorthogonal_AOs():
    overlap = np.array([[1., .2, .05, 0], [.2, 1., 0, .1], [.05, 0, 1., .15], [0, .1, .15, 1.]])
    meta, arrays = character(model(overlap))
    assert meta['orthonormality_errors'][0] < 1e-13
    np.testing.assert_allclose(arrays['weights'].sum(axis=(1, 2)), 1., atol=1e-13)
    np.testing.assert_allclose(arrays['weights'][:, 0, :2], [[1, 0], [0, 1], [0, 1], [0, 1]], atol=1e-13)


def test_p_tensor_preserves_directional_cross_terms_and_rotation_covariance():
    _, arrays = character(model())
    vector = np.array([1., 2., 3.]) / np.sqrt(14)
    arrays['p_tensor'][1, 0] = np.outer(vector, vector)
    normal = np.array([.2, .3, .4])
    first = p_perpendicular(arrays, [0], normal)[1]
    expected = float((vector @ (normal / np.linalg.norm(normal)))**2)
    assert first == pytest.approx(expected)
    rotation = np.array([[0., 0., 1.], [1., 0., 0.], [0., 1., 0.]])
    arrays['p_tensor'][1, 0] = rotation @ arrays['p_tensor'][1, 0] @ rotation.T
    assert p_perpendicular(arrays, [0], rotation @ normal)[1] == pytest.approx(first)


def test_native_spin_channels_and_electron_counts_stay_separate():
    data = model(uks=True)
    data['Molecule']['MolecularOrbitals']['OrbitalLabels'] *= 2
    meta, arrays = character(data)
    assert meta['channels'] == ['alpha', 'beta']
    assert arrays['occupations'][arrays['spin'] == 0].sum() == 3
    assert arrays['occupations'][arrays['spin'] == 1].sum() == 2
    np.testing.assert_array_equal(arrays['indices'], [0, 1, 2, 3, 0, 1, 2, 3])


def test_UNO_retains_fractional_occupations_without_a_fake_energy_axis():
    data = model()
    for row, occ in zip(data['Molecule']['MolecularOrbitals']['MOs'], [1.9, 1.1, .8, .2]):
        row['Occupancy'] = occ
    meta, arrays = character(data, 'UNO')
    assert meta['energy_meaning'] == 'none'
    assert 'energies_ev' not in arrays
    assert arrays['occupations'][2] == .8


def test_QRO_energies_are_explicitly_reference_labels():
    meta, _ = character(model(), 'QRO')
    assert meta['energy_meaning'] == 'QRO_reference_labels'


@pytest.mark.parametrize('change', ['norm', 'overlap', 'population', 'labels', 'spin_count'])
def test_invalid_native_export_cannot_produce_character(change):
    data = model(uks=change == 'spin_count')
    m = data['Molecule']
    if change == 'norm':
        m['MolecularOrbitals']['MOs'][0]['MOCoefficients'][0] = 1.1
    elif change == 'overlap':
        m['S-Matrix'][0][0] = -1
    elif change == 'population':
        m['MolecularOrbitals']['MOs'][0]['Occupancy'] = 1
    elif change == 'labels':
        m['MolecularOrbitals']['OrbitalLabels'][1] = '0C 1p+1'
    else:
        m['MolecularOrbitals']['MOs'][0]['Occupancy'] = 0
    with pytest.raises(ValueError):
        character(data)


def test_DOS_counts_virtual_states_and_preserves_integrated_weight():
    grid = np.linspace(-5., 5., 12001)
    total = gaussian_dos([-1., 1.], [1., 1.], grid, .2)
    assert np.trapezoid(total, grid) == pytest.approx(2., abs=1e-10)
    assert total[np.argmin(abs(grid + 1))] == pytest.approx(total[np.argmin(abs(grid - 1))])


def test_DOS_retains_tails_of_states_outside_the_visible_window():
    grid = np.linspace(0., 1., 100)
    assert gaussian_dos([-.1], [1.], grid, .5)[0] > 1.


def test_zero_normal_rejected_and_linear_geometry_is_not_given_a_unique_plane():
    _, arrays = character(model())
    with pytest.raises(ValueError, match='nonzero'):
        p_perpendicular(arrays, [0], [0, 0, 0])
    _, note = molecular_normal([[0, 0, 0], [0, 0, 1]])
    assert 'No unique plane' in note


def test_molecular_plane_normal_follows_a_tilted_plane():
    points = np.array([[0., 0., 0.], [1., 0., 1.], [0., 1., 1.], [1., 1., 2.]])
    normal, _ = molecular_normal(points)
    assert abs(normal @ np.array([1., 0., 1.])) < 1e-14
    assert abs(normal @ np.array([0., 1., 1.])) < 1e-14
