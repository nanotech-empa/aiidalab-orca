"""Native ORCA core holes, spin/assignment guards and scratch-independent reuse."""

import io
import json
from pathlib import Path

import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca import xps
from aiida_empa_orca.protocols import protocol_settings
from aiida_empa_orca.reference import PROCESS_TYPE as SCF_PROCESS
from aiida_empa_orca.scripts.core_orbitals import assignments

FIXTURE = Path(__file__).parent/'fixtures'/'xps'
REFERENCE = json.loads((FIXTURE/'reference.json').read_text())
CORE = json.loads((FIXTURE/'hcooh-core.json').read_text())


def site_result(atom):
    return xps.parse_site((FIXTURE/f'hcooh-site-{atom}.out').read_text(), CORE, atom, 24,
                          REFERENCE['ground_energy_hartree'])


def test_native_core_assignment_and_three_verified_doublets():
    rows, verified = assignments((FIXTURE/'hcooh-core.out').read_text(), REFERENCE['numbers'])
    assert verified and [r['atom_index'] for r in rows] == [2, 1, 0]
    assert [r['population'] for r in rows] == pytest.approx([.998, .996, .992])
    results = [site_result(i) for i in range(3)]
    assert [r['binding_energy_ev'] for r in results] == pytest.approx([294.800230, 538.066782, 539.901118], abs=1e-6)
    assert results[2]['binding_energy_ev']-results[1]['binding_energy_ev'] == pytest.approx(1.83433554)
    for result in results:
        assert result['electron_counts'] == [11., 12.]
        assert result['final_multiplicity'] == 2
        assert .75 < result['spin_squared'] < .77
        assert result['hole_population'] > .99
    # ORCA reorders this empty core orbital to index 11 during ΔSCF. Looking
    # only at its original index would fail to check the actual final hole.
    assert all(r['hole_orbital_index'] == 11 for r in results)


def test_equivalent_oxygen_atoms_require_and_pass_core_only_localization():
    rows, verified = assignments((FIXTURE/'co2-aiida.out').read_text(), [6, 8, 8])
    assert not verified and any(row['population'] < .95 for row in rows)
    rows, verified = assignments((FIXTURE/'co2-localized.out').read_text(), [6, 8, 8], localized=True)
    assert verified and {row['atom_index'] for row in rows} == {0, 1, 2}
    assert all(row['energy_hartree'] is None for row in rows)  # Localized MOs have no canonical eigenvalues.
    assert 'PIPEK' in (FIXTURE/'co2-localize.log').read_text().upper()


@pytest.mark.parametrize('problem', ['wrong_atom', 'collapse', 'electron_count', 'termination'])
def test_invalid_core_hole_is_rejected(problem):
    text = (FIXTURE/'hcooh-site-0.out').read_text()
    atom = 0
    if problem == 'wrong_atom':
        atom = 1
    elif problem == 'collapse':
        text = text.replace('-11.263700', '-0.126370')
    elif problem == 'electron_count':
        text = text.replace('  11   0.0000', '  11   1.0000')
    else:
        text = text.replace('ORCA TERMINATED NORMALLY', '')
    with pytest.raises(ValueError):
        xps.parse_site(text, CORE, atom, 24, REFERENCE['ground_energy_hartree'])


def test_core_projection_and_incompatible_spin_are_rejected(aiida_profile):
    text = (FIXTURE/'hcooh-core.out').read_text()
    with pytest.raises(ValueError, match='CMatrix'):
        assignments(text+'\nUsing GuessMode=CMatrix for the initial guess\n', REFERENCE['numbers'])
    oh = orm.StructureData(ase=Atoms('OH', positions=[[0, 0, 0], [0, 0, 1]]))
    with pytest.raises(ValueError, match='closed-shell'):
        xps.validate_reference(oh, protocol_settings(overrides={'multiplicity': 2}))
    molecule = orm.StructureData(ase=Atoms(numbers=REFERENCE['numbers'], positions=REFERENCE['positions']))
    with pytest.raises(ValueError, match='closed-shell'):
        xps.validate_reference(molecule, protocol_settings(overrides={'multiplicity': 1, 'reference': 'UKS'}))


