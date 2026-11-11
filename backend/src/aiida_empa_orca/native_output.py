"""AiiDA staging for bounded native output; the collector itself is stdlib only."""

from importlib.resources import files
import json

from aiida import common, orm

from .artifacts import stash_options
from .native_logs import DIRECTORY, MANIFEST, PROTOCOLS, output_policy, validate_manifest, validate_summary


def compact_spec(spec):
    # Optional only so historical CalcJob nodes can still load their process class.
    spec.input('compact_code', valid_type=orm.AbstractCode, required=False)
    spec.input('native_output_policy', valid_type=orm.Dict,
               default=lambda: orm.Dict(dict={'mode': 'remote'}))
    spec.output('native_output_manifest', valid_type=orm.Dict, required=False)


def prepare_compact(info, inputs, folder, protocol):
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
        json.dump({'protocol': protocol, 'policy': policy}, handle)
    with folder.open('compact_output.py', 'w') as handle:
        handle.write(files('aiida_empa_orca').joinpath('native_logs.py').read_text())
    for code in info.codes_info:
        code.stdout_name = DIRECTORY + '/' + code.stdout_name
    compact = common.CodeInfo()
    compact.code_uuid, compact.cmdline_params = inputs.compact_code.uuid, ['compact_output.py']
    compact.stdout_name, compact.join_files = 'compact_output.log', True
    info.codes_info.append(compact)
    info.codes_run_mode = common.CodeRunMode.SERIAL
    info.retrieve_list = [*logs, MANIFEST, 'native_output_tail.txt', 'compact_output.log']
    if len(logs) > 1:
        info.retrieve_list.append('verify_tail.txt')
    return info


def read_manifest(node, repository, protocol):
    """Verify both summaries before the unchanged scientific parser uses them."""
    if MANIFEST not in repository.list_object_names():
        if 'compact_code' in node.inputs:
            raise ValueError('Native-output collection failed; inspect compact_output.log and the remote originals')
        return None  # Historical, full retrieved logs remain readable.
    record = validate_manifest(json.loads(repository.get_object_content(MANIFEST)))
    if record['protocol'] != protocol or record['policy'] != output_policy(node.inputs.native_output_policy.get_dict()):
        raise ValueError('Native-output manifest differs from the reviewed protocol/retention')
    for name in PROTOCOLS[protocol]:
        validate_summary(record, repository.get_object_content(name, mode='rb'), name)
    if record['policy']['mode'] == 'stash' and 'remote_stash' not in node.outputs:
        raise ValueError('The requested native-output stash is missing')
    return record
