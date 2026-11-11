"""AiiDA staging for size-aware native output; collection runs remotely."""

from importlib.resources import files
import json

from aiida import common, orm

from .artifacts import stash_options
from .native_logs import DIRECTORY, MANIFEST, PROTOCOLS, output_policy, validate_manifest, validate_summary


def output_name(repository, name='aiida.out'):
    """New oversized outputs have a distinct extract; historical files stay readable."""
    summary = name.removesuffix('.out') + '_summary.out'
    return summary if summary in repository.list_object_names() else name


def output_content(repository, name='aiida.out', *, mode='r'):
    return repository.get_object_content(output_name(repository, name), mode=mode)


def open_output(repository, name='aiida.out', *, mode='r'):
    return repository.open(output_name(repository, name), mode=mode)


def retrieval_warnings(node):
    """Plain result notices from this operation's nodes, including explicit reuse."""
    warnings = []
    candidates = [node, *node.called_descendants]
    if 'retrieved' in node.outputs and node.outputs.retrieved.creator is not None:
        candidates.append(node.outputs.retrieved.creator)
    for candidate in candidates:
        if 'native_output_manifest' in candidate.outputs:
            warnings.extend(candidate.outputs.native_output_manifest.get_dict().get('warnings', []))
    return list(dict.fromkeys(warnings))


def compact_spec(spec):
    # Optional only so historical CalcJob nodes can still load their process class.
    spec.input('compact_code', valid_type=orm.AbstractCode, required=False)
    spec.input('metadata.options.output_filename', valid_type=str, default='aiida.out')
    spec.input('native_output_policy', valid_type=orm.Dict,
               default=lambda: orm.Dict(dict={'mode': 'remote'}))
    spec.output('native_output_manifest', valid_type=orm.Dict, required=False)


def prepare_compact(info, inputs, folder, protocol, *, extra_request=None):
    """Keep executable arguments/inputs intact; redirect stdout before collection."""
    if 'compact_code' not in inputs:
        raise ValueError('Configure the ORCA tools runtime before submitting compact native output')
    if inputs.compact_code.computer.uuid != inputs.code.computer.uuid:
        raise ValueError('Collect native output on the ORCA calculation computer')
    if inputs.metadata.options.get('additional_retrieve_list'):
        raise ValueError('Additional retrieval is incompatible with bounded native output')
    policy = output_policy(inputs.native_output_policy.get_dict())
    expected = stash_options(policy['stash_directory'], DIRECTORY) if policy['mode'] == 'stash' else {}
    if dict(inputs.metadata.options.get('stash', {})) != expected:
        raise ValueError('Native-output stash differs from the reviewed retention policy')
    logs = PROTOCOLS[protocol]
    if tuple(c.stdout_name for c in info.codes_info) != logs:
        raise ValueError('Native executable outputs differ from the collection protocol')
    folder.get_subfolder(DIRECTORY, create=True)
    with folder.open('native_output_request.json', 'w') as handle:
        json.dump({**(extra_request or {}), 'protocol': protocol, 'policy': policy}, handle)
    with folder.open('compact_output.py', 'w') as handle:
        handle.write(files('aiida_empa_orca').joinpath('native_logs.py').read_text())
    if protocol in ('scf-v1', 'optimization-v1'):
        with folder.open('compact_scf.py', 'w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('compact_scf.py').read_text())
    if protocol == 'energy-export-v1':
        with folder.open('compact_energy.py', 'w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('energy_files.py').read_text())
    for code in info.codes_info:
        code.stdout_name = DIRECTORY + '/' + code.stdout_name
    compact = common.CodeInfo()
    compact.code_uuid, compact.cmdline_params = inputs.compact_code.uuid, ['compact_output.py']
    compact.stdout_name, compact.join_files = 'compact_output.log', True
    info.codes_info.append(compact)
    info.codes_run_mode = common.CodeRunMode.SERIAL
    info.retrieve_list = [*logs, MANIFEST, 'native_output_tail.txt', 'compact_output.log']
    info.retrieve_list.append('*_summary.out')
    if len(logs) > 1:
        info.retrieve_list.append('verify_tail.txt')
    if protocol in ('scf-v1', 'optimization-v1'):
        info.retrieve_list.append('scf_results.json')
    if protocol == 'optimization-v1':
        info.retrieve_list.extend(['aiida.xyz', 'aiida_trj.xyz'])
    if protocol == 'vibrations-v1':
        info.retrieve_list.append('aiida.hess')
    return info


def read_manifest(node, repository, protocol, *, logger=None):
    """Verify both summaries before the unchanged scientific parser uses them."""
    if MANIFEST not in repository.list_object_names():
        if 'compact_code' in node.inputs:
            raise ValueError('Native-output collection failed; inspect compact_output.log and the remote originals')
        return None  # Historical, full retrieved logs remain readable.
    record = validate_manifest(json.loads(repository.get_object_content(MANIFEST)))
    if record['protocol'] != protocol or record['policy'] != output_policy(node.inputs.native_output_policy.get_dict()):
        raise ValueError('Native-output manifest differs from the reviewed protocol/retention')
    for name in PROTOCOLS[protocol]:
        item = next(s for s in [record['summary'], *record.get('additional_summaries', [])]
                    if s.get('source_name', s['name']) == name)
        validate_summary(record, repository.get_object_content(item['name'], mode='rb'), name)
    import hashlib
    for item in record.get('retrieved_outputs', []):
        content = repository.get_object_content(item['name'], mode='rb')
        if len(content) != item['size_bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError('Retrieved native output/notice differs from its recorded checksum')
    for item in record.get('compact_files', []):
        content = repository.get_object_content(item['name'], mode='rb')
        if len(content) != item['size_bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
            raise ValueError('Compact SCF/geometry result differs from its checksum: ' + item['name'])
    if record['policy']['mode'] == 'stash' and 'remote_stash' not in node.outputs:
        raise ValueError('The requested native-output stash is missing')
    if logger is not None:
        for warning in record.get('warnings', []):
            logger.warning(warning)
    return record
