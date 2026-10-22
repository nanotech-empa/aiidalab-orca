# AiiDAlab chat guide: ORCA CASCI, Dyson and Kondo validation

Use this procedure when preparing, inspecting or recovering the ORCA app's
fixed-orbital CASCI → Dyson → Kondo-channel/map calculation. It is an operating
procedure and an automation design, not an instruction to change the user's
method or submit more calculations. Follow the existing task's resource,
retention and publication authorizations.

## Contract for agents in the AiiDAlab chat

Consult this installed app-owned guide before advising on or preparing CASCI,
Dyson, Kondo calculations, recovery or map interpretation. It is supplied in the
chat instructions for relevant turns and can be reopened with
`read_workflow_guide` using guide ID `orca.casci-kondo`. Identify missing evidence
before proposing an action. This document supplies domain guidance, not permission
to submit calculations or override the user's scientific choices.

Use only tools exposed by the current chat. The ORCA adapter currently supports
structure/form preparation, review and SCF/geometry submission; it does not expose
CASCI, Dyson or Kondo submission/editing tools. Use read-only calculation inspection
where available and guide the user to the corresponding app controls for those
stages. Do not invent shell, Python or workflow-submission capabilities. A future
adapter may expose more tools; inspect their actual schemas first. Process control
and submissions retain the chat's existing action-review requirements.

Inspect UUIDs and live process reports before giving a calculation-specific
recommendation. A guide citation, old benchmark report or remembered parameter is
not evidence that a particular calculation passed. Distinguish an observation
failure, a running job, a rejected result and a scientifically unresolved choice.
If this guide cannot be loaded, say so and do not improvise specialized recovery
or claim its checks were followed.

## Implementation boundary

