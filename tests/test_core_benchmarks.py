"""Display boundary checks for immutable, previously validated diagnostics.

The synthetic provenance below tests the reader, not native Co spectroscopy.
"""
import copy

import pytest
from aiida import engine, orm
from aiida.common import LinkType
from ase import Atoms

from aiidalab_orca import core_benchmark_services as service


@engine.calcfunction
def physical_check(structure, values):
    return orm.Dict(dict=values.get_dict())


@engine.calcfunction
def publish(structure, frozen, relaxed, gradient, readback, readback_audit, qe_binding_energies, summary):
    return orm.Dict(dict=summary.get_dict())


def fixture_record(aiida_localhost, *, bad_readback=False, bad_summary=False):
    structure = orm.StructureData(ase=Atoms('CoC', positions=[[0, 0, 0], [1.6, 0, 0]]))
    request = {'reference_uuid': 'neutral-reference', 'spin_channel': 'beta', 'orbital_index': 2}
    core = [{'occupation': value, 'co_p_population': 1., 'energy_hartree': -30.}
            for value in (1., 1., 0.)]
    frozen = {'request': request, 'core_p_orbitals': core, 'final_electron_counts': [17., 15.],
              'energy_hartree': -100., 'binding_energy_ev': 818., 'orbital_optimization_performed': False}
    relaxed = frozen | {'converged': True, 'energy_hartree': -101.,
                       'binding_energy_ev': 789., 'spin_squared': 2.1}
    readback = relaxed | {'energy_hartree': -101. + (2e-7 if bad_readback else 1e-10)}
    audit_job = orm.CalcJobNode(computer=aiida_localhost).store()
    audit_job.set_process_state(engine.ProcessState.FINISHED); audit_job.set_exit_status(0)
    audit = orm.Dict(dict={'basic_readback_passed': True, 'normalization_warnings': False,
                          'orbital_optimization_performed': False})
    audit.base.links.add_incoming(audit_job, link_type=LinkType.CREATE, link_label='readback_audit'); audit.store()
    summary = {'schema': service.SCHEMA, 'accepted_as_scalar_benchmark': True,
               'structure_uuid': str(structure.uuid), 'reference_uuid': 'neutral-reference',
               'frozen_binding_energy_ev': 818., 'relaxed_binding_energy_ev': 789.,
               'core_relaxation_lowering_ev': 100. if bad_summary else 29.,
               'final_gradient': 7e-7, 'final_spin_squared': 2.1,
               'readback_energy_difference_hartree': 1e-10, 'qe_scalar_binding_energy_ev': 788.,
               'model': 'Synthetic read-only reader fixture'}
    return publish(structure, physical_check(structure, orm.Dict(dict=frozen)),
                   physical_check(structure, orm.Dict(dict=relaxed)),
                   orm.Dict(dict={'maximum_orbital_gradient': 7e-7}),
                   physical_check(structure, orm.Dict(dict=readback)), audit,
                   orm.Dict(dict={'Co': {'2p': {'site_0': {'energy': 788.}}}}), orm.Dict(dict=summary))


@pytest.mark.parametrize('bad_readback,bad_summary,reason', [
    (True, False, 'saved-wavefunction'), (False, True, 'summary differs')])
def test_bad_acceptance_evidence_cannot_be_displayed(aiida_profile, aiida_localhost,
                                                   bad_readback, bad_summary, reason):
    data = fixture_record(aiida_localhost, bad_readback=bad_readback, bad_summary=bad_summary)
    with pytest.raises(ValueError, match=reason):
        service.validated_record(data)


def test_geometry_matching_and_plain_data_only(aiida_profile, aiida_localhost, monkeypatch):
    from types import SimpleNamespace
    fixture_record(aiida_localhost)
    settings = orm.Dict(dict={'charge': 0, 'multiplicity': 2})
    source = SimpleNamespace(inputs=SimpleNamespace(settings=settings), outputs=SimpleNamespace(
        structure=orm.StructureData(ase=Atoms('CoC', positions=[[1, 2, 3], [2.6, 2, 3]]))))
    monkeypatch.setattr(service, 'source_node', lambda _: source)
    record = service.records('selected')['records'][0]
    assert record['relaxed_binding_energy_ev'] == 789.
    assert isinstance(record['readback_calcjob_uuid'], str)
    source.outputs.structure = orm.StructureData(ase=Atoms('CoC', positions=[[0, 0, 0], [1.9, 0, 0]]))
    assert service.records('selected') == {'records': [], 'diagnostics': []}
    source.inputs.settings = orm.Dict(dict={'charge': 1, 'multiplicity': 1})
    assert service.records('selected') == {'records': [], 'diagnostics': []}


def test_energy_checks_have_a_separate_collapsed_view(aiida_profile, aiida_localhost, monkeypatch):
    from aiidalab_orca.core_benchmark_view import ScalarCoreBenchmarks
    from aiidalab_orca.app import close_widget_tree
    record = service.validated_record(fixture_record(aiida_localhost))
    rows = {'records': [record], 'diagnostics': []}
    monkeypatch.setattr(service, 'records', lambda _: copy.deepcopy(rows))
    panel = ScalarCoreBenchmarks('selected')
    try:
        assert panel.section.selected_index is None
        assert '789.00' in panel.table.value and 'SOC multiplets' in panel.table.value
        assert 'Saved-wavefunction readback passed' in panel.details.value
        assert record['data_uuid'] in panel.details.value
        assert 'co-scalar-energy-checks.json' in panel.details.value
        rows.update(records=[], diagnostics=['readback failed'])
        panel.refresh.click()
        assert not panel.table.value and 'readback failed' in panel.details.value
        rows['diagnostics'] = []
        panel.refresh.click()
        assert panel.layout.display == 'none'
    finally:
        close_widget_tree(panel)
