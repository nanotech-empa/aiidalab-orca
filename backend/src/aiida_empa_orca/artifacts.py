"""Size-aware electronic-file preservation and provenance-based resolution."""

import hashlib
import json
from importlib.resources import files
from pathlib import PurePosixPath
import stat
import re

from aiida import common, engine, orm
from aiida.parsers import Parser

ELECTRONIC_FILES = ('aiida.gbw', 'aiida.densities', 'aiida.densitiesinfo')
STORAGE_PROCESS = 'aiida.calculations:empa_orca.electronic_storage'


def electronic_names(names):
    """Explicit flat file bundles, also supporting common orbitals and CASCI."""
    if not names or len(set(names)) != len(names) or any(
            not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+', name)
            for name in names):
        raise ValueError('Electronic files must be distinct, plain filenames')
    return tuple(names)


def storage_policy(values):
    values = dict(values)
    if set(values)-{'threshold_mb', 'stash_directory'}:
        raise ValueError('Unknown wavefunction storage option')
    threshold = values.get('threshold_mb', 100)
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 10000:
        raise ValueError('Wavefunction retrieval threshold must be between 0 and 10000 MiB')
    path = values.get('stash_directory', '')
    if not isinstance(path, str) or not PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts or path == '/':
        raise ValueError('Choose an absolute stash directory, without .. components')
    return {'threshold_mb': threshold, 'stash_directory': path}


def remote_files(computer, basepath, names=ELECTRONIC_FILES, expected=None):
    from .reference import ArtifactUnavailable
    result = []
    try:
        with computer.get_transport() as transport:
            for name in names:
                a = transport.get_attribute(str(PurePosixPath(basepath)/name))
                if not stat.S_ISREG(a.st_mode) or a.st_size <= 0:
                    raise ValueError('Missing or empty electronic file: '+name)
                if expected and a.st_size != expected[name]:
                    raise ValueError('Electronic file size changed: '+name)
                result.append({'name': name, 'size_bytes': a.st_size})
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ArtifactUnavailable(f'Electronic storage is inaccessible: {exc}') from exc
    return result


def repository_files(folder, manifest):
    for item in manifest['files']:
        digest, size = hashlib.sha256(), 0
        with folder.base.repository.open('electronic/'+item['name'], mode='rb') as handle:
            for chunk in iter(lambda: handle.read(1024*1024), b''):
                digest.update(chunk)
                size += len(chunk)
        if size != item['size_bytes'] or digest.hexdigest() != item['sha256']:
            raise ValueError('Stored wavefunction integrity check failed: '+item['name'])


def stored_location(node):
    if not node.is_finished_ok or 'manifest' not in node.outputs:
        raise ValueError('Electronic storage did not complete')
    manifest = node.outputs.manifest.get_dict()
    if manifest['storage'] == 'repository':
        repository_files(node.outputs.retrieved, manifest)
        return {'kind': 'repository', 'uuid': str(node.outputs.retrieved.uuid), 'files': manifest['files'],
                'storage_uuid': str(node.uuid)}
    if 'remote_stash' not in node.outputs:
        raise ValueError('The electronic stash is missing')
    stash = node.outputs.remote_stash
    path = str(PurePosixPath(stash.target_basepath)/'electronic')
    remote_files(stash.computer, path, names=[f['name'] for f in manifest['files']],
                 expected={f['name']: f['size_bytes'] for f in manifest['files']})
    return {'kind': 'stash', 'uuid': str(stash.uuid), 'path': path, 'files': manifest['files'],
            'storage_uuid': str(node.uuid)}


def storage_nodes(remote):
    return orm.QueryBuilder().append(orm.RemoteData, filters={'uuid': remote.uuid}, tag='source').append(
        orm.CalcJobNode, with_incoming='source', edge_filters={'label': 'source_folder'}, tag='store',
        filters={'process_type': STORAGE_PROCESS, 'attributes.process_state': 'finished', 'attributes.exit_status': 0},
        project=['uuid']).order_by({'store': {'ctime': 'desc'}}).all(flat=True)


def resolve_electronic(remote, names=ELECTRONIC_FILES):
    """Prefer validated durable copies; retain only plain identifiers in callers."""
    from .reference import check_wavefunction, ArtifactUnavailable
    unavailable = None
    for uuid in storage_nodes(remote):
        try:
            location = stored_location(orm.load_node(uuid))
            if set(names).issubset({item['name'] for item in location['files']}):
                return location
        except ArtifactUnavailable as exc:
            unavailable = exc
        except (KeyError, ValueError, FileNotFoundError):
            continue
    try:
        manifest = (check_wavefunction(remote) if tuple(names) == ELECTRONIC_FILES else
                    remote_files(remote.computer, remote.get_remote_path(), names=names))
    except (FileNotFoundError, ValueError):
        if unavailable:
            raise unavailable
        raise
    return {'kind': 'remote', 'uuid': str(remote.uuid), 'path': remote.get_remote_path(), 'files': manifest}


class ElectronicStorageCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('source_folder', valid_type=orm.RemoteData)
        spec.input('policy', valid_type=orm.Dict)
        spec.input('filenames', valid_type=orm.List, required=False)
        spec.input('metadata.options.parser_name', default='empa_orca.electronic_storage')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('manifest', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_STORAGE', message='Electronic file preservation failed; inspect storage.log.')

    def prepare_for_submission(self, folder):
        source = self.inputs.source_folder
        if source.computer.uuid != self.inputs.code.computer.uuid:
            raise ValueError('Electronic preservation must run on the source computer')
        policy = storage_policy(self.inputs.policy.get_dict())
        names = electronic_names(self.inputs.filenames.get_list()) if 'filenames' in self.inputs else ELECTRONIC_FILES
        sizes = remote_files(source.computer, source.get_remote_path(), names=names)
        storage = 'repository' if sum(x['size_bytes'] for x in sizes) <= policy['threshold_mb']*1024**2 else 'stash'
        request = {'files': list(names), 'threshold_bytes': policy['threshold_mb']*1024**2, 'storage': storage}
        with folder.open('request.json', 'w') as handle:
            json.dump(request, handle)
        with folder.open('store_electronic.py', 'w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('scripts/store_electronic.py').read_text())
        expected_stash = stash_options(policy['stash_directory'], 'electronic') if storage == 'stash' else {}
        if dict(self.inputs.metadata.options.get('stash', {})) != expected_stash:
            raise ValueError('Storage size changed or stash options are inconsistent; rebuild with storage_builder')
        code = common.CodeInfo()
        code.code_uuid = self.inputs.code.uuid
        code.cmdline_params = ['store_electronic.py']
        code.stdout_name = 'storage.log'
        code.join_files = True
        info = common.CalcInfo()
        info.codes_info = [code]
        info.remote_symlink_list = [(source.computer.uuid, source.get_remote_path(), 'source')]
        info.retrieve_list = ['manifest.json', 'storage.log'] + (['electronic'] if storage == 'repository' else [])
        return info


class ElectronicStorageParser(Parser):
    def parse(self, **kwargs):
        try:
            manifest = json.loads(self.retrieved.base.repository.get_object_content('manifest.json'))
            names = (electronic_names(self.node.inputs.filenames.get_list()) if 'filenames' in self.node.inputs
                     else ELECTRONIC_FILES)
            if {f['name'] for f in manifest['files']} != set(names):
                raise ValueError('Incomplete electronic bundle')
            if manifest['storage'] == 'repository':
                repository_files(self.retrieved, manifest)
            elif manifest['storage'] != 'stash' or 'remote_stash' not in self.node.outputs:
                raise ValueError('No verified stash result')
            self.out('manifest', orm.Dict(dict=manifest))
        except (OSError, KeyError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_STORAGE


def stash_options(directory, source):
    return {'stash_mode': 'copy', 'target_base': directory,
            'source_list': [source], 'fail_on_missing': True}


def storage_builder(remote, code, policy, names=ELECTRONIC_FILES):
    policy = storage_policy(policy)
    builder = ElectronicStorageCalculation.get_builder()
    builder.source_folder, builder.code, builder.policy = remote, code, orm.Dict(dict=policy)
    names = electronic_names(names)
    if names != ELECTRONIC_FILES:
        builder.filenames = orm.List(list=list(names))
    from .rendering import calcjob_options
    builder.metadata.options = calcjob_options(remote)
    sizes = remote_files(remote.computer, remote.get_remote_path(), names=names)
    if sum(item['size_bytes'] for item in sizes) > policy['threshold_mb']*1024**2:
        builder.metadata.options.stash = stash_options(policy['stash_directory'], 'electronic')
    # Reuse is explicit and availability-checked; a cached missing stash must not win.
    builder.metadata.disable_cache = True
    return builder


class ElectronicStorageMixin:
    """Optional preservation after a scientific workflow, independently reusable."""
    @classmethod
    def storage_spec(cls, spec):
        spec.input('storage_policy', valid_type=orm.Dict, required=False)
        spec.input('storage_code', valid_type=orm.AbstractCode, required=False)
        spec.output('electronic_manifest', valid_type=orm.Dict, required=False)
        spec.output('electronic_repository', valid_type=orm.FolderData, required=False)
        spec.output('electronic_stash', valid_type=orm.RemoteStashFolderData, required=False)
        spec.exit_code(405, 'ERROR_ELECTRONIC_STORAGE', message='Scientific results are available, but electronic-file preservation failed.')

    def validate_storage_inputs(self):
        if ('storage_policy' in self.inputs) != ('storage_code' in self.inputs):
            raise ValueError('Specify storage_policy and storage_code together')
        if 'storage_policy' in self.inputs:
            storage_policy(self.inputs.storage_policy.get_dict())
            if self.inputs.storage_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('The preservation code must use the ORCA computer')

    def should_preserve(self):
        return 'storage_policy' in self.inputs and 'retrieved' in self.outputs

    def preserve_electronic(self):
        try:
            remote = self.outputs['retrieved'].creator.outputs.remote_folder
            policy = storage_policy(self.inputs.storage_policy.get_dict())
            for uuid in storage_nodes(remote):
                source = orm.load_node(uuid)
                if source.is_finished_ok:
                    try:
                        stored_location(source)
                        self.ctx.electronic_storage_uuid = str(uuid)
                        return
                    except (OSError, ValueError, KeyError):
                        pass
            builder = storage_builder(remote, self.inputs.storage_code, policy)
            return engine.ToContext(electronic_storage=self.submit(builder))
        except (ValueError, OSError, KeyError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_ELECTRONIC_STORAGE

    def inspect_preservation(self):
        node = (orm.load_node(self.ctx.electronic_storage_uuid) if self.ctx.get('electronic_storage_uuid')
                else self.ctx.electronic_storage)
        try:
            location = stored_location(node)
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_ELECTRONIC_STORAGE
        self.out('electronic_manifest', node.outputs.manifest)
        self.out('electronic_repository' if location['kind'] == 'repository' else 'electronic_stash',
                 node.outputs.retrieved if location['kind'] == 'repository' else node.outputs.remote_stash)
