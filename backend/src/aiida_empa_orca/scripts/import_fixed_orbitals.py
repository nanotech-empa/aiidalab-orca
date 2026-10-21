"""Check copies of external files inside a submitted import CalcJob."""
import hashlib
import json
from pathlib import Path

from aiida_empa_orca.fixed_orbitals_data import checked_manifest, check_export


def main():
    request = json.loads(Path('request.json').read_text())
    manifest = checked_manifest(request['manifest'])
    staged = {'gbw':'aiida.gbw', 'input':'source.inp', 'output':'source.out'}
    for row in manifest['files']:
        path = Path(staged[row['role']])
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        if path.stat().st_size != row['size_bytes'] or digest != row['sha256']:
            raise ValueError('An external source file changed: '+row['name'])
    with Path('aiida.json').open() as handle:
        molecule = json.load(handle)['Molecule']
    result = check_export(molecule, request)
    result['source_manifest'] = manifest
    Path('import_manifest.json').write_text(json.dumps(result, indent=2, allow_nan=False))
    Path('aiida.json').unlink()  # This CalcJob's large export; original files are untouched.
    print('Validated imported fixed orbitals; no electronic calculation or orbital transformation performed.')


if __name__ == '__main__':
    main()
