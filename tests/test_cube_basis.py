"""Native ORCA overlap data distinguish AO phases from harmless reordering."""
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import runpy

import numpy as np
import pytest


@pytest.fixture
def frame():
    return runpy.run_path(str(files('aiida_empa_orca').joinpath('scripts/dyson_cubes.py')))['pyscf_frame']


@pytest.fixture
def wavefunction():
    return json.loads((Path(__file__).parent/'fixtures/orca-ch-tzvp-overlap.json').read_text())


def test_native_tzvp_overlap_requires_real_f3_phase_conversion(frame,wavefunction):
    mol,order,signs,error = frame(wavefunction)
    original = np.asarray(wavefunction['Molecule']['S-Matrix'])[np.ix_(order,order)]
    expected = mol.intor('int1e_ovlp')
    assert np.max(np.abs(original-expected)) > .1
    assert error < 1e-7
    labels = [''.join(label.split()) for label in mol.ao_labels()]
    assert {label[-3:] for label,sign in zip(labels,signs) if sign<0} == {'f-3','f+3'}
    # Transforming both the metric and coefficients preserves all AO norms.
    coefficient = np.linspace(-.4,.7,len(order))
    transformed = coefficient[order]*signs
    norm = coefficient @ np.asarray(wavefunction['Molecule']['S-Matrix']) @ coefficient
    assert transformed @ expected @ transformed == pytest.approx(norm,abs=1e-7)


def test_existing_spd_phase_and_ordering_are_unchanged(frame,wavefunction):
    wf = deepcopy(wavefunction)
    labels = wf['Molecule']['MolecularOrbitals']['OrbitalLabels']
    indices = [i for i,label in enumerate(labels) if 'f' not in label]
    wf['Molecule']['MolecularOrbitals']['OrbitalLabels'] = [labels[i] for i in indices]
    wf['Molecule']['S-Matrix'] = np.asarray(wf['Molecule']['S-Matrix'])[np.ix_(indices,indices)].tolist()
    for atom in wf['Molecule']['Atoms']:
        atom['Basis'] = [shell for shell in atom['Basis'] if shell['Shell'].lower() != 'f']
    _,_,signs,error = frame(wf)
    assert np.all(signs==1.) and error<1e-7


def test_inconsistent_radial_basis_still_fails_the_original_overlap_guard(frame,wavefunction):
    wavefunction['Molecule']['Atoms'][0]['Basis'][0]['Exponents'][0] *= 1.2
    with pytest.raises(ValueError,match='basis overlap differs'):
        frame(wavefunction)
