# Site-resolved XPS draft

Open a completed SCF or geometry reference, choose **Results → XPS**, and expand
**Compute / extend XPS…**. Select the C/O atoms to ionize. Atom numbers start at
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

The first implementation accepts closed-shell **RKS singlets**, molecules
containing H/C/N/O/F, and **C or O 1s** ionization. Each ionized state is a UKS
doublet. ORCA `IonizeAlpha` adjusts the charge and spin internally, so the
input XYZ declaration retains the **reference** charge and multiplicity. The
final alpha/beta occupations must sum to N−1 and differ by one electron.
The native UKS ⟨S²⟩ diagnostic is retained and displayed; it is not a proof of
spin purity. A deviation above 0.1 from the doublet value 0.75 is reported.

Open-shell references, broken-symmetry singlets, ECPs, custom scientific-block
overrides, other shells and XAS are rejected or outside this draft. A future
open-shell extension needs a validated treatment of the `S_i ± 1/2` final
multiplets. Alpha/beta removal alone does not identify pure low-spin states.
No spin statistical factors or Clebsch–Gordan weights are inferred from these
single-determinant ΔSCF energies.

## Core assignment and localization

An independent `CoreOrbitalsWorkChain` reads the supplied GBW at the matching
geometry and basis, without SCF iterations. For the supported first-row
molecules, the first occupied orbitals must form a separated 1s core subspace
(one per non-hydrogen atom, below −5 Hartree; the next orbital must lie above
that boundary). ORCA's native Löwdin atomic populations assign each core MO to
an atom. Each atom must have one unique core MO with at least 95% population.
This is an operational assignment criterion, not a measurable probability.

If that criterion fails, `orca_loc` applies Pipek–Mezey localization **only to
the fully occupied 1s subspace**, with a fixed seed and 1e−8 localization
tolerance. It never mixes occupied and virtual orbitals. Such an occupied
rotation preserves the closed-shell determinant and ground-state density.
A second native population analysis verifies the resulting atom assignment.
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
assignment data. Every selected atom contributes **equal integrated area**:
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
