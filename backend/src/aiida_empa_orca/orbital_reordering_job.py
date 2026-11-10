"""Provenance-bound signed permutation of a shared orbital file; no SCF."""

from importlib.resources import files
import json

from aiida import common, engine, orm
from aiida.parsers import Parser

from . import common_orbitals as common_mos
from .artifacts import resolve_electronic, storage_builder, stash_options
from .native_logs import DIRECTORY, output_policy
from .native_output import compact_spec, prepare_compact, read_manifest
from .orbital_reordering import selection_plan, SCHEMA
from .rendering import helper_resources, calcjob_options

PROCESS = 'aiida.workflows:empa_orca.orbital_reordering'
CALCULATION = 'aiida.calculations:empa_orca.orbital_reordering'
PREPARATION = 'signed_permutation_verified_v1'
PROTOCOL = 'orbital-reordering-v1'


def compatibility_storage_policy(retention):
    """Legacy input shape; native_output_policy owns this reference's Leave/Stash.

    Zero prevents full-file retrieval. Leave records no stash destination;
    consumers of this new type must use its explicit native-output policy.
    """
    policy = output_policy(retention)
    return {'threshold_mb': 0, 'stash_directory': policy.get('stash_directory', '')}


def protect_reordered_input(info, inputs, folder):
    """Check the staged GBW before any native downstream consumer can read it."""
    if 'orbital_reference' not in inputs:
        return info
    ref = inputs.orbital_reference.get_dict()
    if ref.get('preparation') != PREPARATION:
        return info
    digest = ref['orbital_mapping']['prepared_file_sha256']
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError('Missing verified reordered-file identity')
    # SERIAL shell stages need not stop on a failing command. Stage under an
    # unreadable-by-ORCA name even if the helper executable never starts.
    renamed = False
    for key in ('local_copy_list', 'remote_copy_list'):
        copies = []
        for source_uuid, source_name, target in getattr(info, key, None) or []:
            if target == 'reference.gbw':
                target = 'unchecked_reference.gbw'
                renamed = True
            copies.append((source_uuid, source_name, target))
        setattr(info, key, copies)
    if not renamed:
        raise ValueError('The reordered input must be staged under its unchecked filename')
    text = ('from pathlib import Path\nimport hashlib\n'
            "source = Path('reference.gbw')\n"
            "unchecked = Path('unchecked_reference.gbw')\n"
            "with unchecked.open('rb') as stream:\n"
            "    digest = hashlib.file_digest(stream, 'sha256').hexdigest()\n"
            f'if digest != {digest!r}:\n'
            "    raise ValueError('Reordered input GBW checksum changed')\n"
            'unchecked.rename(source)\n')
    with folder.open('verify_reordering.py', 'w') as stream:
        stream.write(text)
    check = common.CodeInfo()
    check.code_uuid, check.cmdline_params = inputs.compact_code.uuid, ['verify_reordering.py']
    check.stdout_name, check.join_files, check.withmpi = 'verify_reordering.log', True, False
    info.codes_info.insert(0, check)
    info.retrieve_list.append('verify_reordering.log')
    return info


def validate_request(reference, plan):
    # Initial native qualification is deliberately limited to SCF-derived sets.
    if (reference.get('preparation') != 'moread_noiter_v1' or
            reference.get('kind') not in ('QRO', 'restricted')):
        raise ValueError('Native reordering currently accepts original QRO/restricted references; '
                         'CASSCF, imported and already reordered inputs need separate qualification')
    fresh = selection_plan(reference, plan['source_active_space'], plan['source_occupations'],
        source_reference_uuid=plan['source_reference_uuid'], source_file_sha256=plan['source_file_sha256'])
    if fresh != plan or not fresh['permutation_needed']:
        raise ValueError('Review a nonidentity permutation; contiguous selections retain their original reference')


