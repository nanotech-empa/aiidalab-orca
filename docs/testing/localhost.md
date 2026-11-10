# Localhost: step-by-step acceptance

Read [scope, limits and reporting](README.md) first. Execute only the requested
case(s), in order of their prerequisites. The default first run is L00–L01.
Use a visible ORCA code on the local computer, normally two processes, 2 GiB
and ten minutes. For helper/PDOS/solver stages choose compatible local codes;
set their memory to 2 GiB where exposed. A missing helper blocks its stage.

Use a single native job at a time. The one exception below is L07's deliberately
small two-job batch: one process and 1 GiB per job, two cores/2 GiB in aggregate.
Leave full files on the calculation computer, keep `maxsizeoutput = 5 MiB`,
and keep full cubes in their calculation directory unless stated otherwise.
Do not interpret a requested memory limit as a guaranteed OS cap.

## L00 — Launch and execution context

**Needs:** a configured instance and an approved local scope. **Submits:** nothing.

1. Open ORCA from the homepage. Confirm there is a single clear launch action
   and that the app opens its molecular-analysis page, not a homepage `start` tab.
2. Inspect **New calculation**, **Search calculations** and **Results**.
3. Check the visible code choices and select the local ORCA code for the run.
4. Locate **QPU credentials** without entering or reading a secret. Leave it closed.
5. Confirm ordinary page scrolling works without nested notebook-output scrollbars.

**PASS:** usable navigation and an identifiable local execution context. Opening
the app submits no job. Record unavailable controls as BLOCKED, not an invitation
to install packages or configure computers from this test.

## L01 — Allyl optimization and automatic PDOS

**Needs:** L00. **Submits:** one geometry workflow and its automatic local PDOS child.

1. Choose **New calculation → Calculation goal → Geometry optimization / SCF only**.
2. Under **Step 1: Select structure → Build from SMILES**, enter `C=C[CH2]`,
   generate the molecule and check **C3H5, 8 atoms**. Confirm the structure.
3. In Step 2 enable **Optimize geometry**; use **PBE / def2-SVP**, charge **0**,
   multiplicity **2**. Leave constraints empty. Confirm settings.
4. In Step 3 choose the local ORCA code, **2 processes**, **2 GiB**, **10 minutes**.
   Keep **Compute PDOS / orbital character** enabled; set **PDOS resources** to
   **2 GiB** and **PDOS wall time (minutes) = 10**. Review must show a ten-minute
   limit for ORCA and a separate ten-minute limit for PDOS. Review full-file
   retention and the 5 MiB output threshold.
5. Set label `<prefix>-L01 allyl geometry + PDOS`. Enable **Recompute even if a
   compatible result is available** for this first submission, so an old result
   cannot replace the new-code test.
6. Click **Review calculation**. Check molecule, charge/spin, method, basis,
   optimization, location and resources in the effective input/review.
7. Click **Submit once**. Record the UUID immediately. Refresh status until the
   optimization and PDOS child finish; a finished geometry can precede its PDOS.
8. Open Results and record the optimized reference UUID, total energy and warnings.

**PASS:** optimization is reported converged; the final model has the same eight
atoms and identity; finite energy and usable PDOS are stored. PDOS failure must
be recorded even if the geometry itself succeeded. Do not claim a vibrational
minimum from this optimization alone. **Stop here on the first Desktop trial.**

## L02 — Geometry viewer, PDOS and navigation

**Needs:** L01. **Submits:** nothing.

1. Open **Overview** and inspect input and final geometries with the standard
   structure viewer. Select atoms 1 and 2, then three atoms, and check that
   indices/distances/angles are inspectable. Atom indices start at 1.
2. Open **PDOS & orbital character**. Select carbon, then an explicit atom/fragment
   selection using the visible atom-selection control; clear it again.
3. Change between total, atomic-orbital and perpendicular-p/π-like projections.
   Inspect the displayed molecular-plane normal; do not equate p character with
   a universally defined π subspace for an arbitrary nonplanar molecule.
