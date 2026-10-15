"""SCF execution, fixed coordinates, artifact-aware reuse and app contracts."""

import io
from types import SimpleNamespace

import numpy as np
import pytest
from aiida import orm
from aiida.common import LinkType
from aiida.common.folders import SandboxFolder
from aiida.engine import ProcessState, run_get_node
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca import reference
from aiida_empa_orca.calculation import SinglePointCalculation
from aiida_empa_orca.input import preview_input
from aiida_empa_orca.parser import reference_summary
from aiida_empa_orca.protocols import protocol_settings

OUTPUT = 'Program Version 6.1.1\nSCF CONVERGED AFTER 12 CYCLES\nFINAL SINGLE POINT ENERGY -129.7\nORCA TERMINATED NORMALLY\n'


@pytest.fixture
def electronic_source(aiida_profile_clean, aiida_localhost, tmp_path):
    """Factory with explicit CalcJob provenance and disposable electronic files."""
    def make(optimization=False):
        code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
        initial = orm.StructureData(ase=Atoms('NO', positions=[[0,0,0],[0,0,1.3]])).store()
        final = (orm.StructureData(ase=Atoms('NO', positions=[[0,0,0],[0,0,1.16]])).store()
                 if optimization else initial)
        settings = reference.reference_settings(protocol_settings())
        node = orm.WorkChainNode(process_type=reference.GEOMETRY_PROCESS if optimization else reference.PROCESS_TYPE)
        inputs = {'structure': initial, 'settings': orm.Dict(dict=settings), 'code': code}
        if optimization:
            inputs['optimize'] = orm.Bool(True)
        for name, value in inputs.items():
            value.store()
            node.base.links.add_incoming(value, link_type=LinkType.INPUT_WORK, link_label=name)
        node.store()
        calc = orm.CalcJobNode(process_type='aiida.calculations:empa_orca.single_point')
        calc.base.links.add_incoming(node, link_type=LinkType.CALL_CALC, link_label='calculation')
        calc.base.repository.put_object_from_filelike(io.StringIO('! test input'), 'aiida.inp')
        calc.store()
        folder = tmp_path / str(node.uuid)
        folder.mkdir()
        for name in reference.ELECTRONIC_FILES:
            (folder/name).write_bytes(b'test artifact\n')
        retrieved = orm.FolderData()
        retrieved.base.repository.put_object_from_filelike(io.StringIO(OUTPUT), 'aiida.out')
        summary = reference_summary(OUTPUT)
        outputs = {'output_parameters': orm.Dict(dict={}), 'retrieved': retrieved,
                   'remote_folder': orm.RemoteData(computer=aiida_localhost, remote_path=str(folder))}
        if optimization:
            for filename in ('aiida.xyz', 'aiida_trj.xyz'):
                retrieved.base.repository.put_object_from_filelike(io.StringIO('test geometry artifact'), filename)
            trajectory = orm.TrajectoryData()
            trajectory.set_trajectory(stepids=np.array([0]), symbols=['N','O'], positions=np.array([final.get_ase().positions]))
            summary['scf_evaluation_energies_hartree'] = [-129.7]
            outputs.update(optimization_summary=orm.Dict(dict=summary), trajectory=trajectory)
        else:
            outputs['reference_summary'] = orm.Dict(dict=summary)
        for name, value in outputs.items():
            value.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label=name)
            value.store()
            value.base.links.add_incoming(node, link_type=LinkType.RETURN, link_label=name)
        final.base.links.add_incoming(node, link_type=LinkType.RETURN, link_label='structure')
        for process in (calc, node):
            process.set_process_state(ProcessState.FINISHED)
            process.set_exit_status(0)
        return str(node.uuid), folder
    return make


def test_scf_requires_explicit_convergence_and_finite_energy():
    assert reference_summary(OUTPUT)['energy_hartree'] == -129.7
    for text in (OUTPUT.replace('SCF CONVERGED AFTER 12 CYCLES\n', ''),
                 OUTPUT.replace('SCF CONVERGED AFTER', 'SCF NOT CONVERGED'),
                 OUTPUT.replace('-129.7', '1e999'),
                 OUTPUT.replace('ORCA TERMINATED NORMALLY', '')):
        with pytest.raises(ValueError):
            reference_summary(text)


def test_sp_preview_matches_calcjob_without_geometry_keywords(aiida_profile, aiida_localhost, aiida_manager):
    structure = orm.StructureData(ase=Atoms('NO', positions=[[0,0,0],[0,0,1.3]]))
    settings = protocol_settings(overrides={'optimization': 'VeryTightOpt',
        'constraints': [{'kind':'distance', 'atoms':[0,1], 'value':1.2}],
        'block_parameters': {'geom': {'TolE': 1e-8}, 'scf': {'TolE': 1e-9}}})
    code = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    builder = SinglePointCalculation.get_builder()
    builder.structure, builder.code = structure, code
    builder.parameters = orm.Dict(dict=reference.single_point_parameters(settings))
    builder.maxcore_mb = orm.Int(768)
    builder.metadata.options.resources = {'num_machines':1, 'num_mpiprocs_per_machine':2}
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            for filename, expected in preview_input(structure, settings, single_point=True).items():
                with open(folder.get_abs_path(filename)) as stream:
                    assert stream.read() == expected
            assert info.retrieve_list == ['aiida.out']
        params = builder.parameters.get_dict()
        assert 'SP' in params['input_keywords'] and 'Opt' not in params['input_keywords']
        assert 'geom' not in params['input_blocks']
        assert params['input_blocks']['scf']['tole'] == 1e-9
    finally:
        process.close()


