"""Hamiltonian descriptors and transient staging, with no integral repository copy."""

import hashlib
import re
import shutil
from pathlib import Path, PurePosixPath

from aiida import orm

from .artifacts import resolve_electronic


def hamiltonian_identity(data):
    if isinstance(data, orm.SinglefileData):
        # Historical Hamiltonians remain valid inputs; never migrate their nodes.
        with data.open(mode='rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    record = data.get_dict()
    if (set(record) != {'schema', 'name', 'size_bytes', 'sha256'}
            or record['schema'] != 'orca_energy_hamiltonian_v1'
            or record['name'] != 'hamiltonian.fcidump'
            or type(record['size_bytes']) is not int or record['size_bytes'] <= 0
            or not re.fullmatch('[0-9a-f]{64}', record['sha256'])):
        raise ValueError('Invalid remote Hamiltonian descriptor')
    return record['sha256']


def hamiltonian_location(data):
    hamiltonian_identity(data)
    producer = data.creator
    if (producer is None or not producer.is_finished_ok
            or producer.process_type != 'aiida.calculations:empa_orca.energy_hamiltonian'):
        raise ValueError('Use a descriptor from a successful native Hamiltonian export')
    location = resolve_electronic(producer.outputs.remote_folder, names=['hamiltonian.fcidump'])
    record = data.get_dict()
    if location['files'] != [{key: record[key] for key in ('name', 'size_bytes', 'sha256')}]:
        raise ValueError('Hamiltonian descriptor differs from its native file manifest')
    return location


def stage_hamiltonian(info, data, computer, folder):
    """Copy locally on the same computer; otherwise transiently relay via AiiDAlab."""
    if isinstance(data, orm.SinglefileData):
        info.local_copy_list.append((data.uuid, data.filename, 'hamiltonian.fcidump'))
        return
    location = hamiltonian_location(data)
    source = orm.load_node(location['uuid'])
    path = str(PurePosixPath(location['path']) / 'hamiltonian.fcidump')
    if source.computer.uuid == computer.uuid:
        info.remote_copy_list = [(computer.uuid, path, 'hamiltonian.fcidump')]
        return
    target = Path(folder.get_abs_path('hamiltonian.fcidump'))
    size = data.get_dict()['size_bytes']
    if shutil.disk_usage(target.parent).free < size + max(64 * 1024**2, size // 10):
        raise ValueError('Insufficient temporary disk space to transfer the Hamiltonian between computers')
    # AiiDA uploads this sandbox file but excludes it from the CalcJob input
    # repository. Provenance retains the native descriptor, manifest and checksum.
    info.provenance_exclude_list = ['hamiltonian.fcidump']
    try:
        with source.computer.get_transport() as transport:
            transport.getfile(path, str(target))
        with target.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        if target.stat().st_size != size or sha != hamiltonian_identity(data):
            raise ValueError('Transferred Hamiltonian differs from its recorded checksum')
    except Exception:
        target.unlink(missing_ok=True)
        raise
