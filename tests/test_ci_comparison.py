"""Analytic CI comparisons distinguish degeneracy freedom from changed states."""
from copy import deepcopy

import numpy as np
import pytest

from aiida_empa_orca.scripts.compare_ci_solvers import compare


def bundle(degenerate=False):
    return {'identity':{'structure_uuid':'geometry','orbital_reference_uuid':'orbitals',
        'active_space':{'electrons':1,'orbitals':[0,1]},'active_electrons':1,
        'reference_charge':0,'model':{'integral_transform':'RI'},'method':'CASCI','geometry_mode':'fixed',
        'states':[{'root':i,'charge':0,'multiplicity':2,'energy_hartree':energy}
                  for i,energy in enumerate([-1.,-1. if degenerate else -.5])]},
        'wavefunction':{'Molecule':{'Atoms':[{'ElementNumber':1}], 'S-Matrix':np.eye(2).tolist(),
            'MolecularOrbitals':{'MOs':[{'MOCoefficients':[1.,0.]},{'MOCoefficients':[0.,1.]}]}}},
        'ci_roots':{'0':{'coefficients':{'[u0]':1.}},'1':{'coefficients':{'[0u]':1.}}}}


def test_global_ci_phase_and_degenerate_rotations_are_equivalent():
    first=bundle()
    second=deepcopy(first)
    second['ci_roots']['1']['coefficients']['[0u]']=-1.
    assert compare(first,second)['passed']
    first=bundle(degenerate=True)
    second=deepcopy(first)
    c=float(1/np.sqrt(2))
    second['ci_roots']={'0':{'coefficients':{'[u0]':c,'[0u]':c}},
                        '1':{'coefficients':{'[u0]':-c,'[0u]':c}}}
    result=compare(first,second)
    assert result['passed'] and result['groups'][0]['roots']==[0,1]
    first['identity']['states'][1]['energy_hartree']=-.5
    second['identity']['states'][1]['energy_hartree']=-.5
    assert not compare(first,second)['passed']


def test_incomplete_vectors_are_not_normalized_and_energy_or_orbital_changes_fail():
    first=bundle()
    second=deepcopy(first)
    second['ci_roots']['1']['coefficients']['[0u]']=.5
    with pytest.raises(ValueError,match='truncated'):
        compare(first,second)
    second=deepcopy(first)
    second['identity']['states'][0]['energy_hartree']+=1e-3
    assert not compare(first,second)['passed']
    second=deepcopy(first)
    second['wavefunction']['Molecule']['MolecularOrbitals']['MOs'][0]['MOCoefficients'][0]=-1.
    with pytest.raises(ValueError,match='phases'):
        compare(first,second)