4. Change the energy interval and broadening; restore **HOMO − 1 to LUMO + 1 eV**.
   Check alpha/beta identity and matching spin colors of total/projected curves.
5. Select an orbital mark/list entry and inspect its atom/orbital contributions.
   Orbital indices start at 0. Navigate away and back.

**PASS:** plots update from stored projections, selection/units/spin identities
are clear, and navigation retains useful state without extra calculations.

**L02-IMPORT, local input controls:** download L01's final XYZ, import it in a
new **File / XYZ** draft and check the same eight atoms without submitting.
Also find/import its saved geometry through **AiiDA structures**. Keep the original
entry unchanged. CDXML/other format acceptance needs an agreed fixture with a
known formula; record those formats as not covered rather than inventing one.

## L03 — Single-point mode, validation, review invalidation and reuse

**Needs:** L01. **Submits:** one single-point SCF workflow, then a reuse action.

1. Use **Use final geometry** from L01 to prepare a new draft. Disable
   **Optimize geometry**; keep PBE/def2-SVP, charge 0 and multiplicity 2.
2. Before submitting, try multiplicity **1**. The odd-electron input must be
   rejected. Do not submit it. Restore multiplicity 2.
3. Review valid settings, then edit the run label or a resource field. Confirm
   that the old review cannot be submitted unchanged. Review again.
4. Use label `<prefix>-L03 allyl SCF`, the local limits and ordinary PDOS/storage
   settings. Submit once and record the UUID.
5. Confirm the result is a fixed-geometry SCF, with unchanged coordinates, rather
   than another optimization. Inspect **Copy settings** without submitting it.
6. Prepare the same SCF request with recomputation disabled. Review: the app
   should offer the compatible stored result. Use that action once.
7. Find the new entry through **Search calculations** by label and UUID; open it.

**PASS:** invalid spin is rejected; editing invalidates review; fixed geometry
and reuse are explicit; reuse submits no duplicate electronic calculation.
Record geometry/energy agreement with L01 for maintainer verification.

## L04 — A separate constrained optimization

**Needs:** L01/L02. **Submits:** one independent constrained geometry workflow.

1. Start from L01's final geometry and keep its method/charge/spin.
2. In **Geometry optimization constraints (optional)**, select carbon atoms
   1 and 2 in the viewer and add a distance constraint using that selection.
3. Check the displayed actual distance against the viewer. First leave the
   target blank and check that the starting-value meaning is clear.
4. Set an explicit target **0.05 Å above the displayed actual distance**;
   record both values. Review the input and one-based atom mapping.
5. Submit under `<prefix>-L04 constrained allyl` with local limits.
6. Inspect the final distance and recorded constraint. Keep this entry separate
   from the unconstrained L01 reference used below.

**PASS:** atom mapping/units are clear and the final distance meets the target
to the visible precision (within 0.01 Å for this manual check). The result does
not silently replace L01. Do not interpret it as an unconstrained minimum.

## L05 — KS orbitals, spin density and saved visualizations

**Needs:** L01/L02 and configured local plot/cubehandler/render helpers.
**Submits:** reviewed cube previews and one small render job, serially.

1. Return to L01, open **Orbitals & density**, and inspect the spin-resolved levels.
   The initial range should be HOMO − 1 eV to LUMO + 1 eV; change and reset it.
   Counts on overlapping bars must not hide the underlying orbital identities.
2. Select one frontier alpha orbital and its relevant beta counterpart using
   the displayed indices/occupations; record them. Enable **Spin density (α−β)**
   for this unrestricted reference.
3. Use **80 grid points/axis**, local compatible helpers and **Leave full cubes
   in calculation directory**. Under **Cube resources**, set **2 GiB** and
   **Cube wall time (minutes) = 10**. Review must show **1 process, 2 GiB,
   up to 10 minutes** before generating previews once.
