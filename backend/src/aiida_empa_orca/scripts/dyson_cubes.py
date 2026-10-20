"""Optional Dyson cubes, validated against the exported AO basis, then cubehandler."""
import json
from pathlib import Path
import shutil
import subprocess
from contextlib import nullcontext

import numpy as np
from dyson_orca_tools.io.cube import write_cube, pyscf_molecule, orca_label_to_pyscf

from aiida_empa_orca.scripts.compute_dyson import load_export
from aiida_empa_orca.scripts.plot_cubes import inspect_cube
from aiida_empa_orca.dyson_data import blend_weight
from ase.io.cube import read_cube,write_cube as ase_write_cube


def cube_comments(path,first=None,second=None):
    """Change comments in place without copying a potentially large cube."""
    with Path(path).open('r+b') as handle:
        lines = [handle.readline(),handle.readline()]
        handle.seek(0)
        for original,replacement in zip(lines,(first,second)):
            if replacement is None:
                handle.write(original)
            else:
                text = replacement.encode('ascii')
                if len(text) > len(original)-1:
                    raise ValueError('Cube comment exceeds its reserved line')
                handle.write(text.ljust(len(original)-1,b' ')+b'\n')


def main():
    request = json.loads(Path('request.json').read_text())
    p = request['parameters']
    kondo = 'channels' in request
    table = request['channels'] if kondo else request['table']
    initial = load_export('initial.json.gz',request['artifact'])
    wf = initial['wavefunction']
    mol = pyscf_molecule(wf)
    labels = [orca_label_to_pyscf(label) for label in wf['Molecule']['MolecularOrbitals']['OrbitalLabels']]
    pyscf_labels = [''.join(label.split()) for label in mol.ao_labels()]
    if len(set(labels)) != len(labels) or set(labels) != set(pyscf_labels):
        raise ValueError('Unsupported ORCA/PySCF AO label mapping')
    order = [labels.index(label) for label in pyscf_labels]
    overlap = np.asarray(wf['Molecule']['S-Matrix'])[np.ix_(order,order)]
    if not np.allclose(overlap,mol.intor('int1e_ovlp'),atol=1e-7,rtol=0):
        raise ValueError('ORCA/PySCF basis overlap differs; cube generation would use inconsistent AO functions')
    estimate = (len(p['orbitals'])+int(bool(request.get('blend'))))*p['grid_points']**3*30*(2 if p['retention']=='stash' else 1)+256*1024**2
    if shutil.disk_usage('.').free < estimate:
        raise ValueError('Insufficient free disk for the requested Dyson cubes')
    full = Path('full_cubes')
    full.mkdir()
    manifest = {'retention':p['retention'],'grid_points':p['grid_points'],'cubes':[],
                'reduction':{'program':'cubehandler','method':'slicing','low_precision':False},
                'orbital_source':{'kind':'Kondo' if kondo else 'Dyson','initial_state_uuid':table['initial_state_uuid']},
                'strength_convention':'unit_normalized_eigenchannel' if kondo else 'highest_ms_component'}
    if kondo:
        from dyson_orca_tools.dyson import Dyson
        c = Dyson.get_mo_coeff_array(None, wf)[:, table['active_space']['orbitals']]
        if not np.allclose(c.T @ np.asarray(wf['Molecule']['S-Matrix']) @ c, np.eye(c.shape[1]), atol=1e-7, rtol=0):
            raise ValueError('Kondo active orbitals are not orthonormal in the exported AO basis')
        coefficient_source = nullcontext({r['id']: c @ np.asarray(r['active_coefficients']) for r in table['channels']})
        manifest['channels_uuid'] = request['channels_uuid']
    else:
        coefficient_source = np.load('coefficients.npz', allow_pickle=False)
    with coefficient_source as arrays:
        for _,index in p['orbitals']:
            row = table['channels' if kondo else 'transitions'][index]
            filename = ('kondo_' if kondo else 'dyson_')+row['id']+'.cube'
            # Use upstream orbital evaluation, leaving amplitudes unnormalized.
            write_cube(wf,arrays[row['id']],str(full/filename),nx=p['grid_points'],ny=p['grid_points'],nz=p['grid_points'],margin=8.)
            cube_comments(full/filename,first=('Kondo' if kondo else 'Dyson')+' orbital amplitude (atomic units)')
            record = inspect_cube(full/filename)
            if kondo:
                manifest['cubes'].append(dict(filename=filename, kind='kondo', channel_id=row['id'], index=index,
                    exchange_over_v2_inv_ev=row['exchange_over_v2_inv_ev'], coupling=row['coupling'], full=record))
            else:
                manifest['cubes'].append({'filename':filename,'kind':'dyson','transition_id':row['id'],
                    'index':index,'energy_ev':row['energy_ev'],'strength':row['strength'],'full':record})
    if request.get('blend'):
        blended,template = None,None
        for cube in manifest['cubes']:
            with (full/cube['filename']).open() as handle:
                grid = read_cube(handle)
            row = table['transitions'][cube['index']]
            weight = blend_weight(row,table['initial_state']['multiplicity'],request['blend'])
            if blended is None:
                blended,template = np.zeros_like(grid['data']),grid
            if grid['data'].shape != blended.shape or not np.allclose(grid['origin'],template['origin']) or not np.allclose(grid['atoms'].cell,template['atoms'].cell):
                raise ValueError('Dyson cubes have different grids; intensities cannot be combined')
            # Unnormalized Dyson amplitudes already contain their pole strength.
            blended += weight*grid['data']**2
        filename = 'dyson_blend.cube'
        with (full/filename).open('w') as handle:
            ase_write_cube(handle,template['atoms'],data=blended,origin=template['origin'],comment='Incoherent Dyson spectral intensity')
        # cubehandler appends scaling metadata to comment line 2. Avoid the
        # special OUTER LOOP grammar, which ASE expects to end after Z.
        cube_comments(full/filename,second='XYZ data order; spectral intensity')
        manifest['blend'] = request['blend']
        manifest['cubes'].append({'filename':filename,'kind':'dyson_blend','full':inspect_cube(full/filename)})
    with Path('plot.log').open('w') as log:
        subprocess.run([request['cubehandler_executable'],'shrink',*[str(full/c['filename']) for c in manifest['cubes']],
                        '--output-dir','previews','--prefix','','--method','slicing','--no-low-precision'],
                        stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
    for cube in manifest['cubes']:
        cube['preview'] = inspect_cube(Path('previews')/cube['filename'])
        if cube['preview']['size_bytes'] >= cube['full']['size_bytes']:
            raise ValueError('Cubehandler did not reduce the Dyson cube')
    if p['retention'] == 'delete':
        for cube in manifest['cubes']:
            (full/cube['filename']).unlink()
        full.rmdir()
    Path('manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False))
    Path('initial.json.gz').unlink()


if __name__ == '__main__':
    main()
