"""Staged SCF/geometry collector, reusing aiida-orca's existing cclib reader.

No AiiDA nodes or profile are used here. Large AO/MO arrays stay in the native
files; energies, atomic observables, final orbital table and geometry history
are the compact public results.
"""

import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import sys


PARAMETER_FIELDS = (
    'natom', 'atomnos', 'atommasses', 'coreelectrons', 'charge', 'mult', 'nmo', 'nbasis', 'homos', 'mosyms',
    'moenergies', 'mooccnos', 'scfenergies', 'optdone', 'atomcharges', 'atomspins', 'moments',
)
METADATA_FIELDS = ('package', 'package_version', 'success', 'methods', 'basis_set',
                   'functional', 'symmetry_detected', 'symmetry_used', 'unrestricted')
LIMITS = {'scf_results.json': 2 * 1024**2, 'aiida.xyz': 2 * 1024**2,
          'aiida_trj.xyz': 8 * 1024**2}


class _Diagnostics:
    """Bound reader messages independently of the intact scientific output."""
    def __init__(self):
        self.stream, self.remaining = sys.stdout, 64 * 1024

    def write(self, text):
        raw = text.encode('utf-8')[:self.remaining]
        self.remaining -= len(raw)
        self.stream.write(raw.decode('utf-8', errors='ignore'))
        return len(text)

    def flush(self):
        self.stream.flush()


def _json_value(value):
    if hasattr(value, 'tolist'):
        return value.tolist()
    raise TypeError('Unsupported compact SCF value: ' + type(value).__name__)


def read_parameters(path):
    # The exact same reader used by OrcaBaseParser; no second scientific parser.
    from aiida_orca.parsers.cclib.ccio import ccread
    diagnostics = _Diagnostics()
    with redirect_stdout(diagnostics), redirect_stderr(diagnostics):
        data = ccread(str(path)).getattributes()
    result = {key: data[key] for key in PARAMETER_FIELDS if key in data}
    if 'atomcoords' in data:
        result['atomcoords'] = data['atomcoords'][-1:]
    result['metadata'] = {key: data.get('metadata', {})[key] for key in METADATA_FIELDS
                          if key in data.get('metadata', {})}
    result['compact_output'] = {'schema': 'orca_scf_results_v1',
                                'full_output': 'native_output/aiida.out',
                                'atomcoords': 'final_frame_only',
                                'omitted_metadata_fields': sorted(set(data.get('metadata', {})) - set(result['metadata'])),
                                'omitted_fields': sorted(set(data) - set(result))}
    return json.dumps(result, default=_json_value, allow_nan=False).encode()


def last_orbital_table(path, limit):
    """Preserve the last native table verbatim, with the original stop markers."""
    table, size, active = [], 0, False
    with path.open('rb') as stream:
        for raw in stream:
            if b'ORBITAL ENERGIES' in raw:
                table, size, active = [], 0, True
            if active:
                size += len(raw)
                if size > limit:
                    raise ValueError('The final orbital table exceeds the compact-output budget')
                table.append(raw)
                if b'POPULATION ANALYSIS' in raw or raw.strip().startswith(b'*Only'):
                    active = False
    return b''.join(table)


def collect(root, protocol, summary_limit):
    root = Path(root)
    original = root / 'native_output' / 'aiida.out'
    content = read_parameters(original)
    if len(content) > LIMITS['scf_results.json']:
        raise ValueError('SCF results exceed the compact-output budget; full results remain remote')
    (root / 'scf_results.json').write_bytes(content)
    summary = root / 'aiida.out'
    combined = summary.read_bytes() + last_orbital_table(original, summary_limit)
    if len(combined) > summary_limit:
        raise ValueError('SCF validation/orbital summary exceeds the compact-output budget')
    summary.write_bytes(combined)
    retained, compact = [], [root / 'scf_results.json']
    if protocol == 'optimization-v1':
        for name in ('aiida.xyz', 'aiida_trj.xyz'):
            path, target = root / name, root / 'native_output' / name
            if path.is_symlink() or not path.is_file() or target.exists():
                raise ValueError('Missing, ambiguous or nonregular geometry output: ' + name)
            path.replace(target)
            retained.append(target)
            if target.stat().st_size > LIMITS[name]:
                raise ValueError('Geometry history exceeds the compact-output budget: ' + name)
            path.write_bytes(target.read_bytes())
            compact.append(path)
    return retained, compact
