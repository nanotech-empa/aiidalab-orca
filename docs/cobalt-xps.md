# Co 2p multiplet draft

At a completed neutral-doublet CoPc geometry, open **Results → XPS →
Co 2p · multiplets**. The orbital preparation and the spectrum are separate
submissions. Review each stage before submitting it. The automatic active-space
selection currently requires planar C32H16CoN8 oriented close to the xy plane;
unsupported or ambiguous orbital character stops preparation.

The protocol follows Carniato et al.,
[Ionization-Induced Double Charge Transfer in Metallophthalocyanines Revealed
by Ab Initio Simulation of 2p Photoelectron Spectra](https://doi.org/10.26434/chemrxiv-2026-t0g71),
including its supporting information. This is a **2026 preprint, not a
peer-reviewed method validation**. The implementation generates the occupation
references independently; it does not redistribute the paper or SI.

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
4. Rotate verified Co 1s and three Co 2p orbitals into the active space.
   Frozen-orbital RAS-CI(16,10) includes one 1s-hole spectator configuration,
   all 2p-hole configurations with nine valence electrons, and all
   valence-ionized configurations with eight valence electrons. The resulting
   spin-adapted dimensions are **376 triplets and 316 singlets**, matching the SI.
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

## Validation status

Native ORCA 6.1.1 ARM64 completed the CoPc SA-CASSCF preparation on eight
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

No replacement reference has been accepted, no production grid settings or
energy tolerance have been changed, and no Co 2p spectrum has been submitted.
The proposed resolution is to use one explicit COSX grid throughout the Co
protocol, record it in the protocol identity so incompatible results are not
reused, and reconverge the neutral reference from its saved optimized orbitals.
Using the existing largest grid is the preferred next numerical protocol;
its convergence and subsequent natural-orbital invariance still need validation.
The original results remain preserved with their provenance.
