"""Checkpoint references and bounded, data-only native DMRG retrieval."""

from pathlib import PurePosixPath
import hashlib
import re

from aiida import orm

ARRAYS = ('sweep_energies.npy', 'bond_dims.npy', 'discarded_weights.npy', 'E_oh.npy')
ARRAY_LIMIT = 2 * 1024**2


def compact_arrays(nroots):
    return ARRAYS + (('1pdm.npy',) if nroots == 1 else
                     tuple(f'1pdm-{i}-{i}.npy' for i in range(nroots)))


def checkpoint_node(node):
    """New checkpoints stay remote; old retrieved checkpoints remain usable."""
    if node.outputs.results.get_dict().get('checkpoint_storage') == 'remote':
        return node.outputs.remote_folder
    node.outputs.retrieved.base.repository.get_object('mps/mps_info.bin')
    return node.outputs.retrieved


def checkpoint_manifest(states):
    """Small content hashes identify external MPS without downloading them."""
    parent = states.creator
    saved = parent.outputs.retrieved
    expected = parent.outputs.results.get_dict().get('checkpoint_manifest_sha256')
    if expected:
        text = saved.base.repository.get_object_content('mps.sha256')
        if hashlib.sha256(text.encode()).hexdigest() != expected:
            raise ValueError('Stored checkpoint manifest changed')
    else:
        # Historical immutable repository hashes verify migration to RemoteData.
        repository = states.base.repository if isinstance(states, orm.FolderData) else saved.base.repository
        backend = saved.backend.get_repository()
        rows = []
        for root, _, names in repository.walk('mps'):
            for name in names:
                path = str(PurePosixPath(root) / name)
                item = repository.get_object(path)
                rows.append(f'{backend.get_object_hash(item.key)}  {path}\n')
        text = ''.join(sorted(rows))
    validate_manifest(text)
    return text


def validate_manifest(text):
    if not text or len(text.encode()) > ARRAY_LIMIT:
        raise ValueError('Missing or oversized checkpoint manifest')
    paths = []
    for line in text.splitlines():
        match = re.fullmatch(r'[a-f0-9]{64}  (mps/[^\r\n\\]+)', line)
        if not match or '..' in PurePosixPath(match[1]).parts:
            raise ValueError('Invalid checkpoint manifest')
        paths.append(match[1])
    if len(set(paths)) != len(paths) or 'mps/mps_info.bin' not in paths:
        raise ValueError('Incomplete checkpoint manifest')
    return len(paths)


VERIFY_SCRIPT = '''#!/bin/sh
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c parent-mps.sha256 || exit 1
else
    shasum -a 256 -c parent-mps.sha256 || exit 1
fi
'''


def validate_checkpoint(states, code, settings, hamiltonian_sha256, *, continuation=False):
    parent = states.creator
    if (parent is None or not parent.is_terminated or parent.exit_status not in (0, 311)
            or parent.process_type != 'aiida.calculations:empa_orca.dmrg'
            or 'results' not in parent.outputs):
        raise ValueError('Restart requires a completed native DMRG result')
    previous = parent.inputs.settings.get_dict()
    if any(previous[key] != settings[key] for key in ('nroots', 'ordering')):
        raise ValueError('Restart must preserve roots and orbital ordering')
    if parent.inputs.code.base.extras.get('block2', {}).get('version') != '0.5.4':
        raise ValueError('Restart requires the same verified native Block2 format')
    result = parent.outputs.results.get_dict()
    if result['hamiltonian_sha256'] != hamiltonian_sha256:
        raise ValueError('Restart Hamiltonian differs from the parent')
    if isinstance(states, orm.RemoteData):
        if states.computer.uuid != code.computer.uuid:
            raise ValueError('Remote checkpoints must stay on their calculation computer')
        path = PurePosixPath(states.get_remote_path())
        if not path.is_absolute() or path == PurePosixPath('/') or '..' in path.parts:
            raise ValueError('Invalid remote checkpoint path')
    else:
        states.base.repository.get_object('mps/mps_info.bin')
    if continuation and not (result.get('fixed_m_sweep_continuation') or
            result.get('two_site_to_one_site_at_sweep') == 24 and result['sweeps_completed'] >= 25):
        raise ValueError('Continue sweeps only from a completed one-site checkpoint')
    return previous['max_bond_dimension']


def collector_script(nroots, maxsizeoutput):
    """POSIX utilities only; runs after Block2 inside the same scheduler job."""
    if type(maxsizeoutput) is not int or maxsizeoutput < 0:
        raise ValueError('maxsizeoutput must be a nonnegative byte count')
    names = ' '.join(compact_arrays(nroots))
    return f'''#!/bin/sh
native_status=${{1:-1}}
umask 077
mkdir -p compact || exit 1
test -f dmrg.out && test ! -L dmrg.out || exit 1
size=$(wc -c < dmrg.out)
traceback=false
if grep -q Traceback dmrg.out; then traceback=true; fi
spin_adapted=false
if grep -q 'SPIN ADAPTED - REAL DOMAIN - DOUBLE PREC' dmrg.out; then spin_adapted=true; fi
summary=false
if test "$size" -le {maxsizeoutput} && test {maxsizeoutput} -gt 0; then
    cp dmrg.out compact/dmrg.out || exit 1
else
    summary=true
    printf 'Full native DMRG output exceeds maxsizeoutput. See dmrg_summary.out. The original dmrg.out remains in the remote calculation directory.\\n' > compact/dmrg.out
    (head -n 40 dmrg.out; printf '\\n--- final native output ---\\n'; tail -n 120 dmrg.out) | head -c 1048576 > compact/dmrg_summary.out
fi
for name in {names}; do
    test -f "mps/$name" && test ! -L "mps/$name" || exit 1
    array_size=$(wc -c < "mps/$name")
    test "$array_size" -le {ARRAY_LIMIT} || exit 1
    cp "mps/$name" "compact/$name" || exit 1
done
test -f mps/mps_info.bin && test ! -L mps/mps_info.bin || exit 1
if test -n "$(find mps -type l -print)"; then exit 1; fi
if command -v sha256sum >/dev/null 2>&1; then
    find mps -type f -exec sha256sum {{}} \\; > compact/mps.sha256 || exit 1
else
    find mps -type f -exec shasum -a 256 {{}} \\; > compact/mps.sha256 || exit 1
fi
if test "$(wc -c < compact/mps.sha256)" -gt {ARRAY_LIMIT}; then
    rm compact/mps.sha256
    exit 1
fi
printf '{{"schema_version":1,"checkpoint_storage":"remote","native_exit_status":%s,"traceback":%s,"spin_adapted":%s,"output_bytes":%s,"output_is_summary":%s}}\\n' "$native_status" "$traceback" "$spin_adapted" "$size" "$summary" > compact/dmrg-storage.json
exit "$native_status"
'''
