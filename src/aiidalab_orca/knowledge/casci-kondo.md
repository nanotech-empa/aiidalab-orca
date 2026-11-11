# AiiDAlab chat guide: ORCA CASCI, Dyson and Kondo validation

Read `orca.app` first for the general GUI path, geometry/SCF preparation,
batch state requests, peak-map handoff and shared-chat tool boundaries. Read
`orca.vibrations` for IR/Raman, which is independent of this electronic route.

Use this procedure when preparing, inspecting or recovering the ORCA app's
fixed-orbital CASCI → Dyson → Kondo-channel/map calculation. It is an operating
procedure and an automation design, not an instruction to change the user's
method or submit more calculations. Follow the existing task's resource,
retention and publication authorizations.

## PDOS and orbital-character inspection

New SCF/geometry calculations and common-orbital preparations include orbital
character by default as workflow-managed child CalcJobs. Existing/reused
references are never backfilled automatically. Read the saved PDOS directly;
if its status reports missing tools or a failed analysis, fix/retry only that
postprocessing, without repeating SCF. The geometry/SCF resources page has a
checked **Compute PDOS / orbital character** option and independent **PDOS
resources**. Preparing QRO/UNO includes character analysis for each new set.

The draft **PDOS & orbital character** panel is available from **Orbitals &
density** and inside prepared-reference inspection. Consult
[the PDOS guide](../../../docs/pdos.md) before preparing its native CalcJob or
interpreting π-like contributions. It uses symmetric Löwdin atomic/angular
weights and an editable molecular-plane normal for perpendicular p character.
This is a basis-dependent descriptor, not a unique full π/σ classification or
an automatically justified CAS. Keep native spin/orbital identities unchanged.
QRO energies are reference labels; UNOs use an occupation/index view without a
KS-energy DOS. State DOS includes virtual orbitals and is not occupation weighted.
The shared structure viewer links 3D atom selection and one-based ranges such as
`1 3..5` to the PDOS fragment. Atom numbers start at 1; orbital indices remain
0-based. Its selection panel also measures distances, angles and dihedrals.
Input/final geometry inspection uses the same viewer; optimization frames and
separate trajectory playback are display-only and never change the reference.

Candidate selection forwards indices to the existing cube/inspection selector.
CAS preparation still validates and applies them. Do not claim that candidate
selection reordered orbitals or launched CASCI, or that this panel adds a new
noncontiguous preparation route. Preserve existing research permutations.
The extraction returns compact arrays; full coefficients/overlap remain on
the source computer and no Python selector is shown. Inspect the current
installed revision: separate native/browser qualification is not a live rollout.

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

**Full files** chooses remote/stash retention for large orbital files and Dyson
CI exports. Native text outputs up to **maxsizeoutput**, default 5 MiB per file,
are retrieved unchanged. Larger outputs produce a separate `aiida_summary.out`
(or `verify_summary.out`) plus an explicit notice under the original output
filename. A validation extract cannot supply CI vectors. Dyson uses the complete
retrieved CI log when present, otherwise the checksum-verified remote/stash
original. Catalog/preview requests inherit orbital retention; full cubes keep
their independent choice. Reused/running and historical records keep their
original policy. Verify installed `orca-tools` support before promising controls.

## Establish the reviewed plan

### Finding the controls in the GUI

In **New calculation**, choose the final **Calculation goal**. This keeps the
user in the molecule/SCF setup wizard; it does not open search. After the
reference finishes, the next required preparation/analysis stage opens. Each
later calculation needs its own review and submission. Reusing a saved
reference is an explicit **Open an existing reference instead** action, followed
by selection in **Search calculations** and **View results**.

**Results** has one **Analysis / results** selector, including CASCI, Dyson and
Kondo views of the same retained state workspace. Missing prerequisites keep
the requested analysis selected and offer an explicit prerequisite action.
The main path is **1. Prepare orbital reference → 2. Inspect / confirm active
space → 3. Choose energy solver → ORCA CASCI → 4. Dyson spectrum →
5. Kondo orbitals & maps**, stopping at
the chosen goal and reusing completed steps. The final goal remains visible
during preparation, and **Continue to…** checks its next required step. Navigation never
submits calculations or changes the physical model. CASCI holds orbitals fixed
and should not be described as orbital-optimized CASSCF. Check the installed
GUI version before promising these entry points are present.

The common-orbital selector chooses a prepared reference. To see orbital
shapes, use **View orbitals and choose active space** beneath the preparation
controls. Set **Prepared-orbital PDOS resources** before reviewing preparation;
QRO and UNO character jobs run one at a time. In inspection, set **Catalog
resources and export code**, then click **Review orbital information → Read
orbital information**, select orbitals,
then **Review orbital visualization → Generate orbital previews**. After
completion, **Orbital to display** selects the 3D preview. Preview settings and
file storage are optional advanced controls; no CASCI calculation is needed
to visualize the orbitals.

