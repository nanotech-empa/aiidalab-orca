"""One native AiiDA stage on disposable test storage, without a daemon."""

import hashlib
from importlib.metadata import EntryPoint
import io
from pathlib import Path
import sys

import pytest

pytest.importorskip("pyscf")


def test_cpu_stage_upload_execution_and_parser(
    aiida_code_installed, tmp_path, monkeypatch
):
    import numpy as np
    from pyscf.tools import fcidump
    from aiida import engine, orm
    from aiida.plugins import entry_point
    from aiida_empa_orca.energy import EnergyStageCalculation

    worker_source = Path(__file__).resolve().parents[1] / "quantum-tools/src"
    monkeypatch.syspath_prepend(str(worker_source))
    from quantum_orbital_tools.energy import manifest

    original = entry_point.get_entry_point

    def resolve(group, name):
        values = (
            {"empa_orca.energy_stage": "aiida_empa_orca.energy:EnergyStageCalculation"}
            if group == "aiida.calculations"
            else {}
        )
        if group == "aiida.parsers":
            values["empa_orca.energy_stage"] = (
                "aiida_empa_orca.energy:EnergyStageParser"
            )
        if name in values:
            return EntryPoint(name=name, value=values[name], group=group)
        return original(group, name)

    monkeypatch.setattr(entry_point, "get_entry_point", resolve)
    target = tmp_path / "fixture.fcidump"
    eri = np.zeros((2,) * 4)
    eri[0, 0, 0, 0] = 0.5
    eri[1, 1, 1, 1] = 0.3
    fcidump.from_integrals(
        str(target), np.array([[-1.0, 0.03], [0.03, -0.2]]), eri, 2, 2, nuc=0.7
    )
    raw = target.read_bytes()

    @engine.calcfunction
    def source_fixture(data):
        with data.open(mode="rb") as stream:
            content = stream.read()
        return {
            "hamiltonian": orm.SinglefileData(
                file=io.BytesIO(content), filename="hamiltonian.fcidump"
            ),
            "native_export": orm.Dict(
                dict={
                    "source_is_test_fixture": True,
                    "charge": 0,
                    "active_space": {"electrons": 2},
                    "hamiltonian_sha256": hashlib.sha256(content).hexdigest(),
                }
            ),
        }

    source = source_fixture(
        orm.SinglefileData(file=io.BytesIO(raw), filename="fixture.fcidump")
    )
    executable = tmp_path / "quantum-energy"
    executable.write_text(
        "#!"
        + sys.executable
        + "\nfrom quantum_orbital_tools.energy import main\nmain()\n"
    )
    executable.chmod(0o755)
    code = aiida_code_installed(
        filepath_executable=str(executable),
        prepend_text="export PYTHONPATH="
        + str(worker_source)
        + '${PYTHONPATH:+:$PYTHONPATH}\nexport AIIDA_PATH="$PWD/isolated-aiida"',
    )
    code.base.extras.set("quantum_energy_tools", manifest())
    outputs, node = engine.run_get_node(
        EnergyStageCalculation,
        code=code,
        hamiltonian=source["hamiltonian"],
        native_export=source["native_export"],
        operation=orm.Str("solve-full"),
        sector=orm.Dict(dict={"charge": 0, "ms2": 0}),
        settings=orm.Dict(dict={"nroots": 2, "threads": 1}),
        metadata={
            "options": {
                "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1},
                "max_wallclock_seconds": 30,
                "withmpi": False,
            }
        },
    )
    assert node.is_finished_ok, "\n".join(
        log.message for log in orm.Log.collection.get_logs_for(node)
    )
    assert outputs["result"].get_dict()["used_roots"] == 2
    assert outputs["result"].get_dict()["qpu_jobs_submitted"] == 0
    assert outputs["states"].creator.uuid == node.uuid
    if "generate" not in manifest()["commands"]:
        return
    prior = {}
    for operation, settings in [
        ("generate", {"randomizations": 1, "groups": 5, "times": [1.0]}),
        ("sample-simulator", {"shots": 1000, "max_qubits": 14}),
        ("solve-sampled", {"nroots": 2, "string_limit": 10}),
    ]:
        extra = {}
        if operation == "sample-simulator":
            extra = {
                "circuits": prior["generate"]["circuits"],
                "circuit_manifest": prior["generate"]["result"],
            }
        elif operation == "solve-sampled":
            extra = {"samples": prior["sample-simulator"]["samples"]}
        result, node = engine.run_get_node(
            EnergyStageCalculation,
            code=code,
            hamiltonian=source["hamiltonian"],
            native_export=source["native_export"],
            operation=orm.Str(operation),
            sector=orm.Dict(dict={"charge": 0, "ms2": 0}),
            settings=orm.Dict(dict=settings),
            **extra,
            metadata={
                "options": {
                    "resources": {"num_machines": 1, "num_mpiprocs_per_machine": 1},
                    "max_wallclock_seconds": 30,
                    "withmpi": False,
                }
            },
        )
        assert node.is_finished_ok, "\n".join(
            log.message for log in orm.Log.collection.get_logs_for(node)
        )
        assert result["result"].get_dict()["qpu_jobs_submitted"] == 0
        prior[operation] = result