4. Open each reduced preview. Check the molecule aligns with the cube, signed
   lobes are distinguishable, and spin density is a separate dataset. Download
   one **reduced** cube; record its source UUID/name.
5. In the shared viewer, change isovalue and color. Show the slicing plane in 3D;
   edit its center/normal while viewing 3D, then inspect **2D slice**. Areas
   outside the isolated grid must be empty rather than periodically repeated.
6. Save two named views of one cube: `surface` and `surface-with-slice`. Preserve
   the plane visibility and coloring in the latter. In **Render → Rendering
   resources**, set **2 GiB** and **Render wall time (minutes) = 10**. Set a
   small image (e.g. 800 × 800 px) before saving that view. Select only
   `surface-with-slice` and choose **Review selected views**. Check one CalcJob,
   its recorded source, image size, included slicing plane, and **1 process,
   2 GiB, up to 10 minutes**; then **Submit reviewed render** once.
7. Inspect the stored image and its calculation/source identifier. Switch cube
   and return; verify saved-view identity and settings were not silently lost.

**PASS:** reduced cubes and saved views are usable; the rendered saved view
includes the enabled colored slicing plane. Missing renderer is BLOCKED for
rendering, not PASS based on a browser screenshot. Full cubes/wavefunction must
remain external; a maintainer checks repository contents separately.

**L05-DELETE, optional local storage control:** for one separately generated
preview choose **Delete full cubes after preview validation**. Confirm the
reduced preview remains usable. A maintainer verifies deletion of only that
new full cube and preservation of the source wavefunction. Do not apply this
to full cubes still needed by a map or another calculation.

## L06 — QRO/UNO inspection and explicit CAS confirmation

**Needs:** L01 and local orbital-inspection helpers. **Submits:** orbital
preparation/inspection and a small set of previews.

1. Choose **CAS energy levels → 1. Prepare orbital reference** for L01.
   Keep the inherited preparation limits at 2 processes, 2 GiB and 10 minutes,
   **Leave full files** and `maxsizeoutput` 5 MiB. Under **Prepared-orbital PDOS
   resources**, set 2 GiB and 10 minutes. Review and prepare the common orbitals.
   Check that the review specifies QRO, then UNO: one serial PDOS CalcJob at a
   time, each with those limits. Wait for the whole preparation, including both
   PDOS jobs, to finish. Record the prepared-reference UUID.
2. Open **View orbitals and choose active space** / **2. Inspect / confirm active
   space**. In **Catalog resources and export code**, set 2 GiB and 10 minutes.
   Click **Review orbital information**, verify one serial catalog CalcJob with
   those limits, then **Read orbital information** once. Wait for completion.
3. Inspect QRO and UNO tables separately. Generate previews for **two different
   frontier orbitals**, then switch between them: the selector must not always
   display only the first stored orbital. In **Preview settings and file
   storage… → Preview resources**, set 2 GiB and 10 minutes; keep grid 80 and
   **Leave full cubes**. Check the budget in **Review orbital visualization**
   before **Generate orbital previews**. Wait for each workflow to finish before
   requesting the other set. Keep full grids external.
4. Inspect occupation labels and 3D character. UNO occupations are spin-summed
   natural occupations, not separate alpha/beta populations. Viewing UNOs does
   not by itself make them the chosen CAS reference.
5. For this small integration example set **3 active electrons, 3 active
   orbitals** and inspect the three frontier π-like orbitals. Record their actual
   zero-based indices and prepared reference. Do not copy indices from an old run.
6. Confirm the active space explicitly; then open **3. Choose energy solver**.

**PASS:** references, indices and occupations remain identifiable; confirmation
is required before computation. Reviews expose the selected helper limits;
editing a budget invalidates its review and QRO/UNO PDOS jobs run sequentially.
CAS(3,3) is this test model, not a universal
recommended active space. If inspection does not support these orbital
characters, stop rather than silently picking another space. A missing general
orbital-reordering control is not implemented by preview selection.