The **Orbital indices** text field is synchronized with the highlighted list
in both directions. It accepts zero-based indices separated by spaces or
commas, inclusive ranges such as `3..10` (including both endpoints), and mixed
entries such as `1 3..10 14, 18..21`; spaces around `..` are accepted.
Duplicates count once. Invalid text keeps the previous highlights and blocks
review/submission until corrected or replaced by clicking rows. Changing
orbital sets resets the field to the new set's highlighted selection.
Arbitrary selections are supported for previews; they do not automatically
change the CAS. The general CASCI preparation still requires a contiguous
window and explicit confirmation; the QPU permutation path is separate.

An SCF reference alone does not establish a reviewed active space. The user
must inspect/select orbitals or explicitly confirm a deliberate electron/orbital
count before a new CASCI request. A confirmation belongs to that exact prepared
reference and active space. Compatible saved CASCI results can establish the
recorded choice; changing the orbital reference requires review again.

Restricted references retain their restricted orbitals. Unrestricted preparation
provides QROs for the current CAS input and UNOs for inspection. UNO occupations
are SCF diagnostics, not correlated natural occupations; inspecting UNOs does
not switch the CAS basis. After confirming the active space, optional **Optimize
orbitals · CASSCF** creates a new shared reference from one state or a weighted
state average at fixed charge/geometry. Multiplicities remain distinct; the
optimization weights are not populations, Clebsch–Gordan factors or intensities.
Native orbital-gradient convergence and a frozen-orbital energy readback must
pass. Inspect its natural occupations/shapes and confirm the new reference
before computing compatible CASCI sectors for Dyson/Kondo. Never combine
independently optimized references. Arbitrary orbital reordering remains a
separate capability and must not be inferred from this step.
Verified imported fixed references remain distinct, provenance-linked sources.

In the CASSCF form, **One selected state** with root 0 requests one energy in
the chosen charge/multiplicity sector. CAS(n,m) counts electrons/orbitals, not
states. For an energy ladder in the optimized orbital basis, inspect/reconfirm
that reference and request several CASCI roots. A state average is a separate
orbital objective; use it when several states should share the optimization.
The openBIS companion adapter in `aiidalab-openbis#153` includes CASSCF reference
and complete state tables in the entry's export, with the existing CAS method
family. Verify that the installed exporter includes that mapping; the ORCA app
alone does not upgrade it. No new server object type is needed.

The separate correlation workspace can reuse verified CASSCF for
SC/FIC/DLPNO-NEVPT2 or CASPT2 energies; consult `orca.correlation` for its
diagnostics and rejection gates. Those outputs supply no compatible state
vectors or corrected transition amplitudes. Keep the current shared-orbital
CASCI → Dyson/Kondo branch intact rather than routing energy corrections into it.

### Scientific and execution inputs

Explain the GUI terminology explicitly: **Common orbitals** are the shared
spatial-orbital basis. **Electronic states** counts CASCI eigenstates (roots)
within the selected charge/multiplicity sector: one requests its lowest state,
two also requests the next. This count does not select the active orbital space.

The submission form accepts space/comma-separated lists: **Charges** such as
`0 +1 -1 +2 -2`, and **Multiplicities (2S+1)** such as `1 2 3 4`. Charges are
absolute molecular charges; for reference charge q₀, active electrons at charge
q are reference active electrons − (q − q₀). **Review charge / spin combinations**
lists every requested pair, including parity/capacity skip reasons and explicit
requested versus available state counts. When fewer spin-adapted states exist,
the review proposes all available states; the user must see this before
submission. Do not silently replace a requested spin or misclassify missing
files/resource errors as forbidden combinations. Those errors block the batch.

**Submit reviewed calculations** submits one persistent batch that starts
sector WorkChains in sequence for valid new pairs; matching saved/running requests are reused. The table shows job count,
per-job resources and each ORCA input. The reviewed sectors run sequentially in a persistent AiiDA batch, one at a time.
Each waits for the previous workflow and its CalcJobs to terminate, including
failed sectors; the queue continues after closing the browser. A submission
error stops subsequent requests and retains accepted UUIDs. Closing the GUI
does not stop submitted calculations. **Available charge** filters the saved
calculation selector without altering the submission lists or active-space
confirmation. Additional charge sectors do not relax Dyson's N±1 rule.

Explain execution inheritance: orbital preparation uses the SCF code,
computer and original resources. The preparation panel displays those actual
settings; saved remote/stashed wavefunctions are read on that computer.
CASCI retains the orbital reference's computer, but the user can edit its
process count, memory and wall time in **CASCI resources and advanced settings**.
The batch review shows the execution target and per-calculation resources.
The full compatible state diagram remains the main result. **Calculation
history and status** is collapsed below it and only inspects individual runs;
its charge/calculation selectors do not filter the diagram, reset its energy
zero/limits, or overwrite the submission draft.

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

## Spectral weights and map normalization

The default **Spin averaged · unpolarized** convention uses the implemented
spin-multiplet factor F; **Single spin component · M_S = S** uses the stored
highest-projection component. Initial-state population p is separate from F.
For a doublet initial state, singlet-final F = 1 and triplet-final F = 3/2.
Do not relabel these choices as one person's tool or infer a polarized-tip model.

