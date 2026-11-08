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
CASSCF_MARKERS = re.compile(
    STATE_MARKERS.pattern + r'|Guess MOs are being read from file|'
    r'Input Geometry matches current geometry|Input basis set matches current basis set|'
    r'THE CAS-SCF GRADIENT HAS CONVERGED|DOING ONE FINAL ITERATION FOR PRINTING|'
    r'^BLOCK\s+\d+\s+WEIGHT=|^\s+Multiplicity\s+\.\.\.|ROOT=\d+\s+WEIGHT=|'
    r'^\s+PrintLevel|(?:CI|CAS[- ]?SCF).*?(?:NOT CONVERGED|DID NOT CONVERGE)', re.I)
SCF_MARKERS = re.compile(
    r'SCF (?:CONVERGED AFTER|NOT CONVERGED)|ORCA TERMINATED NORMALLY|'
    r'FINAL SINGLE POINT ENERGY|THE OPTIMIZATION HAS CONVERGED|Program Version|'
    r'Expectation value of <S\*\*2>|Number of Electrons\s+NEL|Total number of electrons|'
    r'^\s*WARNING:|ERROR|DID NOT CONVERGE', re.I)
COMMON_MARKERS = re.compile(
    r'ORCA TERMINATED NORMALLY|MaxIter==0 has been chosen - skipping the SCF|'
    r'SCF CONVERGED AFTER|Guess MOs are being read from file|'
    r'Input Geometry matches current geometry|Input basis set matches current basis set|'
    r'Number of (?:basis functions|contracted basis functions)|Number of Electrons\s+NEL|'
    r'Quasi-Restricted Orbitals were saved in aiida.qro|^\s*WARNING:|ERROR|DID NOT CONVERGE', re.I)
CORRELATION_MARKERS = re.compile(
    CASSCF_MARKERS.pattern + r'|Program Version|Number of Electrons\s+NEL|'
    r'Hartree-Fock type|\b(?:Charge|Mult)\s+\.{2,}|SCF CONVERGED AFTER|'
    r'ORCA\s+MP2|^\s*Total Energy|RI-MP2 CORRELATION ENERGY|MP2 TOTAL ENERGY|'
    r'FINAL SINGLE POINT ENERGY|Freezing NCore=|Number of frozen core electrons|'
    r'Orbital Range Operator|Expectation value of <S\*\*2>|'
    r'ORCA finished by error|Segmentation fault|poorly|normaliz|project|CMatrix|'
    r'negative|denominator|intruder|NOT CONVERGED|DID NOT CONVERGE|'
    r'\bPT2\s*=|<\s*(?:NEVPT2|CASPT2)\s*>|Orbitals.*canonical|'
    r'(?:NEVPT2|CASPT2) Results|\bMULT\s+\d+,\s*ROOT\s+\d+|'
    r'Reference\s+(?:Energy|Weight)|Last\s+frozen\s+orbital|'
    r'DLPNO-NEVPT2 SETTINGS|^TCut\w+:|(?:Energy|Residual) convergence tolerance|'
    r'LMP2-Iter=|\|\s*\d+>|CASPT2.*Levelshift|CASPT2 calculation|'
    r'Iter\s+EPT2\s+EHylleraas\s+residual norm\s+Time|'
    r'^\s*\d+\s+[-+.\dEeDd]+\s+[-+.\dEeDd]+\s+[-+.\dEeDd]+\s+[-+.\dEeDd]+\s*$', re.I)
OPTICAL_MARKERS = re.compile(
    SCF_MARKERS.pattern + r'|ORCA-CIS/TD-DFT FINISHED WITHOUT ERROR|'
    r'NOT CONVERGED|poorly\s+normalized|imaginary\s+excitation|negative\s+excitation|'
    r'ORCA finished by error|Segmentation fault|\b(?:Charge|Mult)\s+\.{2,}|'
    r'^\s*Total Energy\s*:|Tamm-Dancoff approximation|'
    r'Number of roots to be determined|Convergence tolerance for the residual|'
    r'Maximum residual norm|CONVERGENCE OF RESIDUAL NORM REACHED|'
    r'^TD-DFT(?:/TDA)? EXCITED STATES|^STATE\s+\d+:|'
    r'^\s*\d+[ab]\s*->\s*\d+[ab]\s*:|NATURAL TRANSITION ORBITALS|'
    r'Natural Transition Orbitals were saved in|^\s*E=\s*[-+.\dEeDd]+ au|'
    r'ABSORPTION SPECTRUM VIA TRANSITION (?:ELECTRIC DIPOLE MOMENTS|VELOCITY)|'
    r'^\s*\d+-\d+\S*\s+->\s+\d+-\d+\S*\s+', re.I)
VIBRATION_MARKERS = re.compile(
    SCF_MARKERS.pattern + r'|RAMAN SPECTRUM|'
    r'^\s*\d+:\s+[-\d.]+\s+[-\d.Ee+]+\s+[-\d.Ee+]+(?:\s*\(|\s*$|\s+[-\d.Ee+]+\s*\()', re.I)
