from types import SimpleNamespace

import pytest

from quantum_orbital_tools.energy_hardware import (
    instance_reference,
    plan_hash,
    submit_or_resume,
)
from quantum_orbital_tools.ibm_ledger import JobLedger, LedgerError


def test_connection_uses_selected_worker_account_and_environment_precedence(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    runtime = pytest.importorskip('qiskit_ibm_runtime')
    from quantum_orbital_tools.energy_hardware import connect

    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('QUANTUM_ENERGY_ACCOUNT', raising=False)
    calls = []
    monkeypatch.setattr(runtime, 'QiskitRuntimeService', lambda **kwargs: calls.append(kwargs) or kwargs)
    with pytest.raises(ValueError, match='Configure QPU credentials'):
        connect()
    assert not calls
    settings = tmp_path / '.config/aiidalab-orca/qpu.json'
    account = tmp_path / '.qiskit/qiskit-ibm.json'
    for path, data in [(settings, {'ibm_account': 'project'}), (account, {})]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
        path.chmod(0o600)
    assert connect() == {'name': 'project', 'filename': str(account)}
    monkeypatch.setenv('QUANTUM_ENERGY_ACCOUNT', 'admin-configured')
    assert connect() == {'name': 'admin-configured'}


def setup_case(tmp_path):
    qiskit = pytest.importorskip("qiskit")
    pytest.importorskip("qiskit_ibm_runtime")
    from qiskit.providers.fake_provider import GenericBackendV2

    target = GenericBackendV2(4, seed=42).target
    backend = SimpleNamespace(
        name="test_backend",
        target=target,
        status=lambda: SimpleNamespace(operational=True),
        check_faulty=lambda _: None,
    )
    service = SimpleNamespace(
        active_instance=lambda: "test-instance",
        backend=lambda **kwargs: backend,
        jobs=lambda **kwargs: [],
    )
    plan = {
        "pilot_id": "test-pilot",
        "campaign_id": "test-campaign",
        "backend": backend.name,
        "instance_reference": instance_reference(service),
        "shots": 100,
        "max_execution_seconds": 10,
        "budget_total_seconds": 20,
        "budget_margin_seconds": 5,
    }
    plan["request_sha256"] = plan_hash(plan)
    circuit = qiskit.QuantumCircuit(4)
    circuit.x(0)
    circuit.measure_all()
    return service, backend, plan, [circuit], JobLedger(tmp_path / "ledger")


def test_hardware_needs_explicit_action_and_resumes_same_job(tmp_path):
    service, backend, plan, circuits, ledger = setup_case(tmp_path)
    calls = []
    job = SimpleNamespace(
        job_id=lambda: "job-1", backend=lambda: backend, tags=["energy-test-pilot"]
    )
    service.job = lambda _: job

    def factory(**kwargs):
        def run(*args, **kwargs):
            calls.append("submit")
            return job

        return SimpleNamespace(run=run)

    with pytest.raises(ValueError, match="explicit hardware"):
        submit_or_resume(
            service,
            plan,
            circuits,
            authorized=False,
            ledger=ledger,
            sampler_factory=factory,
        )
    assert calls == []
    first, new = submit_or_resume(
        service, plan, circuits, authorized=True, ledger=ledger, sampler_factory=factory
    )
    second, new_again = submit_or_resume(
        service,
        plan,
        circuits,
        authorized=False,
        ledger=ledger,
        sampler_factory=factory,
    )
    assert first.job_id() == second.job_id() == "job-1"
    assert new is True and new_again is False and calls == ["submit"]


def test_uncertain_provider_response_never_triggers_blind_resubmission(tmp_path):
    service, _, plan, circuits, ledger = setup_case(tmp_path)
    calls = []

    def factory(**kwargs):
        def run(*args, **kwargs):
            calls.append("submit")
            raise RuntimeError("lost provider response")

        return SimpleNamespace(run=run)

    with pytest.raises(RuntimeError, match="lost provider"):
        submit_or_resume(
            service,
            plan,
            circuits,
            authorized=True,
            ledger=ledger,
            sampler_factory=factory,
        )
    with pytest.raises(LedgerError, match="unresolved"):
        submit_or_resume(
            service,
            plan,
            circuits,
            authorized=True,
            ledger=ledger,
            sampler_factory=factory,
        )
    assert calls == ["submit"]
