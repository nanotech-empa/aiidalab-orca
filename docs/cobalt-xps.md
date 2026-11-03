# Co 2p multiplet draft

At a completed neutral-doublet CoPc geometry, open **Results → XPS →
Co 2p · multiplets**. The orbital preparation and the spectrum are separate
submissions. Review each stage before submitting it. The automatic active-space
selection currently requires planar C32H16CoN8 oriented close to the xy plane;
unsupported or ambiguous orbital character stops preparation.

The app's **Automatic checks and supported scope** explains which validation
runs without user configuration. This is a CoPc-specific protocol; changing the
metal to Fe or Zn does not establish a supported active space or spin model.
Passing numerical checks does not establish the physical ground state.
When the selected doublet is above another computed neutral spin sector, the
reference notice shows the energy difference before spectrum submission. It
remains an explicit reference choice; numerical compatibility does not resolve
the spin ordering.

**Integration protocol: Consistent grid (recommended)** is applied automatically
when preparing new Co valence orbitals. There is no grid setting to remember
for the later spectrum. Numerical details are available under **Numerical
settings**. Protocol v2 pins all three COSX angular grids to 3, with their
default radial accuracy, and verifies the actual generated grids in native
output. The neutral reference, natural-orbital step and spectrum carry the
protocol and generated grid definitions in provenance. The 1e−7 Hartree energy
guard remains unchanged.

Older references remain visible, marked **update required**. Spectrum review
and submission are blocked for these references, including direct workflow
submission outside the GUI. Select the older reference and click **Review
reference update**, then **Reconverge reference with consistent grid**. This
submits a new neutral SA-CASSCF reference from the saved optimized valence
orbitals. The geometry, electron count, spin sectors, basis and active-space
selection are retained. Geometry optimization, DFT and AVAS are not repeated.
The original calculation and reference energy are preserved. Recovery does not
submit a spectrum; after it succeeds the updated reference is selected and
**Review Co 2p calculation** becomes available.

Recovery checks the repository, stash and remote folder for the required GBW.
If the saved orbitals are unavailable, the review explains that orbital
preparation must be rebuilt. The generic **Recompute this stage** checkbox is
not needed to update an old protocol; it controls reuse of already compatible
results. Compatible results are reused by provenance and actual file availability,
independently of AiiDA caching. Detailed native validation failures are shown
in the app, including the measured energy difference when that guard fails.

