"""Default-new-only scheduling, retained results, and explicit opt-out."""
from aiida import engine, orm
from aiida.common import LinkType
from aiida.engine import ProcessState
from ase import Atoms
import pytest

from aiida_empa_orca import pdos_workflow as workflow
from aiida_empa_orca.common_orbitals import CommonOrbitalsWorkChain
from aiida_empa_orca.pdos import OrbitalCharacterCalculation, OrbitalCharacterParser
from aiida_empa_orca.reference import ReferenceWorkChain
from aiida_empa_orca.workchains import GeometryWorkChain


class CharacterHarness(workflow.OrbitalCharacterMixin, engine.WorkChain):
    """Supply a converged reference without running an electronic calculation."""
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('structure', valid_type=orm.StructureData)
        spec.input('retrieved', valid_type=orm.FolderData)
        spec.input('settings', valid_type=orm.Dict)
        spec.input('reuse', valid_type=orm.Bool, default=lambda: orm.Bool(False))
        spec.output('structure', valid_type=orm.StructureData)
        spec.output('retrieved', valid_type=orm.FolderData)
        cls.character_spec(spec)
        spec.outline(cls.seed, cls.run_orbital_character, cls.inspect_orbital_character)

    def seed(self):
        self.ctx.reusing = self.inputs.reuse.value
        self.out('structure', self.inputs.structure)
        self.out('retrieved', self.inputs.retrieved)


@pytest.fixture
def seed(aiida_profile_clean, aiida_localhost, tmp_path):
    path = tmp_path / 'reference'
    path.mkdir()
    (path / 'aiida.gbw').write_bytes(b'disposable test source')
    calc = orm.CalcJobNode(computer=aiida_localhost).store()
    remote = orm.RemoteData(computer=aiida_localhost, remote_path=str(path))
    retrieved = orm.FolderData()
    for name, node in (('remote_folder', remote), ('retrieved', retrieved)):
        node.base.links.add_incoming(calc, link_type=LinkType.CREATE, link_label=name)
        node.store()
    calc.set_process_state(ProcessState.FINISHED)
    calc.set_exit_status(0)
    return {'structure': orm.StructureData(ase=Atoms('H2', positions=[[0, 0, 0], [0, 0, .74]])),
            'retrieved': retrieved, 'settings': orm.Dict(dict={'charge': 0, 'multiplicity': 1})}


@pytest.mark.parametrize('cls', [ReferenceWorkChain, GeometryWorkChain, CommonOrbitalsWorkChain])
def test_every_new_reference_workflow_enables_character_by_default(aiida_profile, cls):
    assert cls.spec().inputs['character_enabled'].default().value is True
    assert cls.spec().inputs['character_memory_gib'].default().value == 8


@pytest.mark.parametrize('disabled,reuse,state', [(True, False, 'disabled'), (False, True, 'reused_reference')])
def test_optout_and_reuse_do_not_discover_tools_or_backfill(seed, monkeypatch, disabled, reuse, state):
    monkeypatch.setattr(workflow, 'available_codes', lambda _: pytest.fail('No backfill or tool query'))
    outputs, node = engine.run_get_node(CharacterHarness, **seed,
        character_enabled=orm.Bool(not disabled), reuse=orm.Bool(reuse))
    assert node.is_finished_ok and not node.called_descendants
    assert outputs['pdos_status'].get_dict()['state'] == state
    assert outputs['structure'].uuid == seed['structure'].uuid


def test_missing_worker_retains_reference_and_reports_analysis_only_problem(seed):
    outputs, node = engine.run_get_node(CharacterHarness, **seed)
    assert node.is_finished_ok and not node.called_descendants
    report = outputs['pdos_status'].get_dict()
    assert report['state'] == 'incomplete'
    assert report['sets']['SCF']['state'] == 'unavailable'
    assert 'worker' in report['sets']['SCF']['message']
    assert outputs['retrieved'].uuid == seed['retrieved'].uuid


def test_failed_export_is_a_child_and_does_not_fail_electronic_reference(seed, aiida_localhost, entry_points):
    entry_points.add(OrbitalCharacterCalculation, 'aiida.calculations:empa_orca.orbital_character')
    entry_points.add(OrbitalCharacterParser, 'aiida.parsers:empa_orca.orbital_character')
    export = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/false').store()
    helper = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/bin/true').store()
    outputs, node = engine.run_get_node(CharacterHarness, **seed,
        character_export_code=export, character_helper_code=helper)
    assert node.is_finished_ok
    report = outputs['pdos_status'].get_dict()
    assert report['sets']['SCF']['state'] == 'failed'
    child = orm.load_node(report['sets']['SCF']['uuid'])
    assert child.caller.uuid == node.uuid and child.is_failed
    assert child.inputs.identity['source_uuid'] == str(node.uuid)
    assert child.inputs.structure.uuid == outputs['structure'].uuid
    assert child.get_option('resources')['num_mpiprocs_per_machine'] == 1
    assert outputs['retrieved'].uuid == seed['retrieved'].uuid


def test_code_discovery_filters_computer_and_hidden_workers(aiida_profile_clean, aiida_localhost):
    export = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/test/orca_2json').store()
    helper = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/test/character').store()
    helper.base.extras.set('aiidalab_orca_role', 'orbital_character')
    hidden = orm.InstalledCode(computer=aiida_localhost, filepath_executable='/test/hidden').store()
    hidden.base.extras.set('aiidalab_orca_role', 'orbital_character')
    hidden.is_hidden = True
    plan = workflow.default_plan(aiida_localhost.uuid)
    assert plan['ready'] and plan['export_uuid'] == str(export.uuid) and plan['helper_uuid'] == str(helper.uuid)
    assert plan['memory_gib'] == 8
    b = ReferenceWorkChain.get_builder()
    workflow.configure(b, plan)
    assert b.character_enabled.value and b.character_export_code.uuid == export.uuid


def test_invalid_analysis_memory_is_rejected_before_submission():
    with pytest.raises(ValueError, match='memory'):
        workflow.default_plan('unused', enabled=False, memory_gib=0)