def test_ionization_input_preserves_reference_charge_and_geometry():
    params = xps.site_parameters(REFERENCE['settings'], 2)
    assert params['charge'] == 0 and params['multiplicity'] == 1  # ORCA performs the ionization internally.
    assert 'UKS' in params['input_keywords'] and 'RKS' not in params['input_keywords']
    assert 'DeltaSCF' in params['input_keywords'] and 'Opt' not in params['input_keywords']
    assert params['input_blocks']['scf']['IonizeAlpha'] == 2
    assert 'GuessMode' not in params['input_blocks']['scf']


def test_site_calcjob_stages_one_checked_gbw_and_retrieves_no_large_files(aiida_profile, aiida_localhost, aiida_manager):
    structure = orm.StructureData(ase=Atoms(numbers=REFERENCE['numbers'], positions=REFERENCE['positions']))
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    repository = orm.FolderData()
    repository.base.repository.put_object_from_filelike(io.BytesIO(b'placeholder'), 'electronic/aiida.gbw')
    repository.store()
    b = xps.XpsSiteCalculation.get_builder()
    b.structure, b.settings, b.code = structure, orm.Dict(dict=REFERENCE['settings']), code
    b.source_retrieved, b.core_reference, b.atom_index = repository, orm.Dict(dict=CORE), orm.Int(0)
    b.source_repository, b.source_filename = repository, orm.Str('aiida.gbw')
    b.metadata.options.resources = {'num_machines': 1, 'num_mpiprocs_per_machine': 4}
    process = instantiate_process(aiida_manager.get_runner(), b)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            text = Path(folder.get_abs_path('aiida.inp')).read_text()
            assert '* xyzfile 0 1' in text and 'IonizeAlpha 2' in text
            assert 'Opt' not in text and '%moinp "reference.gbw"' in text
            assert info.retrieve_list == ['aiida.out']
            assert info.local_copy_list == [(repository.uuid, 'electronic/aiida.gbw', 'reference.gbw')]
    finally:
        process.close()


def make_source(aiida_localhost, tmp_path):
    structure = orm.StructureData(ase=Atoms(numbers=REFERENCE['numbers'], positions=REFERENCE['positions'])).store()
    settings = orm.Dict(dict=REFERENCE['settings']).store()
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true', default_calc_job_plugin='orca.orca').store()
    helper = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true', default_calc_job_plugin='empa_orca.electronic_storage').store()
    source = orm.WorkChainNode(process_type=SCF_PROCESS)
    for key, value in {'structure': structure, 'settings': settings, 'code': code}.items():
        source.base.links.add_incoming(value, link_type=LinkType.INPUT_WORK, link_label=key)
    source.store()
    producer = orm.CalcJobNode().store()
    ground = orm.FolderData()
    ground.base.repository.put_object_from_filelike(io.StringIO(
        f'SCF CONVERGED AFTER 12 CYCLES\nFINAL SINGLE POINT ENERGY {REFERENCE["ground_energy_hartree"]}\nORCA TERMINATED NORMALLY\n'), 'aiida.out')
    remote = orm.RemoteData(computer=aiida_localhost, remote_path=str(tmp_path/'deleted-scratch'))
    for key, value in {'retrieved': ground, 'remote_folder': remote, 'output_parameters': orm.Dict(dict={})}.items():
        value.base.links.add_incoming(producer, link_type=LinkType.CREATE, link_label=key)
        value.store()
        value.base.links.add_incoming(source, link_type=LinkType.RETURN, link_label=key)
    structure.base.links.add_incoming(source, link_type=LinkType.RETURN, link_label='structure')
    source.set_process_state(ProcessState.FINISHED)
    source.set_exit_status(0)
    return str(source.uuid), str(helper.uuid)


def make_site(source_uuid, atom):
    source = orm.load_node(source_uuid)
    node = orm.CalcJobNode(process_type=xps.SITE_PROCESS)
    for key, value in {'structure': source.outputs.structure, 'settings': source.inputs.settings,
                       'code': source.inputs.code, 'source_retrieved': source.outputs.retrieved,
                       'atom_index': orm.Int(atom).store(), 'core_reference': orm.Dict(dict=CORE).store()}.items():
        node.base.links.add_incoming(value, link_type=LinkType.INPUT_CALC, link_label=key)
    node.store()
    data = site_result(atom) | {'signature': xps.site_signature(source.outputs.structure,
        source.inputs.settings.get_dict(), source.inputs.code.uuid, source.outputs.retrieved.uuid, atom)}
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(io.StringIO((FIXTURE/f'hcooh-site-{atom}.out').read_text()), 'aiida.out')
    for key, value in {'retrieved': retrieved, 'site_result': orm.Dict(dict=data)}.items():
        value.base.links.add_incoming(node, link_type=LinkType.CREATE, link_label=key)
        value.store()
    node.set_process_state(ProcessState.FINISHED)
    node.set_exit_status(0)
    return str(node.uuid)