The implemented protocol follows the preprint and supporting information of Carniato et al.,
[Ionization-Induced Double Charge Transfer in Metallophthalocyanines Revealed
by Ab Initio Simulation of 2p Photoelectron Spectra](https://doi.org/10.26434/chemrxiv-2026-t0g71),
subsequently published in
[J. Phys. Chem. Lett. 17, 4804–4810 (2026)](https://doi.org/10.1021/acs.jpclett.6c00486).
A check on 2026-11-03 found unchanged printed ORCA input examples in the
[published supporting information](https://doi.org/10.1021/acs.jpclett.6c00486.s001)
and the same stated Co active space and frozen-spectrum root counts. The journal
main text has not been compared in full. Publication does not validate this
implementation or its molecular spectra. Occupation references are generated
independently; the paper and SI are not redistributed here.

## Model and limits

1. Native Co 3d AVAS inspection, with explicit Löwdin orbital-character checks.
   AVAS may select an additional bonding MO. The draft verifies five
   predominantly Co-d orbitals and the highest inactive ligand π MO before
   reordering them into the six-orbital active space. Ambiguous selection fails.
2. SA-CASSCF(9 electrons, 6 orbitals): five Co d orbitals plus ligand π.
   All 70 doublets and 20 quartets are included (the paper requests 100 per
   multiplicity; these complete spaces contain fewer states). Orbitals are
   optimized, while the molecular geometry stays fixed.
3. Canonicalize the selected neutral doublet into state-specific natural
   orbitals in a separate CAS-CI step. Its total energy must match the
   state-averaged-orbital reference within 1e−7 Hartree. This is an active-space
   change of representation, not another orbital optimization. ORCA 6.1.1 forces
   the final representation to `unchanged` for `maxiter 1`, including `NoIter`.
   This step instead skips preliminary SCF (`MaxIter 0`), permits two CAS-CI
   passes, and uses `GTol 1e6` to stop before any orbital update and allow final
   natural-orbital rotation. Explicit controls follow `TightSCF` in the input,
   which would otherwise reset the gradient threshold. The parser requires
   exactly these two passes,
   active-only natural finalization, unchanged internal/external representations
   and no orbital-update step. The loose threshold is a control for this
   representation-only job; its convergence banner is not evidence of optimized
   orbitals. The original SA-CASSCF remains the optimized orbital reference.
4. A separate `empa_orca.cobalt_core` CalcJob verifies Co 1s and three Co 2p
   identities from the successful CASSCF's native Löwdin orbital-composition
   table. It checks atom identity, deep-core character, full occupations and
   at least 95% Co s/p populations. The same producing node, geometry and
   native output are required; the parser independently repeats the check
   and verifies the source-output fingerprint. No GBW is read or modified by
   this inspection. It avoids ORCA 6.1.1's GUESS crash when reading the
   CASSCF GBW into a UKS inspection. The following native spectrum calculation
   reads the original, unchanged natural-orbital GBW and rotates the verified
   Co 1s and three Co 2p orbitals into the active space.
   Frozen-orbital RAS-CI(16,10) includes one 1s-hole spectator configuration,
   all 2p-hole configurations with nine valence electrons, and all
   valence-ionized configurations with eight valence electrons. The resulting
   spin-adapted dimensions are **376 triplets and 316 singlets**. These equal
   the paper's requested root counts; this alone does not establish identical
   CI spaces (see the reference-space audit below).
5. Native SOMF spin–orbit coupling mixes these states. Co 2p multiplets arise
   from the computed many-electron Hamiltonian, not an empirical split doublet.

Basis: cc-pwCVTZ on Co, cc-pVTZ on H/C/N, cc-pVTZ/C correlation fitting,
SARC/J, RIJCOSX, finite Gaussian nuclei and no frozen core. Initial local
resources: eight processes and 12 GiB memory budget. The existing PBE/def2-TZVP
optimized geometry is retained; the paper instead optimized at B3LYP/cc-pVTZ.
No hybrid geometry calculation is introduced here.

The 1s-hole spectator uses the dominant neutral configuration in the
state-specific natural-orbital basis and requires its
weight to be at least 0.8. A more strongly mixed ground state requires a more
general spectator preparation, rather than silently using one configuration.

### Reference-space audit: roots versus configurations

The published SI's explicit Fe example contains 90 distinct 1s-hole occupation
configurations. Its unpruned quartet/doublet spaces have 564/1050 CSFs, while it
requests 445/841 roots. The current Co input instead contains one 1s-hole
configuration and has 376/316 CSFs as well as 376/316 roots. Applying the Fe
reference-list construction to Co would give 50 1s-hole configurations and
465/385 CSFs, retaining the requested 376/316 roots. The SI does not print an
explicit Co input, so this analogue remains to be tested natively. Matching
root counts is not a reference-space validation. A frozen control must check
the actual dimensions, selected 1s-state character and energies before changing
the model or interpreting its intensity differences. This audit changes no
existing inputs or results; the orbital-relaxation benchmark is independent.

The four spin-coupled 1s spectator components are equally populated for an
unpolarized doublet reference and core removal. Spin coupling is already
included in the native SOC transition moments; no extra multiplicity factor
is applied. This spin average is explicit rather than selecting only one
intermediate spin component.

Relative intensities use the paper's **bound 1s←2p transition approximation**
to XPS. No continuum photoelectron or absolute photoionization cross section is
computed. This approximation and its fixed-valence-orbital limitations must be
considered before interpreting satellite weights or comparing with experiment.
The 1s ΔSCF spin-projection formula is not applied to Co 2p.

## Provenance, reuse and storage

- `empa_orca.cobalt_valence`: composes common orbitals, AVAS and SA-CASSCF.
- `empa_orca.cobalt_states`: native ORCA CalcJob for each independent stage.
- `empa_orca.cobalt_core`: submitted native-output core assignment; no SCF or
  localization and no wavefunction copy.
- `empa_orca.cobalt_xps`: neutral natural-orbital preparation, core inspection,
  RAS-CI/SOC and preservation.

Each stage uses AiiDA provenance and actual GBW availability, including stored
repository bundles and stash locations. Compatible intermediate calculations
can be reused after a failed later stage. Required artifacts are checked before
reuse; artifact-producing calculations disable cache reads. Preservation follows
the electronic reference's size threshold and stash policy. Only native text
and parsed results are retrieved by the scientific CalcJob itself.

The plot retains unshifted energies, native relative weights and node UUIDs.
Display alignment is a separate saved energy shift. Gaussian/Lorentzian widths
are adjustable; CSV and view JSON retain the scientific and display values.
The viewer explicitly marks this as a frozen-orbital model with unvalidated
absolute binding energies. Passing numerical checks does not supply the missing
ionized-state orbital relaxation, and a display shift is not a computed
correction to the binding energies.

Previously validated scalar DFT diagnostics at the same geometry appear under
**Scalar Co 2p energy checks**. This expandable section retains the diagnostic's
own basis, Hamiltonian, neutral reference and spin projection. It shows frozen
and relaxed energies, the saved-wavefunction check and the completed QE scalar
value, with a provenance download. These single-determinant energy checks do
not establish SOC multiplets or supply an energy correction to the RAS-CI plot.
The reader checks the linked convergence/readback evidence before showing an
energy; an invalid record shows its diagnostic instead.

The separate **Multireference Co 2p energy checks** section reads a completed,
accepted energy-only CoPc RASSCF benchmark. It remains hidden when no accepted
record exists. Its reader checks the linked optimization/readback jobs, captured
validators, all 480 native state energies, final gradient, saved-checkpoint
identity, core/valence evidence and neutral energy reference. Invalid evidence
shows a diagnostic and clears previously displayed energies. The table compares
the lowest frozen and relaxed spin-free energies in each spin sector; the two
minima can have different configuration character. The state-average lowering
and complete provenance are downloadable. This display does not submit a
calculation, add SOC, or assign photoionization intensities. The relaxed
multireference benchmark remains unvalidated at the time of this implementation.

## Validation status

The original protocol v1 ORCA 6.1.1 ARM64 run completed CoPc SA-CASSCF on eight
processes in about 37 minutes, at the existing PBE geometry. The gradient
converged to 1.08e−4; the doublet root-0 energy is −3038.6762444642 Hartree.
The 20.4 MiB GBW was preserved in the AiiDA repository and its checksum checked.
Workflow: `d9b39f48-03fa-493f-850d-89e21583ef99`.

In this finite active-space, state-averaged model, the lowest quartet lies
0.489 eV below the selected doublet. The doublet therefore remains an explicit
reference choice, not an established multireference ground state. This ordering
needs investigation before interpreting a spectrum or comparing with experiment.

The generated 376/316 spin-free dimensions and the native SOC/emission parser
have regression tests, including a reduced atomic format calculation. That
reduced calculation is not a molecular spectrum validation.

On 2026-10-20 the representation-only CoPc calculation
`b0543a93-2153-4361-8dda-c3aa21044291` terminated normally, without any orbital
update. Its CAS energy before/after natural finalization agreed to about
3e−12 Hartree. However, its neutral energy, −3038.6767387580 Hartree, differs
from the preceding optimized SA-CASSCF result by −0.0004942938 Hartree
(−0.0134504 eV). The unchanged 1e−7 Hartree reference guard rejects this result,
and the Co 2p spectrum is not launched. Its GBW is preserved for diagnosis;
this does not make it an accepted spectrum reference.

An independent frozen CAS-CI restart with the original 70/20 state average,
`484abd89-4fc9-4595-ae52-ff9d61e73ed3`, reproduces the new neutral energy.
Native ORCA terminated normally; the generic upstream ORCA parser used for this
diagnostic is not CAS-aware and returned 311. Native text, rather than that
generic parser's status, supplies the comparison; this is not an accepted app
reference.
Across all 90 states, restart energies differ from the saved SA-CASSCF values
by −0.01330 to −0.01386 eV. Wavefunction checksums, geometry and exported
occupied/active subspaces were verified; no significant change on file read
was found. The natural-orbital rotation itself passes its invariance check,
but the complete molecular RAS-CI/SOC spectrum remains unvalidated.

### Restart discrepancy: controlled COSX grid comparison

Further native CalcJob diagnostics on 2026-10-20 locate the discrepancy in the
COSX quadrature used by the two execution paths. Geometry, original GBW,
orbital basis, fitting bases, finite-nucleus treatment, integral thresholds,
active space and all 70 doublets/20 quartets were held fixed. No diagnostic
performed an orbital-optimization step.

ORCA printed identical default grid definitions for the original optimization
and the default frozen restart. Explicitly making all three grids identical
removes ambiguity about which grid is used. The current documented control is
`AngularGridX`; `IntAccX -1,-1,-1` retains the default radial accuracy for each
selected angular grid. The generated grids, including their point counts,
were checked in the native output.

| Calculation / evaluation | Generated COSX grids | Neutral doublet root 0 (Hartree) |
| --- | --- | --- |
| Original SA-CASSCF result | Default definitions: 41,976 / 86,516 / 183,635 points | −3038.6762444642 |
| All grids set to angular grid 2 | 86,516 points each; IntAcc 4.020 | −3038.6762444642 |
| Default frozen restart | Same default definitions as the original run | −3038.6767387580 |
| All grids set to angular grid 3 | 183,635 points each; IntAcc 4.338 | −3038.6767387580 |

The medium-grid restart (`111aa667-2707-453d-8116-c4605bc0b7f5`) reproduces
all 90 original state energies within about 1e−10 Hartree at the printed precision.
The largest-grid control (`658608c9-114a-4139-9bea-24eaec2cef15`) reproduces
all 90 default-restart energies exactly at the printed precision.
Thus the original result behaves as a medium-grid evaluation, while the
frozen restart and natural-finalization job behave as largest-grid evaluations.
The source-code mechanism is not established; this is a controlled numerical
diagnosis, not a claim that the GBW changed or that state selection changed
the Hamiltonian. A legacy `GridX`/explicit-radial control
(`044d7258-4514-4e98-9f3b-39efb7f7d199`) generated different radial grids and
is not used as the decisive comparison.

The [ORCA manual](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/RI.html#cosx-numerical-grids)
describes three COSX grids and their use at different stages. These controls
are numerical integration settings, separate from the orbital basis and
physical active-space model.

These diagnostics did not accept a replacement reference or change an energy
tolerance. The subsequently user-approved protocol v2 now uses the same explicit
largest grid throughout the Co calculations. The protocol identity prevents
reuse of incompatible v1 results. A separate reference-update workflow can
reconverge from saved optimized valence orbitals, with direct input links to the
original producing calculation's reference and files. Original results remain
preserved. Live reconvergence and subsequent natural-orbital validation are
recorded below; the full molecular spectrum is still unvalidated.


### Live validation of protocol v2 and app recovery

The browser selected the old reference, confirmed the pre-submission block,
reviewed the update and submitted workflow
`13f2c6c4-ad1e-4a88-b32c-ed7921687942`. Its only children were native
SA-CASSCF CalcJob `35f2d164-26b6-42d9-a7df-c429bc7c8728` and electronic-file
preservation. It converged in four optimization macro-iterations plus the
final printing pass, in 15 minutes 48 seconds on eight processes. The final
orbital gradient is 1.31e−4, below the unchanged 2.5e−4 criterion. The new
neutral doublet root-0 energy is −3038.6768378690 Hartree. Geometry node
`0314a4b4-d54c-44f9-845e-0c56cb6ba381` is unchanged. The original protocol v1
reference remains intact.

Native natural-orbital validation
`d5f2b6de-4f0e-43b0-aca2-c5137b761de0` then passed both unchanged energy checks:
its neutral energy agrees with the reconverged reference at printed precision,
and the final native CAS macro reports an energy change of −4.55e−12 Hartree.
No orbital-update step occurred during this representation-only calculation.
All three generated grids have 183,635 points in both calculations. The new
natural-orbital GBW was preserved by
`f0845138-3c35-4137-8438-cb6d8e55bb47`, ready for later provenance-based reuse.
This validation was a native CalcJob; the full spectrum was not submitted.

A repeat recovery request, workflow
`90e0b710-366d-4b63-a939-5c6017ca3d92`, reused the compatible result with zero
child CalcJobs, without AiiDA caching. Browser tests also checked the updated
reference's ready state, spectrum review, blocking when selecting an old
reference and invalidation of an earlier review after switching references.
The app-discovery audit passed. Focused XPS/protocol/UI regression tests:
32 passed. Labelled native excerpts cover both the original mismatch and the
successful fixed-grid restart; no executable or wavefunction is distributed.

The model's lowest quartet still lies 0.489 eV below the selected doublet.
The integration fix does not resolve that separate model/spin-ordering issue
or validate a molecular Co 2p spectrum against experiment.

### Native core assignment on tigu

On 2026-10-20, `empa_orca.cobalt_core` CalcJob
`5836cad3-f07f-45a5-bf8a-035743791db9` completed and passed parser validation
on tigu. It reads the native population table from successful natural-orbital
producer `c64ca4a7-a549-465f-b53b-fdaa6956aa49`: Co 1s is MO 0 and Co 2p
is MOs 2–4, each with 100% Co s/p character at printed precision and occupation
2. The report links the original producer and fingerprints its native output.
Only text was staged for this one-process check; the wavefunction was not
converted, copied or localized. This validates the core-assignment stage,
not the full molecular RAS-CI/SOC spectrum.

### Frozen-spectrum audit and relaxation diagnostics (2026-11-03)

The isolated-molecule scalar checks now have independently validated saved
wavefunctions at both fixed optimized geometries. They use PBE/UKS,
spin-free X2C, x2c-TZVPall and RI-J/x2c/J. Each ion is an MS=1 determinant
created by removing one beta electron from the selected Co 2p orbital.

| Geometry | Frozen ORCA (eV) | Relaxed ORCA (eV) | Relaxation lowering (eV) | QE scalar (eV) | Final S² |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoPc, C32H16CoN8 | 817.94451 | 789.42810 | 28.51641 | 788.19639 | 2.465892 |
| Co-dcHp, C28H16CoN6 | 817.55222 | 788.85869 | 28.69353 | 788.35200 | 2.067209 |

These are conditional single-determinant energy benchmarks, not pure triplets,
2p centroids or SOC-resolved 2p₃/₂ lines. The table retains each method's own
Hamiltonian and energy reference; it supplies no correction to the different
cc-pwCVTZ/cc-pVTZ multireference spectrum. QE includes its stored
pseudopotential correction. No experimental alignment is applied.

The accepted comparison records are
`9aa6dabc-7e31-4644-9de1-e71887162788` and
`9e8ea1f5-4136-4966-9242-21cbd102809b`. Native final gradients are 9.01e−7
and 7.65e−7 respectively. Independent readback changes the ion energies by
at most 2.01e−10 Hartree, below the unchanged 1e−7 guard. Both datasets are
available through **Scalar Co 2p energy checks**. The completed CoPc selected
four-carbon dataset and Co-dcHp one-carbon pilot have also passed actual
browser checks of the raw spin branches, QE overlay, readback notices and
provenance downloads. The full 28-carbon Co-dcHp campaign remains in progress.

The earlier frozen CoPc RAS-CI/SOC output contains low-energy core-hole
states that do not carry the reported bright spectrum's weight:

| Native feature | State index | Binding energy (eV) |
| --- | ---: | ---: |
| Lowest SOC state in the Co 2p energy window | 420 | 791.29202 |
| Lowest reported nonzero spectral stick | 870 | 823.78938 |
| Largest discrete spectral stick | 1280 | 838.62634 |

The largest discrete stick need not be the maximum of a broadened curve.
An audit of all 1,444 SOC states and 5,760 printed transitions verifies the
native-to-stored energy conversion. An independent frozen readback of the
written neutral natural-orbital GBW reproduces all 90 neutral energies within
1.01e−10 Hartree. It confirms the selected doublet configuration `222210`
and its weight 0.96530. Thus this check does not support either an energy
conversion error or a wrong neutral-configuration assignment as the cause
of the high bright peaks.

For the low state, the printed SOC weights of triplet roots 105/106 sum to
0.996074. Those spin-free parents have almost no occupation of the selected
ligand π orbital: the native printed configuration weights bound its occupation
between 0 and 0.0021 electrons. The first bright state's leading parents retain
approximately two electrons there, as does the selected neutral configuration.
This is consistent with charge-transfer final states and weak coupling in the
single-configuration bound-transition approximation. It does not validate
that approximation's intensities. A weighted average of spin-free occupations
alone is not a SOC occupation expectation; off-diagonal matrix elements would
also be needed. No omitted configuration weights were renormalized.

The immutable native spectrum is
`03ccc873-6789-4ef8-8ecd-84e9f261b3fb`; the configuration/energy audit is
`80139bea-877c-4711-ae63-e4aecd844833`. The neutral readback is
`993e892d-1172-4f2e-bfd4-8086a9c9f386`, with multiplicity-selected diagnostic
`7f7f21a1-d33a-4226-a8bf-4c77912d8c78`. These are instance provenance
identifiers, not a publicly distributed wavefunction dataset.

A separate, approved energy-only CoPc benchmark optimizes an explicit
Co 2p⁵/valence⁹ ORMAS space: 14 electrons in 9 orbitals, 270 triplets and
210 singlets, with equal block weights and the original MR Hamiltonian.
The damped optimization inspected on 2026-11-03 stopped without convergence.
Its stored checkpoint reproduces all 480 states of completed macro 41 within 5.01e−10
Hartree, but its gradient is 0.6967 against the required 2.5e−4. This qualifies
only diagnostic reuse, not a relaxed energy or spectrum. Orbital-relaxation
and intensity-model investigations remain separate. Independently optimized
orbital sets cannot be passed to the existing common-orbital Dyson kernel.

No relaxed multireference Co spectrum or Co-dcHp multiplet protocol is yet
validated. The supported scalar/1s diagnostics do not establish a transferable
Co/Fe/Zn active space. A new physical restriction, spin manifold or intensity
treatment requires scientific review; failed convergence is not permission to
weaken the original checks.