## L07 — CASCI states, a small batch and a common energy diagram

**Needs:** L06. **Submits:** neutral states and charged sectors, as described.

1. Choose **ORCA CASCI — fixed orbitals** and continue to CASCI controls.
   Keep the L06 common orbitals and CAS(3,3), correlation auxiliary **def2-SVP/C**.
2. Request **Charges = 0**, **Multiplicities (2S+1) = 2**, **Electronic states = 3**.
   Review charge/spin combinations, resources and native input, then submit.
   Expect neutral roots **0, 1, 2**. Save this run as the original orbital branch.
3. Review the matrix for charges `-1 +1` and multiplicities `1 3`, three states.
   Inspect sector electron counts (4 and 2) and valid/skipped combinations.
   This review alone must submit nothing.
4. For one actual batch test select charges `-1 +1`, multiplicity **1**, three
   states. Keep **2 processes, 2 GiB and 10 minutes per sector**, **Leave full
   files** and `maxsizeoutput` **5 MiB**. Review must specify sequential execution.
   Submit the two-sector batch once; record its batch UUID and verify the second
   sector remains queued until the first terminates. Wait for both before another
   calculation. The AiiDA queue continues if the browser closes. Reopening and
   reviewing while it is active must follow the existing batch and block another
   submission.
5. Request multiplicity **3** for each of charges **-1** and **+1**, one request
   at a time, three states each, using local limits. Reuse matching results if offered.
6. Open the many-electron diagram, select a different **Energy zero**, change
   the plotted range, and inspect one root from each charge/spin column.

**PASS:** state/sector counts and reductions are explicit, each calculation
retains its input, sectors and their CalcJobs do not overlap (including after a
failed sector), repeated Submit cannot duplicate the batch, and all plotted
energies share the selected zero. These are
many-electron energies, not KS orbital energies. No Hamiltonian export is needed.

## L08 — Dyson coefficients, linked spectra and maps

**Needs:** L07 and local export/Dyson/cube/map/render helpers.
**Submits:** Dyson processing, limited cubes/maps and a small figure, serially.

1. Open **4. Dyson spectrum** for the original L06/L07 orbital branch. Select
   neutral doublet **root 0**, **Removal and addition**, and all computed
   compatible final singlet/triplet states from L07. Check shared reference IDs.
2. Under **Dyson validation, resources and codes**, set **Dyson processes = 1**,
   2 GiB and 10 minutes. Set **State-export resources · serial** to 2 GiB and
   10 minutes too. Keep **Leave full files / maxsizeoutput 5 MiB** and the
   existing norm-loss tolerance **1e−5**. Review must show exports running one
   at a time, followed by the Dyson evaluation, with these per-job budgets.
   Review and **Compute Dyson transitions** once. Wait for the whole workflow.
   Do not change a failed export/CI tolerance to make it pass.
3. Inspect the transition table, spectrum and default **Spin averaged ·
   unpolarized** convention. Switch to the stored highest-spin component if
   offered; record the convention and CG factors, then restore the default.
4. Click a spectrum region/peak. Check highlighted state endpoints and connecting
   segments agree with the exact transition table. A zero shift of the spectrum
   is independent of the energy-diagram zero. Counts/line merging must not lose
   individual transition identities.
5. Generate amplitude cubes for **one removal and one addition transition**,
   80 grid points/axis, full cubes **Leave**. Under **Cube resources**, set
   2 GiB and 10 minutes; verify 1 process in the review. Inspect both reduced
   previews after completion.
6. For one chosen spectral maximum use **Prepare spectral map at this peak**.
   Inspect the complete contributing transition set before requesting any
   additional cubes. Retain full cubes needed by the map; submit stages serially.