def checked_resources(reference, values):
    if set(values) != {'memory_mb', 'wallclock_seconds'}:
        raise ValueError('Review an explicit preparation memory and wall-time budget')
    budget = helper_resources(values, default_seconds=600)
    # Several decoded JSON documents, Python numeric objects and dense matrices
    # coexist. This conservative preflight is not a memory-use guarantee.
    estimate = 1024 * reference['n_orbitals']**2
    if estimate > .75 * budget['memory_mb'] * 1024**2:
        raise ValueError('Full MO/overlap JSON exceeds the reviewed memory allowance; review a larger budget')
    return budget


def validate_catalog(catalog, reference, remote, plan):
    record, ref = catalog.get_dict(), reference.get_dict()
    producer = catalog.creator
    if (producer is None or not producer.is_finished_ok or
            producer.process_type != 'aiida.calculations:empa_orca.orbital_catalog' or
            producer.inputs.orbital_reference.uuid != reference.uuid or
            record['orbital_reference_uuid'] != str(reference.uuid) or
            record['source_remote_uuid'] != str(remote.uuid)):
        raise ValueError('The reviewed orbital catalog must belong to this successful source')
    selected = record['sets'][ref['kind']]
    if (selected['filename'] != ref['filename'] or selected['sha256'] != plan['source_file_sha256'] or
            [r['index'] for r in selected['levels']] != list(range(ref['n_orbitals'])) or
            [r['occupation'] for r in selected['levels']] != plan['source_occupations']):
        raise ValueError('The source occupations/file identity differ from the reviewed native catalog')


def _script(stage):
    """The job-local helper uses the exact submitted pure implementation."""
    return '''import hashlib, json, runpy
from pathlib import Path
request = json.loads(Path('reordering_request.json').read_text())
api = runpy.run_path('orbital_reordering.py')
def sha(name):
    with Path(name).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
plan, reference = request['plan'], request['reference']
if sha('source.gbw') != plan['source_file_sha256']:
    raise ValueError('Staged source checksum differs from the reviewed orbital catalog')
source = json.loads(Path('source.json').read_text())
''' + ('''prepared = api['permute_document'](source, reference, plan)
Path('prepared.json').write_text(json.dumps(prepared, allow_nan=False))
''' if stage == 'prepare' else '''actual = json.loads(Path('prepared_copy.json').read_text())
checks = api['verify_roundtrip'](source, actual, reference, plan)
record = {'schema': api['SCHEMA'], 'plan': plan, 'checks': checks,
          'source_file_sha256': sha('source.gbw'),
          'prepared_file_sha256': sha('prepared_copy.gbw'),
          'prepared_size_bytes': Path('prepared_copy.gbw').stat().st_size}
Path('prepared_copy.gbw').rename('aiida.gbw')
Path('reordering.json').write_text(json.dumps(record, indent=2, allow_nan=False))
for name in ('source.json', 'prepared.json', 'prepared_copy.json'):
    Path(name).unlink()
''')


class OrbitalReorderingCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure': orm.StructureData, 'orbital_reference': orm.Dict,
                         'source_remote': orm.RemoteData, 'catalog': orm.Dict,
                         'plan': orm.Dict, 'export_code': orm.AbstractCode}.items():
            spec.input(key, valid_type=typ)
        common_mos.source_spec(spec)
        compact_spec(spec)
        spec.input('metadata.options.parser_name', default='empa_orca.orbital_reordering')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('orbital_reference', valid_type=orm.Dict)
        spec.output('orbital_mapping', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_REORDERING', message='Signed orbital permutation did not pass validation.')

    def prepare_for_submission(self, folder):
        from .casci import validate_reference
        validate_reference(self.inputs.orbital_reference, self.inputs.source_remote)
        ref, plan = self.inputs.orbital_reference.get_dict(), self.inputs.plan.get_dict()
        validate_request(ref, plan)
        validate_catalog(self.inputs.catalog, self.inputs.orbital_reference, self.inputs.source_remote, plan)
        if (str(self.inputs.structure.uuid) != ref['structure_uuid'] or
                str(self.inputs.orbital_reference.uuid) != plan['source_reference_uuid'] or
                self.inputs.source_filename.value != ref['filename']):
            raise ValueError('The geometry, source reference or file differs from the reviewed permutation')
        if 'compact_code' not in self.inputs:
            raise ValueError('Configure the ORCA tools helper on this computer')
        if any(code.computer.uuid != self.inputs.code.computer.uuid for code in
               (self.inputs.export_code, self.inputs.compact_code)):
            raise ValueError('ORCA, its exporter and the helper must use the source computer')
        with folder.open('reordering_request.json', 'w') as stream:
            json.dump({'reference': ref, 'plan': plan}, stream, allow_nan=False)
        with folder.open('orbital_reordering.py', 'w') as stream:
            stream.write(files('aiida_empa_orca').joinpath('orbital_reordering.py').read_text())
        for name, stage in [('prepare_reordering.py', 'prepare'), ('check_reordering.py', 'check')]:
            with folder.open(name, 'w') as stream:
                stream.write(_script(stage))
        with folder.open('orca.json.conf', 'w') as stream:
            json.dump({'MOCoefficients': True, 'Basisset': True,
                       '1elIntegrals': ['S'], 'JSONFormats': ['json']}, stream)
        info = common.CalcInfo()
        common_mos.copy_orbital(info, self.inputs, target='source.gbw')
        stages = [(self.inputs.export_code, ['source.gbw', '-json'], 'aiida.out'),
                  (self.inputs.compact_code, ['prepare_reordering.py'], 'prepare.out'),
                  (self.inputs.export_code, ['prepared.json', '-gbw'], 'write.out'),
                  (self.inputs.export_code, ['prepared_copy.gbw', '-json'], 'verify.out'),
                  (self.inputs.compact_code, ['check_reordering.py'], 'check.out')]
        info.codes_info = []
        for executable, args, log in stages:
            code = common.CodeInfo()
            code.code_uuid, code.cmdline_params, code.stdout_name = executable.uuid, args, log
            code.join_files, code.withmpi = True, False
            info.codes_info.append(code)
        info = prepare_compact(info, self.inputs, folder, PROTOCOL)
        info.retrieve_list.append('reordering.json')
        return info


class OrbitalReorderingParser(Parser):
    def parse(self, **kwargs):
        try:
            repo = self.retrieved.base.repository
            if len(repo.get_object_content('reordering.json', mode='rb')) > 2*1024**2:
                raise ValueError('Orbital mapping exceeds the compact-result limit')
            record = json.loads(repo.get_object_content('reordering.json'))
            ref, plan = self.node.inputs.orbital_reference.get_dict(), self.node.inputs.plan.get_dict()
            validate_request(ref, plan)
            if (record['schema'] != SCHEMA or record['plan'] != plan or
                    record['checks']['array_checks_passed'] is not True or
                    record['checks']['plan_sha256'] != plan['plan_sha256'] or
                    record['source_file_sha256'] != plan['source_file_sha256']):
                raise ValueError('The verified mapping differs from the reviewed source/selection')
            from .artifacts import remote_files
            remote_files(self.node.computer, self.node.outputs.remote_folder.get_remote_path(),
                names=['aiida.gbw'], expected={'aiida.gbw': record['prepared_size_bytes']})
            manifest = read_manifest(self.node, repo, PROTOCOL, logger=self.logger)
            orbital = dict(ref, preparation=PREPARATION, filename='aiida.gbw',
                           parent_orbital_reference_uuid=plan['source_reference_uuid'],
                           reordered_active_space=plan['native_active_space'],
                           orbital_mapping=record)
            self.out('orbital_reference', orm.Dict(dict=orbital))
            self.out('orbital_mapping', orm.Dict(dict=record))
            self.out('native_output_manifest', orm.Dict(dict=manifest))
        except (KeyError, ValueError, OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_REORDERING


class OrbitalReorderingWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure': orm.StructureData, 'orbital_reference': orm.Dict,
                         'source_remote': orm.RemoteData, 'code': orm.AbstractCode,
                         'export_code': orm.AbstractCode, 'storage_code': orm.AbstractCode,
                         'storage_policy': orm.Dict, 'catalog': orm.Dict, 'plan': orm.Dict, 'resources': orm.Dict,
                         'native_output_policy': orm.Dict}.items():
            spec.input(key, valid_type=typ)
        for key, typ in {'orbital_reference': orm.Dict, 'orbital_mapping': orm.Dict,
                         'remote_folder': orm.RemoteData, 'retrieved': orm.FolderData,
                         'native_output_manifest': orm.Dict}.items():
            spec.output(key, valid_type=typ)
        spec.outline(cls.setup, cls.prepare, cls.inspect,
                     engine.if_(cls.should_stash)(cls.preserve, cls.inspect_storage), cls.results)
        spec.exit_code(400, 'ERROR_SOURCE', message='Orbital source or reviewed mapping is invalid.')
        spec.exit_code(401, 'ERROR_PREPARATION', message='Signed permutation failed; no new reference is available.')
        spec.exit_code(402, 'ERROR_STORAGE', message='Orbital-file preservation failed.')

    def setup(self):
        from .casci import validate_reference
        try:
            ref = validate_reference(self.inputs.orbital_reference, self.inputs.source_remote)
            validate_request(ref, self.inputs.plan.get_dict())
            validate_catalog(self.inputs.catalog, self.inputs.orbital_reference,
                             self.inputs.source_remote, self.inputs.plan.get_dict())
            if self.inputs.code.uuid != self.inputs.orbital_reference.creator.inputs.code.uuid:
                raise ValueError('Use the ORCA code bound to the source reference')
            self.ctx.retention = output_policy(self.inputs.native_output_policy.get_dict())
            if self.inputs.storage_policy.get_dict() != compatibility_storage_policy(self.ctx.retention):
                raise ValueError('The compatibility storage input must describe this new reference, not its source')
            self.ctx.budget = checked_resources(ref, self.inputs.resources.get_dict())
            self.ctx.location = resolve_electronic(self.inputs.source_remote, names=[ref['filename']])
        except (KeyError, ValueError, OSError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def prepare(self):
        b = OrbitalReorderingCalculation.get_builder()
        for key in ('structure', 'orbital_reference', 'source_remote', 'catalog', 'code', 'export_code', 'plan'):
            b[key] = self.inputs[key]
        common_mos.attach_orbital(b, self.ctx.location, self.inputs.orbital_reference.get_dict()['filename'])
        b.compact_code = self.inputs.storage_code
        b.native_output_policy = orm.Dict(dict=self.ctx.retention)
        b.metadata.options = calcjob_options(self.inputs.source_remote,
            seconds=self.ctx.budget['wallclock_seconds'], memory_mb=self.ctx.budget['memory_mb'])
        b.metadata.options.environment_variables = {'OMP_NUM_THREADS': '1',
            'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
        if self.should_stash():
            b.metadata.options.stash = stash_options(self.ctx.retention['stash_directory'], DIRECTORY)
        b.metadata.disable_cache = True
        return engine.ToContext(pending=self.submit(b))

    def inspect(self):
        self.ctx.prepared_uuid = str(self.ctx.pending.uuid)
        success = self.ctx.pending.is_finished_ok
        del self.ctx['pending']
        if not success:
            return self.exit_codes.ERROR_PREPARATION

    def should_stash(self):
        return self.ctx.retention['mode'] == 'stash'

    def preserve(self):
        node = orm.load_node(self.ctx.prepared_uuid)
        b = storage_builder(node.outputs.remote_folder, self.inputs.storage_code,
                            {'threshold_mb': 0, 'stash_directory': self.ctx.retention['stash_directory']},
                            names=['aiida.gbw'])
        b.metadata.options = calcjob_options(node.outputs.remote_folder,
            seconds=self.ctx.budget['wallclock_seconds'], memory_mb=self.ctx.budget['memory_mb'])
        b.metadata.options.environment_variables = {'OMP_NUM_THREADS': '1',
            'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
        return engine.ToContext(pending_storage=self.submit(b))

    def inspect_storage(self):
        success = self.ctx.pending_storage.is_finished_ok
        del self.ctx['pending_storage']
        if not success:
            return self.exit_codes.ERROR_STORAGE

    def results(self):
        node = orm.load_node(self.ctx.prepared_uuid)
        for key in self.spec().outputs:
            if key in node.outputs:
                self.out(key, node.outputs[key])
