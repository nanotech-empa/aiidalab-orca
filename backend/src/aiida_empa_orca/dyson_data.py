"""Validated fixed-orbital state pairs and explicit spectral conventions."""
import math

import numpy as np

HARTREE_EV = 27.211386245988
IDENTITY = ('orbital_reference_uuid', 'structure_uuid', 'active_space', 'model', 'method', 'geometry_mode')


def compatible(initial, final):
    if any(initial[key] != final[key] for key in IDENTITY):
        raise ValueError('Dyson states must share geometry, orbital reference, active space and integral model')
    if initial['method'] != 'CASCI' or initial['geometry_mode'] != 'fixed':
        raise ValueError('The first Dyson implementation requires fixed-orbital CASCI states')
    a, b = initial['states'][0], final['states'][0]
    if abs(a['charge']-b['charge']) != 1:
        raise ValueError('Initial and final states must differ by one electron')
    if abs(a['multiplicity']-b['multiplicity']) != 1:
        raise ValueError('Spin-free one-electron transitions require multiplicities differing by one')


def selection(values, initial, finals):
    if set(values)-{'initial_root','final_roots','max_missing_ci_norm'}:
        raise ValueError('Unknown Dyson selection')
    root = values.get('initial_root',0)
    if type(root) is not int or root not in [s['root'] for s in initial['states']]:
        raise ValueError('Select an initial root from the CASCI result')
    chosen = values.get('final_roots',{})
    if not chosen or set(chosen) != set(finals):
        raise ValueError('Select final roots for each supplied final sector')
    sectors = set()
    for key,data in finals.items():
        compatible(initial,data)
        sector = (data['states'][0]['charge'],data['states'][0]['multiplicity'])
        if sector in sectors:
            raise ValueError('Choose one CASCI calculation per final charge/multiplicity sector')
        sectors.add(sector)
        roots = chosen[key]
        if (not isinstance(roots,list) or not roots or any(type(r) is not int for r in roots) or
                len(set(roots)) != len(roots) or not set(roots) <= {s['root'] for s in data['states']}):
            raise ValueError('Select existing, unique final roots')
    loss = values.get('max_missing_ci_norm',1e-5)
    if type(loss) not in (float,int) or not math.isfinite(loss) or not 0 <= loss <= .01:
        raise ValueError('Maximum missing CI norm must be between 0 and 0.01')
    return {'initial_root':root,'final_roots':{k:sorted(v) for k,v in sorted(chosen.items())},
            'max_missing_ci_norm':float(loss)}


def checked_ci(coefficients, norb, nel, mult):
    if not coefficients:
        raise ValueError('Missing determinant coefficients; rerun this CASCI sector with PrintWF det')
    for det,c in coefficients.items():
        text = det.strip('[]')
        if (len(text) != norb or set(text)-set('2ud0') or
                2*text.count('2')+text.count('u')+text.count('d') != nel or
                text.count('u')-text.count('d') != mult-1 or not math.isfinite(c)):
            raise ValueError('Invalid determinant electron/spin count or coefficient')
    norm = sum(c*c for c in coefficients.values())
    if not 0 < norm <= 1+1e-6:
        raise ValueError('Invalid printed CI norm')
    return norm


def spectrum(table, omega, eta, side='both', shift=0.):
    """Upstream Lorentzian convention: each peak has area pi * strength.

    eta is HWHM in eV. A rigid shift never changes the selected initial state.
    """
    omega = np.asarray(omega,dtype=float)
    if not math.isfinite(eta) or eta <= 0 or not math.isfinite(shift) or side not in ('both','removal','addition'):
        raise ValueError('Use a positive finite HWHM and a finite energy shift')
    result = {'removal':np.zeros_like(omega),'addition':np.zeros_like(omega)}
    for row in table['transitions']:
        if side == 'both' or row['side'] == side:
            result[row['side']] += eta*row['strength']/((omega-row['energy_ev']-shift)**2+eta**2)
    result['total'] = result['removal']+result['addition']
    return result


def spin_factor(initial_mult,final_mult,convention='unpolarized'):
    """Convert the M_S=S component to an initial-spin-averaged, spin-summed weight.

    Wigner-Eckart spin-1/2 coupling, for spin-pure states without SOC:
    higher final spin: (m_i+1)/m_i; lower final spin: 1. The same factor
    applies to addition and removal. Raw AO amplitudes are never rescaled.
    """
    if convention not in ('unpolarized','highest_ms_component') or abs(initial_mult-final_mult) != 1:
        raise ValueError('Unsupported spin convention or spin-forbidden transition')
    return (initial_mult+1)/initial_mult if convention == 'unpolarized' and final_mult > initial_mult else 1.


def weighted_table(table,convention='unpolarized'):
    transitions = []
    for row in table['transitions']:
        factor = spin_factor(table['initial_state']['multiplicity'],row['final_multiplicity'],convention)
        component = row.get('component_strength',row['strength'])
        transitions.append(dict(row,component_strength=component,spin_factor=factor,
                                strength=component*factor))
    return dict(table,display_spin_convention=convention,strength_convention=convention,
                source_strength_convention=table.get('source_strength_convention',table.get('strength_convention','highest_ms_component')),
                transitions=transitions)


def blend_options(values):
    if set(values)-{'mode','energy_ev','lower_ev','upper_ev','eta_ev','spin_convention','shift_ev'}:
        raise ValueError('Unknown blend parameter')
    p = {'mode':'energy','energy_ev':0.,'lower_ev':-1.,'upper_ev':1.,'eta_ev':.04,
         'spin_convention':'unpolarized','shift_ev':0.} | values
    if p['mode'] not in ('energy','window') or p['spin_convention'] not in ('unpolarized','highest_ms_component'):
        raise ValueError('Select an energy/window and an explicit spin convention')
    for key in ('energy_ev','lower_ev','upper_ev','eta_ev','shift_ev'):
        if type(p[key]) not in (int,float) or not math.isfinite(p[key]):
            raise ValueError('Blend energies and broadening must be finite numbers')
    if p['eta_ev'] <= 0 or p['lower_ev'] >= p['upper_ev']:
        raise ValueError('Use a positive HWHM and an increasing energy window')
    return p


def blend_weight(row,initial_mult,options):
    p = blend_options(options)
    pole,eta = row['energy_ev']+p['shift_ev'],p['eta_ev']
    if p['mode'] == 'energy':
        weight = eta/((p['energy_ev']-pole)**2+eta**2)
    else:
        weight = math.atan((p['upper_ev']-pole)/eta)-math.atan((p['lower_ev']-pole)/eta)
    return weight*spin_factor(initial_mult,row['final_multiplicity'],p['spin_convention'])


def fixed_orbital_kernel(initial,final,parameters,indices):
    """Adapt the library to explicit CASCI indices, including fully occupied actives.

    Natural occupations do not define the inactive/active boundary. The supplied
    CASCI provenance does; the upstream kernel otherwise guesses from n == 2.
    """
    from dyson_orca_tools.dyson import Dyson
    kernel = Dyson(initial,final,parameters)
    if not indices or indices != list(range(indices[0],indices[0]+kernel.num_active_orbs)):
        raise ValueError('The fixed-orbital kernel requires explicit contiguous CASCI indices')
    kernel.num_inactive_orbs = indices[0]
    if not kernel.calculation_is_casci(atol=1e-7):
        raise ValueError('The selected active orbitals are not shared orthonormal CASCI orbitals')
    return kernel