def test_reuse_needs_no_wavefunction_and_survives_float_storage(aiida_profile_clean, aiida_localhost, tmp_path):
    from aiidalab_orca import xps_services as service
    source_uuid, helper_uuid = make_source(aiida_localhost, tmp_path)
    previous = [make_site(source_uuid, i) for i in range(3)]
    source = orm.load_node(source_uuid)
    assert len(xps.matching_sites(source.outputs.structure, source.inputs.settings.get_dict(), source.inputs.code.uuid,
                                   source.outputs.retrieved.uuid)) == 3
    plan = service.prepare(source_uuid, [0, 1, 2])
    assert len(plan['reuse']) == 3 and not plan['missing'] and not plan['regenerate_reference']
    force = service.prepare(source_uuid, [0], force_recompute=True)
    assert not force['reuse'] and force['regenerate_reference']
    builder = xps.XpsWorkChain.get_builder()
    builder.structure, builder.settings, builder.code = source.outputs.structure, source.inputs.settings, source.inputs.code
    builder.source_retrieved, builder.source_remote = source.outputs.retrieved, source.outputs.remote_folder
    builder.helper_code = orm.load_code(helper_uuid)
    builder.storage_policy = orm.Dict(dict={'threshold_mb': 100, 'stash_directory': str(tmp_path/'stash')})
    builder.atom_indices = orm.List(list=[0, 1, 2])
    outputs, node = run_get_node(builder)
    assert node.is_finished_ok and not node.called_descendants
    assert set(outputs['sites']) == {'atom_0000', 'atom_0001', 'atom_0002'}
    assert {str(data.creator.uuid) for data in outputs['sites'].values()} == set(previous)
    record = service.result(str(node.uuid))
    assert len(record['sites']) == 3 and isinstance(record['sites'][0]['binding_energy_ev'], float)


def test_spectrum_preserves_energy_and_equal_area_convention():
    from aiidalab_orca.xps import XpsSpectrum
    from aiidalab_orca.app import close_widget_tree
    sites = [site_result(i) | {'symbol': 'C' if i == 0 else 'O', 'label': f'atom {i+1}', 'data_uuid': f'data-{i}'} for i in range(3)]
    view = XpsSpectrum({'uuid': 'result', 'sites': sites})
    try:
        view.edge.value = 'O'
        view.axis.value = 'relative'
        assert len(view.figure.data) == 3
        x = np.asarray(view.figure.data[0].x)
        assert x[np.argmax(view.figure.data[0].y)] == pytest.approx(0, abs=.01)
        assert x[np.argmax(view.figure.data[1].y)] == pytest.approx(1.83433554, abs=.01)
        assert np.trapezoid(view.figure.data[0].y, x) == pytest.approx(1, abs=1e-5)
        view.width.value = .8
        assert np.trapezoid(view.figure.data[0].y, np.asarray(view.figure.data[0].x)) == pytest.approx(1, abs=1e-4)
        assert 'xps-view.json' in view.download.value
    finally:
        close_widget_tree(view)


def test_qe_overlay_counts_only_selected_equivalent_atoms():
    from aiidalab_orca.xps import XpsSpectrum
    from aiidalab_orca.app import close_widget_tree
    site = site_result(1) | {'symbol': 'O', 'label': 'O2', 'data_uuid': 'site-data'}
    comparison = {'uuid': 'qe-workflow', 'label': 'QE', 'sites': [
        {'symbol': 'O', 'atom_index': 1, 'equivalent_atom_indices': [1, 2], 'weight': 2, 'binding_energy_ev': 537.0}]}
    view = XpsSpectrum({'uuid': 'result', 'sites': [site]}, [comparison])
    try:
        view.qe.value = 0
        view.axis.value = 'relative'
        assert len(view.figure.data) == 3
        qe = view.figure.data[-1]
        assert qe.name == 'QE total'
        assert np.trapezoid(qe.y, qe.x) == pytest.approx(1, abs=1e-5)
        assert np.asarray(qe.x)[np.argmax(qe.y)] == pytest.approx(0, abs=.01)
    finally:
        close_widget_tree(view)
