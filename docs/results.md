# Independent molecular analyses

Keep **New calculation**, **Search calculations** and **Results** as the app's
main entry points. Opening a completed SCF/geometry reference starts in the
Results overview. Independent properties can branch from that reference.
CASCI, Dyson and Kondo have explicit preparation dependencies, described in
[the guided CAS workflow](cas-workflow.md).

## Where to start

In **New calculation**, choose the final **Calculation goal**, such as Dyson or
Kondo, then prepare the molecule and review its geometry/SCF calculation in the
same wizard. Choosing a goal keeps you in setup. When the reference finishes,
the next required preparation/analysis stage opens. Later calculations
each require their own settings, review and submission.

To reuse an existing reference, explicitly click **Open an existing reference
instead**, select a completed SCF/optimization in **Search calculations**, then
click **View results**. This opens the selected goal for that reference.

**Results** has one **Analysis / results** selector for the overview, orbitals,
PDOS, orbital preparation, active-space confirmation, energy solver, optional
CASSCF, correlation energies, CASCI, quantum-assisted energies, Dyson spectra/maps,
Kondo, vibrations, export and calculation details. A missing
prerequisite keeps the requested analysis selected and offers an explicit action
such as **Prepare orbital reference**, **Inspect and choose active orbitals**,
or **Compute Dyson transitions**. The final goal
remains visible while preparing these stages; **Continue to…** returns to that
goal to check the next step. No navigation action submits a calculation.

Ordinary orbital inspection starts from SCF results. CASCI first needs a common
spatial-orbital reference and an explicitly reviewed active space; it holds
orbitals fixed, unlike CASSCF. Dyson needs compatible initial and N±1 final
states. Kondo adds the local-moment and charging-energy checks described in
[the Kondo guide](kondo.md). The prerequisite action opens the preparation form
and explains the next step. The app never substitutes a
different spin or submits a prerequisite calculation automatically.

| Section | Contents |
| --- | --- |
| Overview | Final geometry, reference method/charge/spin/energy, XYZ download and optional optimization-convergence plot |
| Orbitals & density | SCF orbital levels and optional cubes/spin density; a separate QRO/UNO inspection view |
| PDOS & orbital character | Atom/fragment and angular projections, with the standard structure viewer and orbital candidates |
| Optical excitations · UV–Vis | Independent fixed-geometry TDA/TDDFT, clickable spectrum/states and reviewed NTO hole/particle previews; see [optical analysis](optical.md) |
| 1. Prepare orbital reference | Prepare or reuse the shared spatial orbitals without SCF iterations |
| 2. Inspect / confirm active space | Inspect occupations/shapes and explicitly select the CAS input orbitals/electrons |
| 3. Choose energy solver | Continue with fixed-orbital ORCA CASCI, optional CASSCF optimization or quantum-assisted energies |
| Optimize orbitals · CASSCF | Optimize one state or an explicit state average; verify, inspect and confirm the new reference |
| ORCA CASCI states and multiplicities | Request fixed-orbital states after preparation and inspect compatible charge/spin sectors |
| Quantum-assisted energy levels | Export the selected reference's Hamiltonian and follow the separate sampling/energy workflow |
| Correlation energies · MP2 / NEVPT2 / CASPT2 | Fresh-HF MP2 or verified-CASSCF corrections, with independent energies and diagnostics |
| Dyson spectrum; Dyson orbitals & maps; Kondo orbitals & maps | Compatible transitions and channels, with separate optional cube/map calculations |
| Vibrations | Stored IR/Raman spectra and animated modes, plus an optional frequency-calculation form |
| XPS · Work in progress | Informational placeholder; XPS calculation controls are unavailable |
| Calculation details | Effective reference inputs, electronic-file storage status and provenance identifiers |

For example, a researcher can inspect ordinary DFT orbitals without preparing
common orbitals or CASCI; inspect IR/Raman without opening electronic-state
analysis; or compute CASCI states without requesting Dyson transitions. Resonance
Raman belongs to the vibrational-analysis family, but its separate workflow is
not implemented yet. The current frequency workflow still requires a completed
ORCA optimization; the interface explains that prerequisite for SCF-only runs.

## Existing results first

Each property shows its saved-calculation selector and available results before
the calculation inputs. **Compute…** actions reveal those inputs on request.
Review and submission continue to use the existing independent workflows,
including provenance-based reuse, file checks, storage policies and explicit
recomputation where needed. Merely opening a section never submits a calculation.

No-data messages explain what is missing. An unavailable optional section does
not prevent inspection of the geometry or other analyses. The reference header
always identifies the selected geometry's SCF reference. Charge/spin sectors,
common-orbital references and active spaces remain explicit in their own views;
the interface does not group calculations just because their formulas match.

## Connected electronic analysis

**Analysis / results → ORCA CASCI states and multiplicities** opens the CASCI diagram without
constructing a Dyson viewer. **Inspect active orbitals** opens the corresponding
reference and active window in **2. Inspect / confirm active space**.
Applying an inspected window returns to the CASCI controls with that reference.

**Dyson spectrum** keeps the existing linked many-electron diagram, transition
selection, spectrum and spin-weight convention together. **Use selection for
cubes / maps** opens **Dyson orbitals & maps**. Existing constant-height figures
appear before map-generation controls; the shared 3D cube and slicing-plane
viewer remains available in the same view. Full/reduced cube handling and saved
figure provenance are unchanged.

## Viewer lifetime

Property panels are constructed on first opening and retained when switching
sections. Energy ranges, selected roots/orbitals, camera state and other viewer
settings are kept. Vibration animations pause while their section or IR/Raman
tab is hidden, then resume only if the user had left them playing. A deliberate
manual pause is retained. Replacing the loaded reference disposes its viewers
and polling tasks once.

Correlation energies form a separate branch; the corrected results do not
replace current Dyson/Kondo vectors or spectral peak energies. See the
[correlation guide](correlation.md) and [validation record](release-readiness.md)
for supported methods, rejection checks and remaining qualification work.

## Export to openBIS

The optional [shared-export workspace](openbis-export.md) opens the common
experiment/molecule selection and combined review for the whole geometry entry.
Related completed analyses are automatically split into their scientific
categories. It exports AiiDA-stored data only. Opening and reviewing the form do
not upload or submit calculations.