PROTOCOLS = {'casci-v1': ('aiida.out',), 'casscf-v1': ('aiida.out', 'verify.out'),
             'scf-v1': ('aiida.out',), 'optimization-v1': ('aiida.out',),
             'common-orbitals-v1': ('aiida.out',), 'correlation-v1': ('aiida.out',),
             'optical-v1': ('aiida.out',), 'vibrations-v1': ('aiida.out',)}
COMPACT_LIMITS = {'scf_results.json': 2 * 1024**2, 'aiida.xyz': 2 * 1024**2,
                  'aiida_trj.xyz': 8 * 1024**2, 'aiida.hess': 16 * 1024**2}
HESSIAN_SECTIONS = {'hessian', 'normal_modes', 'vibrational_frequencies', 'atoms',
                    'dipole_derivatives', 'polarizability_derivatives', 'ir_spectrum', 'frequency_scale_factor'}


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


def _collect_log(root, name, markers, tail_name, *, mark_omissions=False):
    original = root / DIRECTORY / name
    selected, size, error = [], 0, None
    checksum = hashlib.sha256()
    gap = False
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
            if markers.search(raw.decode('utf-8', errors='replace')):
                # Do not turn formerly separated words/diagnostics into a new
                # multiline match when omitting an unrelated native section.
                piece = (b'# Native section omitted.\n' if mark_omissions and gap and selected else b'') + raw
                size += len(piece)
                if size > SUMMARY_LIMIT:
                    error = 'Native validation summary exceeds the compact-output budget'
                elif error is None:
                    raw.decode('utf-8')  # Scientific validation lines must decode exactly.
                    selected.append(piece)
                gap = False
            elif raw.strip():
                gap = True
    after = original.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        error = 'Native output changed during collection'
    summary = b''.join(selected)
    header = f'# Compact ORCA validation summary. Full log: native_output/{name}; see native_output.json.\n'.encode()
    if error is None:
        if len(header) + len(summary) > SUMMARY_LIMIT:
            error = 'Native validation summary exceeds the compact-output budget'
        else:
            summary = header + summary
    (root / name).write_bytes(summary)
    with original.open('rb') as stream:
        stream.seek(max(0, after.st_size - TAIL_LIMIT))
        (root / tail_name).write_bytes(stream.read(TAIL_LIMIT))
    return ({'name': name, 'size_bytes': after.st_size, 'sha256': checksum.hexdigest()},
            {'name': name, 'size_bytes': len(summary), 'sha256': hashlib.sha256(summary).hexdigest()}, error)


def _collect_hessian(root):
    """Keep the exact numeric sections consumed by the existing vibration parser."""
    source, target = root / 'aiida.hess', root / DIRECTORY / 'aiida.hess'
    if source.is_symlink() or not source.is_file() or target.exists():
        raise ValueError('Missing or unsafe native Hessian')
    source.replace(target)
    record = _file_record(target)
    content, active = bytearray(), False
    with target.open('rb') as stream:
        while raw := stream.readline(LINE_LIMIT + 1):
            if len(raw) > LINE_LIMIT:
                raise ValueError('Native Hessian line exceeds the compact-output budget')
            line = raw.decode('utf-8').strip()
            if line.startswith('$'):
                active = line[1:] in HESSIAN_SECTIONS
            if active and line and not line.startswith('#'):
                content.extend((' '.join(line.split()) + '\n').encode())
                if len(content) > COMPACT_LIMITS['aiida.hess']:
                    raise ValueError('Vibrational result exceeds the compact-Hessian budget')
    source.write_bytes(content)
    return record, _file_record(source)


