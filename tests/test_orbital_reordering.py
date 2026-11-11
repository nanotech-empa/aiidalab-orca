"""Synthetic signed-coefficient and partition regressions; no native jobs."""

from copy import deepcopy

import numpy as np
import pytest

from aiida_empa_orca import orbital_reordering as reorder

SOURCE = '11111111-1111-4111-8111-111111111111'
SHA = 'a'*64


@pytest.fixture
def spatial_source():
    # Invented seven-dimensional basis, not molecular calculation output.
    rng = np.random.default_rng(37)
    x = rng.normal(size=(7, 7))
    s = x.T @ x + np.eye(7)
    values, vectors = np.linalg.eigh(s)
    q, _ = np.linalg.qr(rng.normal(size=(7, 7)))
    c = (vectors / np.sqrt(values)) @ vectors.T @ q
    occ = [2, 2, 2, 1, 0, 0, 0]
    ref = {'kind': 'QRO', 'n_electrons': 7, 'n_orbitals': 7, 'charge': 0,
           'source_multiplicity': 2, 'structure_uuid': 'synthetic-geometry'}
    document = {'ORCA Header': {'Version': 'synthetic'}, 'Citations': [
        {'RN001': {'Authors': ['Invented Author'], 'Title': 'Synthetic citation one'}},
        {'RN002': {'Authors': ['Another Invented Author'], 'Title': 'Synthetic citation two'}}],
        'Molecule': {
        'Atoms': [{'ElementNumber': 7, 'NuclearCharge': 7, 'Coords': [0, 0, 0],
                   'ElementLabel': 'N', 'Idx': 0, 'BasisAuxJ': [],
                   'Basis': [{'Shell': 's', 'Exponents': [1], 'Coefficients': [1]}]}],
        'BaseName': 'synthetic', 'HFTyp': 'ROHF', 'PointGroup': 'C1',
        'CoordinateUnits': 'Angs', 'Origin': [0, 0, 0],
        'Charge': 0, 'Multiplicity': 2, 'S-Matrix': s.tolist(),
        'MolecularOrbitals': {'EnergyUnit': 'Eh', 'OrbitalLabels': list(range(7)),
            'MOs': [{'MOCoefficients': c[:, i].tolist(), 'Occupancy': occ[i],
                     'OrbitalEnergy': float(i-3), 'OrbitalSymLabel': 'A',
                     'OrbitalSymmetry': 0} for i in range(7)]}}}
    return ref, document


def plan_for(ref, doc, indices=(1, 3, 5), electrons=3):
    occ = [r['Occupancy'] for r in doc['Molecule']['MolecularOrbitals']['MOs']]
    return reorder.selection_plan(ref, {'electrons': electrons, 'orbitals': list(indices)}, occ,
        source_reference_uuid=SOURCE, source_file_sha256=SHA)


def test_noncontiguous_partition_and_whole_signed_overlap(spatial_source):
    ref, source = spatial_source
    original = deepcopy(source)
    plan = plan_for(ref, source)
    assert plan['native_to_source'] == [0, 2, 1, 3, 5, 4, 6]
    assert plan['inactive_source_indices'] == [0, 2]
    assert plan['external_source_indices'] == [4, 6]
    assert plan['native_active_space'] == {'electrons': 3, 'orbitals': [2, 3, 4]}
    assert [plan['source_to_native'][i] for i in plan['native_to_source']] == list(range(7))
    prepared = reorder.permute_document(source, ref, plan)
    prepared['Molecule']['BaseName'] = 'synthetic-copy'
    check = reorder.verify_roundtrip(source, prepared, ref, plan)
    assert check['full_signed_overlap_error'] < 1e-12
    assert check['occupation_weighted_density_error'] == 0
    assert check['array_checks_passed'] is True
    assert check['native_readback_qualified'] is False
    assert source == original
    assert prepared['Citations'] == source['Citations']
    assert prepared['Citations'] is not source['Citations']
    # Independent direct equality includes every column's sign and its row data.
    for native, index in enumerate(plan['native_to_source']):
        assert prepared['Molecule']['MolecularOrbitals']['MOs'][native] == source['Molecule']['MolecularOrbitals']['MOs'][index]


