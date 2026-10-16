"""Discard coefficient arrays from ORCA 6 JSON before retrieving orbital metadata."""
import hashlib
import io
import json
from pathlib import Path
import re


def compact_json(handle):
    """Read ORCA's pretty JSON with O(number of orbitals) memory.

    The standard JSON decoder validates the retained document. Coefficients are
    numeric arrays, printed one number per line by the supported ORCA exporter.
    Reject an unexpected array format instead of misreading occupations.
    """
    kept = io.StringIO()
    skipping = False
    for line in handle:
        if skipping:
            closing = re.fullmatch(r'\s*\](,?)\s*', line)
            if closing:
                kept.write('[]'+closing[1]+'\n')
                skipping = False
            elif not re.fullmatch(r'\s*[-+0-9.eE]+,?\s*', line):
                raise ValueError('Unexpected ORCA MO-coefficient array format')
            continue
        match = re.fullmatch(r'(\s*"MOCoefficients"\s*:\s*)\[\s*', line)
        if match:
            kept.write(match[1])
            skipping = True
        elif '"MOCoefficients"' in line:
            raise ValueError('Unexpected ORCA MO-coefficient array layout')
        else:
            kept.write(line)
    if skipping:
        raise ValueError('Truncated ORCA MO-coefficient array')
    return json.loads(kept.getvalue())


def main():
    request = json.loads(Path('request.json').read_text())
    result = {'sets': {}}
    for kind, item in request['sets'].items():
        staged = Path(item['staged'])
        with staged.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        if staged.stat().st_size != item['size_bytes'] or (item.get('sha256') and digest != item['sha256']):
            raise ValueError('The staged orbital file changed: '+kind)
        path = staged.with_suffix('.json')
        with path.open() as handle:
            data = compact_json(handle)
        # The coefficients have been removed before any JSON object is decoded.
        molecule = data['Molecule']
        for mo in molecule['MolecularOrbitals']['MOs']:
            mo.pop('MOCoefficients', None)
        result['sets'][kind] = {'molecule': molecule, 'sha256': digest,
                                'source_filename': item['name'], 'size_bytes': item['size_bytes']}
        path.unlink()
        staged.unlink()  # Only this CalcJob's expendable staging copy.
    Path('orbital_metadata.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
