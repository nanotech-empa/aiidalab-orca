# XPS operating guide for agents

## Contract for agents in the AiiDAlab chat

Consult this installed app-owned guide before preparing, recovering or
interpreting XPS. Reopen it with `read_workflow_guide` and ID `orca.xps` after
switching topics or when the current procedure is uncertain. Inspect the live
reference, outputs and visible app errors as well. This guide is not permission
to submit, invent capabilities, override user choices or bypass action review.
The current ORCA chat form adapter does not expose the XPS submission controls;
use the app's XPS panel rather than claiming a chat-form action submitted XPS.
If this guide cannot be loaded, report that limitation and do not improvise a
specialized recovery protocol.

Read [the user guide](../../../docs/xps.md) and, for metal 2p multiplets,
[the method-specific guide](../../../docs/cobalt-xps.md) before acting. Inspect the current
installed revision, canonical component branches and active calculations first.
This guide applies to agents assisting inside AiiDAlab as well as repository
development. It does not authorize additional calculations or physical changes.

## Required evidence

Record the reference UUID, optimized/fixed geometry, charge, spin projection,
functional, basis, relativistic Hamiltonian, numerical settings, code UUID and
actual ORCA version. Identify the original SCF producer. Do not substitute a
new reference with similar energy without checking its electronic state.
Every scientific native operation runs inside a submitted CalcJob, including
core preparation, localization, precision refinement and readback. Use the
configured ORCA executable and automatically resolved tools code on the same
computer. Preserve the requested allocation and electronic-file policy.

Updating the container backend does not update an older remote ORCA-tools
installation. Its allowlist must include `xps_finalize.py`. Qualify the actual
configured launcher as well as the staged script before a production campaign;
a launcher "Usage" error is a software deployment failure, not SCF instability.
Keep the historical code/executable intact when replacing that launcher.

For diagnostic ShellJobs, map every `SinglefileData` to an explicit, unique
staging filename, including evidence files. An original input still named
`aiida.inp` can overwrite the intended execution input even when its node key
is different. Check the complete destination map and the actual staged input
hash. A zero launcher/ShellJob exit status does not establish native ORCA
success; require the native normal-termination and stage-specific checks.

For every accepted doublet-reference 1s branch require:

- Native normal termination and actual final gradient convergence, including
  release of the constrained orbitals when freeze-and-release was requested.
- Matching geometry/basis and no CMatrix projection of individual orbitals.
- No poorly normalized MO warning at any stage.
- Correct alpha/beta electron counts, one deep-core hole, its requested spin
  channel, and at least 95% native target-atom population. Verify the shell;
  a Co 2p vacancy is not a Co 1s vacancy.
- A saved-GBW `NoIter CalcGuessEnergy` calculation, with energy invariant to
  1e−7 Hartree, S² invariant to 1e−5, and the same physical checks.

The automatic three-stage contract lives in `scripts/xps_validation.py`,
`scripts/xps_finalize.py` and `XpsSiteCalculation`. A completed process or a
printed energy alone is insufficient. Distinguish native success, parser
success, physical acceptance, storage completion and host-app result loading.
Test the host submission/service path and result model before claiming the
app works end to end. Standalone pilots qualify only the stage they execute.

## Bounded recovery

Inspect the latest iterations, total energy, orbital gradient and density
changes before choosing a numerical recovery. If still improving near the
iteration cap, more iterations can be justified. A plateau, oscillation,
normalization problem, wrong hole or wrong state needs a diagnosis. Do not
blindly restart the same calculation or propagate its damaged checkpoint.

For a process paused after repeated transport failures, first verify that the
configured connection works again and inspect the same process and scheduler
job. `verdi process play <UUID>` resumes that paused process; it does not
repair a native scientific failure. Do not duplicate its submission or revive
an intentionally killed process. When CSCS authentication expires, ask the user
to renew it before retrying the configured route.

ORCA 6.1.1 `IonizeAlpha/Beta` plus `FreezeAndRelease` can print "No orbitals to
constrain!". A named solver is not evidence it activated. The validated
doublet construction uses an occupied-MO swap plus a compact spin configuration.
For an odd neutral electron count N, the swap frontier is
`(N+1)//2−2` for alpha removal or `(N−1)//2−2` for beta removal; all indices start
at zero. This is an input representation change, not permission to alter the
electronic state. On a new ORCA version, compare direct and compact frozen
densities, energies, occupations and hole identity before trusting it.

The automatic refinement starts from the converged released cation. It must
not reionize it, repeat the neutral configuration swap, or reintroduce
constraints. Fresh Fock builds and a tighter gradient can resolve small
checkpoint-energy drift; weakening the readback threshold cannot validate it.