For transition t, let Z_t be the stored squared norm of its signed orbital
coefficients, D_t(r) its unnormalized Dyson orbital, and L the selected
Lorentzian broadening. The spectrum uses `p_i F_t Z_t L(E-epsilon_t)`;
the incoherent spatial sum uses `p_i F_t L(E-epsilon_t) |D_t(r)|^2`.
The amplitude already carries Z_t: multiplying the spatial intensity by Z_t
again double-counts its strength. Preserve signed amplitudes for later exchange;
do not normalize raw cubes to one to conceal truncation or acceptance errors.
Vacuum extrapolation is applied to amplitudes before their intensities are summed.

Complete spectral maps include every computed compatible transition and its
off-resonant tail. Peak-detection prominence/height thresholds choose observation
energies, not the transition manifold. A 50/50 initial-state mixture is an
explicit physical choice; retain the computed state energies by default.
Numerical maps and rendered figures are separate stages: after map completion,
use **Render shared-scale figure** and **Stored figures** to inspect/export images.

For Kondo, use the displayed interval and positive charging costs at the chosen
mu. In the app's `epsilon = E + (N-N0) mu` convention, a vacuum-aligned clean-Au
Fermi level near -5.3 eV corresponds to a simple `mu ~ +5.3 eV` reservoir estimate.
Adsorption/screening can change that estimate; the model paper uses different
effective mu values for different molecules. Do not copy a raw DFT Fermi energy,
fit an unreviewed alignment, or infer a temperature from an exchange eigenvalue.
Compare only explicitly chosen values within the supplied-root charging interval.

## Official ORCA references and the app boundary

- [Wavefunction types, UNOs and QROs](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/hftype.html).
- [Active spaces, CI roots and CASSCF controls](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html).
- [Orbital and density cube plots](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/plots.html).
- [ORCA troubleshooting](https://www.faccts.de/docs/orca/6.1/manual/contents/quickstartguide/troubleshooting.html).

Consult the manual matching the actual executable. Native ORCA CASSCF/UNO
capabilities do not establish a corresponding GUI control. The Dyson spectral
and Kondo conventions are app-level post-processing; their model reference is
[Calvo-Fernandez et al., PRB 110, 165113](https://doi.org/10.1103/PhysRevB.110.165113).

## Final map review

Use full-resolution cubes for numerical maps and cubehandler-reduced cubes for
interactive previews. Preserve isolated-molecule boundaries. The current
default source plane is 1.5 Å above the highest atom along +z; record the actual
plane and observation height, including any viewer override. Use a shared
explicit brightness scale for compared images and μ points.

Save maps and PNG/PDF figures through CalcJobs with all settings as inputs.
Verify Search → the molecular reference → Analysis / results → Kondo orbitals &
maps, select the intended μ result, and inspect the stored images. A service
test or generated report alone is not browser-rendering evidence.

Each image is an individual unit-normalized eigenchannel intensity map.
Exchange eigenvalues are not brightness weights. These results do not establish
a combined experimental Kondo map, Kondo temperature, linewidth, Fano profile
or PP-STM CO-tip simulation. Document qualitative agreement and discrepancies
without selecting a new model solely to match the picture.
## Editable spin and memory units

The geometry/SCF multiplicity is always editable; there is no lowest-multiplicity
checkbox. A fresh default uses the lowest allowed value, while a user's manual or
copied choice is retained and validated against electron count and charge. The
allowed-values hint is bounded by the electron count and does not predict the
physical ground-state spin. Geometry/SCF and CASCI memory inputs display GiB;
the existing `memory_mb` settings and backend still use integer MiB (2 GiB =
2048 MiB). Assistant snapshots and copied settings preserve that meaning.

## Exporting results to openBIS

The optional **Export to openBIS** workspace passes the geometry/SCF entry UUID
to the shared exporter; see [the export guide](../../../docs/openbis-export.md).
Its experiment/molecule selectors and combined review cover all connected,
completed results at that exact stored geometry, including independent analysis
workflows. Do not add an app-specific calculation picker or bypass the common
review. Refresh results if new analyses finish; a changed result set invalidates
the old review. Only the shared form's explicit Export action publishes data.

Dyson/Kondo orbitals and maps use `SPM_SIMULATION`. Whole CASCI state tables,
Dyson transitions and Kondo exchange matrices retain their structure in AiiDA
archives, with labelled unclassified result records pending a dedicated schema.
Do not call UNO occupations an energy DOS or hide multi-root data behind one
energy value. The export boundary is data already stored in AiiDA: remote/stash
references do not include external file contents. Do not retrieve or regenerate
files to make an export appear complete. Future schema changes must update the
normative openBIS document and its code/models before any reviewed deployment.


For Dyson execution, review the main and **State-export resources · serial**
budgets separately. Exports form a daemon-owned serial queue before Dyson
processing. Cube, map and figure helpers have separate resource controls and
reviews, initially 2 GiB / 10 minutes. Use one process for the localhost GUI test.
A budget edit invalidates review; a still-active analysis stage blocks another
submission for the same orbital reference, including after reopening the page.
The CI/norm-loss tolerance is scientific validation, not an execution budget:
never relax it to make a resource or export failure pass. Follow L08 in the full
GUI guide and stop before L09 unless separately authorized.