7. Use the source plane **1.5 Å above the highest atomic z**, normal to +z,
   through the reset or slice controls. For this first map set **Observation
   heights (Å) = 1.5** too: these heights are measured from the same highest-z
   reference, not added above the source slice. The GUI normally starts with
   observation heights 5 and 7 Å. Record the chosen plane; this convention is
   molecular and does not establish a real surface.
8. Set **Map resources** to 2 GiB / 10 minutes; review, then compute one map.
   After it finishes, use **Figure appearance / export → Figure resources**
   with the same budget, **Review shared-scale figure → Render shared-scale
   figure**, and inspect **Stored figures**. Both jobs are serial, 1 process.
   Changing memory/wall time must invalidate the corresponding review; repeated
   Submit must not duplicate a job. A second stage for the same orbital
   reference is blocked while one remains active, also after reopening the GUI.
   Record numerical-map and figure UUIDs.

**PASS:** transitions obey the displayed single-electron spin compatibility,
weights/conventions remain explicit, and plots/maps use the selected endpoints
and stored coefficients. Missing states are not invented. Figures compared
together use the same scale; do not auto-normalize each panel for appearance.

## L09 — Kondo channels and a small map

**Needs:** the compatible original-branch Dyson states from L08 and a nonzero-spin
initial state. **Submits:** exchange channels and limited cube/map/render stages.

1. Open **5. Kondo orbitals & maps** for the neutral doublet.
2. Read the model assumptions and displayed chemical-potential guidance. Use a
   μ **strictly inside the displayed stability interval**, recording its value,
   limits and convention. If no valid interval can be established in the UI,
   stop and report BLOCKED/FAIL as appropriate; do not assume μ=0 or alignment
   to a substrate. A chosen midpoint is a model parameter, not an experimental fit.
3. Under **Kondo channel resources · serial**, set **2 GiB / 10 minutes**.
   Review must show **1 process**. Change the wall time to 9 minutes: review
   must become invalid and Submit disabled. Restore 10, review again and submit
   **Compute Kondo orbitals** once. Inspect eigenvalues, units, AFM/FM signs
   and channel identities after completion.
4. Select at most two channel previews, **grid 80**, full cubes **Leave**.
   Set both **Native reference cubes · serial** and **Channel cubes and
   reduction · serial** to **2 GiB / 10 minutes**. **Review Kondo cubes** must
   describe up to two serial CalcJobs: matching initial-state reference grids
   are reused or generated first, then the selected channel cubes and reduction.
   A budget edit must invalidate review and disable Generate. Restore/review,
   submit once, and wait. A failed reference step must not launch channel cubes.
5. Compute one constant-height channel map/figure with the same plane convention
   as L08. Set **Map resources** and **Figure resources** to **2 GiB / 10
   minutes**, review each stage and submit one at a time. The busy guard must
   also reject another stage for this orbital reference after reopening the app.

**PASS:** positive charging costs are enforced, channel identities connect to
their maps, and no singlet/local-moment or NRG/resonance-width claim is invented.
No compatible AFM channel is a reportable physical outcome, not permission to
alter μ or the state set solely to obtain a brighter map.

## L10 — State-specific CASSCF and downstream reference identity

**Needs:** L06; retain the original branch for L07–L09. **Submits:** CASSCF and
its independent readback, then a small downstream CASCI request.

1. From **3. Choose energy solver**, choose **Optimize the orbitals first —
   CASSCF / SA-CASSCF**. Use the confirmed CAS(3,3), charge 0.
2. Choose **One selected state**, multiplicity **2**, **Root to optimize = 0**.
   Use **2 processes / 2 GiB / 10 minutes** and the standard 75 macro-iteration
   cap. Set **PDOS resources · serial** to **2 GiB / 10 minutes** too. Review
   must show optimization plus readback in one serial CalcJob sharing the
   ten-minute budget, followed by one serial PDOS CalcJob. Check that a PDOS
   budget edit invalidates review, restore/review and submit once.
3. Submit once and wait for optimization **and independent frozen readback**.
   Successful native termination without a passing readback is insufficient.
