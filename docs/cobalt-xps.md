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
was found. The cause of this native restart discrepancy remains under
investigation. The natural-orbital rotation itself passes its invariance check,
but the complete molecular RAS-CI/SOC spectrum remains unvalidated.
