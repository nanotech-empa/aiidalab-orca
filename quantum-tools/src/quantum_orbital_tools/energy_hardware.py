"""IBM adapter with reviewable compilation and durable, single-attempt jobs.

Accounts are configured on the worker. Credentials never enter AiiDA inputs,
plans, receipts, source files or returned diagnostics. No server-mock samples
are accepted as molecular data.
"""

import hashlib
import json
import os
from pathlib import Path
import uuid

from .hamiltonian import file_sha256
from .ibm_ledger import JobLedger, LedgerError


def connect():
    from qiskit_ibm_runtime import QiskitRuntimeService

    name = os.environ.get("QUANTUM_ENERGY_ACCOUNT")
    if not name:
        raise ValueError("Configure QUANTUM_ENERGY_ACCOUNT on the hardware worker")
    return QiskitRuntimeService(name=name)


def instance_reference(service):
    instance = service.active_instance()
    if not instance:
        raise ValueError("The provider account has no explicit active instance")
    return hashlib.sha256(str(instance).encode()).hexdigest()


def plan_hash(plan):
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in plan.items() if k != "request_sha256"},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def prepare(h, request, settings, service=None):
    from qiskit import qpy
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
    from .energy import integer

    backend_name = settings.get("backend", "").strip()
    if not backend_name or backend_name.startswith("mock_"):
        raise ValueError("Select a real provider backend for hardware preparation")
    shots = integer(settings, "shots", 1000, 100, 100000)
    maximum = integer(settings, "max_execution_seconds", 60, 1, 3600)
    budget = integer(settings, "budget_total_seconds", 90, 1, 86400)
    margin = integer(settings, "budget_margin_seconds", 30, 0, 3600)
    if maximum + margin > budget:
        raise ValueError(
            "Hardware execution limit and margin exceed the campaign budget"
        )
    if (
        file_sha256(Path("circuits.qpy"))
        != request["circuit_manifest"]["circuits_sha256"]
    ):
        raise ValueError("Logical circuits changed")
    if request["circuit_manifest"].get("sector") != request.get("sector") or request[
        "circuit_manifest"
    ].get("nelec") != list(h.nelec):
        raise ValueError("Logical circuits belong to a different electron/spin sector")
    service = service or connect()
    backend = service.backend(name=backend_name)
    if not backend.status().operational or backend.num_qubits < 2 * h.norb:
        raise ValueError("The requested hardware backend is unavailable or too small")
    with Path("circuits.qpy").open("rb") as stream:
        circuits = qpy.load(stream)
    if shots * len(circuits) > 10_000_000:
        raise ValueError(
            "This app limits one hardware request to ten million circuit executions"
        )
    manager = generate_preset_pass_manager(
        backend=backend,
        optimization_level=1,
        seed_transpiler=integer(settings, "seed", 42, 0, 2**32 - 1),
    )
    compiled, summary = [], []
    for circuit in circuits:
        isa = manager.run(circuit)
        backend.check_faulty(isa)
        compiled.append(isa)
        summary.append(
            {
                "name": isa.name,
                "depth": isa.depth(),
                "two_qubit_gates": sum(x.operation.num_qubits == 2 for x in isa.data),
            }
        )
    with Path("prepared.qpy").open("wb") as stream:
        qpy.dump(compiled, stream)
    identity = str(uuid.uuid4())
    plan = {
        "pilot_id": identity,
        "campaign_id": identity,
        "backend": backend_name,
        "instance_reference": instance_reference(service),
        "shots": shots,
        "max_execution_seconds": maximum,
        "budget_total_seconds": budget,
        "budget_margin_seconds": margin,
        "logical_qubits": 2 * h.norb,
        "sector": request.get("sector"),
        "nelec": list(h.nelec),
        "hamiltonian_sha256": request["hamiltonian_sha256"],
        "logical_circuits_sha256": request["circuit_manifest"]["circuits_sha256"],
        "prepared_sha256": file_sha256(Path("prepared.qpy")),
        "circuits": summary,
    }
    plan["request_sha256"] = plan_hash(plan)
    return {
        "hardware_plan": plan,
        "prepared_sha256": plan["prepared_sha256"],
        "qpu_jobs_submitted": 0,
        "execution_kind": "hardware_preparation_only",
    }


def identified_job(service, ledger, plan):
    row = ledger.get(plan["pilot_id"], "hardware")
    tag = "energy-" + plan["pilot_id"]
    jobs = (
        [service.job(row["job_id"])]
        if row["job_id"]
        else service.jobs(limit=2, job_tags=[tag])
    )
    unique = {job.job_id(): job for job in jobs}
    if len(unique) != 1:
        raise LedgerError(
            "The previous submission is unresolved; do not submit another hardware job"
        )
    job = next(iter(unique.values()))
    tags = job.tags() if callable(getattr(job, "tags", None)) else job.tags
    if job.backend().name != plan["backend"] or tag not in tags:
        raise LedgerError("Provider job identity differs from the prepared request")
    if not row["job_id"]:
        ledger.bind(plan["pilot_id"], "hardware", job.job_id())
    return job