4. Inspect the reported state energy and optimized orbitals. One requested
   state correctly gives one energy. Record the new orbital-reference UUID.
5. Inspect/reconfirm its active space, then compute neutral doublet CASCI with
   three roots on that new reference. Keep it distinct from L07.

**PASS:** a verified new reference is created; root/charge/space are retained;
the old reference is unchanged; downstream selection cannot silently mix them.

## L11 — State-averaged CASSCF

**Needs:** L06, returning to its original prepared reference. **Submits:** one
state-average optimization/readback, distinct from L10.

1. Choose **State average (SA)** at charge 0, CAS(3,3).
2. Set one row to multiplicity **2**, **3 roots**. Add multiplicity **4**, **1 root**.
   Leave root weights blank for equal weights per individual state.
3. Review: the objective must contain **four individual states, weight 0.25 each**.
   These are orbital-optimization weights, not populations or tunnelling weights.
4. Submit with local limits. Inspect all state energies, normalized weights and
   independent per-state readback. Record the separate optimized-reference UUID.

**PASS:** every requested state is accounted for and checked. Do not treat the
average objective energy as the four-state spectrum, or replace L10 automatically.

## L12 — Correlation energies from the selected-state reference

**Needs:** verified L10 CASSCF. **Submits:** one method per subcase, serially.
Record each subcase independently. Do not substitute the L11 state average.

1. Open **Correlation energies · MP2 / NEVPT2 / CASPT2 → CASSCF → …** and select
   the verified L10 reference. Keep its geometry/charge/CAS and **Freeze chemical
   core** enabled. Match the reference's displayed correlation auxiliary model;
   do not invent or silently replace an auxiliary basis.
2. With one process, 2 GiB and ten minutes, review/submit each requested subcase:

   | Subcase | Method / extra setting | Observe |
   | --- | --- | --- |
   | L12-SC | SC-NEVPT2 | Reference, correction and total separately |
   | L12-FIC | FIC-NEVPT2 | Native acceptance checks, no Koopmans/denominator warning |
   | L12-DLPNO | DLPNO-NEVPT2, NormalPNO | Explicit PNO settings; compare to FIC, not SC |
   | L12-TIGHT | DLPNO-NEVPT2, TightPNO | A separate result, not overwritten NormalPNO |
   | L12-CASPT2 | CASPT2; real, imaginary and IPEA shifts all **0 Ha** | Native shifts, reference weights and residual checks |

3. Inspect the result table/model checks after every job. Reference plus correction
   must equal total within displayed precision; reference-readback checks must pass.
4. Return to the CAS/Dyson workspaces: these energy-only results must not become
   selectable replacements for the original state vectors/transition amplitudes.

**PASS per subcase:** explicit model and finite, validated energies with preserved
reference identity. A lower total energy does not itself establish higher accuracy.
An unexpected warning is a failure needing investigation, not a reason to add shifts.
The known rejected allyl state-average FIC pilot is documented in
[release readiness](../release-readiness.md); it is not this positive test recipe.

## L13 — Independent closed-shell formaldehyde geometry

**Needs:** L00. **Submits:** one new geometry/PDOS workflow.

Repeat L01 with SMILES **`C=O`**, expected **CH2O, 4 atoms**, PBE/def2-SVP,
charge **0**, multiplicity **1**, label `<prefix>-L13 formaldehyde`. Keep the
local limits, empty constraints and ordinary storage. Record this new optimized
reference UUID; do not continue vibrations/optics from an allyl or constrained entry.

**PASS:** correct model and converged geometry/PDOS. This is an independent
closed-shell branch, not evidence that every earlier electronic method supports it.

## L14 — IR/Raman, mode selection and animation

**Needs:** optimized L13 and local spectroscopy helpers. **Submits:** one frequency job.

1. Open **Vibrations / IR / Raman** from L13. Keep **Also compute Raman activities
   and polarizability derivatives** enabled. Review and **Compute vibrations**.