The maintained application is [nanotech-empa/aiidalab-orca](https://github.com/nanotech-empa/aiidalab-orca).
Its [Kondo component](https://github.com/nanotech-empa/aiidalab-orca/pull/21)
contains separate exchange, native-cube and map stages. Companion changes
[25](https://github.com/nanotech-empa/aiidalab-orca/pull/25),
[26](https://github.com/nanotech-empa/aiidalab-orca/pull/26) and
[27](https://github.com/nanotech-empa/aiidalab-orca/pull/27) respectively reject
explicit CI nonconvergence, stream large state summaries and expose reviewed
CI controls. Check their actual merge/deployment state before claiming a guard
is present. An integration checkout may contain these changes before main does.

Native parsers and WorkChains enforce identity, artifact, CI-norm, exchange and
grid checks. They store scientific outputs with provenance. A unified validation
report/dashboard and a convergence-aware retry coordinator remain **planned**.
The A2n operational scripts are evidence from one benchmark, not a portable
submission API. Use the app services and native WorkChains for new work.

## Establish the reviewed plan

Record the geometry UUID and coordinate frame, common-orbital reference and
checkpoint checksum, basis/element overrides, exact inactive/active indices,
reference electron count, charge/spin sectors, roots, integral approximation,
CI controls and printing threshold. Also record executable/runtime identity,
computer, scheduler resources and the retention policy. Check source methods
before a benchmark; document controlled differences before submission.
Check local free space before large output retrieval. Inspect source metadata
and checksums remotely where possible instead of copying an entire large run.

The active space, molecular charge and physical initial spin need scientific
judgment. A small illustrative CAS is not an automatic protocol. Keep different
orbital families separate, even if they describe the same geometry. A conditional
excited triplet calculation does not establish triplet occupation on a surface.

The model follows [Calvo-Fernández et al., PRB 110, 165113](https://doi.org/10.1103/PhysRevB.110.165113).
It assumes a spin-pure local moment with S > 0, spin-free states, one shared
spatial basis and equal scalar substrate coupling of active orbitals. A singlet
ground state, SOC or nonequilibrium populations can require a different model;
do not silently substitute a triplet or infer its population from STM bias.

## Evidence at each gate

| Gate | Evidence to inspect | Required response |
| --- | --- | --- |
| Existing result / files | Successful provenance-linked result, compatible inputs, and the particular artifacts needed next | Reuse explicit results independently of AiiDA caching; distinguish unavailable transport from missing files |
| Native CASCI | Generated and echoed fixed-orbital controls, correct roots/spin, normal termination, all relevant CI blocks and late warnings | Reject explicit CI nonconvergence even if the process printed energies or terminated normally |
| Wavefunction export | Source state/checkpoint identity, archive checksum, roots and raw printed CI norms | Stop on truncated or inconsistent vectors; retain the source and failed attempt |
| Dyson | Same orbital reference, exact active indices and model; addition/removal electron count; ΔS = ±½; signed amplitudes and stored component convention | Stop on incompatible sectors; never repair by phase fitting, renormalization or silently changing the reference |
| Exchange | Positive charging costs at explicit μ; valid matrix/eigenpairs; selected and missing sectors | Reject invalid costs; expose small-gap, missing-sector and degeneracy warnings |
| Native cubes | Exact initial CASCI checkpoint, common origin/axes/shape/geometry and source checksums | Combine signed amplitudes on the native grid; no hidden interpolation, phase fitting or grid renormalization |
| Maps / figures | Full-cube source, plane/reference/height, boundary and propagation model, common colour scale, linked numerical and figure outputs | Reopen through the app; inspect actual images and report the model's limits |

Do not infer a retained CI-vector norm from a small energy change. The default
maximum missing printed CI norm is 1e-5; it is a truncation diagnostic, not a
bound on a Dyson orbital or map error. A norm failure normally requires an
explicit frozen-CASCI rerun with tighter printing and rechecked invariants.
Do not normalize the truncated coefficients or loosen the threshold to pass.
Energy-invariance tolerances must come from the reviewed comparison, not a
universal value copied from a different molecule.
If both an export and its GBW are lost, restore them or explicitly recompute
the affected sector from the exact common orbitals. If those common orbitals
are also lost, do not mix regenerated orbitals with old sectors automatically.

Root 0 means the lowest computed state in that particular charge/multiplicity
sector. It is not proof of the physical global ground state. Preserve absolute
energies and state identities; a display zero or rigid spectral offset is not a
substrate chemical potential.

For exchange, μ uses ε = E + (N−N₀)μ. Thus
Δ₋ = −removal_pole − μ and Δ₊ = addition_pole + μ. The interval is checked only
against supplied roots. Without an established alignment, review a scan inside
the charge-stability interval and label it as a model scan. Raw highest-Ms Dyson
components already contain their component Clebsch–Gordan factors. Use the
exchange conversion implemented in `kondo_data.py`; do not apply the spectral
spin-sum factor or multiply the Dyson strength a second time.

## Convergence and bounded recovery

Follow specific process UUIDs and scheduler IDs. Confirm their current state;
an old lock or state file does not prove that a process is alive. A failed
observation or elapsed timeout does not prove that a scientific job stopped.
Inspect the same handle again before any restart. Running tigu jobs survive a
local internet outage; AiiDA monitoring/retrieval may wait or pause. Renew CSCS
authentication through the user when needed, then resume the existing processes.

Inspect root-resolved energy changes and residual histories, especially the
slowest roots. Rounded printed values are diagnostics, not convergence decisions
or observable-error bounds. Distinguish slow improvement from a plateau,
divergence, lost roots, memory failure, runtime crash or parser failure.

When the iteration limit is reached, a previously approved bounded policy may
allow a new attempt with a larger limit and unchanged scientific inputs. Check
the actual input and resources before submission, preserve the old attempt and
link the decision. More iterations help only when the iterative solve makes
progress. Stop for review if the bound is exhausted or the trend is poor.
`MaxDim` can increase memory. A solver change needs a controlled comparison in
the same basis, including exported vectors and degenerate-state subspaces;
matching energies alone is insufficient. The observed ORCA ACCCI export crash
is a reason to validate that route, not a universal claim that ACCCI is invalid.

After CI/export acceptance, compare root prefixes using existing states before
requesting a larger electronic calculation. Report changes in the exchange
matrix, leading eigenvalues and degenerate-channel projectors/subspaces. A
small change in two leading eigenvalues can coexist with a larger full-matrix
change. None of these finite-prefix tests bounds the uncomputed tail. Keep
individual degenerate orbital shapes labelled as basis-dependent.

## Proposed coordinator and validation report

Retain separate scientific WorkChains/CalcJobs. A coordinator should consume
their immutable outputs and a reviewed policy; an agent interprets the report
and proposes actions. The following is a design contract, **not a shipped API**:

- A plan identifies the scientific signature, required sectors/roots, codes,
  resource ceilings, retention, numerical policy and maximum recovery attempts.
- Each gate report identifies its producing process and input UUIDs/checksums,
  check implementation/version, expected and observed values, units/tolerances,
  evidence location, result and reason. Use `passed`, `waiting`, `review_needed`
  and `failed` explicitly; transport unavailable is a reason for waiting, not
  a failed checksum or proof of deletion.
- A recovery proposal names the affected stage, existing live process or source,
  proposed input difference, compute/storage cost, invariants to recheck and
  bounded stopping condition. A review decision records what was authorized;
  changed scientific decisions never follow merely from elapsed waiting time.
- Persist reports and reviewed decisions as new provenance-linked AiiDA outputs.
  Do not retrofit scientific attributes or repositories on existing nodes.
  Keep only UUIDs/plain values in UI/agent state and reload nodes per operation.
- Before acting, recheck that the selected source and settings have not changed
  since review. Reuse exact completed stages; do not duplicate a live attempt.
  A user override creates a new plan/attempt with an explicit lineage.

A compact app summary should expose the gate, reason, evidence and one concrete
next action. Typical actions are reconnect/resume, restore an exact artifact,
review a bounded CI continuation, or regenerate a cube. Changing the active
space, physical state, solver, integral model or acceptance tolerance needs
scientific review. A green process indicator must not conceal a pending choice.

## Final map review

Use full-resolution cubes for numerical maps and cubehandler-reduced cubes for
interactive previews. Preserve isolated-molecule boundaries. The current
default source plane is 1.5 Å above the highest atom along +z; record the actual
plane and observation height, including any viewer override. Use a shared
explicit brightness scale for compared images and μ points.

Save maps and PNG/PDF figures through CalcJobs with all settings as inputs.
Verify Search → the molecular reference → States & Dyson → Kondo orbitals &
maps, select the intended μ result, and inspect the stored images. A service
test or generated report alone is not browser-rendering evidence.

Each image is an individual unit-normalized eigenchannel intensity map.
Exchange eigenvalues are not brightness weights. These results do not establish
a combined experimental Kondo map, Kondo temperature, linewidth, Fano profile
or PP-STM CO-tip simulation. Document qualitative agreement and discrepancies
without selecting a new model solely to match the picture.