@pytest.mark.parametrize('change', ['missing', 'modified', 'malformed'])
def test_native_citations_are_preserved_through_roundtrip(spatial_source, change):
    ref, doc = spatial_source
    assert set(doc) == {'ORCA Header', 'Citations', 'Molecule'}
    assert set(doc['Molecule']) == {'Atoms', 'BaseName', 'MolecularOrbitals',
        'CoordinateUnits', 'Multiplicity', 'Charge', 'HFTyp', 'PointGroup', 'Origin', 'S-Matrix'}
    plan = plan_for(ref, doc)
    actual = reorder.permute_document(doc, ref, plan)
    if change == 'missing': actual.pop('Citations')
    if change == 'modified': actual['Citations'][0]['RN001']['Title'] = 'Changed title'
    if change == 'malformed': actual['Citations'] = 'not bibliography records'
    with pytest.raises(ValueError, match='Citations'):
        reorder.verify_roundtrip(doc, actual, ref, plan)


def test_older_export_without_citations_remains_valid(spatial_source):
    ref, doc = deepcopy(spatial_source)
    doc.pop('Citations')
    plan = plan_for(ref, doc)
    actual = reorder.permute_document(doc, ref, plan)
    assert 'Citations' not in actual
    assert reorder.verify_roundtrip(doc, actual, ref, plan)['array_checks_passed']


@pytest.mark.parametrize('level', ['document', 'molecule', 'orbitals'])
def test_bibliography_support_does_not_allow_unknown_scientific_arrays(spatial_source, level):
    ref, doc = deepcopy(spatial_source)
    plan = plan_for(ref, doc)
    target = {'document': doc, 'molecule': doc['Molecule'],
              'orbitals': doc['Molecule']['MolecularOrbitals']}[level]
    target['Unknown-MO-Density'] = [[1, 0], [0, 1]]
    with pytest.raises(ValueError):
        reorder.permute_document(doc, ref, plan)


def test_exact_allyl_pilot_and_contiguous_identity():
    ref = {'kind': 'QRO', 'n_electrons': 23, 'n_orbitals': 67, 'charge': 0,
           'source_multiplicity': 2}
    occ = [2]*11 + [1] + [0]*55
    def make(indices):
        return reorder.selection_plan(ref, {'electrons': 3, 'orbitals': indices}, occ,
            source_reference_uuid=SOURCE, source_file_sha256=SHA)
    contiguous = make([10, 11, 12])
    assert not contiguous['permutation_needed']
    assert contiguous['native_to_source'] == list(range(67))
    pilot = make([9, 11, 13])
    assert pilot['inactive_source_indices'] == list(range(9))+[10]
    assert pilot['external_source_indices'] == [12]+list(range(14, 67))
    assert pilot['native_to_source'][10:13] == [9, 11, 13]
    assert pilot['native_active_space'] == {'electrons': 3, 'orbitals': [10, 11, 12]}
    assert pilot['plan_sha256'] != contiguous['plan_sha256']


def test_restricted_formaldehyde_pi_pilot():
    ref = {'kind': 'restricted', 'n_electrons': 16, 'n_orbitals': 38,
           'charge': 0, 'source_multiplicity': 1}
    plan = reorder.selection_plan(ref, {'electrons': 2, 'orbitals': [6, 8]}, [2]*8+[0]*30,
        source_reference_uuid=SOURCE, source_file_sha256=SHA)
    assert plan['inactive_source_indices'] == list(range(6))+[7]
    assert plan['external_source_indices'] == list(range(9, 38))
    assert plan['native_active_space'] == {'electrons': 2, 'orbitals': [7, 8]}
    assert plan['native_to_source'] == list(range(6))+[7, 6, 8]+list(range(9, 38))


@pytest.mark.parametrize('indices,nel', [([1, 3, 3], 3), ([1, 3, 7], 3),
    ([-1, 3, 5], 3), ([True, 3, 5], 3), ([1, 4, 5], 3), ([1, 3, 5], 2),
    ([1, 3, 5], 5), ([], 0)])
def test_reject_ambiguous_or_physically_inconsistent_partition(spatial_source, indices, nel):
    ref, doc = spatial_source
    with pytest.raises(ValueError):
        plan_for(ref, doc, indices, nel)


def test_active_order_is_explicit_not_silently_sorted(spatial_source):
    ref, doc = spatial_source
    plan = plan_for(ref, doc, (5, 3, 1))
    assert plan['native_to_source'][2:5] == [5, 3, 1]
    assert plan['source_active_space']['orbitals'] == [5, 3, 1]
    prepared = reorder.permute_document(doc, ref, plan)
    assert reorder.verify_roundtrip(doc, prepared, ref, plan)['array_checks_passed']