2. Inspect frequency/IR/Raman tables and warnings. A nonlinear four-atom molecule
   has **six internal vibrational modes**; do not count translations/rotations.
3. Click a spectral peak and choose a different normal mode. Verify the molecule
   animates and mode/frequency selection agree.
4. Confirm amplitude starts at **1**; change to **2**, then back to **1**.
   Old large arrows must be replaced, not accumulated. Pause/play if available.
5. Switch IR/Raman and other analysis panels, then return. Hidden animations
   should pause while selection/manual pause state remain meaningful.
6. Download one spectrum/table and verify labels and units are retained.

**PASS:** six meaningful real modes, finite spectra and usable animation.
An imaginary internal mode requires investigation; do not hide it with plot
limits or claim an equilibrium spectrum. Resonance Raman is not covered.

## L15 — TDA, optical plots and NTO hole/particle previews

**Needs:** L13 and local optical/plot/cubehandler helpers. **Submits:** response
and a selected NTO preview pair, serially.

1. Open **Optical excitations · UV–Vis**. Choose **TDA**, **3 excited roots**,
   singlet response and NTO analysis. Review fixed geometry, local limits and
   storage, then submit.
2. Inspect the state table, strengths and warnings. Optical excited roots start
   at **1**, unlike CASCI roots. Keep dark states, including a possibly dark first state.
3. Select a state by table/spectrum, change FWHM and switch **Energy (eV)** /
   **Wavelength (nm)**. Check displayed/downloaded units. Export States CSV and
   a spectrum CSV/SVG; changing a display must not submit another response job.
4. Choose one leading NTO pair for one selected singlet. Use local helpers,
   80-point grids and full cubes **Leave**. Review and **Generate hole/particle previews**.
5. Refresh NTO previews, choose **Inspect pair**, switch **Hole / Particle** and
   inspect the shared viewer. Both members must belong to the same run/state/pair.
6. Change isovalue, switch member and return. The actual value must remain
   meaningful; an empty surface at an out-of-range value is not a failed cube.

**PASS:** state identities, native NTO weights and paired previews remain linked.
NTO weights are not KS occupations. A response table alone is not a stored cube.
This generated geometry is an integration example, not the exact pyridine benchmark.

## L16 — Full TDDFT and triplet response controls

**Needs:** L13/L15. **Submits:** separate response jobs, one at a time.

1. Repeat the singlet response with **full TDDFT**, three roots and its own label.
   Inspect method identity, finite roots, strengths and convergence checks.
2. Compare to TDA at the same geometry. Different excitation energies are allowed;
   they are different approximations. Full-TDDFT NTO weights can exceed one and
   must not be normalized as probabilities.
3. If the singlet-reference triplet-response option is exposed, make a separate
   three-root request and inspect its family/root identities. Triplet NTO generation
   is unqualified in the current app and must remain blocked.

**PASS:** methods/families are distinct, forbidden NTO requests are not silently
relabelled singlets, and no CASCI/Dyson state-vector route is inferred from these results.

## L17 — Water and fresh-HF RI-MP2

**Needs:** L00. **Submits:** water geometry, then two separate correlation jobs.

1. Generate **`O`**, expected **H2O, 3 atoms**, charge 0/multiplicity 1. Optimize
   at PBE/def2-SVP using the local limits and label `<prefix>-L17 water`.
2. Open **Correlation energies → HF → RI-MP2**. Select frozen chemical core;
   review and submit with one process, 2 GiB and ten minutes.
3. Verify a **fresh converged HF reference** is reported, not the stored DFT
   energy masquerading as HF. Inspect reference/correction/total and core count.
4. Run a separately labelled no-frozen-core control. Check the policy/count and
   result remain separate; neither result supplies current Dyson amplitudes.

**PASS:** RHF identity for the singlet, explicit core policy, checked finite sums
and preserved source geometry. Do not rank methods by total energy alone.