def submit_or_resume(
    service, plan, circuits, *, authorized, ledger, sampler_factory=None
):
    """No blind retry, including after a timeout or lost provider response."""
    if (
        plan_hash(plan) != plan["request_sha256"]
        or instance_reference(service) != plan["instance_reference"]
    ):
        raise ValueError("The reviewed hardware request or provider instance changed")
    row = ledger.prepare(plan, "hardware")
    if row["state"] != "prepared":
        return identified_job(service, ledger, plan), False
    if authorized is not True:
        raise ValueError(
            "New hardware execution requires the explicit hardware Submit action"
        )
    backend = service.backend(name=plan["backend"])
    if not backend.status().operational:
        raise ValueError("Hardware backend is unavailable")
    from qiskit_ibm_runtime.utils.validations import validate_isa_circuits

    validate_isa_circuits(circuits, backend.target)
    for circuit in circuits:
        backend.check_faulty(circuit)
    if sampler_factory is None:
        from qiskit_ibm_runtime import SamplerV2

        sampler_factory = SamplerV2
    sampler = sampler_factory(
        mode=backend,
        options={
            "max_execution_time": plan["max_execution_seconds"],
            "default_shots": plan["shots"],
            "environment": {"job_tags": ["energy-" + plan["pilot_id"]]},
        },
    )
    if not ledger.claim_submission(plan, "hardware"):
        return identified_job(service, ledger, plan), False
    try:
        job = sampler.run(circuits, shots=plan["shots"])
        ledger.bind(plan["pilot_id"], "hardware", job.job_id())
        return identified_job(service, ledger, plan), True
    except BaseException:
        ledger.ambiguous(plan["pilot_id"], "hardware")
        raise


def sample(h, request, settings, service=None):
    from qiskit import qpy

    plan = request["prepared_manifest"]["hardware_plan"]
    if (
        plan["hamiltonian_sha256"] != request["hamiltonian_sha256"]
        or plan["logical_qubits"] != 2 * h.norb
        or plan.get("sector") != request.get("sector")
        or plan.get("nelec") != list(h.nelec)
        or file_sha256(Path("prepared.qpy")) != plan["prepared_sha256"]
    ):
        raise ValueError(
            "Prepared hardware circuits do not match the selected Hamiltonian"
        )
    with Path("prepared.qpy").open("rb") as stream:
        circuits = qpy.load(stream)
    service = service or connect()
    ledger = JobLedger(
        os.environ.get(
            "QUANTUM_ENERGY_LEDGER_DIR",
            str(Path.home() / ".local/share/quantum-energy/ibm"),
        )
    )
    job, submitted = submit_or_resume(
        service,
        plan,
        circuits,
        authorized=settings.get("hardware_authorized", False),
        ledger=ledger,
    )
    status = str(job.status()).upper().split(".")[-1]
    ledger.observe(plan["pilot_id"], "hardware", status)
    receipt = {
        "execution_kind": "ibm_hardware",
        "job_id": job.job_id(),
        "status": status,
        "new_submission": submitted,
        "qpu_jobs_submitted": int(submitted),
        "hardware_plan": plan,
        "samples_available": False,
    }
    if status == "DONE":
        counts = {}
        pubs = job.result()
        if len(pubs) != len(circuits):
            raise ValueError("Provider result has the wrong number of circuits")
        for pub in pubs:
            part = pub.data.meas.get_counts()
            if sum(part.values()) != plan["shots"]:
                raise ValueError("Provider result has the wrong number of shots")
            for bits, count in part.items():
                if (
                    len(bits) != 2 * h.norb
                    or set(bits) - set("01")
                    or type(count) is not int
                    or count < 1
                ):
                    raise ValueError(
                        "Provider bitstrings do not match the logical register"
                    )
                counts[bits] = counts.get(bits, 0) + count
        packet = {
            "n_qubits": 2 * h.norb,
            "nelec": list(h.nelec),
            "sector": request.get("sector"),
            "counts": counts,
            "shots": sum(counts.values()),
            "qubit_to_classical": list(range(2 * h.norb)),
            "hamiltonian_sha256": request["hamiltonian_sha256"],
            "physical_samples": True,
            "execution_kind": "ibm_hardware",
            "provider_job_id": job.job_id(),
        }
        Path("samples.json").write_text(
            json.dumps(packet, indent=2, allow_nan=False) + "\n"
        )
        receipt.update(
            samples_available=True, samples_sha256=file_sha256(Path("samples.json"))
        )
    return receipt
