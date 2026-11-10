# Optical excitations: TDA/TDDFT and NTOs

Choose **Optical excitations · UV–Vis** as a calculation goal, or open it from
the Results selector of a converged DFT geometry/SCF entry. This is a separate
fixed-geometry analysis; no CAS preparation is required. Opening it, clicking
a spectrum or inspecting an existing result submits nothing.

## Review and calculate

Use **Compute / extend optical excitations…**. Choose **TDA-DFT** or **Full
TDDFT**, the number of excited roots and whether to compute native NTOs.
For an RKS singlet, optional spin-adapted triplets form an additional family
with the same number of roots. UKS uses spin-conserving response; its spin
expectations and native multiplicity estimates do not establish pure-spin
eigenstates. Spin flip and SOC are not part of this route.

Geometry, charge, functional, basis, element overrides and integration settings
follow the selected DFT reference. The saved SCF orbitals seed a continued SCF;
the ground energy must agree with the source within `1e-7 Hartree`. There is
no hidden geometry optimization, functional change or reference regeneration.
Missing electronic files require reviewing/recomputing the SCF reference first.
HF would instead produce CIS/RPA and is rejected here. Composite/double-hybrid
methods and ECP electron counting are outside this initial validation scope.

The closed advanced section contains resources, response iterations, explicit
recomputation and an optional list of NTO states. Empty means all requested
states. TDDFT state numbers start at **1**, unlike the CASCI root convention.
Atom indices remain one-based and ORCA orbital indices zero-based.

**Review optical calculation** shows the native input and execution computer;
**Submit reviewed calculation** is the only execution action. Edits invalidate
review. Matching running/successful requests can be reused. A result must have
normal native completion, a converged SCF, correct charge/electron identity,
complete state and length-gauge oscillator-strength tables, and passing native
residual checks for every response family. A failure is retained for diagnosis;
the app does not silently loosen tolerances, substitute a method or change spin.
These checks do not replace an independent SCF stability assessment.

## Interpret the results

The linked spectrum, state table and selector show vertical excitation energies,
wavelengths, oscillator strengths, native spin diagnostics and printed dominant
orbital contributions. Dark states remain visible/selectable. Gaussian display
broadening is specified in eV. The wavelength view plots the same energy-broadened
function with an ordinate per eV; it does not claim a density per nm or an
absolute molar extinction coefficient. No automatic intensity normalization is
applied. Downloaded data retain the native numerical tables and provenance.

**NTO analysis** and **Cube preview pairs** are separate state-table columns.
Analysis availability means the native pair/weight table was computed, not that
cube previews exist. Ready pairs are counted only when both members are stored
for this optical calculation. Running, failed and unavailable-file states are
shown separately. **Refresh NTO previews** refreshes these local records without
checking remote full files or starting work.

Download **States CSV** for the unbroadened state table, **Spectrum CSV** for the
currently displayed broadened curve, or **Spectrum SVG** for an editable figure.
CSV/SVG exports retain method, source UUIDs, units and relevant display settings.
The spectrum ordinate remains per eV in either horizontal-axis representation.
The full JSON download retains native response contributions and NTO weights.

ORCA's `FINAL SINGLE POINT ENERGY` can be the selected excited-state total.
The parser records the separately printed ground-state SCF energy and the
labelled excitations instead of treating that final scalar as the ground state.
Native printed state indices and family root indices are preserved separately,
including the different triplet numbering in the state and spectrum tables.
Native state listings may number triplets within their family (1–N) or after
the singlets (N+1–2N). The parser requires a complete, consistent numbering
scheme, preserves the native index, and records family roots separately.
This does not change stored historical results or qualify triplet NTOs.

Normal termination and native energy convergence alone do not satisfy the
app's residual-convergence check. Each requested response family must print
residual convergence and a residual at or below its native tolerance.
A synthetic regression fixture models normal termination with a triplet
energy-only stop, without a final residual-convergence certificate. It remains
rejected. Parsing its state rows in a unit test does not establish convergence.

