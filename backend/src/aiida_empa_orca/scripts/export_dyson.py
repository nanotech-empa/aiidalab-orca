"""Preserve a self-contained CASCI wavefunction export inside its CalcJob."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from dyson_orca_tools.io.orca_output import parse_orca_output

from aiida_empa_orca.dyson_data import checked_ci


def main():
    request = json.loads(Path('request.json').read_text())
    source = Path('aiida.gbw')
    item = request['file']
    if source.stat().st_size != item['size_bytes']:
        raise ValueError('CASCI wavefunction size changed')
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle,'sha256').hexdigest()
    if item.get('sha256') and item['sha256'] != digest:
        raise ValueError('CASCI wavefunction checksum changed')
    state = json.loads(Path('aiida.json').read_text())
    identity = request['identity']
    row = identity['states'][0]
    molecule = state['Molecule']
    if molecule['Charge'] != row['charge'] or molecule['Multiplicity'] != row['multiplicity']:
        raise ValueError('Exported wavefunction charge/multiplicity differs from CASCI')
    if not all(atom.get('Basis') for atom in molecule['Atoms']):
        raise ValueError('Basis shells are missing from ORCA JSON; request Basisset (case-sensitive)')
    if molecule['CoordinateUnits'] not in ('Angs','Angstrom'):
        raise ValueError('Unsupported exported coordinate units')
    if ([a['ElementNumber'] for a in molecule['Atoms']] != request['atomic_numbers'] or
            not np.allclose([a['Coords'] for a in molecule['Atoms']],request['positions'],atol=1e-7,rtol=0)):
        raise ValueError('Exported wavefunction geometry differs from the CASCI input')
    mo = np.column_stack([r['MOCoefficients'] for r in molecule['MolecularOrbitals']['MOs']])
    overlap = np.asarray(molecule['S-Matrix'])
    if (mo.ndim != 2 or overlap.shape != (mo.shape[0],mo.shape[0]) or not np.isfinite(mo).all() or
            not np.isfinite(overlap).all() or not np.allclose(overlap,overlap.T,atol=1e-10,rtol=0)):
        raise ValueError('Invalid orbital coefficients or AO overlap matrix')
    active = identity['active_space']['orbitals']
    c = mo[:,active]
    if not np.allclose(c.T@overlap@c,np.eye(len(active)),atol=1e-7,rtol=0):
        raise ValueError('Exported active orbitals are not orthonormal')
    parsed = parse_orca_output(Path('aiida.out'))
    roots = {}
    for r in parsed.roots:
        expected = next((s for s in identity['states'] if s['multiplicity'] == r.mult and s['root'] == r.index),None)
        if expected is None or r.energy is None or abs(r.energy-expected['energy_hartree']) > 1e-9:
            raise ValueError('Printed CI state energies differ from the parsed CASCI result')
        if str(r.index) in roots:
            raise ValueError('Ambiguous duplicate determinant blocks')
        norm = checked_ci(r.spin_ci,len(active),identity['active_electrons'],r.mult)
        roots[str(r.index)] = {'coefficients':r.spin_ci,'norm':norm}
    if set(roots) != {str(s['root']) for s in identity['states']}:
        raise ValueError('Missing printed CI roots')
    if parsed.norb != len(active) or parsed.nelc != identity['active_electrons']:
        raise ValueError('Printed CI active space differs from CASCI provenance')
    Path('exports').mkdir()
    Path('retrieved_exports').mkdir()
    path = Path('exports/state.json.gz')
    payload = {'schema_version':1,'state_uuid':request['state_uuid'],'identity':identity,
               'wavefunction':state,'ci_roots':roots,'source_gbw_sha256':digest}
    with path.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as zipped:
            zipped.write(json.dumps(payload,allow_nan=False,separators=(',',':')).encode())
    with path.open('rb') as handle:
        sha = hashlib.file_digest(handle,'sha256').hexdigest()
    size = path.stat().st_size
    retrieved = size <= request['threshold_mb']*1024**2
    if retrieved:
        shutil.copyfile(path,'retrieved_exports/state.json.gz')
    artifact = {'schema_version':1,'state_uuid':request['state_uuid'],'identity':identity,
                'sha256':sha,'size_bytes':size,'source_gbw_sha256':digest,
                'ci_norms':{key:r['norm'] for key,r in roots.items()},'retrieved_copy':retrieved,
                'basis_available':True,'format':'orca_json_and_printed_ci_gzip_v1'}
    Path('artifact.json').write_text(json.dumps(artifact,indent=2,allow_nan=False))
    # Delete staging copies, never files in the source calculation.
    source.unlink()
    Path('aiida.json').unlink()
    print('Validated and preserved',len(roots),'CASCI roots;',size,'compressed bytes')


if __name__ == '__main__':
    main()