def test_natural_occupations_must_not_be_frozen(spatial_source):
    ref, doc = deepcopy(spatial_source)
    ref['kind'] = 'CASSCF'
    for i, occ in ((1, 1.8), (5, .2)):
        doc['Molecule']['MolecularOrbitals']['MOs'][i]['Occupancy'] = occ
    plan = plan_for(ref, doc)
    assert reorder.verify_roundtrip(doc, reorder.permute_document(doc, ref, plan), ref, plan)['array_checks_passed']
    with pytest.raises(ValueError, match='partially occupied'):
        plan_for(ref, doc, (1, 3, 4))
    # Planning natural occupations is not qualification of ORCA's CASSCF writer.
    doc['Molecule']['HFTyp'] = 'CASSCF'
    with pytest.raises(ValueError, match='no implicit'):
        reorder.permute_document(doc, ref, plan)


@pytest.mark.parametrize('change', ['map', 'inverse', 'sha', 'source', 'electrons', 'reference'])
def test_stale_or_tampered_review_is_rejected(spatial_source, change):
    ref, doc = deepcopy(spatial_source)
    plan = plan_for(ref, doc)
    if change == 'map': plan['native_to_source'][0:2] = [2, 0]
    if change == 'inverse': plan['source_to_native'][0] = 4
    if change == 'sha': plan['source_file_sha256'] = 'b'*64
    if change == 'source': plan['source_reference_uuid'] = '22222222-2222-4222-8222-222222222222'
    if change == 'electrons': plan['source_active_space']['electrons'] = 1
    if change == 'reference': ref['structure_uuid'] = 'changed-geometry'
    with pytest.raises(ValueError):
        reorder.permute_document(doc, ref, plan)


@pytest.mark.parametrize('change', ['phase', 'mixture', 'occupation', 'energy', 'geometry',
    'basis', 'labels', 'symmetry', 'spin', 'overlap', 'ecp', 'extra_mo_data'])
def test_complete_roundtrip_rejects_scientific_changes(spatial_source, change):
    ref, doc = spatial_source
    plan = plan_for(ref, doc)
    actual = reorder.permute_document(doc, ref, plan)
    mol = actual['Molecule']; rows = mol['MolecularOrbitals']['MOs']
    if change == 'phase': rows[3]['MOCoefficients'] = [-x for x in rows[3]['MOCoefficients']]
    if change == 'mixture':
        first, second = [np.array(rows[i]['MOCoefficients']) for i in (2, 4)]
        rows[2]['MOCoefficients'] = ((first+second)/np.sqrt(2)).tolist()
        rows[4]['MOCoefficients'] = ((first-second)/np.sqrt(2)).tolist()
    if change == 'occupation': rows[3]['Occupancy'] = .5
    if change == 'energy': rows[3]['OrbitalEnergy'] += .001
    if change == 'geometry': mol['Atoms'][0]['Coords'][2] = .001
    if change == 'basis': mol['Atoms'][0]['Basis'][0]['Exponents'][0] = 2
    if change == 'labels': mol['MolecularOrbitals']['OrbitalLabels'].reverse()
    if change == 'symmetry': rows[3]['OrbitalSymmetry'] = 1
    if change == 'spin': mol['Multiplicity'] = 4
    if change == 'overlap': mol['S-Matrix'][0][0] += .001
    if change == 'ecp': mol['Atoms'][0]['ECP'] = {}
    if change == 'extra_mo_data': mol['MO-Density'] = [[1]]
    with pytest.raises(ValueError):
        reorder.verify_roundtrip(doc, actual, ref, plan)


@pytest.fixture
def basis_roundtrip(spatial_source):
    ref, doc = deepcopy(spatial_source)
    atom = doc['Molecule']['Atoms'][0]
    atom['Coords'] = [.125, -.25, .5]
    # Invented shells, preserving native nesting and distinct identities.
    atom['Basis'] = [{'Shell': 's', 'Exponents': [1.25, .5],
                      'Coefficients': [0.0, -.25], 'AngularMomentum': 0}]
    atom['BasisAuxJ'] = [{'Shell': 'p', 'Exponents': [2.5, .75],
                          'Coefficients': [0.0, -.5], 'AngularMomentum': 1}]
    plan = plan_for(ref, doc)
    return ref, doc, plan, reorder.permute_document(doc, ref, plan)


