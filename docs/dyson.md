# Fixed-geometry Dyson transitions and spectral functions (draft)

Open a completed geometry/SCF result, expand **CASCI states · fixed geometry
(draft)**, select a common reference and active space, and open **Dyson orbitals
and spectral functions**. Compute missing CASCI sectors with the existing controls
above it. UNO visualization remains an inspection feature; this draft consumes
CASCI states prepared in the shared QRO/restricted reference.

Choose an initial CASCI root and final roots from compatible charge/spin sectors.
The default initial state is the lowest **computed** state at the reference
charge; it is not proof that the physical ground state has been found. Initial
and final states must share geometry, common orbital-reference identity, exact
active indices and electron convention, and the CASCI integral model. For
single-electron, spin-free tunnelling the app and backend enforce
`abs(S_final - S_initial) = 1/2`, equivalently multiplicities differing by one.
A singlet connects to doublets; a doublet connects to singlets and triplets.

**Review Dyson calculation** explains which existing wavefunctions will be
exported and which exports or Dyson results will be reused. It does not silently
repeat electronic calculations. Submit to obtain the transition table and
compact AO coefficient arrays. The table records each final state/root,
transition energy, component strength, retained CI norm, spin channel and active
orbital composition. The initial state's identity and CI norm are also retained.

## Spin and energy conventions

The stored Dyson amplitudes reproduce Andrés's kernel: the component between
initial and final spin states with `M_S = S`. They are not normalized to one.
Their squared AO norm `d.T @ S_AO @ d` is stored as the **component strength**.
Printed CI coefficients are checked and retained without renormalization.
The default maximum missing printed CI norm is `1e-5`; it is a diagnostic cutoff,
not an error bound on the final spectrum. A failed cutoff asks for a smaller
CASCI printing threshold, not a hidden renormalization.

The spectrum offers two conventions without repeating any electronic calculation:

- **Highest M_S component**: use the stored strength, matching the upstream tool.
- **Unpolarized, spin summed**: average over equally populated initial spin
  projections and sum over final projections and tunnelling-electron spin.

For spin-pure states without SOC, the Wigner–Eckart/Clebsch–Gordan spin-1/2 relation gives the
factor below relative to the stored highest-projection component. It applies to
addition and removal. The automated tests independently sum explicit Fock-space
matrix elements over spin-lowered multiplets, including singlet/doublet and
doublet/singlet/triplet cases.

| Initial multiplicity | Final multiplicity | Unpolarized factor |
| --- | --- | --- |
| 1 | 2 | 2 |
| 2 | 1 | 1 |
| 2 | 3 | 3/2 |
| m | m−1 | 1 |
| m | m+1 | (m+1)/m |

The raw amplitudes already contain the Clebsch–Gordan coefficient of the chosen
component. The conversion accounts for the other projections; it must not
apply that coefficient twice or simply multiply by the final multiplicity.
The transition table and JSON export show the component strength, conversion
factor and selected weight separately, with explicit normalization conventions.

This is not a model of spin-polarized tunnelling, non-equilibrium spin
populations, spin–orbit mixing, or higher-order/inelastic tunnelling processes.
No general STM cross section is inferred solely from a Dyson norm.

Removal poles use `E_initial − E_final`; addition poles use
`E_final − E_initial`, converted from Hartree to eV. Their signs follow these
energy differences; addition is not forced to be positive. The optional rigid
energy offset changes the displayed alignment, not the initial physical state.
No substrate Fermi energy is inferred from an isolated molecule.

The interactive Lorentzian uses the upstream convention
`eta / ((omega − pole)^2 + eta^2)`: eta is **HWHM** in eV and the integrated area
is **pi times the selected weight**. The default HWHM is 0.04 eV. Spectrum CSV and
JSON downloads retain the spin convention, energy offset, range, broadening and
raw transition table. The spectrum contains only the computed selected states;
missing sectors/roots are not a complete spectral sum.

## Separate components and storage

- `empa_orca.dyson_export`: reuses an available validated export or runs an
  `orca_2json` CalcJob followed by the configured ORCA Dyson helper. A compressed
  bundle contains the matching MO coefficients, AO overlap, basis shells,
  geometry, printed CI vectors and provenance identity. Charge/spin, geometry,
  electron counts, orbital orthonormality and CI norms are checked. Small bundles
  receive a retrieved copy up to the reference WFN retrieval threshold; all
  bundles are natively stashed in the reference's stash directory. Large exports
  are not automatically retrieved. The small duplicate stash is intentional.
- `empa_orca.dyson`: combines compatible exported states through
  `dyson_orca_tools.dyson.Dyson`. It retrieves the transition table and compressed
  AO coefficient arrays. The recorded active indices are used explicitly, including fully occupied
  active orbitals; their occupations do not redefine the inactive core.
  The CASCI branch is required; separately optimized
  orbital bases are rejected in this draft.
- `empa_orca.dyson_cubes`: independently generates requested Dyson amplitudes and
  optional intensity blends using the exported basis and PySCF, then reduces
  them with cubehandler before retrieval. The ORCA/PySCF AO labels and overlap
  matrices must agree. Full cubes can be stashed, left in the working directory,
  or deleted after preview validation.

