# Independent molecular analyses

Keep **New calculation**, **Search calculations** and **Results** as the app's
main entry points. Opening a completed SCF/geometry reference starts in the
Results overview. Each analysis is optional; these sections are not successive
steps of a single workflow.

| Section | Contents |
| --- | --- |
| Overview | Final geometry, reference method/charge/spin/energy, XYZ download and optional optimization-convergence plot |
| Orbitals & density | SCF orbital levels and optional cubes/spin density; a separate QRO/UNO inspection view |
| States & Dyson | CASCI state energies, with separate views for optional Dyson spectra and orbital/maps results |
| Vibrations | Stored IR/Raman spectra and animated modes, plus an optional frequency-calculation form |
| XPS | C/O 1s binding energies and chemical shifts for selected atoms, with an optional ionization-calculation form |
| Calculation details | Effective reference inputs, electronic-file storage status and provenance identifiers |

For example, a researcher can inspect ordinary DFT orbitals without preparing
common orbitals or CASCI; inspect IR/Raman without opening electronic-state
analysis; or compute CASCI states without requesting Dyson transitions. Resonance
Raman belongs to the vibrational-analysis family, but its separate workflow is
not implemented yet. The current frequency workflow still requires a completed
ORCA optimization; the interface explains that prerequisite for SCF-only runs.
XPS accepts a fixed-geometry SCF reference and does not optimize the geometry.
Its first implementation requires a closed-shell RKS singlet; see
[the XPS guide](xps.md) for core assignment, spin and reuse conventions.

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

**States & Dyson → Many-electron states** opens the CASCI diagram without
constructing a Dyson viewer. **Inspect active orbitals** opens the corresponding
reference and active window in **Orbitals & density → QRO / UNO inspection**.
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

Opening a workspace does not change its stored scientific parameters or
physical conventions. Each analysis uses its own independent backend workflow.