Select a restart's physical source and execution configuration separately.
A historical frozen control can use the same ORCA executable with different
MPI/scratch settings. Retain the reviewed launcher explicitly and verify its
computer, executable and resource limits; inheriting the source's code can lose
the job-local shared-memory configuration. Check the first native energy
against the qualified source before trusting further optimization.

A time-limited optimization can save a GBW from an earlier completed macro
than the last energy printed in its output. Fingerprint the actual saved GBW
and independently read it in a frozen native CalcJob with the same manifold,
weights, Hamiltonian and numerical grids. Compare every requested state energy
within the existing 1e−7 Hartree guard, and repeat normalization and core/valence
identity checks. Record the macro actually reproduced. Qualification for a
diagnostic or bounded numerical restart does not accept an optimized energy;
native gradient convergence and final readback remain separate requirements.
Finite orbital-rotation probes are diagnostics inside the reviewed model,
not a convergence test or permission to change occupation restrictions.

The current CoPc energy-only benchmark has now failed both its damped-SuperCI
and bounded perturbative-SuperCI attempts. The latter reproduces its qualified
starting energy but stalls near a gradient norm of 0.4, against 2.5e−4. Its
native convergence failure is preserved even though the ShellJob exits zero.
Do not extend that same trajectory automatically or use it as a relaxed
spectrum. Consult the dated method-guide evidence before choosing another
converger. ORCA's documented omission of active-active rotations in incomplete
spaces and its canonicalization dependence need consideration; changing a
solver does not establish a fully variational RASSCF treatment.

Inspect the whole numerical history before proposing another solver. The
earlier CoPc SuperCI→DIIS attempt actually executed 43 DIIS updates and became
unstable; the later damped run never reaching DIIS does not make it untested.
Native H2 controls now establish that TRAH can retain a small explicit ORMAS
space and both spin blocks, using `ActConstraints Unchanged`. They do not
qualify that representation for the Co core hole. Review a changed active-MO
convention, require all-state frozen compatibility, and establish equivalent
full-gradient evidence before accepting a solver with different native
convergence reporting. The reviewed CoPc frozen TRAH control subsequently
terminated normally without an orbital update, but all 480 state energies
failed the unchanged 1e−7 Hartree compatibility guard (largest difference
3.76e−6 Hartree). That failed comparison did not authorize an optimization.

Identical COSX grids do not establish identical integral evaluation. Native
ORCA warns that TRAH-CASSCF automatically enables `COSX_IntSymmetry Full`;
the earlier two-step control did not request that treatment. The manual
documents full integral permutation symmetry as a distinct COSX option. Record
it separately from angular/radial grid parameters. After explicit scientific
review, a frozen two-step control added only that option and passed all physical
checks. Its 480 state energies match the frozen TRAH output within 1.01e−10
Hartree. This isolates the historical mismatch to the COSX treatment without
relaxing the guard. The conditional four-step TRAH diagnostic was submitted
only after that matched-scheme check passed; compatibility does not establish
orbital convergence or accept an XPS energy. Preserve the historical failed
comparison. Any subsequent compatibility/readback must use the same explicit
numerical scheme and retain the all-state 1e−7 guard; a later binding energy
also needs a consistently evaluated neutral reference.

The bounded CoPc TRAH trial subsequently failed native convergence and the
original core-identity checks. Its reported macro error grows from 0.697 to
15.30; two target MOs fall to 89.2% Co-p character against the required 95%,
and the three-deepest-Co-p assignment fails. The exact occupation-group count
remains five electrons, which does not establish that those orbitals still
represent the intended 2p shell. Do not increase the iteration cap or follow
ORCA's generic restart suggestion without diagnosing this state change.
The failed checkpoint is not qualified for reuse and no energy is accepted.

The separate read-only snapshot inspection also measures substantial mixing
with formerly inactive Co-p orbitals. Atomic Co-p purity alone cannot
distinguish radial shell mixing. That overlap diagnostic introduces no new
acceptance threshold and is not assigned to an iteration/energy. Distinguish
energy minimization from finding the intended core-hole stationary point;
core-hole state following needs method validation. The dated method guide
records the native failure and relevant primary literature.

The subsequent small Ne/cc-pCVDZ CAS(1,1) test does not qualify a new NR
recovery. Both reviewed runs start from the same validated 1s-hole source.
The augmented-Hessian solver reaches a small full gradient and normal native
termination but refills the 1s shell, leaving a valence hole; the core check
rejects it. Pure-NR Pople actually activates, then native ORCA 6.1.1 segfaults
after its first inner linear solve. Inner convergence is not orbital
convergence, and successful inspection of a saved GBW cannot accept a crashed
native run. Neither candidate receives a readback or checkpoint qualification.
The original full-gradient, core/spin/norm and 1e−7-Hartree readback gates stay
unchanged. Do not extrapolate this atomic test to a Co recovery or launch a
large NR calculation without a separate reviewed and validated path.