@pytest.mark.parametrize('field', ['Basis', 'BasisAuxJ'])
@pytest.mark.parametrize('delta,accepted', [
    (float(np.nextafter(reorder.DATA_TOLERANCE, 0)), True),
    (reorder.DATA_TOLERANCE, True),
    (float(np.nextafter(reorder.DATA_TOLERANCE, np.inf)), False)])
def test_basis_float_absolute_boundary_uses_existing_data_tolerance(basis_roundtrip, field, delta, accepted):
    ref, doc, plan, actual = basis_roundtrip
    actual['Molecule']['Atoms'][0][field][0]['Coefficients'][0] = delta
    if accepted:
        assert reorder.verify_roundtrip(doc, actual, ref, plan)['array_checks_passed']
    else:
        with pytest.raises(ValueError, match=field):
            reorder.verify_roundtrip(doc, actual, ref, plan)


def test_native_like_float_roundoff_needs_no_array_repair(basis_roundtrip):
    ref, doc, plan, actual = basis_roundtrip
    atom = actual['Molecule']['Atoms'][0]
    atom['BasisAuxJ'][0]['Coefficients'][1] = float(np.nextafter(-.5, -np.inf))
    atom['Coords'][0] = float(np.nextafter(.125, np.inf))
    original_source, original_actual = deepcopy(doc), deepcopy(actual)
    assert reorder.verify_roundtrip(doc, actual, ref, plan)['array_checks_passed']
    assert doc == original_source and actual == original_actual


@pytest.mark.parametrize('field', ['Basis', 'BasisAuxJ'])
@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
@pytest.mark.parametrize('side', ['source', 'prepared'])
def test_nonfinite_basis_floats_are_rejected(basis_roundtrip, field, value, side):
    ref, doc, plan, actual = basis_roundtrip
    target = doc if side == 'source' else actual
    target['Molecule']['Atoms'][0][field][0]['Coefficients'][0] = value
    with pytest.raises(ValueError, match=field):
        reorder.verify_roundtrip(doc, actual, ref, plan)


@pytest.mark.parametrize('change', ['integer', 'integer_to_float', 'integer_to_bool',
    'float_to_integer', 'text', 'list_to_tuple', 'new_key', 'missing_key', 'length', 'order',
    'atom_index', 'atom_index_type', 'nuclear_identity'])
def test_basis_tolerance_keeps_structure_types_order_and_identity_exact(basis_roundtrip, change):
    ref, doc, plan, actual = basis_roundtrip
    atom = actual['Molecule']['Atoms'][0]; shell = atom['BasisAuxJ'][0]
    if change == 'integer': shell['AngularMomentum'] = 2
    if change == 'integer_to_float': shell['AngularMomentum'] = 1.0
    if change == 'integer_to_bool': shell['AngularMomentum'] = True
    if change == 'float_to_integer': shell['Coefficients'][0] = 0
    if change == 'text': shell['Shell'] = 's'
    if change == 'list_to_tuple': shell['Coefficients'] = tuple(shell['Coefficients'])
    if change == 'new_key': shell['Unknown'] = 0
    if change == 'missing_key': shell.pop('AngularMomentum')
    if change == 'length': shell['Exponents'].append(.25)
    if change == 'order': shell['Exponents'].reverse()
    if change == 'atom_index': atom['Idx'] = 1
    if change == 'atom_index_type': atom['Idx'] = False
    if change == 'nuclear_identity': atom['ElementNumber'] = 8
    with pytest.raises(ValueError):
        reorder.verify_roundtrip(doc, actual, ref, plan)


@pytest.mark.parametrize('case', ['nan', 'complex', 'uhf', 'rank', 'missing_basis', 'nonfinite_occ'])
def test_unqualified_exports_fail_closed(spatial_source, case):
    ref, doc = deepcopy(spatial_source)
    plan = plan_for(ref, doc)
    mol = doc['Molecule']; rows = mol['MolecularOrbitals']['MOs']
    if case == 'nan': rows[0]['MOCoefficients'][0] = float('nan')
    if case == 'complex': rows[0]['MOCoefficients'][0] = 1j
    if case == 'uhf': mol['HFTyp'] = 'UHF'
    if case == 'rank': rows.pop()
    if case == 'missing_basis': mol['Atoms'][0].pop('Basis')
    if case == 'nonfinite_occ': rows[0]['Occupancy'] = float('inf')
    with pytest.raises(ValueError):
        reorder.permute_document(doc, ref, plan)
