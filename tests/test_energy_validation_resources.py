"""Internal Hamiltonian validation uses the reviewed export allocation."""

from copy import deepcopy
import io
from types import SimpleNamespace

import pytest
from aiida import orm
from aiida.common import LinkType

from aiida_empa_orca.energy import EnergyExportWorkChain
from aiidalab_orca import energy_services as service
from test_casci import common_reference  # noqa: F401
from test_reference import electronic_source  # noqa: F401
from test_l06_resources import completed_common  # noqa: F401


SPACE = {'electrons': 3, 'orbitals': [6, 7]}


@pytest.fixture
def export_context(completed_common, configured_orca_tools):
    uid = completed_common[0]
    code = orm.load_node(uid).inputs.code
    code.base.extras.set('quantum_energy_tools', {
        'protocol': 'quantum-energy/v1', 'source_sha256': '0'*64,
        'commands': ['validate'], 'versions': {},
    })
    return uid, str(code.uuid)


@pytest.mark.parametrize('nprocs,memory,seconds', [(2,2048,600), (1,1024,300), (4,3072,540)])
def test_real_validation_builder_inherits_budget_and_threads(export_context, nprocs, memory, seconds):
    uid, code = export_context
    plan = service.prepare_export(uid, SPACE,
        {'nprocs': nprocs, 'memory_mb': memory, 'wallclock_seconds': seconds}, code,
        native_output_policy={'mode': 'remote', 'maxsizeoutput': 5*1024**2})
    parent = service.builder(plan)
    native = orm.CalcJobNode()
    for key, value in plan['validation_options'].items():
        if key != 'environment_variables':
            native.set_option(key, value)
    native.store()
    hamiltonian = orm.SinglefileData(file=io.BytesIO(b'synthetic integral fixture'), filename='model.fcidump')
    metadata = orm.Dict(dict={'synthetic': True})
    for name, node in [('hamiltonian',hamiltonian), ('native_export',metadata)]:
        node.base.links.add_incoming(native, link_type=LinkType.CREATE, link_label=name)
        node.store()
    captured = []
    process = SimpleNamespace(inputs=SimpleNamespace(worker_code=parent.worker_code, settings=parent.settings),
        ctx=SimpleNamespace(export_uuid=str(native.uuid)),
        submit=lambda child: captured.append(child) or orm.CalcJobNode())
    EnergyExportWorkChain.validate(process)
    assert len(captured) == 1
    child = captured[0]
    options = child.metadata.options
    assert options.resources == {'num_machines':1, 'num_mpiprocs_per_machine':nprocs}
    assert options.max_memory_kb == memory*1024
    assert options.max_wallclock_seconds == seconds
    assert not options.withmpi
    assert dict(options.environment_variables) == {
        key:str(nprocs) for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}
    assert {key: dict(options)[key] for key in plan['validation_options']} == plan['validation_options']
    assert child.hamiltonian.uuid == hamiltonian.uuid
    assert child.native_export.uuid == metadata.uuid
    assert child.operation.value == 'validate' and child.settings.get_dict() == {}
    changed = deepcopy(plan)
    changed['validation_options']['max_memory_kb'] *= 2
    with pytest.raises(ValueError, match='Export context changed'):
        service.builder(changed)


def test_export_review_describes_serial_validator_and_invalidates_budget(export_context, monkeypatch):
    from aiidalab_orca.quantum_energy import QuantumEnergy
    uid, _ = export_context
    monkeypatch.setattr(service, 'submit', lambda *_: pytest.fail('No job is submitted by this regression'))
    panel = QuantumEnergy(uid, SPACE)
    try:
        panel.processes.value = 2
        panel.memory.value = 2
        panel.minutes.value = 10
        panel.full_files.mode.value = 'remote'
        panel._choose('export')
        assert panel._plan is not None
        assert 'one validation worker (2 CPU threads)' in panel.review.value
        assert 'total memory 2 GiB' in panel.review.value and 'up to 10 minutes' in panel.review.value
        for control, value in [(panel.memory,1),(panel.minutes,9),(panel.processes,1)]:
            previous = control.value
            control.value = value
            assert panel._plan is None and panel.submit_button.disabled
            control.value = previous
            assert panel._plan is None and panel.submit_button.disabled
            panel._review_current()
    finally:
        panel.close()
