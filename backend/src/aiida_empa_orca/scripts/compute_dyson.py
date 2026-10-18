"""Use Andrés's fixed-orbital Dyson kernel; retain raw spin-component amplitudes."""
import gzip
import hashlib
import json
from pathlib import Path
import importlib.metadata

import numpy as np
from dyson_orca_tools.dyson import Dyson
from dyson_orca_tools.spectral import peak_energy
from aiida_empa_orca.dyson_data import fixed_orbital_kernel


def load_export(path,artifact):
    with Path(path).open('rb') as handle:
        if hashlib.file_digest(handle,'sha256').hexdigest() != artifact['sha256']:
            raise ValueError('Preserved wavefunction export checksum changed')
    with gzip.open(path,'rt') as handle:
        value = json.load(handle)
    if value['state_uuid'] != artifact['state_uuid'] or value['identity'] != artifact['identity']:
        raise ValueError('Export contents differ from their provenance')
    return value


def state_parameters(bundle,root):
    identity = bundle['identity']
    row = next(s for s in identity['states'] if s['root'] == root)
    return {'nelc':identity['active_electrons'],'norb':len(identity['active_space']['orbitals']),
            'mult':row['multiplicity'],'spin_ci':bundle['ci_roots'][str(root)]['coefficients']}


def main():
    request = json.loads(Path('request.json').read_text())
    initial = load_export('initial.json.gz',request['artifacts']['initial'])
    selected = request['selection']
    root_i = selected['initial_root']
    initial_row = next(r for r in initial['identity']['states'] if r['root'] == root_i)
    norm_i = initial['ci_roots'][str(root_i)]['norm']
    if norm_i < 1-selected['max_missing_ci_norm']:
        raise ValueError('Initial CI printout is too truncated; recompute that CASCI sector with a lower print threshold')
    wf_i = initial['wavefunction']
    molecule_i = wf_i['Molecule']
    c_i = Dyson.get_mo_coeff_array(None,wf_i)
    s = np.asarray(molecule_i['S-Matrix'])
    indices = initial['identity']['active_space']['orbitals']
    arrays,transitions = {},[]
    for key,roots in selected['final_roots'].items():
        final = load_export(key+'.json.gz',request['artifacts'][key])
        wf_f = final['wavefunction']
        molecule_f = wf_f['Molecule']
        if molecule_i['Atoms'] != molecule_f['Atoms']:
            raise ValueError('Dyson states have different geometry or basis metadata')
        if not np.allclose(s,molecule_f['S-Matrix'],atol=1e-10,rtol=0):
            raise ValueError('Dyson states have different AO overlap matrices')
        c_f = Dyson.get_mo_coeff_array(None,wf_f)
        if c_i.shape != c_f.shape or not np.allclose(c_i[:,indices].T@s@c_f[:,indices],np.eye(len(indices)),atol=1e-7,rtol=0):
            raise ValueError('CASCI active orbitals differ; do not mix separately regenerated references')
        for root in roots:
            final_row = next(r for r in final['identity']['states'] if r['root'] == root)
            norm_f = final['ci_roots'][str(root)]['norm']
            if norm_f < 1-selected['max_missing_ci_norm']:
                raise ValueError('Final CI printout is too truncated; lower the CI print threshold for that sector')
            params = {'parameters':{'initial':state_parameters(initial,root_i),'final':state_parameters(final,root)}}
            dyson = fixed_orbital_kernel(wf_i,wf_f,params,indices)
            mo = dyson.dyson_mo_coefficients()
            ao = dyson.dyson_orbital(mo)
            strength = dyson.strength(ao)
            if not np.isfinite(ao).all() or not np.isfinite(strength) or strength < -1e-12:
                raise ValueError('Invalid Dyson coefficients or pole strength')
            removal = final_row['charge'] > initial_row['charge']
            name = key+'_r'+str(root)
            arrays[name] = ao
            transitions.append({'id':name,'sector':key,'final_state_uuid':final['state_uuid'],
                'final_root':root,'final_charge':final_row['charge'],'final_multiplicity':final_row['multiplicity'],
                'side':'removal' if removal else 'addition',
                'energy_ev':peak_energy(initial_row['energy_hartree'],final_row['energy_hartree'],removal),
                'strength':strength,'initial_ci_norm':norm_i,'final_ci_norm':norm_f,
                'active_coefficients':mo.tolist(),'active_indices':indices,
                'spin_channel':'alpha' if ((removal and final_row['multiplicity'] < initial_row['multiplicity']) or
                                          (not removal and final_row['multiplicity'] > initial_row['multiplicity'])) else 'beta'})
    transitions.sort(key=lambda r:r['energy_ev'])
    table = {'schema_version':1,'initial_state_uuid':initial['state_uuid'],'initial_state':initial_row,
             'orbital_reference_uuid':initial['identity']['orbital_reference_uuid'],
             'active_space':initial['identity']['active_space'],'transitions':transitions,
             'strength_convention':'highest_ms_component','ci_normalization':'printed_coefficients_not_renormalized',
             'energy_convention':'removal E_initial-E_final; addition E_final-E_initial; eV',
             'dyson_orca_tools_version':importlib.metadata.version('dyson-orca-tools')}
    np.savez_compressed('coefficients.npz',**arrays)
    Path('transitions.json').write_text(json.dumps(table,indent=2,allow_nan=False))
    for key in request['artifacts']:
        Path(key+'.json.gz').unlink()
    print('Computed',len(transitions),'fixed-orbital CASCI transitions')


if __name__ == '__main__':
    main()