def collect_output(request, root=Path('.')):
    """Bound each summary and tail; exhausting a budget never accepts partial data."""
    protocol = request.get('protocol')
    if protocol not in PROTOCOLS:
        raise ValueError('Unsupported native-output collection protocol')
    policy, root = output_policy(request['policy']), Path(root)
    records, summaries, errors = [], [], []
    molecular = protocol in ('scf-v1', 'optimization-v1')
    markers = (OPTICAL_MARKERS if protocol == 'optical-v1'
               else VIBRATION_MARKERS if protocol == 'vibrations-v1'
               else CORRELATION_MARKERS if protocol == 'correlation-v1'
               else SCF_MARKERS if molecular else COMMON_MARKERS if protocol == 'common-orbitals-v1'
               else STATE_MARKERS if protocol == 'casci-v1' else CASSCF_MARKERS)
    for name in PROTOCOLS[protocol]:
        tail = 'native_output_tail.txt' if name == 'aiida.out' else 'verify_tail.txt'
        original, summary, error = _collect_log(root, name, markers, tail,
                                               mark_omissions=protocol in ('correlation-v1', 'optical-v1', 'vibrations-v1'))
        records.append(original)
        summaries.append(summary)
        if error:
            errors.append(name + ': ' + error)
    for name in PROTOCOLS[protocol]:
        prop = root / name.replace('.out', '.property.txt')
        if prop.exists():
            if prop.is_symlink() or not prop.is_file():
                raise ValueError('Native property output is not a regular file')
            target = root / DIRECTORY / prop.name
            if target.exists():
                raise ValueError('Refusing to overwrite a preserved native property output')
            prop.replace(target)  # Only this CalcJob's output, without copying it.
            records.append(_file_record(target))
    compact = []
    if protocol == 'vibrations-v1':
        try:
            original, result = _collect_hessian(root)
            records.append(original)
            compact.append(result)
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(str(exc))
    if protocol in ('correlation-v1', 'optical-v1', 'vibrations-v1'):
        # Preserve this job's generated files without copying inputs or touching
        # the parent wavefunction. Optical NTOs remain resolvable from this bundle.
        for path in sorted(root.iterdir()):
            if (not re.fullmatch(r'aiida[._][A-Za-z0-9_.-]+', path.name)
                    or path.name in ('aiida.out', 'aiida.inp', 'aiida.coords.xyz', 'aiida.hess')):
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError('Unsupported native output: ' + path.name)
            target = root / DIRECTORY / path.name
            if target.exists():
                raise ValueError('Refusing to overwrite native output: ' + path.name)
            path.replace(target)
            records.append(_file_record(target))
    if molecular and not errors:
        try:
            # orca-tools uses runpy without adding the CalcJob directory to
            # sys.path. Load the reviewed sibling script by its staged path.
            import runpy
            collect = runpy.run_path(str(root / 'compact_scf.py'))['collect']
            retained, results = collect(root, protocol, SUMMARY_LIMIT)
            records.extend(_file_record(path) for path in retained)
            compact = [_file_record(path) for path in results]
            summaries[0] = _file_record(root / 'aiida.out')
        except Exception as exc:
            errors.append('Compact SCF collection failed: ' + str(exc)[:2000])
    error = '; '.join(errors) or None
    record = {'schema': SCHEMA, 'protocol': protocol, 'policy': policy,
              'status': 'error' if error else 'complete', 'error': error,
              'directory': DIRECTORY, 'files': records,
              'summary': summaries[0],
              'diagnostic_tail_limit': TAIL_LIMIT}
    if len(summaries) > 1:
        record['additional_summaries'] = summaries[1:]
    if molecular:
        record['compact_files'] = compact
    if protocol == 'vibrations-v1':
        record['compact_files'] = compact
    (root / MANIFEST).write_text(json.dumps(record, allow_nan=False, indent=2))
    return record


def validate_manifest(record):
    if (record.get('schema') != SCHEMA or record.get('protocol') not in PROTOCOLS
            or record.get('directory') != DIRECTORY):
        raise ValueError('Unsupported native-output manifest')
    output_policy(record['policy'])
    if record.get('status') != 'complete':
        raise ValueError(record.get('error') or 'Native-output collection did not complete')
    summaries = [record['summary'], *record.get('additional_summaries', [])]
    expected = list(PROTOCOLS[record['protocol']])
    if [s['name'] for s in summaries] != expected or any(
            not 0 <= s['size_bytes'] <= SUMMARY_LIMIT for s in summaries):
        raise ValueError('Invalid compact-output budget or filenames')
    names = [f['name'] for f in record['files']]
    if names[:len(expected)] != expected or len(set(names)) != len(names):
        raise ValueError('Missing or ambiguous full native output')
    for item in [*summaries, *record['files']]:
        allowed = (item['name'] in expected + [n.replace('.out', '.property.txt') for n in expected]
                   + ['aiida.xyz', 'aiida_trj.xyz'] or record['protocol'] in ('correlation-v1', 'optical-v1', 'vibrations-v1')
                   and re.fullmatch(r'aiida[._][A-Za-z0-9_.-]+', item['name']))
        if (not allowed
                or type(item['size_bytes']) is not int or item['size_bytes'] < 0
                or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
            raise ValueError('Invalid native-output identity')
    if record['protocol'] in ('scf-v1', 'optimization-v1', 'vibrations-v1'):
        expected_files = (['aiida.hess'] if record['protocol'] == 'vibrations-v1' else
                          ['scf_results.json'] + (['aiida.xyz', 'aiida_trj.xyz'] if record['protocol'] == 'optimization-v1' else []))
        compact = record.get('compact_files', [])
        if [item['name'] for item in compact] != expected_files:
            raise ValueError('Missing compact SCF/geometry results')
        for item in compact:
            if (type(item['size_bytes']) is not int or not 0 < item['size_bytes'] <= COMPACT_LIMITS[item['name']]
                    or not re.fullmatch('[0-9a-f]{64}', item['sha256'])):
                raise ValueError('Invalid compact SCF/geometry identity')
    return record


def validate_summary(record, content, name='aiida.out'):
    validate_manifest(record)
    item = next(s for s in [record['summary'], *record.get('additional_summaries', [])] if s['name'] == name)
    if len(content) != item['size_bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
        raise ValueError('Compact output differs from its recorded checksum')


def main():
    request = json.loads(Path('native_output_request.json').read_text())
    record = collect_output(request)
    print('Collected compact native output:', record['status'])


if __name__ == '__main__':
    main()
