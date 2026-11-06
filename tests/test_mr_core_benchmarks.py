"""Synthetic provenance tests for display admission, not native Co validation."""
import base64
import copy
import hashlib
import io
import json
from types import SimpleNamespace

import pytest
from aiida import engine, orm
from aiida.common import LinkType
from ase import Atoms

from aiidalab_orca import mr_core_benchmark_services as service


@engine.calcfunction
def controls(structure, source_reference, model, values):
    return orm.Dict(dict=values.get_dict())


@engine.calcfunction
def relaxed_check(stdout, frozen_control, model, validator_source, values):
    return orm.Dict(dict=values.get_dict())


@engine.calcfunction
def acceptance(stdout, relaxed_validation, frozen_control, model,
               validator_source, control_validator_source, values):
    return orm.Dict(dict=values.get_dict())


def native_job(computer, model, states, *, optimizer=False, validation=None,
               source=None, bad_normalization=False, failed=False, gradient=1e-4):
    job = orm.CalcJobNode(computer=computer)
    inputs = {'nodes__model': model}
    if source is not None:
        inputs['nodes__source'] = source
    if validation is not None:
        inputs['nodes__validation'] = validation
    for label, node in inputs.items():
        job.base.links.add_incoming(node, link_type=LinkType.INPUT_CALC, link_label=label)
    job.store()
    job.set_process_state(engine.ProcessState.FINISHED)
    job.set_exit_status(400 if failed else 0)
    lines = ['CI-PROBLEM SOLVED', 'ORCA TERMINATED NORMALLY']
    if optimizer:
        lines += ['--- Orbital Update [SuperCI]', 'THE CAS-SCF ENERGY   HAS CONVERGED',
                  'THE CAS-SCF GRADIENT HAS CONVERGED', f'||g|| = {gradient}']
    if bad_normalization:
        lines.append('POORLY NORMALIZED MO DETECTED')
    for block, (mult, count) in enumerate(service.EXPECTED.items()):
        lines.append(f'CAS-SCF STATES FOR BLOCK {block} MULT= {mult} NROOTS= {count}')
        lines += [f'ROOT {r["root"]}: E= {r["energy_hartree"]:.12f} Eh'
                  for r in states if r['multiplicity'] == mult]
    output = orm.SinglefileData(io.BytesIO(('\n'.join(lines) + '\n').encode()), filename='aiida.out')
    output.base.links.add_incoming(job, link_type=LinkType.CREATE, link_label='aiida_out')
    output.store()
    folder = orm.RemoteData(computer=computer, remote_path='/tmp/synthetic-mr-' + str(job.uuid))
    folder.base.links.add_incoming(job, link_type=LinkType.CREATE, link_label='remote_folder')
    folder.store()
    return str(job.uuid), str(output.uuid), str(folder.uuid)


def fixture_record(computer, *, fault=None):
    structure = orm.StructureData(ase=Atoms('CoC', positions=[[0, 0, 0], [1.6, 0, 0]])).store()
    reference = orm.Dict(dict={'ground_energy_hartree': -130.}).store()
    model = orm.Dict(dict={'basis': 'cc-pVTZ', 'cobalt_basis': 'cc-pwCVTZ',
                          'protocol': 'synthetic display fixture'}).store()
    script = orm.SinglefileData(io.BytesIO(b'synthetic validator'), filename='validator.py').store()
    digest = hashlib.sha256(script.get_content().encode()).hexdigest()
    states = [{'multiplicity': m, 'root': i, 'energy_hartree': -101. + m * .01 + i * .001}
              for m, count in service.EXPECTED.items() for i in range(count)]
    # Match native printed precision; fixtures do not claim physical energies.
    for row in states:
        row['energy_hartree'] = round(row['energy_hartree'], 12)
    old = [r | {'energy_hartree': r['energy_hartree'] + 1.} for r in states]
    numerical = {'synthetic_consistent_grid': True}
    frozen = controls(structure, reference, model, orm.Dict(dict={
        'frozen_controls_passed': True, 'maximum_neutral_restart_difference_hartree': 1e-10,
        'core_numerical': numerical, 'core_states': old, 'neutral_reference_energy_hartree': -130.}))
    gradient = 1e-3 if fault == 'gradient' else 1e-4
    optimizer_uuid, stdout_uuid, folder_uuid = native_job(
        computer, model, states, optimizer=True, gradient=gradient,
        failed=fault == 'native_failure')
    orbitals = {str(i): {'occupation': 5 / 3 if i < 141 else 1.5,
                         'energy_hartree': -30. if i < 141 else -.5,
                         'co_p': 1. if i < 141 else 0.,
                         'co_d': 1. if 141 <= i < 146 else 0.,
                         'ligand_pz': 1. if i == 146 else 0.} for i in range(138, 147)}
    if fault == 'core_identity':
        orbitals['138']['co_p'] = .7
    if fault == 'valence_identity':
        orbitals['146']['ligand_pz'] = .1
    average = service._mean(service._states(states))
    relaxed = {'native_orbital_optimization_validated': True,
               'accepted_as_relaxed_xps': False, 'final_orbital_gradient': gradient,
               'initial_seed_energy_difference_hartree': 0., 'states': states,
               'target_orbitals': orbitals, 'valence_assignment': {'ligand_pi': 146, 'co_d': list(range(141, 146))},
               'numerical': numerical, 'validator_sha256': digest,
               'state_average_energy_hartree': average,
               'frozen_state_average_energy_hartree': service._mean(service._states(old)),
               'state_average_relaxation_hartree': average - service._mean(service._states(old))}
    checked = relaxed_check(orm.load_node(stdout_uuid), frozen, model, script, orm.Dict(dict=relaxed))
    saved = copy.deepcopy(states)
    if fault == 'state_readback':
        saved[-1]['energy_hartree'] += 2e-7
    if fault == 'native_missing_state':
        saved = saved[:-1]
    source = orm.load_node(folder_uuid)
    if fault == 'checkpoint':
        source = orm.RemoteData(computer=computer, remote_path='/tmp/wrong-checkpoint').store()
    _, readback_uuid, _ = native_job(computer, model, saved, source=source, validation=checked,
                                    bad_normalization=fault == 'normalization')
    values = relaxed | {
        'accepted_as_energy_benchmark': True, 'accepted_as_multiplet_spectrum': False,
        'maximum_state_readback_difference_hartree': 0.,
        'readback_state_average_energy_hartree': average,
        'readback_target_orbitals': orbitals, 'neutral_reference_energy_hartree': -130.,
        'spin_free_ionization_energies_hartree': [r | {'binding_energy_hartree': r['energy_hartree'] + 130.}
                                                for r in states],
        'readback_validator_sha256': digest, 'control_validator_sha256': digest}
    if fault == 'missing_state':
        values['spin_free_ionization_energies_hartree'] = values['spin_free_ionization_energies_hartree'][:-1]
    if fault == 'energy_zero':
        values['neutral_reference_energy_hartree'] += .1
    if fault == 'validator':
        values['readback_validator_sha256'] = 'wrong source'
    if fault == 'acceptance':
        values['accepted_as_energy_benchmark'] = False
    return acceptance(orm.load_node(readback_uuid), checked, frozen, model,
                      script, script, orm.Dict(dict=values))


