# Site-resolved XPS draft

Open a completed SCF or geometry reference, choose **Results → XPS**, and expand
**Compute / extend XPS…**. Select the C/N/O/F/Co atoms to ionize. Atom numbers start at
1 and match the geometry viewer; the atom list also gives Cartesian positions.
Review the execution plan and submit. Only missing selected sites are computed,
sequentially. Existing results appear above the calculation form.

For a supplied geometry, leave **Optimize geometry** unchecked in the initial
calculation. This prepares its SCF reference. Every subsequent XPS calculation
uses those exact atomic positions; XPS does not invoke geometry optimization.
An already optimized reference can also be used.

## Scientific model and spin

The observable is a vertical core binding energy of the isolated molecule,
`BE_i = E(core hole at atom i, N−1; R) − E(ground state, N; R)`.
The functional and orbital basis are inherited from the reference. This is
neither a negative KS orbital energy nor an automatically aligned substrate
binding energy. The conversion uses 27.211386245988 eV per Hartree.

The 1s implementation accepts closed-shell **RKS singlets** and **UKS
doublets**, with H/C/N/O/F and at most one all-electron Co atom. ECPs,
broken-symmetry singlet references, higher initial multiplicities, custom
scientific-block overrides and XAS remain outside this draft. Co 2p is a
[separate multireference method](cobalt-xps.md), not a 1s ΔSCF extension.

For a singlet reference, `IonizeAlpha` produces a UKS doublet. For a doublet
reference both channels are computed: beta removal gives an MS=1 high-spin
determinant; alpha removal gives an MS=0 **spin-mixed broken-symmetry
determinant**, not a pure singlet. Neither branch is assumed spin-pure: inspect
its reported S². The final occupations independently verify N−1 and the
requested spin projection.

