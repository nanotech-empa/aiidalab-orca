# Optional Remote QPU tests

Read [the test contract](README.md) and the installed
[quantum-energy guide](../../src/aiidalab_orca/knowledge/quantum-energy.md).
Simulator and Remote CPU permissions do not authorize hardware use.

## Agree on hardware scope

Record explicit approval for:

- Provider, accessible project/instance and configured worker/computer.
- Backend name, source model/circuit IDs and allowed test cases.
- Maximum new jobs, circuits, shots per circuit and aggregate QPU budget.
- Execution timeout/margin and whether cancellation is authorized. Retrieving
  an existing job is distinct from creating a new one.

An initial small scope can be **one CAS(3,3) circuit, 100 shots, at most one
new hardware job**; the time budget must be agreed from the provider review.
A Phoenix application is not yet an allocation. Do not assume an IBM Open
account reaches it or choose a backend solely because its name appears.

## Q01 — User-owned credentials

**Submits:** no QPU job. Saving and checking connectivity are separate.

1. Open **QPU credentials** below the main tabs. This configures the AiiDAlab
   server, not every remote worker automatically.
2. The user enters the account name, assigned instance CRN and API key directly
   in the masked form. An agent pauses for that action and never requests the
   key in chat, reads its DOM value, or includes it in screenshots/reports.
3. The user saves/selects the account. Preserve other accounts; replacement
   requires the explicit replacement choice and user intent.
4. If authorized, click **Check connection (no QPU job)**. Record only the alias
   and success/error message.
5. A remote hardware worker needs its own owner/setup-managed credentials.
   Never transfer a key through AiiDA inputs.

**PASS:** visible account initialization/selection and a separate read-only
check, without hardware execution. File permissions and exclusion from notebook,
AiiDA and Git are separate maintainer checks, not inferred from masked dots.
An unsupported provider is BLOCKED, not an invitation to pretend it is IBM.

## Q02 — Prepare hardware without execution

**Needs:** L18 circuits and authorized provider preparation. **Submits:** CPU
preparation/provider discovery and compilation; no QPU job.

1. Select the authorized model/circuits in **Quantum-assisted energy levels**.
   Choose **Real IBM QPU** only for the implemented IBM adapter.
2. Enter the approved backend, shots, execution cap, budget and margin. Keep
   real-hardware execution authorization **off**.
3. Review/submit **Prepare hardware circuits for review (no QPU job)** on the
   configured worker. Inspect compiled qubits, depths, two-qubit gates and request ID.
4. Check instance/backend and limits. Model/circuit/budget changes need new review.

**PASS:** a validated prepared plan and no hardware execution. Access, instruction
or budget failures block Q03.

## Q03 — One authorized hardware submission

**Needs:** Q02 and execution authorization for this reviewed request.

1. Record provider/backend, model, circuit count, shots, cap, margin and job limit.
2. Enable **I authorize execution of this reviewed request on real hardware**.
   Review sampling and submit the reviewed stage **once**.
3. Record the AiiDA UUID and provider job ID separately. Refresh/retrieve the
   same request. A lost response never authorizes a second job; use only the
   app's same-request recovery path.
4. Inspect preserved counts, sector retention, actual reported usage and
   physical/simulator/mock labels. Mock data are not hardware measurements.
5. If authorized, analyze existing counts with the same model. Inspect residual,
   spin, coverage and energy checks; compare L18/L07 only for matching identities.

**PASS for integration:** one traceable provider submission, retained measurements,
explicit usage and correct validation behavior. A scientific rejection remains
a rejected result; report the guard separately. Do not increase shots or relax
checks/recovery settings automatically. This establishes neither quantum
advantage nor converged Dyson/Kondo amplitudes.
