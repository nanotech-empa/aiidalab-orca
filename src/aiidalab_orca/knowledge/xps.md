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
