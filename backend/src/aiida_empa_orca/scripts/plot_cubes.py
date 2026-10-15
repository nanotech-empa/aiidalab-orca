"""ORCA 6.1 cube export followed by the shared cubehandler CLI."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
from ase.io.cube import read_cube


def inspect_cube(path):
    with Path(path).open() as handle:
        cube = read_cube(handle)
    data = cube['data']
    if data.ndim != 3 or min(data.shape)<2 or not np.isfinite(data).all():
        raise ValueError('Invalid cube grid: '+str(path))
    from ase.units import Bohr
    # Cube values remain in atomic units. ASE exposes the cell in Angstrom.
    volume = abs(np.linalg.det(cube['atoms'].cell.array))/Bohr**3/data.size
    return {'shape': list(data.shape), 'size_bytes': Path(path).stat().st_size,
            'minimum': float(data.min()), 'maximum': float(data.max()),
            'integral': float(data.sum()*volume), 'squared_integral': float((data*data).sum()*volume)}


def main():
    request = json.loads(Path('request.json').read_text())
    p = request['parameters']
    for item in request['files']:
        path = Path(item['name'])
        if path.stat().st_size != item['size_bytes']:
            raise RuntimeError('Wavefunction size changed: '+item['name'])
        if item.get('sha256'):
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            if digest != item['sha256']:
                raise RuntimeError('Wavefunction checksum changed: '+item['name'])
    count = len(p['orbitals'])+int(p['spin_density'])
    estimate = count*p['grid_points']**3*24*(2 if p['retention']=='stash' else 1) + 256*1024**2
    if shutil.disk_usage('.').free < estimate:
        raise RuntimeError('Insufficient free disk for the requested cube grid and orbital count')
    full = Path('full_cubes')
    full.mkdir()
    manifest = {'retention': p['retention'], 'grid_points': p['grid_points'], 'cubes': [],
                'reduction': {'program': 'cubehandler', 'method': 'slicing', 'low_precision': False}}
    with Path('plot.log').open('w') as log:
        def plot(commands, produced, target, metadata):
            subprocess.run([request['plot_executable'], 'aiida.gbw', '-i'], input='\n'.join(commands+['11','12'])+'\n',
                           text=True, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
            generated = Path(produced)
            if not generated.is_file():
                raise RuntimeError('ORCA did not produce '+produced+'; inspect plot.log')
            generated.rename(full/target)
            manifest['cubes'].append({**metadata, 'filename': target, 'full': inspect_cube(full/target)})
        grid = ['4', str(p['grid_points'])]
        for spin, index in p['orbitals']:
            plot(grid+['2',str(index),'3',str(spin)], f'aiida.mo{index}{"ab"[spin]}.cube',
                 f'orbital_{"ab"[spin]}_{index:04d}.cube', {'kind': 'orbital', 'spin': spin, 'index': index})
        if p['spin_density']:
            plot(grid+['1','3','y'], 'aiida.spindens.cube', 'spin_density.cube', {'kind': 'spin_density'})
        subprocess.run([request['cubehandler_executable'], 'shrink',
                        *[str(full/c['filename']) for c in manifest['cubes']],
                        '--output-dir','previews','--prefix','','--method','slicing','--no-low-precision'],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    for cube in manifest['cubes']:
        cube['preview'] = inspect_cube(Path('previews')/cube['filename'])
        if cube['preview']['size_bytes'] >= cube['full']['size_bytes']:
            raise RuntimeError('Cubehandler did not reduce '+cube['filename']+'; use a finer full-resolution grid')
    # Only this job's generated full cubes can be deleted, and only after validation.
    if p['retention'] == 'delete':
        for cube in manifest['cubes']:
            (full/cube['filename']).unlink()
        full.rmdir()
    Path('manifest.json').write_text(json.dumps(manifest, indent=2))
    # These are expendable staging copies, never the source calculation's files.
    for item in request['files']:
        Path(item['name']).unlink()


if __name__ == '__main__':
    main()
