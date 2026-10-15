"""Executed in a CalcJob sandbox; preserve a complete electronic-file bundle."""
import hashlib
import json
from pathlib import Path
import shutil


def main():
    request = json.loads(Path('request.json').read_text())
    total = sum((Path('source')/name).stat().st_size for name in request['files'])
    storage = 'repository' if total <= request['threshold_bytes'] else 'stash'
    if storage != request['storage']:
        raise RuntimeError('Electronic file sizes changed since review; review the storage plan again')
    if shutil.disk_usage('.').free < total*(2 if storage=='stash' else 1)+100*1024**2:
        raise RuntimeError('Insufficient free space for the electronic-file copy')
    destination = Path('electronic')
    destination.mkdir()
    manifest = {'storage': storage, 'total_bytes': total, 'files': []}
    for name in request['files']:
        source, target = Path('source')/name, destination/name
        before = source.stat()
        digest = hashlib.sha256()
        with source.open('rb') as inp, target.open('wb') as out:
            for chunk in iter(lambda: inp.read(1024*1024), b''):
                digest.update(chunk)
                out.write(chunk)
        after = source.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise RuntimeError('Source changed while preserving '+name)
        if not target.stat().st_size:
            raise RuntimeError('Empty electronic file: '+name)
        manifest['files'].append({'name': name, 'size_bytes': after.st_size, 'sha256': digest.hexdigest()})
    Path('manifest.json').write_text(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