def test_reuse_checks_files_and_preserves_coordinates(electronic_source):
    uuid, folder = electronic_source()
    source = orm.load_node(uuid)
    builder = reference.get_reference_builder(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code)
    assert builder.reuse_source.value == uuid
    outputs, node = run_get_node(builder)
    assert node.is_finished_ok and not node.called_descendants
    assert outputs['structure'].uuid == source.inputs.structure.uuid
    assert outputs['remote_folder'].uuid == source.outputs.remote_folder.uuid
    from aiidalab_orca.history import search_runs, inspect_run
    from aiidalab_orca.services import result
    rows = search_runs(kind='scf', method='PBE')['rows']
    assert {r['uuid'] for r in rows} == {uuid, node.uuid}
    data = result(uuid)
    assert data['single_point'] and not data['optimized'] and data['summary']['energy_hartree'] == -129.7
    assert 'available' in inspect_run(uuid)['reuse_status']
    (folder/'aiida.gbw').unlink()
    assert 'recomputation' in inspect_run(uuid)['reuse_status']
    assert result(uuid)['summary']['energy_hartree'] == -129.7  # Energy survives scratch loss.
    plan = reference.plan_reference(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code)
    assert plan['action'] == 'compute' and len(plan['unavailable']) == 2
    builder = reference.get_reference_builder(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code, plan=plan)
    assert builder.bypass_cache.value


def test_reuses_final_optimization_state_only_at_matching_geometry(electronic_source):
    uuid, _ = electronic_source(optimization=True)
    source = orm.load_node(uuid)
    settings, code = source.inputs.settings.get_dict(), source.inputs.code
    assert reference.plan_reference(source.inputs.structure, settings, code)['action'] == 'compute'
    plan = reference.plan_reference(source.outputs.structure, settings, code)
    assert plan['source_uuid'] == uuid
    outputs, node = run_get_node(reference.get_reference_builder(source.outputs.structure, settings, code, plan=plan))
    assert node.is_finished_ok and not node.called_descendants
    assert outputs['reference_summary'].uuid == source.outputs.optimization_summary.uuid
    assert reference.plan_reference(source.outputs.structure, settings | {'method':'PBE0'}, code)['action'] == 'compute'


def test_disappearing_files_and_unreachable_storage_do_not_launch_silently(electronic_source, monkeypatch):
    uuid, folder = electronic_source()
    source = orm.load_node(uuid)
    args = (source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code)
    plan = reference.plan_reference(*args)
    (folder/'aiida.densities').unlink()
    with pytest.raises(FileNotFoundError):
        reference.get_reference_builder(*args, plan=plan)
    def unreachable(_):
        raise reference.ArtifactUnavailable('storage unavailable')
    monkeypatch.setattr(reference, 'check_wavefunction', unreachable)
    with pytest.raises(reference.ArtifactUnavailable):
        reference.plan_reference(*args)


def test_stale_cache_regenerates_once_and_forced_run_bypasses_cache(electronic_source, monkeypatch, aiida_manager):
    uuid, folder = electronic_source()
    source = orm.load_node(uuid)
    builder = reference.get_reference_builder(source.inputs.structure, source.inputs.settings.get_dict(), source.inputs.code, force_recompute=True)
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        assert process.setup() is None
        captured = []
        def submit(child):
            captured.append(child)
            return orm.WorkChainNode().store()
        process.submit = submit
        process.run_scf()
        assert captured[-1].orca.metadata.disable_cache is True
        cached = orm.CalcJobNode().store()
        cached.base.extras.set('_aiida_cached_from', 'test-source')
        process.ctx.scf = SimpleNamespace(is_finished_ok=True, outputs=source.outputs, called_descendants=[cached])
        (folder/'aiida.gbw').unlink()
        assert process.inspect_scf() is None and process.needs_regeneration()
        process.run_scf()
        assert captured[-1].orca.metadata.disable_cache is True
        assert process.inspect_scf().status == 403 and not process.needs_regeneration()
    finally:
        process.close()


def test_app_scf_keeps_scientific_controls_and_validates_spin(electronic_source, monkeypatch):
    from aiidalab_orca import services
    from aiidalab_orca.app import OrcaApp
    uuid, _ = electronic_source()
    source = orm.load_node(uuid)
    monkeypatch.setattr(services, 'codes', lambda:[('Test ORCA', str(source.inputs.code.uuid))])
    app = OrcaApp()
    try:
        app.structure.example.click()
        app.optimize.value = False
        app._confirm_structure()
        app._confirm_settings()
        app._review()
        assert app.review['plan']['action'] == 'reuse'
        assert 'SP' in app.review['input_files']['aiida.inp'].split()
        assert 'Reuse a compatible electronic state' in app.plan_html.value
        assert app.method.layout.display != 'none' and app.science.scf_convergence.layout.display != 'none'
        app.multiplicity.value = 1
        app._confirm_settings()
        assert not app._settings_confirmed and '15 electrons' in app.science_message.value
    finally:
        app.close()