The two-state Yamaguchi energy estimate is
`E_S ≈ E_BS + S²_BS/(S²_HS − S²_BS) × (E_BS − E_HS)`.
It is accepted only for HS S² in [1.8, 2.2], BS S² in [0.5, 1.5], and a
separation of at least 0.5 in S². These diagnostics are necessary checks, not
proof of the two-state model. The approximation follows the
[NO core-ionization study](https://doi.org/10.1016/j.cplett.2019.136617).
It provides an **energy estimate**, with no spin-pure singlet wavefunction.
Raw energies and S² remain available. No Clebsch–Gordan, multiplicity or
photoionization intensity factors are inferred from ΔSCF energies.

For UKS doublet references the default convergence strategy is ORCA's
[freeze-and-release](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/deltascf.html):
constrain the target non-Aufbau orbitals initially, then release them for full
orbital relaxation. MOM is disabled for this strategy. Final hole/electron/spin
checks apply unchanged; a failed or collapsed solution is not accepted.
In ORCA 6.1.1, `IonizeAlpha`/`IonizeBeta` can leave this strategy inactive
("No orbitals to constrain!"). The doublet protocol therefore uses an
equivalent compact configuration: swap the target occupied MO with the last
occupied MO of the ionized spin channel, declare the cation charge and spin,
and set `AlphaConf 0,1` or `BetaConf 0,1`. Frozen-density controls must verify
this equivalence when qualifying another ORCA version or reference type.
The actual constraint activation and release are checked in the native output.
The legacy singlet route retains the original XYZ declaration and lets ORCA
perform `IonizeAlpha` internally.

### Automatic checks for doublet references

Each site CalcJob performs three native ORCA runs in one allocation:

1. Core-hole preserving optimization, with the requested final gradient
   tolerance. Both constrained and released phases must finish successfully.
2. A numerical precision refinement of that same cation, without another
   ionization or configuration reset. It rebuilds the Fock matrix each cycle
   and requires an orbital gradient of 1e−6 or the stricter reference value.
3. `NoIter CalcGuessEnergy` reads the final GBW and independently evaluates its
   density. Energy must agree within 1e−7 Hartree, with unchanged electron
   counts and S² within 1e−5. The hole and normalization checks apply again.

All stages must terminate normally, preserve geometry/basis, and retain one
localized hole on the selected atom and shell. A final "SCF CONVERGED" banner
does not override a failed final gradient. Poor-normalization warnings stop
acceptance. The final 1s check also rejects transfer into a higher shell of the
same atom, which matters for cobalt. The parser independently recomputes the
checks from the retrieved native outputs. Large electronic files stay under
the selected storage policy; the checks themselves retrieve text and JSON.

These steps are automatic: users do not need to configure a Python code or
manually select validation switches. A failed site displays its reason and
inspection guidance. Increase the SCF iteration limit only when its convergence
trace is still improving; a collapsed hole, damaged GBW or incompatible spin
requires inspection rather than another identical submission. Older unaudited
branches remain viewable but are not reused by the new doublet protocol.
See the [agent operating guide](agents/xps.md) for recovery and provenance rules.

## Core assignment and localization

An independent `CoreOrbitalsWorkChain` reads the supplied GBW at the matching
geometry and basis, without SCF iterations. The separated deep-core subspace contains one 1s orbital per first-row heavy
atom and, when present, Co 1s/2s/three 2p orbitals. All lie below −5 Hartree;
the next orbital must lie above that boundary. Co shells are assigned separately
and never included in the ligand 1s localization window. ORCA's native Löwdin atomic populations assign each core MO to
an atom. Each atom must have one unique core MO with at least 95% population.
This is an operational assignment criterion, not a measurable probability.

If that criterion fails, `orca_loc` applies Pipek–Mezey localization **only to
the fully occupied 1s subspace**, with a fixed seed and 1e−8 localization
tolerance. It never mixes occupied and virtual orbitals. For UKS, localization acts independently in each fully occupied spin subspace.
These rotations preserve the reference determinant and its density.
A second native population analysis verifies the resulting atom assignment.
New core preparations also evaluate the neutral density before and after
localization and require its energy to match the reference within 1e−7 Hartree.
Localized orbital energies are not presented as canonical eigenvalues.
Ambiguous assignments stop the workflow.

The restart must preserve individual MO identities. An explicit
`GuessMode CMatrix` invokes occupied-subspace projection even at matching
basis and geometry; a real native test showed that it rotates the core MOs
and sets their printed initial energies to zero. The XPS procedure therefore
uses the matched-basis default read and rejects CMatrix in core preparation.

After ΔSCF, the parser identifies the actual final empty deep-core orbital;
ORCA can reorder it during optimization. Exactly one such hole must exist,
with at least 95% target-atom population. This catches valence-hole collapse
and ionization on the wrong atom. ORCA 6.1.1 skips its Löwdin analysis after
`IonizeAlpha` because that routine still expects the reference electron count.
The final-hole check therefore uses **native Mulliken MO populations**, with
an independent electron-count check from the orbital occupations. Mulliken
populations can slightly exceed 100% and are not probabilities.

## Small components, reuse and storage

- `empa_orca.xps_core`: shared core preparation and preservation.
- `empa_orca.xps_site`: one independently reusable native ORCA ionization
  CalcJob, retaining the binding energy and validation data as a `Dict`.
- `empa_orca.xps_multiplets`: composes alpha/beta workflows and links the
  approximate singlet energy to both raw results through a calcfunction.
- `empa_orca.xps`: a small collection workflow for selected sites, reusing
  verified site results and submitting new sites serially.

Reuse checks provenance, coordinates, effective electronic parameters, ORCA
code, initial SCF producer and atom index. It reparses the retrieved output
and compares it with the stored result using AiiDA's float serialization.
Finished site energies remain reusable without any remote wavefunction.
Changing the requested atom subset does not repeat completed compatible sites.

New sites require a prepared core GBW. Actual availability is checked in the
repository, stash and remote directory. Missing core orbitals trigger their
preparation. If the original GBW is also gone, the workflow explicitly
recomputes only the fixed-geometry SCF with caching disabled, then verifies
that its energy matches the original within 1e−6 Hartree before continuing.
Inaccessible storage is reported as inaccessible, not treated as deletion.
An altered replacement SCF solution stops the workflow for inspection.

The reference's size threshold and stash directory apply to prepared core
orbitals and newly computed core-hole wavefunctions. Preservation runs through
the existing independent storage CalcJob. Scientific CalcJobs retrieve only
text/validation data; GBW/density bundles are retrieved below the threshold
or stashed above it. New artifact-producing calculations disable cache reads;
verified explicit reuse works whether global AiiDA caching is enabled or not.
Partial successful site energies survive a later site or storage failure.

The ORCA tools code is resolved automatically on the ORCA computer. Users do
not select a Python interpreter. Core preparation uses the native ORCA code
and its sibling `orca_loc` executable; the ORCA/MPI environment comes from the
configured code. All preparation, localization, SCF and storage work runs
inside CalcJobs and uses AiiDA transports.

## Results and QE comparison

The viewer offers per-edge binding energies or chemical shifts, adjustable
Gaussian FWHM, site curves and their sum, spin diagnostics, and core-hole
assignment data. Every displayed component contributes **equal integrated area**:
these are schematic line shapes, not calculated photoionization cross sections
or satellite intensities. Downloadable CSV and view JSON include the scientific
node identifiers.

Completed QE XPS workflows at the same relative Cartesian geometry and atom
ordering can be overlaid after their provenance is available in this profile.
Only the selected ORCA atoms contribute to that overlay, including correct
counting of selected members of a QE equivalence class. Binding-energy mode
uses each calculation's stored energies; chemical-shift mode separately
subtracts the lowest displayed energy per edge and method. QE absolute energies
include its stored pseudopotential corrections. A different functional or
spin/core-hole model must be documented when interpreting the comparison.

The planned user benchmark is **QE through the QE app on Daint versus ORCA
locally**, at the supplied geometry, **without relaxation**. No QE benchmark
has yet been run for the new supplied geometry.

### Comparison with existing QE results at their stored geometry

The existing QE-app formic-acid run covered only the carbonyl oxygen at a
hand-built geometry. The optimized ORCA example below uses a different
geometry and cannot be compared directly with that run. To remove this
difference, an additional ORCA SCF and O2 1s ionization were computed at
**exactly the stored QE atom order and Cartesian coordinates**, without
relaxation. Both methods use PBE.

| Calculation at the same stored geometry | Carbonyl O 1s binding energy (eV) |
| --- | ---: |
| Existing QE-app run, 30/240 Ry cutoffs | 537.83102 |
| Existing standalone QE compatibility test, 60/480 Ry cutoffs | 538.02055 |
| ORCA, PBE/def2-TZVP, explicit UKS core-ionized doublet | 537.21133 |

ORCA lies **0.61969 eV below the QE-app result** and 0.80922 eV below the
standalone QE test. The actual staged ground/core-hole pseudopotentials match
by file hash in the two QE runs; their cutoffs and SCF thresholds differ.
Their 0.18953 eV difference shows that numerical convergence still needs to be
checked before an accuracy comparison. Both include the stored O 1s correction
of 668.22 eV. Their valence calculations have one spin component; the core hole
is represented by the pseudopotential. ORCA instead relaxes an explicit
all-electron UKS doublet (final ⟨S²⟩ = 0.756508). Thus matching the geometry and
functional does not make the core-hole, spin or basis approximations identical.

This is a single-site development comparison, not an accuracy benchmark or a
test of relative chemical shifts: the saved QE runs contain no second oxygen
site. Both QE results are selectable as overlays in the XPS workspace of the
new fixed-geometry ORCA reference.

Provenance:

- QE-app XPS: `c074ddf9-3bfa-462e-b99f-0bb4efa253e1` (parent
  `3e07fea0-3281-42a5-93af-255d6a0e31b8`).
- Standalone QE compatibility test: `f76a299c-173b-4eb0-8a3d-a6181b46b577`.
- ORCA fixed-geometry SCF: `13668010-5649-4960-80f9-684ea3f434b5`.
- ORCA XPS: `c70cb18e-1273-46e5-9fa4-ffdec48a94a3`.
- ORCA site data: `1cf24625-705d-466d-8297-7b1cd7526229`.

## Local validation

Native ORCA 6.1.1 ARM64 calculations were submitted through the app services.
At PBE/def2-TZVP, the optimized formic-acid development example gives:

| Site | Vertical binding energy (eV) | UKS ⟨S²⟩ |
| --- | ---: | ---: |
| C1 1s | 294.80023 | 0.76569 |
| O2 1s (carbonyl) | 538.06678 | 0.75740 |
| O3 1s (hydroxyl) | 539.90112 | 0.75664 |

The oxygen splitting is 1.83434 eV. These are development results, without a
basis/functional convergence study. Their source workflow is
`b72c1e4a-8db8-4532-9397-e564bc5a489c`. This earlier development geometry was
optimized; the upcoming user-supplied-geometry benchmark will not be relaxed.

A separate fixed linear CO₂ test at PBE/def2-SVP exercised actual core-only
localization: its two oxygen core MOs initially shared atomic populations,
then localized successfully. The two site binding energies agreed within
2e−8 eV. A completed formic-acid reuse submission produced zero new children.
Regression tests also exercise reuse with a nonexistent scratch directory,
wrong-site/collapsed holes, incompatible spins and stored-float rounding.

References: [ORCA ΔSCF and core ionization](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/deltascf.html#core-ionized-states),
[native population analyses](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/population.html),
[localization utilities](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/utilities.html#orca-loc).

### Open-shell NO validation

Native ORCA 6.1.1 ARM64, PBE/def2-TZVP, neutral doublet, fixed bond length
1.151 Å. All four atom/spin CalcJobs passed core identity and occupation checks.

| Site | Triplet BE (eV) | Raw BS BE (eV) | Estimated singlet BE (eV) | Estimated splitting (eV) | Published PBE splitting (eV) |
| --- | ---: | ---: | ---: | ---: | ---: |
| N 1s | 409.86273 | 410.40054 | 410.95389 | 1.09116 | 1.16 |
| O 1s | 542.51782 | 542.73552 | 542.95804 | 0.44022 | 0.45 |

The paper uses a different, core-flexible uncontracted basis. This checks the
spin-branch/projection implementation; it does not establish converged absolute
binding energies. Our absolute PBE values are roughly 0.5–0.6 eV above its
uncorrected values. Atomic relativistic corrections are not applied here.

Reference SCF: `6df5b64d-a57e-4330-991a-f865379d1547`.
XPS workflow: `78919f42-4f70-406e-ba0f-f0a68392f125`.
The app selector displays raw HS/BS or triplet/estimated singlet; its history
contains the parent result rather than duplicate internal spin workflows.
