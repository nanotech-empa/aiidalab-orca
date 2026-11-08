# Optical-excitation operating guide

Before a new submission, review **Full files**: leave complete native logs,
electronic files and NTOs on the calculation computer, or stash them in a chosen
directory there. Only bounded validation text, a diagnostic tail and a checksum
manifest enter AiiDA. NTO previews inherit that retention; no wavefunction
retrieval threshold is offered. Full cubes retain their separate leave/stash/
delete choice. Reused results retain their original storage policy. Historical
data remain readable; do not migrate or rewrite their nodes.

Open **Optical excitations · UV–Vis** from a completed DFT geometry/SCF entry.
This independent route needs no CAS, CASSCF or Hamiltonian export. The chat's
form adapter does not currently submit these controls; describe the actual
visible form rather than inventing an unexposed submission tool.

The input preserves fixed geometry, charge, DFT functional/basis/element
settings and grids. Choose TDA or full TDDFT explicitly, root count, optional
spin-adapted triplets from an RKS singlet, and optional NTO analysis. A continued
SCF reads saved source orbitals and must reproduce the source ground energy
within 1e-7 Hartree. Do not silently regenerate a missing reference, optimize
coordinates, change functional/spin or loosen a failed convergence criterion.
HF/CIS/RPA, double hybrids, composite methods, spin flip and SOC are outside
this first route. ECP electron counting is not qualified here.

TDDFT excited roots start at 1, distinct from zero-based CASCI roots. ORCA MO
indices start at 0 and viewer atom indices at 1. Preserve the global native
state index separately from the family root: triplet state listings and optical
tables use different numbering. UKS response is spin conserving, not a general
spin-pure multiplicity ladder. Report native spin expectations without asserting
that rounded multiplicity labels are exact quantum numbers.

Require SCF convergence, native method/charge/electron identity, complete roots,
electric-dipole length-gauge strengths and native residual convergence in each
family. Native normal termination alone is insufficient. A converged reference
also does not certify SCF stability. The final single-point scalar can be an
excited-state total; the separate SCF energy defines the excitation reference.
Use durable stored result tables rather than reparsing an arbitrary final scalar.

Spectrum/table clicks only select a state. Retain dark states. The table separates
native NTO analysis from ready cube preview pairs. A ready pair requires both
members stored under the same optical calculation; status inspection must not
open a remote transport. Refresh NTO previews to see later jobs. Running,
failed or missing-file states are distinct from a generated preview. Broadening is
a display choice in eV, with no automatic intensity normalization. The wavelength
view retains a per-eV ordinate, not a transformed spectral density per nm.
Native oscillator strengths are not an absolute extinction coefficient.
States CSV preserves the unbroadened state table; Spectrum CSV/SVG describe
the currently displayed curve with its units, broadening, method and source
identifiers. Full JSON retains the native tables. Invalid plot limits remove
plot downloads rather than leaving a stale exported image.

Inspect transition-specific NTO hole/particle pairs and native weights. They
are not KS MO occupations. Full-TDDFT NTO weights can exceed one and must not
be renormalized as probabilities. Printed canonical contributions and NTOs are
different bases; their equal indices do not identify the same orbitals.
Keep the printed-weight threshold and omitted contributions explicit.

NTO previews are separate reviewed CalcJobs using native ORCA files and the
existing cubehandler pipeline. Generate both members of each selected pair.
Reduced previews, full-cube retention and native electronic-file preservation
are distinct policies. Preserve spin in filenames so alpha/beta NTOs cannot
overwrite each other. Use the existing isolated-molecule viewer and saved-view
rendering. Inspect pair plus Hole/Particle controls use the existing single
viewer. Switching members within a stored run/state preserves view settings,
including the actual isovalue. Never rescale the new cube to preserve apparent
brightness; an out-of-range isovalue correctly gives an empty surface. Saved
views/rendering target the currently selected member. Missing/unreachable
sources are not permission to rerun science.
Triplet energies are available; triplet NTO generation is explicitly unqualified
and blocked. Do not relabel singlet NTO files as triplet ones.

The numerical reference is the ORCA 6.1 manual's exact pyridine geometry/input:
PBE/def2-SVP TDA, five roots, NTO states 1–3. The exact-input native
control reproduces its printed excitation energies, oscillator strengths and
leading NTO weights. The app continuation differs by at most 0.000028 eV in
its first three TDA energies; preserve those stored values. Allyl UKS tests
spin-channel/NTO integration only, not a literature accuracy comparison. Full TDDFT
and triplet-format controls establish separate implementation checks, not
equivalent physics or experimental accuracy. See [the user guide](../../../docs/optical.md).
Current optical results provide no CASCI vectors and cannot replace Dyson/Kondo
states. Excited-state optimization, resonance Raman and solvent/core protocols
need separate reviewed implementations.
