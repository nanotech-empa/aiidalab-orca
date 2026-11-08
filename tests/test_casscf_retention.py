"""Compact CASSCF logs retain the complete optimization/readback contract."""

import json

import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import casscf, native_logs
from aiida_empa_orca.artifacts import stash_options
from test_casci import common_reference, electronic_source, reference_data  # noqa: F401
from test_casscf import SPACE, native_output, objective


def collect_pair(root, first, second):
    directory = root / native_logs.DIRECTORY
    directory.mkdir()
    for name, text in (('aiida.out', first), ('verify.out', second)):
        (directory / name).write_text(text)
    (root / 'aiida.property.txt').write_text('full optimized properties')
    (root / 'verify.property.txt').write_text('full readback properties')
    return native_logs.collect_output({'protocol': 'casscf-v1', 'policy': {'mode': 'remote'}}, root)


def test_large_casscf_and_readback_logs_preserve_the_exact_verified_result(tmp_path):
    ref = reference_data()
    settings = casscf.casscf_settings(objective(), ref, SPACE)
    body = '    [20u]   0.0000012345\n' * 100000
    first = native_output(settings).replace('ORCA TERMINATED NORMALLY', body + 'ORCA TERMINATED NORMALLY')
    second = native_output(settings, frozen=True)
    record = collect_pair(tmp_path, first, second)
    for name in ('aiida.out', 'verify.out'):
        content = (tmp_path / name).read_bytes()
        assert len(content) < 2000
        native_logs.validate_summary(record, content, name)
    compact = [(tmp_path / name).read_text() for name in ('aiida.out', 'verify.out')]
    assert casscf.verified_result(*compact, ref, SPACE, settings) == casscf.verified_result(first, second, ref, SPACE, settings)
    assert (tmp_path / native_logs.DIRECTORY / 'aiida.out').read_text() == first
    assert not (tmp_path / 'verify.property.txt').exists()
    assert (tmp_path / native_logs.DIRECTORY / 'verify.property.txt').exists()
    for tail in ('native_output_tail.txt', 'verify_tail.txt'):
        assert (tmp_path / tail).stat().st_size <= native_logs.TAIL_LIMIT


@pytest.mark.parametrize('issue', ['late_failure', 'wrong_weight', 'changed_subspace', 'energy_mismatch'])
def test_compaction_keeps_reasons_to_reject_a_candidate(tmp_path, issue):
    ref = reference_data()
    settings = casscf.casscf_settings(objective(), ref, SPACE)
    first, second = native_output(settings), native_output(settings, frozen=True)
    if issue == 'late_failure':
        first += 'CAS-SCF DID NOT CONVERGE\n'
    elif issue == 'wrong_weight':
        first = first.replace('ROOT=0 WEIGHT= 0.500000', 'ROOT=0 WEIGHT= 0.400000')
    elif issue == 'changed_subspace':
        second = second.replace('Active Orbitals ... unchanged', 'Active Orbitals ... natural')
    else:
        second = native_output(settings, frozen=True, shift=2e-7)
    collect_pair(tmp_path, first, second)
    with pytest.raises(ValueError):
        casscf.verified_result((tmp_path / 'aiida.out').read_text(), (tmp_path / 'verify.out').read_text(), ref, SPACE, settings)


@pytest.mark.parametrize('mode', ['remote', 'stash'])
def test_casscf_retention_does_not_change_the_native_inputs(common_reference, aiida_manager, mode):  # noqa: F811
    ref_uuid, remote_uuid, code_uuid, _ = common_reference
    ref = orm.load_node(ref_uuid)
    b = casscf.CasscfWorkChain.get_builder()
    b.structure = orm.load_node(ref.get_dict()['structure_uuid'])
    b.orbital_reference, b.source_remote = ref, orm.load_node(remote_uuid)
    b.code = b.storage_code = orm.load_code(code_uuid)
    b.active_space, b.settings = orm.Dict(dict=SPACE), orm.Dict(dict=objective())
    b.storage_policy = orm.Dict(dict={'threshold_mb': 100, 'stash_directory': '/legacy'})
    b.native_output_policy = orm.Dict(dict={'mode': mode, 'stash_directory': '/user/stash'})
    parent = instantiate_process(aiida_manager.get_runner(), b)
    children = []
    parent.submit = lambda child: children.append(child) or orm.CalcJobNode().store()
    try:
        assert parent.setup() is None
        assert parent.should_stash() == (mode == 'stash')
        parent.calculate()
        child = instantiate_process(aiida_manager.get_runner(), children[0])
        try:
            with SandboxFolder() as folder:
                info = child.prepare_for_submission(folder)
                for name, frozen in (('aiida', False), ('verify', True)):
                    with folder.open(name + '.inp') as handle:
                        assert handle.read() == casscf.casscf_input(ref.get_dict(), SPACE, objective(), readback=frozen)
                assert not {'aiida.gbw', 'aiida.property.txt', 'verify.property.txt'} & set(info.retrieve_list)
                with folder.open('native_output_request.json') as handle:
                    assert json.load(handle)['policy']['mode'] == mode
                expected = stash_options('/user/stash', 'native_output') if mode == 'stash' else {}
                assert dict(child.inputs.metadata.options.get('stash', {})) == expected
        finally:
            child.close()
    finally:
        parent.close()