Reuse is explicit and works without AiiDA caching. Completed Dyson tables and
coefficients can be reused before checking old scratch. For new transitions,
exports are checked first, then preserved GBWs. Files are checked again when
consumed, including their SHA-256. Missing files stop with a recovery explanation;
unreachable storage is not classified as deleted. Actual artifact-producing
CalcJobs use `metadata.disable_cache=True`. **Recompute Dyson coefficients**
bypasses transition reuse while retaining compatible exports.

If both an export and its CASCI GBW are gone, restore them or explicitly rerun
that CASCI sector using the original common orbitals. If the original common
orbitals are also lost, do not mix regenerated and old sectors automatically.
Extending the available roots still uses the existing per-sector CASCI workflow.

## Intensity blends and cube viewing

The spectral viewer selects an energy or an energy window. In the cube controls,
choose the transitions and enable **Include spectral intensity blend**. All
selected transitions contribute, including broadened tails; membership is not a
hard cut at the selected energy. This job is separate from electronic-state and
Dyson coefficient calculation.

At a single energy the cube contains
`sum_f spin_factor_f * |d_f(r)|^2 * L_eta(omega − pole_f)`.
For a window, replace the Lorentzian by its analytic integral over the window.
There is no coherent sum between distinct final states, and the pole strength
must not be multiplied in again: it is already in the unnormalized amplitude.
The exact selection, spin convention, offset, HWHM and window are CalcJob inputs
and appear in the cube manifest.

The shared EMPA viewer supports 3D isosurfaces, isolated-boundary 2D slices,
saved visualizations and submitted preview/full-resolution rendering jobs.
These are **spectral intensity cubes**, not quantitative STM currents. The
separate [constant-height map component](maps.md) now adds explicit planes,
meqpy-style vacuum propagation, numerical-map storage and shared-scale figures.
Spatial coordinates and cube amplitudes retain their
atomic-unit conventions; reduced previews are for inspection, not integration.

## Deployment and boundaries

The [linked transition explorer](transition-explorer.md) connects selectable
spectral regions to exact many-electron state endpoints, existing orbital
previews and CG multiplet-weight readouts. It also supports drag-selected
energy windows for the map/blend controls, without submitting calculations.

Install the backend with its `dyson` extra on the execution computer:

```bash
python -m pip install -e 'backend[dyson]'
verdi code create core.code.installed --label orca-dyson \
    --computer localhost --filepath-executable /path/to/bin/orca-dyson \
    --default-calc-job-plugin empa_orca.dyson
```

Register `orca_2json` and cubehandler on the same computer. On tigu, install the
same backend and optional dependencies there and register the corresponding
executables for that computer. The app exposes **Dyson tools**, not a generic
Python interpreter or PythonJob. Code setup is an administrator task. Helpers
run serially and default to one OpenMP/BLAS thread unless the configured runtime
already specifies a thread count. Scheduler account/queue information is
inherited from the source calculation.

The reviewed upstream dependency is pinned to commit
`96658a681815faf1cf260bcb26fe712ca7715103`: its cube writer accepts explicit grid
sizes, which the released v0.1.0 writer does not. The integration calls the
library kernel/writer directly; it does not invoke the upstream spectrum CLI's
known overwritten-grid variable. No upstream code is patched or vendored.

Current scientific scope remains all-electron, fixed-geometry CASCI in one common
spatial basis, with no SOC or CASSCF orbital relaxation. The inexpensive NO
CAS(3,3) case checks the pipeline; pentacene with an agreed protocol and matched
reference data remains the scientific benchmark.

## Validation of the local draft

The test environment is Python 3.12.11, AiiDA 2.9.2, AiiDAlab 26.9.0,
ORCA 6.1.1 ARM64, PySCF 2.14.0 and the upstream commit above. The combined
suite has 149 passing tests. These include independent spin-multiplet sums,
the fully occupied active-orbital case, rejection of duplicate final sectors,
energy signs, HWHM/area and energy-window integrals, CI diagnostics,
provenance-based reuse with caching enabled/disabled, and missing-source
recovery without submitting an electronic calculation.

Real local CalcJobs used the saved NO PBE/def2-SVP QRO reference and CAS(3,3).
The neutral doublet connected to three singlet and two triplet roots in each
charged sector, giving ten transitions. Both initial doublet roots were tested.
Individual cubes and point/window intensity blends were reduced by cubehandler;
full-cube stashing, preview-only deletion after validation, and full-resolution
rendering from a stash were exercised. At an 80-cubed grid, the relative
integration discrepancy was approximately 4e-5 for the strongest individual
transitions and 8e-4 for the tested window blend; grid convergence is not assumed.
A size threshold of zero also exercises export preservation without a retrieved
wavefunction copy. Separate Dyson and cube CalcJobs successfully consumed that
stash-only export, including an excited initial root and a 120-cubed grid.
A missing retrieved copy therefore does not require a new CASCI calculation.

A real browser session submitted Dyson and cube/blend workflows from the app,
reopened their results in the shared EMPA viewer, switched both spin conventions,
changed broadening, and reviewed explicit reuse. App-discovery audits and
`pip check` pass. This is execution and internal-consistency evidence, not a
converged NO spectrum or reproduction of the pentacene publication.
