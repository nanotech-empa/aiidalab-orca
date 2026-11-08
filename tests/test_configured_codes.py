"""Use configured ORCA codes without naming or connecting to real computers."""

import pytest
from aiida import orm
from aiida.engine.utils import instantiate_process
from ase import Atoms

from aiida_empa_orca.protocols import protocol_settings
from aiida_empa_orca.reference import ReferenceWorkChain
from aiida_empa_orca.workchains import GeometryWorkChain
from aiidalab_orca import services


@pytest.fixture(params=[
    ("core.local", "core.direct"),
    ("core.ssh", "core.slurm"),
    ("core.ssh", "core.pbspro"),
])
def configured_computer(aiida_profile_clean, request):
    transport, scheduler = request.param
    return orm.Computer(
        label="configured-computer", hostname="unused.invalid",
        transport_type=transport, scheduler_type=scheduler,
        workdir="/work/{username}/orca",
    ).store()


def test_discovery_uses_visible_orca_codes_on_configured_computers(configured_computer):
    visible = []
    for index, plugin in enumerate(("orca.orca", "empa_orca.optimization", "empa_orca.single_point")):
        code = orm.InstalledCode(
            label=f"configured-orca-{index}", computer=configured_computer,
            filepath_executable="/configured/orca", default_calc_job_plugin=plugin,
        ).store()
        visible.append((code.full_label, str(code.uuid)))
    retired = orm.InstalledCode(
        label="retired", computer=configured_computer,
        filepath_executable="/configured/old-orca", default_calc_job_plugin="orca.orca",
    ).store()
    retired.is_hidden = True
    orm.InstalledCode(
        label="another-program", computer=configured_computer,
        filepath_executable="/configured/another-program", default_calc_job_plugin="core.arithmetic.add",
    ).store()
    assert services.codes() == sorted(visible)


@pytest.mark.parametrize("workflow, run_method", [
    (GeometryWorkChain, "run_optimization"), (ReferenceWorkChain, "run_scf"),
])
def test_initial_workflow_preserves_reviewed_inputs_for_any_scheduler(
        configured_computer, aiida_manager, monkeypatch, workflow, run_method):
    code = orm.InstalledCode(
        label="configured-orca", computer=configured_computer,
        filepath_executable="/configured/orca", default_calc_job_plugin="orca.orca",
    ).store()
    builder = workflow.get_builder()
    builder.code = code
    builder.structure = orm.StructureData(ase=Atoms("H2", positions=[[0, 0, 0], [0, 0, .75]]))
    settings = protocol_settings(overrides={
        "multiplicity": 1, "reference": "RKS", "nprocs": 4, "memory_mb": 4096,
        "wallclock_seconds": 600,
    })
    builder.settings = orm.Dict(dict=settings)
    process = instantiate_process(aiida_manager.get_runner(), builder)
    submitted = []

    def capture(child):
        submitted.append(child)
        return orm.WorkChainNode().store()

    monkeypatch.setattr(process, "submit", capture)
    try:
        assert process.setup() is None
        getattr(process, run_method)()
        child = submitted[0].orca
        assert child.code.uuid == code.uuid
        assert child.structure.uuid == builder.structure.uuid
        assert child.metadata.options.resources == {"num_machines": 1, "num_mpiprocs_per_machine": 4}
        assert child.metadata.options.withmpi is False
        assert child.metadata.options.max_wallclock_seconds == 600
        assert child.metadata.options.max_memory_kb == 4096 * 1024
        assert child.maxcore_mb.value == 768
        assert child.parameters.get_dict()["multiplicity"] == 1
    finally:
        process.close()