The native ORCA 6.1.1 TRAH output in this control omits the two-step solver's
`CI-PROBLEM SOLVED` and `E(CAS)=` markers.
Their absence alone is not a native convergence failure. A format-aware reader
must instead verify the actual TRAH stage, termination, complete state tables,
state-average consistency and all existing physical checks. Do not insert fake
legacy markers or relax the numerical guard to make a new solver pass. In the
original CoPc control, the independent comparison still fails after separating
this format mismatch from the numerical difference. The separately reviewed
matched-COSX control passes the original energy guard; no fake marker or
post-hoc tolerance change is used.

Select CI states by their native multiplicity and root headers, not by the
position of a printed block. ORCA can print the lower quartet before the
doublet. Check a selected configuration's associated energy against the
corresponding spin-resolved state energy before interpreting its weight.

Keep every failed attempt and its native output. A corrected parser or
post-hoc analysis creates new provenance, rather than rewriting an old node.
When reporting progress, distinguish tested facts, hypotheses and the next
bounded action. If approval or an external change is required, say so explicitly.

## Physical limits and review points

MS=0 UKS is not a pure singlet; MS=1 UKS is not automatically a pure triplet.
Raw accepted determinants may be retained even when two-state Yamaguchi
projection fails its documented S² domain. Never weaken that gate to force
a projected spectrum. Schematic equal-area lines are not photoionization
cross sections or Clebsch–Gordan weighted intensities.

A scalar Co 2p ΔSCF energy is not a SOC-resolved 2p₃/₂ prediction. A relaxed
DFT determinant does not validate the absolute energies or intensities of a
frozen RAS-CI/SOC spectrum. Independently optimized multireference core-hole
orbitals, altered active spaces, empirical/composite shifts, continuum matrix
elements and nonorthogonal Dyson approximations require scientific review.
Do not silently combine these methods or reuse a common-orbital Dyson kernel
for separately optimized orbital sets.

For the bound-transition model, distinguish requested roots from the native
configuration and CSF dimensions in every multiplicity block. Matching the
paper's 376/316 Co root counts does not prove the same CI space was used.
The current draft retains one neutral-derived 1s-hole configuration; this is
not automatically the lowest 1s-ionized eigenstate when charge-transfer
configurations are admitted. The published SI explicitly selects the lowest
1s-ionized state for Fe/Mn and provides an Fe input with a larger 1s-hole space;
it does not print a Co input. Inspect the selected 1s state's native character
as well as its energy, and consult the reference-space audit in the method
guide. An energy-only comparison of a larger space neither validates XPS
intensities nor authorizes replacing the production protocol or submitting SOC.

The documented fixed-geometry CoPc controls now find a π⁰/d⁹ 1s state
35.24–35.25 eV below the restricted π²/d⁷ reference. All 480 Co 2p spin-free
energies remain invariant within the 1e−7 Hartree guard. This is an
instance-specific reference-space sensitivity check, with native provenance in the
method guide. A new spectrum needs transition weights from the qualified
1s state and separate scientific review; the 1s energy change is not an XPS
binding-energy correction.
Review the paper's intermediate-state and energy conventions before treating
the expanded 1s space as a production correction.

During core-hole orbital relaxation, individual valence MOs can mix within a
full valence-CAS block. A fixed-index character failure alone does not prove
that the intended subspace was lost. Diagnose it with native coefficient and
AO-overlap exports, normalization checks and projector eigenvalues; summed
populations alone cannot establish the required directions. Rotations across
occupation-restricted groups can change the model. Preserve the reviewed
criteria, and use an earlier qualified source or seek scientific review when
the invariant diagnostic still fails them. Never retune a cutoff just to pass.

The expandable **Scalar Co 2p energy checks** section shows previously validated
energy-only diagnostics at the selected neutral-doublet geometry. Each record
keeps its own DFT model and reference. Discovery requires a completed validation
output; the reader checks the linked core identity, electron count, convergence,
gradient and saved-wavefunction evidence before showing energies. Consult its
downloaded provenance when using the relaxation lowering. This diagnostic does
not supply a correction to the multireference spectrum.

For QE comparisons match geometry and atom order, record pseudopotential
corrections, scalar/SOC treatment, charge/spin and energy reference. A molecule
on a metallic substrate is not an isolated molecule referenced to vacuum.
Resolve experimental alignment separately; never hide disagreement with an
unreported shift or an adjustable zero chosen to match experiment.
