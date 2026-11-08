"""Bounded correlation output preserves every existing scientific decision."""

import pytest
from aiida import orm
from aiida.common.folders import SandboxFolder
from aiida.engine.utils import instantiate_process

from aiida_empa_orca import correlation, native_logs
from aiidalab_orca import correlation_services
from test_correlation import reference, mp2_text, nevpt_text, dlpno_text, caspt2_text
from test_reference import electronic_source  # noqa: F401


def case(method):
    ref = reference()
    if method == 'RI-MP2':
        return mp2_text(), (ref['settings'] | {'multiplicity':1}, {'method':method}, 10)
    text, expected = (dlpno_text() if method == 'DLPNO-NEVPT2' else
                      caspt2_text() if method == 'CASPT2' else nevpt_text())
    text = text.replace('PT2 = SC-NEVPT2', 'PT2 = '+method)
    return text, (ref['settings'], {'method':method}, 15, ref, expected)


def compact(tmp, text):
    original = tmp / 'native_output'
    original.mkdir()
    (original / 'aiida.out').write_text(text)
    return native_logs.collect_output({'protocol':'correlation-v1','policy':{'mode':'remote'}}, tmp)


@pytest.mark.parametrize('method', correlation.METHODS)
def test_large_logs_keep_identical_energies_and_native_diagnostics(tmp_path, method):
    text, args = case(method)
    text = text.replace('ORCA TERMINATED NORMALLY', 'unrelated native detail\n'*100000+'ORCA TERMINATED NORMALLY')
    record = compact(tmp_path, text)
    native_logs.validate_manifest(record)
    summary = (tmp_path/'aiida.out').read_text()
    assert len(summary)<12000
    assert correlation.parse_result(summary,*args)==correlation.parse_result(text,*args)
    assert (tmp_path/'native_output'/'aiida.out').read_text()==text


@pytest.mark.parametrize('method,before,after', [
    ('SC-NEVPT2','ORCA TERMINATED NORMALLY','WARNING: poorly normalized CI\nORCA TERMINATED NORMALLY'),
    ('FIC-NEVPT2','ORCA TERMINATED NORMALLY','Koopmans matrices have at least one negative eigenvalue\nORCA TERMINATED NORMALLY'),
    ('DLPNO-NEVPT2','RMAX= 5.3e-08 => CONVERGED','RMAX= 5.3e-02 => CONVERGED'),
    ('CASPT2','0.00000288','-0.00000288'),
    ('CASPT2','IJAB = 0.237441258','IJAB = -0.237441258'),
    ('CASPT2','CASPT2 calculation converged in 2 iterations','CASPT2 calculation did not converge'),
    ('RI-MP2','SCF CONVERGED AFTER 11 CYCLES','SCF NOT CONVERGED'),
])
def test_failure_markers_are_not_lost_in_the_summary(tmp_path, method, before, after):
    text, args = case(method)
    bad = text.replace(before,after)
    assert bad!=text
    compact(tmp_path,bad)
    for sample in (bad,(tmp_path/'aiida.out').read_text()):
        with pytest.raises(ValueError):
            correlation.parse_result(sample,*args)


def test_correlation_native_files_are_in_the_preserved_bundle_not_the_repository(tmp_path):
    generated = ['aiida.gbw','aiida.densities','aiida.densitiesinfo','aiida.pt2.tmp']
    for name in generated:
        (tmp_path/name).write_bytes(b'native file content')
    for name in ('aiida.inp','aiida.coords.xyz','reference.gbw'):
        (tmp_path/name).write_bytes(b'unchanged input')
    record=compact(tmp_path,mp2_text())
    for name in generated:
        assert not (tmp_path/name).exists()
        assert (tmp_path/'native_output'/name).read_bytes()==b'native file content'
    for name in ('aiida.inp','aiida.coords.xyz','reference.gbw'):
        assert (tmp_path/name).read_bytes()==b'unchanged input'
    assert set(generated)<={r['name'] for r in record['files']}
    native_logs.validate_manifest(record)


@pytest.mark.parametrize('label',['tigu','another configured computer'])
@pytest.mark.parametrize('mode',['remote','stash'])
def test_correlation_resources_and_retention_do_not_depend_on_computer_name(electronic_source, aiida_manager, monkeypatch, label, mode):  # noqa: F811
    uid,_=electronic_source()
    source=orm.load_node(uid)
    source.inputs.code.computer.label=label
    monkeypatch.setattr(correlation_services,'helper_code',lambda _:str(source.inputs.code.uuid))
    plan=correlation_services.review(uid,'RI-MP2',{'nprocs':16,'memory_mb':8192},True,
                                     native_output_policy={'mode':mode,'stash_directory':'/chosen/stash'})
    builder=correlation_services.builder(plan)
    p=instantiate_process(aiida_manager.get_runner(),builder)
    try:
        with SandboxFolder() as folder:
            info=p.prepare_for_submission(folder)
            assert info.codes_info[0].cmdline_params==['aiida.inp']
            assert info.codes_info[0].stdout_name=='native_output/aiida.out'
            assert not any(name.endswith(('.gbw','.densities','.property.txt')) for name in info.retrieve_list)
            assert builder.metadata.options.resources=={'num_machines':1,'num_mpiprocs_per_machine':16}
            with folder.open('aiida.inp') as h:
                assert h.read()==plan['input']
    finally:
        p.close()


@pytest.mark.parametrize('label',['tigu','another configured computer'])
def test_optical_review_also_respects_configured_resources(electronic_source, label, monkeypatch):  # noqa: F811
    from aiidalab_orca import optical_services
    uid,_=electronic_source()
    source=orm.load_node(uid)
    monkeypatch.setattr(optical_services,'helper_code',lambda _:str(source.inputs.code.uuid))
    source.inputs.code.computer.label=label
    plan=optical_services.review(uid,{'nprocs':16,'memory_mb':8192},True)
    builder=optical_services.builder(plan)
    assert builder.metadata.options.resources=={'num_machines':1,'num_mpiprocs_per_machine':16}
    assert builder.code.uuid==source.inputs.code.uuid