## L18 — Ideal-simulator energy route, and honest DMRG coverage

**Needs:** L06/L07 and configured local energy/circuit/simulator/PySCF helpers.
**Submits:** export, circuits, ideal samples and sampled-space solve, serially.

1. Return to the original L06 CAS(3,3), choose **Quantum-assisted energy levels
   (simulator or QPU)**. The earlier ORCA CASCI is a comparator, not a prerequisite.
2. In the numbered stages use local workers, two CPU threads, 2 GiB, ten minutes.
   **Review Hamiltonian export → Submit reviewed stage**, matching def2-SVP/C.
   Record the exported-model identity. Export must not run a full CASCI solve.
3. Keep neutral charge 0/minimum multiplicity 2. Use evolution time **1.0 Ha⁻¹**,
   **1 circuit per time**, **2 excitation groups**, seed **42**. Review/submit circuit generation.
4. Select **Ideal QPU simulator**, **1000 shots per circuit**. Review and submit
   sampling. Do not select real IBM hardware. Inspect counts and the explicit
   simulator label.
5. Request **3 energy levels**, at most **16 strings per spin** and **1000
   determinants**. Review/submit the sampled-subspace solve and inspect residual,
   spin/sector, coverage and energy diagnostics.
6. Select **Saved ORCA comparison** from L07. If requested, run the separate
   **Optional reference: full exported Hamiltonian (PySCF)** with the same model.
   Compare only when orbital/integral/sector identities match. Selected-space
   results need not equal the full-space energies.

**PASS:** each stage is independently reviewed, model identities and limitations
are retained, and opening the route submits no QPU job. Missing configured workers
block the stage. Do not install them or move to remote hardware implicitly.

**DMRG coverage checkpoint:** inspect the offered energy-solver choices. The
current standard GUI has no general native DMRG submission path. Record
`L18-DMRG = BLOCKED (GUI route not exposed)` rather than running a backend
WorkChain from Python. Existing DMRG calculations/native tests remain separate
evidence; see [DMRG checkpoint rules](../dmrg.md). The neutral allyl example is
odd-electron and is outside the current native DMRG singlet recipe. Do not relabel
it a singlet. A future GUI case needs an explicitly supported singlet test model.

## L19 — Forced output summary, storage and durable reopening

**Needs:** L01/L03. **Submits:** one separate SCF storage control.

1. Start from L01's final geometry, disable optimization, preserve PBE/def2-SVP,
   charge 0/multiplicity 2. Set label `<prefix>-L19 forced summary`.
2. Keep full electronic files **Leave on the calculation computer**. Set
   **Output retrieval → maxsizeoutput (MiB) = 0** and enable recomputation for
   this control. Review the effective settings and submit once.
3. Inspect the result notice: the usual output is a notice, the summary is a
   separate file, and the original full output remains external. Parsed energies,
   levels and complete PDOS projections must remain available.
4. Compare the energy at the identical final geometry with L03. Record any
   difference for maintainer checking; do not change the tolerance or hide warnings.
5. Restore the draft threshold to **5 MiB**. Close/reopen the app, search the
   L01/L03/L19 labels, and reopen stored plots/previews by UUID. Check that no
   background scientific calculation was submitted merely by reopening.

**PASS:** the summary is explicit and the scientific results remain usable.
Maintainer read-only checks verify byte preservation for ordinary output,
summary manifests, native parser results and absence of full electronic/cube
files in retrieved. Browser-only operators must not claim repository inspection
if that information is not exposed in their UI.

**L19-STASH, optional local storage control:** repeat the fixed-geometry SCF
control once with **Stash on the calculation computer**, an approved local stash
directory and threshold **5 MiB**. Record the selected directory and stored
retention information. A maintainer verifies the stash identity/content without
retrieving full files into AiiDA. Never remove or overwrite an existing stash
to manufacture a recovery test. Restore ordinary draft settings afterward.