For an explicitly reviewed retry, ORCA documents `ETol` as the excited-state
energy-change tolerance in Hartree and `RTol` as the residual-norm tolerance
([ORCA 6.1 response controls](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/tddft.html#general-features)).
Under **Resources and advanced settings**, select **Set response tolerances
explicitly** to edit ETol and RTol. The numerical control for the reviewed
energy-stop retry is `ETol 1e-12`, with `RTol 2.5e-7` unchanged. Tightening the energy criterion reduces early
energy-only stopping; it does not certify residual convergence. Acceptance
still requires the printed residual certificate for every family. Geometry,
functional, basis and spin treatment stay fixed. Keep the reviewed 100-iteration,
2-process, 2-GiB, 600-second limits. A retry is a separate calculation requiring
explicit review, not an automatic remedy or a reinterpretation of the old node.
The checkbox is off by default: existing inputs, settings and reuse identities
retain native defaults. Selecting it changes the reviewed request explicitly.
Changing either tolerance or the checkbox invalidates review; restoring a value
still requires a new review. Both values appear in review, native input and
stored settings. The parser checks that each family used the requested native
tolerances; a printed rounding difference never weakens the requested residual
limit. Oversized-output extracts retain both tolerance lines and stopping criteria.

NTOs are a separate orbital basis for one transition. Each listed pair contains
a hole and particle orbital; it is not a pair of unchanged KS orbitals. Native
weights are response-pseudodensity eigenvalues and are not renormalized. Full
TDDFT weights can exceed one. Only pairs above the recorded printing threshold
are listed. Dominant canonical-orbital contributions are truncated response
information and are not interchangeable with these NTO weights.

Select a state with NTO analysis, choose pair numbers and **Review NTO previews**.
**Preview resources · serial** exposes memory and wall time, initially one
process, 2 GiB and ten minutes. Review shows this budget. Changing either value
invalidates review; restoring the old value still requires a new review.
Any required native-NTO preservation finishes before cube generation and uses
the same budget per job. Hole/particle plotting and cubehandler reduction run
sequentially within the preview CalcJob. Failure stops the successor stage.
Only one preview request can run per optical result, including different states
or browser sessions. Submission consumes its review before contacting AiiDA;
after an uncertain response, inspect status and review again rather than retrying
the old submission. Reused previews keep their original recorded resources.
Both members of every pair are generated together by submitted CalcJobs using
native ORCA orbitals and the existing cubehandler reduction. The shared viewer
provides isosurfaces, slicing, saved views and separate rendering. Choose an
**Inspect pair** entry, then switch **Hole / Particle** in that same viewer.
Within one saved preview calculation/state, switching preserves the camera,
isovalues, lighting and slicing settings. Cube amplitudes are not rescaled. An
isovalue above the new field's range correctly shows no surface; lower it
explicitly when needed. Blue/gold surfaces mark amplitude signs, not hole and
particle identities. Saved views and rendering still refer to the selected
member. Full-cube
retention is explicit: leave, stash or delete after preview validation.
Native NTO electronic files inherit the optical calculation's remote/stash
choice; no retrieval threshold is offered. Only reduced cube previews are
retrieved. Missing/unreachable files are reported rather
than silently recomputed. Triplet energies are supported, but **triplet NTO
generation is not qualified in this draft**; unavailable NTOs cannot be selected
as though they belonged to a singlet transition.

These results describe optical response at the reference electron count.
They provide no compatible CASCI charge-sector vectors for current Dyson/Kondo
calculations. Excited-state optimization, vibronic spectra, resonance Raman,
solvent-response protocols and core-excitation methods require separate routes.

## Numerical reference

The first benchmark uses the exact fixed pyridine geometry and PBE/def2-SVP
input from the [ORCA 6.1 NTO example](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/tddft.html#natural-transition-orbitals).
The native ORCA 6.1.1 TDA control reproduces these printed reference values:

| State | Excitation (eV) | Oscillator strength | Leading NTO weights |
| --- | --- | --- | --- |
| S1 | 4.294795 | 0 | 0.99945993 |
| S2 | 4.325874 | 0.003830922 | 0.99857289 |
| S3 | 5.442702 | 0.019114326 | 0.63243468, 0.36314467 |

Oscillator strengths agree within `1e-8`, and these NTO weights agree to their
printed precision. Full-TDDFT and mixed singlet/triplet controls test separate
method identities, native convergence and state mapping; their different
energies are not compared to TDA as though they were the same approximation.
This is a manual reproduction and implementation check, not validation of a
universal functional/basis choice or experimental accuracy.


The normal app submission continues the already-converged SCF from its saved
orbitals. Its first three TDA energies are 4.294767, 4.325848 and 5.442703 eV:
the largest difference from the manual is **0.000028 eV**. The continued SCF
ground energy differs from its source by `8.1e-10 Hartree`. These tiny numerical
restart differences are reported rather than rounding the stored results to
the manual. The exact-input native control is the reference reproduction.

The app-level open-shell integration check uses its existing PBE/def2-SVP allyl
radical doublet geometry. It retains UKS spin expectations and distinct alpha/
beta NTO pairs. This is a parser/workflow check, not a claim of quantitative
agreement with a different literature geometry or method. The NTO pipeline
also checks complete native hole/particle pairs, full-cube normalization and
reduced-preview provenance; preview grids are for inspection, not quantitative
integration.

## Full native files and previews

Review **Full files** before a new optical submission: leave complete logs,
GBW/density and NTO files on the calculation computer, or stash the bundle in
an explicitly chosen directory there. Only a validation summary (at most 2 MiB),
a 64 KiB diagnostic tail and a checksum manifest are retrieved. The existing
response convergence, continued-reference energy and state/NTO identity checks
still run against retained native validation text. An exceeded budget fails
collection; it never silently accepts a truncated spectrum.

NTO hole/particle previews inherit this choice. Stashed native files remain
usable for new previews; full cubes retain their separate leave/stash/delete
choice and pass through cubehandler before reduced previews are retrieved.
Historical results remain readable without migration.

## Export and runtime acceptance

Whole-entry openBIS export uses the shared exporter: complete optical state/NTO
analysis maps to existing `UNCLASSIFIED_SIMULATION` records with method family
DFT; stored NTO cubes map to `SPM_SIMULATION`. The companion adapter follows the
pending shared ORCA exporter series and its review hold. It introduces no new
schema and performs no extra remote retrieval or calculation. Local tests are
not a live-server publication/import acceptance.

The declared/CI target remains Python ≥3.12, AiiDA ≥2.9.2 and AiiDAlab ≥26.9.
The development container still pins AiiDAlab 26.6: a dry run of the declared
26.9 version conflicts with that image constraint. The pin and live profile were
left unchanged. Native and browser checks in this container do not clear that
release-runtime alignment gate.
