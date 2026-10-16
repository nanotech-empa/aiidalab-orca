"""Numerical maps run on the source computer inside a CalcJob."""
import hashlib
import json
from pathlib import Path

import numpy as np
from aiida_empa_orca.maps_data import compute_maps


def main():
    request = json.loads(Path('request.json').read_text())
    checksums = {}
    for key, source in request['cubes'].items():
        path = Path(source['path'])
        if path.stat().st_size != source['size_bytes']:
            raise ValueError('Staged amplitude cube size differs from its manifest')
        with path.open('rb') as handle:
            checksums[key] = hashlib.file_digest(handle, 'sha256').hexdigest()
    arrays, metadata = compute_maps({k: v['path'] for k, v in request['cubes'].items()},
                                    request['table'], request['parameters'])
    metadata['source_sha256'] = checksums
    np.savez_compressed('maps.npz', **arrays)
    Path('map-metadata.json').write_text(json.dumps(metadata, indent=2, allow_nan=False))
    for source in request['cubes'].values():
        Path(source['path']).unlink()  # Only this job's staging copies.


if __name__ == '__main__':
    main()
