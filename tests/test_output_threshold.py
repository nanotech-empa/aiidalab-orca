"""Size-aware original-output retrieval, explicit extracts and CLI behavior."""

import io
import json
from types import SimpleNamespace

import pytest
from aiida import orm
from aiida.common import AttributeDict, LinkType
from click.testing import CliRunner

from aiida_empa_orca import native_logs
from aiida_empa_orca.native_output import output_content, read_manifest, retrieval_warnings
from test_casci import output
from test_native_output import parse


def collect(root, limit, *, mode='remote', text=None):
    text = text if text is not None else output() + 'unselected iteration details\n' * 20
    directory = root / native_logs.DIRECTORY
    directory.mkdir()
    (directory / 'aiida.out').write_text(text)
    policy = {'mode': mode, 'maxsizeoutput': limit}
    if mode == 'stash':
        policy['stash_directory'] = '/reviewed/stash'
    record = native_logs.collect_output({'protocol': 'casci-v1', 'policy': policy}, root)
    native_logs.validate_manifest(record)
    repo = orm.FolderData()
    for path in root.iterdir():
        if path.is_file():
            repo.base.repository.put_object_from_file(path, path.name)
    node = SimpleNamespace(inputs=AttributeDict({'native_output_policy': orm.Dict(dict=policy)}),
                           outputs={'remote_stash': object()} if mode == 'stash' else {})
    assert read_manifest(node, repo.base.repository, 'casci-v1') == record
    return text, record, repo


@pytest.mark.parametrize('mode', ['remote', 'stash'])
@pytest.mark.parametrize('delta', [-1, 0, 1])
def test_exact_size_boundary_and_scientific_equivalence(tmp_path, aiida_profile, mode, delta):
    text = output() + 'full iteration details\n' * 20
    original, record, repo = collect(tmp_path, len(text.encode()) + delta, mode=mode, text=text)
    content = output_content(repo.base.repository)
    assert parse(content) == parse(original)
    assert (tmp_path / 'native_output/aiida.out').read_text() == text
    if delta >= 0:
        assert repo.base.repository.get_object_content('aiida.out') == text
        assert record['retrieved_outputs'][0]['kind'] == 'full'
        assert not record['warnings']
        assert not (tmp_path / 'aiida_summary.out').exists()
    else:
        notice = repo.base.repository.get_object_content('aiida.out')
        assert 'notice, not the original output' in notice and 'aiida_summary.out' in notice
        assert 'maxsizeoutput=' in notice and 'native_output/aiida.out' in notice
        assert 'full iteration details' not in content
        assert record['summary']['name'] == 'aiida_summary.out'
        assert record['warnings'] == [notice.strip()]


def test_standard_output_does_not_inherit_the_extract_line_limit(tmp_path, aiida_profile):
    text = output() + 'X' * (native_logs.LINE_LIMIT + 1) + '\n'
    _, record, repo = collect(tmp_path, native_logs.DEFAULT_MAXSIZEOUTPUT, text=text)
    assert record['retrieved_outputs'][0]['kind'] == 'full'
    assert repo.base.repository.get_object_content('aiida.out') == text


def test_casscf_outputs_choose_retention_independently(tmp_path):
    text = output()
    directory = tmp_path / 'native_output'
    directory.mkdir()
    (directory / 'aiida.out').write_text(text + 'detailed CI vector\n' * 500)
    (directory / 'verify.out').write_text(text)
    limit = len(text.encode())
    record = native_logs.collect_output({'protocol': 'casscf-v1',
        'policy': {'mode': 'remote', 'maxsizeoutput': limit}}, tmp_path)
    native_logs.validate_manifest(record)
    assert [r['kind'] for r in record['retrieved_outputs']] == ['summary_notice', 'full']
    assert (tmp_path / 'verify.out').read_text() == text
    assert record['summary']['name'] == 'aiida_summary.out'
    assert record['additional_summaries'][0]['name'] == 'verify.out'
    record['maxsizeoutput'] += 1
    with pytest.raises(ValueError, match='threshold'):
        native_logs.validate_manifest(record)


@pytest.mark.parametrize('oversized', [False, True])
def test_outputcat_displays_original_or_explicit_notice(tmp_path, aiida_profile, oversized):
    from aiida.cmdline.commands.cmd_calcjob import calcjob_outputcat
    _, record, repo = collect(tmp_path, 0 if oversized else native_logs.DEFAULT_MAXSIZEOUTPUT)
    calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.casci')
    calc.base.attributes.set('options', {'output_filename': 'aiida.out'})
    calc.store()
    repo.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label='retrieved')
    repo.store()
    manifest = orm.Dict(dict=record)
    manifest.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label='native_output_manifest')
    manifest.store()
    result = CliRunner().invoke(calcjob_outputcat, [str(calc.pk)])
    assert result.exit_code == 0, result.output
    assert result.output == repo.base.repository.get_object_content('aiida.out')
    assert bool(retrieval_warnings(calc)) == oversized
    if oversized:
        extract = CliRunner().invoke(calcjob_outputcat, [str(calc.pk), 'aiida_summary.out'])
        assert extract.exit_code == 0 and 'CAS-SCF STATES FOR BLOCK' in extract.output


def test_notice_or_extract_tampering_is_rejected(tmp_path, aiida_profile):
    _, record, repo = collect(tmp_path, 0)
    node = SimpleNamespace(inputs=AttributeDict({'native_output_policy': orm.Dict(dict=record['policy'])}), outputs={})
    repo.base.repository.put_object_from_filelike(io.StringIO('altered notice'), 'aiida.out')
    with pytest.raises(ValueError, match='checksum'):
        read_manifest(node, repo.base.repository, 'casci-v1')


@pytest.mark.parametrize('value', [-1, True, 1.5, '5MB'])
def test_invalid_byte_threshold_is_rejected(value):
    with pytest.raises(ValueError, match='maxsizeoutput'):
        native_logs.output_policy({'mode': 'remote', 'maxsizeoutput': value})


def test_output_threshold_widget_defaults_to_five_mib():
    from aiidalab_orca.retention import FullFileRetention
    from aiidalab_orca.widget_lifecycle import close_widget_tree
    panel = FullFileRetention()
    try:
        assert panel.values() == {'mode': 'remote', 'maxsizeoutput': 5 * 1024**2}
        revision = panel.revision
        panel.maxsizeoutput.value = 2
        assert panel.values()['maxsizeoutput'] == 2 * 1024**2 and panel.revision > revision
    finally:
        close_widget_tree(panel)


def test_historical_summary_manifest_remains_readable(aiida_profile):
    import hashlib
    content = b'ORCA TERMINATED NORMALLY\n'
    item = {'name': 'aiida.out', 'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    record = {'schema': native_logs.SCHEMA, 'protocol': 'casci-v1', 'directory': 'native_output',
              'status': 'complete', 'policy': {'mode': 'remote'}, 'summary': item, 'files': [item]}
    repo = orm.FolderData()
    repo.base.repository.put_object_from_filelike(io.BytesIO(content), 'aiida.out')
    repo.base.repository.put_object_from_filelike(io.StringIO(json.dumps(record)), native_logs.MANIFEST)
    node = SimpleNamespace(inputs=AttributeDict({'native_output_policy': orm.Dict(dict={'mode': 'remote'})}), outputs={})
    assert read_manifest(node, repo.base.repository, 'casci-v1') == record
