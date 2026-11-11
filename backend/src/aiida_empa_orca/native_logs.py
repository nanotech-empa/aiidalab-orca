"""Bounded native-output summaries; this stdlib-only module also runs remotely.

The original log and property file remain in ``native_output/``. Only the
selected validation lines, a bounded diagnostic tail and a manifest are retrieved.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re


DIRECTORY = 'native_output'
MANIFEST = 'native_output.json'
SUMMARY_LIMIT = 2 * 1024**2
TAIL_LIMIT = 64 * 1024
LINE_LIMIT = 64 * 1024
SCHEMA = 'orca_native_output_v1'
STATE_MARKERS = re.compile(
    r'ORCA TERMINATED NORMALLY|Number of active (?:electrons|orbitals)|'
    r'Total number of electrons|^\s*Active\s+\d+\s*-\s*\d+|'
    r'CI-PROBLEM SOLVED|>>>\s*CAS-CI\.|'
    r'^\s*(?:Active|Internal|External)\s+Orbitals|'
    r'CAS-SCF STATES FOR BLOCK|^\s*ROOT\s+\d+\s*:|'
    r'Spin-Determinant CI Printing|DENSITY MATRIX|^\s*WARNING:', re.I)


def output_policy(values=None):
    """Explicit retention of full native files; no retrieval mode exists."""
    values = dict(values or {'mode': 'remote'})
    if set(values) - {'mode', 'stash_directory'}:
        raise ValueError('Unknown full-file retention setting')
    mode = values.get('mode')
    if mode not in ('remote', 'stash'):
        raise ValueError('Choose remote retention or stashing for full files')
    if mode == 'remote':
        return {'mode': 'remote'}
    directory = values.get('stash_directory', '')
    if (not isinstance(directory, str) or not PurePosixPath(directory).is_absolute()
            or directory == '/' or '..' in PurePosixPath(directory).parts):
        raise ValueError('Choose an absolute stash directory on the calculation computer')
    return {'mode': mode, 'stash_directory': directory}


def read_state_summary(handle):
    """Keep all validation markers, including late warnings and repeated blocks."""
    result, size = [], 0
    for line in handle:
        if STATE_MARKERS.search(line):
            size += len(line.encode('utf-8'))
            if size > SUMMARY_LIMIT:
                raise ValueError('CASCI validation summary exceeds the compact-output budget')
            result.append(line)
    return ''.join(result)


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _file_record(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Native output must be a regular file: ' + str(path))
    before = path.stat()
    checksum = _digest(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Native file changed during collection: ' + path.name)
    return {'name': path.name, 'size_bytes': after.st_size, 'sha256': checksum}


def collect_output(request, root=Path('.')):
    """Collect CASCI output with bounded memory and bounded retrieved files.

    Exhausting a software budget invalidates the summary; no lines or states
    are silently dropped from an accepted result. The complete source survives.
    """
    if request.get('protocol') != 'casci-v1':
        raise ValueError('Unsupported native-output collection protocol')
    policy = output_policy(request['policy'])
    root = Path(root)
    original = root / DIRECTORY / 'aiida.out'
    selected, size, error = [], 0, None
    checksum = hashlib.sha256()
    before = original.stat()
    if original.is_symlink() or not original.is_file():
        raise ValueError('Native output is not a regular file')
    with original.open('rb') as stream:
        while raw := stream.readline(LINE_LIMIT + 1):
            checksum.update(raw)
            if len(raw) > LINE_LIMIT:
                error = 'Native output contains a line exceeding the compact-output budget'
                for chunk in iter(lambda: stream.read(1024**2), b''):
                    checksum.update(chunk)
                break
            if STATE_MARKERS.search(raw.decode('utf-8', errors='replace')):
                size += len(raw)
                if size > SUMMARY_LIMIT:
                    error = 'CASCI validation summary exceeds the compact-output budget'
                elif error is None:
                    raw.decode('utf-8')  # Scientific validation lines must decode exactly.
                    selected.append(raw)
    after = original.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        error = 'Native output changed during collection'
    summary = b''.join(selected)
    header = b'# Compact ORCA validation summary. Full log: native_output/aiida.out; see native_output.json.\n'
    if error is None:
        if len(header) + len(summary) > SUMMARY_LIMIT:
            error = 'CASCI validation summary exceeds the compact-output budget'
        else:
            summary = header + summary
    (root / 'aiida.out').write_bytes(summary)
    with original.open('rb') as stream:
        stream.seek(max(0, after.st_size - TAIL_LIMIT))
        (root / 'native_output_tail.txt').write_bytes(stream.read(TAIL_LIMIT))
    records = [{'name': 'aiida.out', 'size_bytes': after.st_size, 'sha256': checksum.hexdigest()}]
    prop = root / 'aiida.property.txt'
    if prop.exists():
        if prop.is_symlink() or not prop.is_file():
            raise ValueError('Native property output is not a regular file')
        target = root / DIRECTORY / prop.name
        if target.exists():
            raise ValueError('Refusing to overwrite a preserved native property output')
        prop.replace(target)  # Move only this CalcJob's output, without copying it.
        records.append(_file_record(target))
    record = {'schema': SCHEMA, 'protocol': 'casci-v1', 'policy': policy,
              'status': 'error' if error else 'complete', 'error': error,
              'directory': DIRECTORY, 'files': records,
              'summary': {'name': 'aiida.out', 'size_bytes': len(summary),
                          'sha256': hashlib.sha256(summary).hexdigest()},
              'diagnostic_tail_limit': TAIL_LIMIT}
    (root / MANIFEST).write_text(json.dumps(record, allow_nan=False, indent=2))
    return record


def validate_manifest(record):
    if (record.get('schema') != SCHEMA or record.get('protocol') != 'casci-v1'
            or record.get('directory') != DIRECTORY):
        raise ValueError('Unsupported native-output manifest')
    output_policy(record['policy'])
    if record.get('status') != 'complete':
        raise ValueError(record.get('error') or 'Native-output collection did not complete')
    summary = record['summary']
    if summary['name'] != 'aiida.out' or not 0 <= summary['size_bytes'] <= SUMMARY_LIMIT:
        raise ValueError('Invalid compact-output budget or filename')
    names = [f['name'] for f in record['files']]
    if not names or names[0] != 'aiida.out' or len(set(names)) != len(names):
        raise ValueError('Missing or ambiguous full native output')
    for item in [summary, *record['files']]:
        if (item['name'] not in ('aiida.out', 'aiida.property.txt')
                or type(item['size_bytes']) is not int or item['size_bytes'] < 0
                or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('Invalid native-output identity')
    return record


def validate_summary(record, content):
    validate_manifest(record)
    item = record['summary']
    if len(content) != item['size_bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
        raise ValueError('Compact output differs from its recorded checksum')


def main():
    request = json.loads(Path('native_output_request.json').read_text())
    record = collect_output(request)
    print('Collected compact native output:', record['status'])


if __name__ == '__main__':
    main()