@pytest.mark.parametrize('fault,reason', [
    ('acceptance', 'accepted energy-only'), ('native_failure', 'native multireference'),
    ('gradient', 'orbital-gradient'), ('normalization', 'normalization'),
    ('state_readback', 'summary differs'), ('checkpoint', 'checkpoint'),
    ('native_missing_state', 'Native state table'),
    ('core_identity', 'deep Co 2p'), ('valence_identity', 'ligand-pi'),
    ('missing_state', '480-state'), ('energy_zero', 'summary differs'),
    ('validator', 'validator differs')])
def test_failed_evidence_cannot_display_energies(aiida_profile, aiida_localhost, fault, reason):
    data = fixture_record(aiida_localhost, fault=fault)
    with pytest.raises(ValueError, match=reason):
        service.validated_record(data)


def test_geometry_discovery_and_plain_result(aiida_profile, aiida_localhost, monkeypatch):
    data = fixture_record(aiida_localhost)
    record = service.validated_record(data)
    assert len(record['states']) == 480
    assert record['accepted_as_multiplet_spectrum'] is False
    assert isinstance(record['readback_calcjob_uuid'], str)
    source = SimpleNamespace(inputs=SimpleNamespace(settings=orm.Dict(dict={'charge': 0, 'multiplicity': 2})),
                             outputs=SimpleNamespace(structure=orm.StructureData(
                                 ase=Atoms('CoC', positions=[[1, 2, 3], [2.6, 2, 3]]))))
    monkeypatch.setattr(service, 'source_node', lambda _: source)
    assert service.records('selected')['records'][0]['data_uuid'] == str(data.uuid)
    source.outputs.structure = orm.StructureData(ase=Atoms('CoC', positions=[[0, 0, 0], [2., 0, 0]]))
    assert service.records('selected') == {'records': [], 'diagnostics': []}


def test_separate_collapsed_view_and_failure_clears_old_values(aiida_profile, aiida_localhost, monkeypatch):
    from aiidalab_orca.mr_core_benchmark_view import MultireferenceCoreBenchmarks
    from aiidalab_orca.app import close_widget_tree

    record = service.validated_record(fixture_record(aiida_localhost))
    result = {'records': [record], 'diagnostics': []}
    monkeypatch.setattr(service, 'records', lambda _: copy.deepcopy(result))
    panel = MultireferenceCoreBenchmarks('selected')
    try:
        assert panel.section.selected_index is None
        assert 'spin-free' in panel.table.value and '480-state' in panel.table.value
        assert 'different configuration character' in panel.table.value
        assert 'all 480 states' in panel.details.value
        encoded = panel.details.value.split('base64,')[1].split('"')[0]
        assert json.loads(base64.b64decode(encoded))['records'][0]['data_uuid'] == record['data_uuid']
        result.update(records=[], diagnostics=['readback failed'])
        panel.refresh.click()
        assert panel.table.value == '' and 'readback failed' in panel.details.value
        result['diagnostics'] = []
        panel.refresh.click()
        assert panel.layout.display == 'none'
    finally:
        close_widget_tree(panel)
