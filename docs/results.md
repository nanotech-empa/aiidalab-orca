# Independent molecular analyses

Keep **New calculation**, **Search calculations** and **Results** as the app's
main entry points. Opening a completed SCF/geometry reference starts in the
Results overview. Each analysis is optional; these sections are not successive
steps of a single workflow.

## Where to start

In **New calculation**, choose the final **Calculation goal**, such as Dyson or
Kondo, then prepare the molecule and review its geometry/SCF calculation in the
same wizard. Choosing a goal keeps you in setup. When the reference finishes,
the requested analysis opens with guidance for its next step. Later calculations
each require their own settings, review and submission.

To reuse an existing reference, explicitly click **Open an existing reference
instead**, select a completed SCF/optimization in **Search calculations**, then
click **View results**. This opens the selected goal for that reference.

**Results** has one **Analysis / results** selector for the overview, orbitals,
CASCI, Dyson spectra/maps, Kondo, vibrations and calculation details. A missing
prerequisite keeps the requested analysis selected and offers an explicit action
such as **Prepare CASCI states** or **Compute Dyson transitions**. The final goal
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
| CASCI states; Dyson spectrum; Dyson orbitals & maps; Kondo orbitals & maps | Views of one shared electronic-state workspace, with retained references and selections |
| Vibrations | Stored IR/Raman spectra and animated modes, plus an optional frequency-calculation form |
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

**Analysis / results → CASCI states** opens the CASCI diagram without
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

The backend workflows, scientific parameters, physical conventions and package
pins are unchanged by this presentation refactor.
