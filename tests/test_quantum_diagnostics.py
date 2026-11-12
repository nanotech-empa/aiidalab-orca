"""Stored data and real widget transitions, with no solver or native submissions."""
import hashlib
import io
import json

import pytest
from aiida import engine, orm
from aiida.common import LinkType
from aiidalab_orca import energy_services as service, quantum_energy
from aiidalab_orca.widget_lifecycle import close_widget_tree


@pytest.fixture
def saved(aiida_profile_clean, aiida_localhost):
    def make(*, descriptor=True, wrong_sha=False, counts=None):
        model=orm.WorkChainNode(process_type='aiida.workflows:empa_orca.energy_export').store()
        h=orm.Dict(dict={'sha256':'a'*64}) if descriptor else orm.SinglefileData(file=io.BytesIO(b'old fcidump'),filename='hamiltonian.fcidump')
        native=orm.Dict(dict={'hamiltonian_sha256':'a'*64})
        for label,node in [('hamiltonian',h),('native_export',native)]:
            node.store();node.base.links.add_incoming(model,link_type=LinkType.RETURN,link_label=label)
        model.set_process_state(engine.ProcessState.FINISHED);model.set_exit_status(0)
        stage=orm.CalcJobNode(computer=aiida_localhost,process_type='aiida.calculations:empa_orca.energy_stage')
        for label,node in [('hamiltonian',h),('native_export',native),
                           ('operation',orm.Str('sample-simulator').store()),
                           ('sector',orm.Dict(dict={'charge':0,'ms2':1}).store())]:
            stage.base.links.add_incoming(node,link_type=LinkType.INPUT_CALC,link_label=label)
        stage.store()
        counts=counts or {'001011':792,'100110':208}
        packet={'counts':counts,'shots':sum(counts.values()),'n_qubits':len(next(iter(counts))),
                'hamiltonian_sha256':'a'*64,'sector':{'charge':0,'ms2':1},
                'execution_kind':'ideal_statevector_simulator','qubit_to_classical':list(range(len(next(iter(counts))))),'nelec':[2,1]}
        raw=json.dumps(packet).encode()
        result={'samples_sha256':'b'*64 if wrong_sha else hashlib.sha256(raw).hexdigest(),
                'execution_kind':packet['execution_kind']}
        for label,node in [('samples',orm.SinglefileData(file=io.BytesIO(raw),filename='samples.json')),
                           ('result',orm.Dict(dict=result))]:
            node.base.links.add_incoming(stage,link_type=LinkType.CREATE,link_label=label);node.store()
        stage.set_process_state(engine.ProcessState.FINISHED);stage.set_exit_status(0)
        return str(model.uuid),str(stage.uuid)
    return make


@pytest.mark.parametrize('descriptor',[True,False])
def test_counts_from_matching_descriptor_and_legacy_file_only(saved,descriptor):
    model,stage=saved(descriptor=descriptor)
    result=service.sample_diagnostics(stage,model,{'charge':0,'ms2':1})
    assert result['counts']==[('001011',792),('100110',208)] and result['shots']==1000
    json.dumps(result)
    other,_=saved()
    with pytest.raises(ValueError,match='Hamiltonian and sector'):
        service.sample_diagnostics(stage,other,{'charge':0,'ms2':1})
    with pytest.raises(ValueError,match='Hamiltonian and sector'):
        service.sample_diagnostics(stage,model,{'charge':1,'ms2':0})
    with pytest.raises(ValueError,match='no longer available'):
        service.sample_diagnostics('00000000-0000-0000-0000-000000000000',model,{'charge':0,'ms2':1})


def test_count_fingerprint_rejected_and_large_display_explicit(saved):
    model,stage=saved(wrong_sha=True)
    with pytest.raises(ValueError,match='fingerprint'):
        service.sample_diagnostics(stage,model,{'charge':0,'ms2':1})
    model,stage=saved(counts={f'{i:06b}':1 for i in range(64)})
    result=service.sample_diagnostics(stage,model,{'charge':0,'ms2':1})
    assert len(result['counts'])==50 and result['omitted_bitstrings']==14 and result['shots']==64


def test_real_workspace_shows_counts_and_clears_stale_context(saved,monkeypatch):
    model,stage=saved()
    monkeypatch.setattr(quantum_energy.casci_services,'reference_data',lambda _:{'source_multiplicity':2,'charge':0,'settings':{'basis':'def2-SVP'}})
    monkeypatch.setattr(service,'models',lambda *args:[{'uuid':model,'state':'finished','finished_ok':True,'created':'now','label':'saved'}])
    monkeypatch.setattr(service,'resources',lambda *args:[])
    monkeypatch.setattr(service,'orca_comparisons',lambda *args:[])
    monkeypatch.setattr(service,'submit',lambda *args:pytest.fail('Opening saved diagnostics must not submit'))
    widget=quantum_energy.QuantumEnergy('reference',{'electrons':3,'orbitals':[10,11,12]})
    try:
        assert widget.samples.value==stage
        assert all(text in widget.sample_details.value for text in ['Saved sample counts','001011','792','208','1000',stage])
        widget.samples.value=None
        assert widget.sample_details.value==''
        widget.samples.value=stage
        widget.charge.value=1
        assert widget.samples.value is None and widget.sample_details.value==''
    finally:close_widget_tree(widget)


def test_solver_specific_warning_and_padded_tables_preserve_numbers():
    cls=quantum_energy.QuantumEnergy
    reference={'origin':'orca_casci','multiplicity':2,'levels':[{'root':0,'energy_hartree':-5.0}]}
    result={'samples_execution_kind':'ideal_statevector_simulator','levels':[{'root':0,'energy_hartree':-4.9,'spin_squared':.87}],
            'requested_roots':1,'used_roots':1,'dimension':4,'spin_expectation_consistent':False,
            'selection':{'input_shots':1000,'sector_valid_shots':1000,'alpha_strings':2,'beta_strings':2}}
    warning=cls._orca_comparison_table(result,reference)
    assert 'simulator-selected subspace' in warning and 'Other solver columns' in warning
    text=cls._level_table(result)
    assert '-4.9000000000' in text and 'padding:10px 14px' in text
    assert 'Numerical residual norms are not retained' in text and '1000' in text and 'Spin contamination' in text
    full=result|{'samples_execution_kind':None,'levels':[{'root':0,'energy_hartree':-5.0,'spin_squared':.75}], 'selection':None}
    comparison=cls._orca_comparison_table(full,reference)
    assert '1 energy-ordered pairs' in comparison and 'largest |ΔE| = 0.000e+00' in comparison
    assert 'padding:10px 14px' in comparison and 'without alignment shifts' in comparison
