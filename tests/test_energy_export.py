import pytest

from aiida_empa_orca.energy import export_input, portable_fcidump
from test_casci import reference_data
from test_casci import common_reference  # noqa: F401 -- disposable fixture
from test_reference import electronic_source  # noqa: F401 -- disposable fixture


def test_export_is_one_configuration_in_the_selected_sector():
    reference = reference_data()
    text = export_input(
        reference,
        {"electrons": 3, "orbitals": [6, 7]},
        {"multiplicity": 2, "nroots": 1},
    )
    assert "{2 1}" in text
    assert "DumpActInts true" in text and "NoIter" in text
    assert "ActOrbs unchanged" in text and "maxiter 1" in text
    with pytest.raises(ValueError, match="one diagnostic root"):
        export_input(reference, {"electrons": 3, "orbitals": [6, 7]}, {"nroots": 2})


def test_portable_spin_header_preserves_every_integral_byte():
    raw = (
        b" &FCI NORB=2,NELEC=3,MS2=0,\n ORBSYM=1,1,\n &END\n 1.5 1 1 0 0\n .7 0 0 0 0\n"
    )
    original = bytes(raw)
    result, record = portable_fcidump(raw, 3, 2)
    assert raw == original
    assert result == raw.replace(b"MS2=0", b"MS2=1")
    assert record["alpha_electrons"] == 2 and record["beta_electrons"] == 1
    assert record["integral_records_changed"] is False
    with pytest.raises(ValueError, match="electron count"):
        portable_fcidump(raw, 2, 1)
    with pytest.raises(ValueError, match="inconsistent"):
        portable_fcidump(raw.replace(b"MS2=0", b"MS2=2"), 3, 2)


def test_native_calcjob_uses_the_verified_code_and_source(
    common_reference,  # noqa: F811 -- imported pytest fixture
    aiida_manager,
):
    from aiida import orm
    from aiida.common.folders import SandboxFolder
    from aiida.engine.utils import instantiate_process
    from aiida_empa_orca import common_orbitals, artifacts
    from aiida_empa_orca.energy import EnergyHamiltonianCalculation

    ref_uuid, remote_uuid, code_uuid, _ = common_reference
    ref, remote, code = (
        orm.load_node(ref_uuid),
        orm.load_node(remote_uuid),
        orm.load_code(code_uuid),
    )
    builder = EnergyHamiltonianCalculation.get_builder()
    builder.orbital_reference, builder.code = ref, code
    builder.structure = orm.load_node(ref.get_dict()["structure_uuid"])
    builder.active_space = orm.Dict(dict={"electrons": 3, "orbitals": [6, 7]})
    builder.settings = orm.Dict(dict={"nroots": 1, "multiplicity": 2})
    common_orbitals.attach_orbital(
        builder, artifacts.resolve_electronic(remote, names=["aiida.qro"]), "aiida.qro"
    )
    builder.metadata.options.resources = {
        "num_machines": 1,
        "num_mpiprocs_per_machine": 1,
    }
    process = instantiate_process(aiida_manager.get_runner(), builder)
    try:
        with SandboxFolder() as folder:
            info = process.prepare_for_submission(folder)
            text = open(folder.get_abs_path("aiida.inp")).read()
            assert "{2 1}" in text and "NoIter" in text and "DumpActInts true" in text
            assert info.remote_copy_list == [
                (
                    code.computer.uuid,
                    remote.get_remote_path() + "/aiida.qro",
                    "reference.gbw",
                )
            ]
            assert (
                "aiida.gbw" not in info.retrieve_list
                and "aiida.fcidump" in info.retrieve_list
            )
    finally:
        process.close()


def test_worker_discovery_ignores_unrelated_nodes(aiida_code_installed):
    from aiida import orm
    from aiidalab_orca.energy_services import resources

    orm.Str("Unrelated data in a real profile").store()
    code = aiida_code_installed(filepath_executable="/usr/bin/true")
    code.base.extras.set(
        "quantum_energy_tools",
        {
            "protocol": "quantum-energy/v1",
            "source_sha256": "0" * 64,
            "commands": ["validate"],
            "versions": {},
        },
    )
    found = resources("validate")
    assert str(code.uuid) in [row["uuid"] for row in found]
    assert all(row["computer"] for row in found)
