# From an SCF reference to CASCI, Dyson and Kondo

Choose the final **Calculation goal** in **New calculation**. Prepare a new
molecular reference in that wizard, or explicitly **Open an existing reference
instead**. The same procedure applies to any supported molecule; an example
active space is never a validated default for another system.

For these electronic-analysis goals the path is:

**SCF reference → orbital reference → inspect/confirm the active space → CASCI
states → Dyson transitions → Kondo channels**, stopping at the chosen goal.

The goal remains visible. **Continue to…** opens the next required stage using
available results. Navigation and active-space confirmation submit no jobs.
Each actual preparation or scientific calculation has an explicit action.

## 1. Prepare the orbital reference

In **Results → Analysis / results → 1. Prepare orbital reference**, review the
preparation, then prepare or reuse the common spatial-orbital reference.

| Starting point | Current preparation and CAS input |
| --- | --- |
| Restricted SCF | Retain its restricted spatial orbitals; no QRO conversion is necessary |
| Unrestricted SCF | Generate/preserve QROs for the shared CAS input and UNOs for inspection |
| Verified imported reference | Reuse its fixed spatial orbitals and recorded provenance |

Preparation reads the saved wavefunction without SCF iterations. It
inherits the SCF calculation's ORCA code, computer and resource
limits; its execution summary shows these settings. Remote/stashed wavefunctions
are accessed on that computer. **Prepared-orbital PDOS resources** separately
controls memory and wall time for automatic orbital-character analysis
(initially 2 GiB and 10 minutes per serial CalcJob). For unrestricted references,
QRO analysis completes before UNO analysis starts. The preparation review
shows those limits; budget edits require a new review. Subsequent CASCI keeps the orbital reference's
computer, while its processes, memory and wall time are editable under
**CASCI resources and advanced settings**.

A new orbital reference has a new identity; existing CASCI states remain tied to their
original reference. If the reference already exists, reuse it. Click
**View orbitals and choose active space** beneath the preparation controls when
it is available. The selected common-orbital reference is the input file set;
the next stage provides its orbital list and visualizations.

## 2. Inspect and confirm the active space

Choose **2. Inspect / confirm active space**. Set the catalog memory and wall
time, then **Review orbital information → Read orbital information**
explicitly submits a metadata-export job when no reusable catalog exists.
Inspect orbital occupations and, when useful, request orbital-shape previews.
See [the inspection guide](orbital-inspection.md) for those controls.
The primary actions are visible: **Read orbital information**, select orbitals,
**Review orbital visualization**, then **Generate orbital previews**. Once the
job finishes, choose **Orbital to display** to view an orbital's shape.

The **Orbital indices** field and highlighted list are synchronized. Enter
zero-based indices separated by spaces or commas, with inclusive ranges such
as `1 3..10 14, 18..21`. Arbitrary selections can generate previews; selecting
them does not itself change the CAS or submit a job.

Select a contiguous orbital window and use its selection button, or enter the
active electron/orbital counts and click **Confirm this active space**.
The app validates the inactive/active partition and records your confirmation
for that exact orbital reference and active space. Editing draft counts alone
does not change the confirmed CAS input. Changing the reference requires a
new confirmation unless compatible saved CASCI states already define it.

The current GUI supports contiguous windows in the prepared orbital ordering.
UNO inspection is diagnostic: it does not switch the CAS input from QROs to
UNOs, and equal QRO/UNO indices do not identify the same orbital. Optional
[CASSCF orbital optimization](casscf.md) produces a separate reference with
correlated natural occupations. Inspect and confirm that new reference before
continuing; no orbital permutation or optimization happens implicitly.

## 3. Choose the solver and request states

**3. Choose energy solver** offers fixed-orbital ORCA CASCI, optional
[CASSCF / SA-CASSCF orbital optimization](casscf.md), or the
[quantum-assisted energy route](quantum-energy.md). CASSCF creates a new
verified reference: inspect and confirm it before requesting CASCI sectors or
exporting its Hamiltonian. The Dyson/Kondo goal retains the compatible ORCA
state-vector route.

For dynamical-correlation energies, use the separate
[Correlation energies](correlation.md) workspace after verified CASSCF.
NEVPT2/CASPT2 results do not feed the current Dyson/Kondo amplitudes.

For ORCA CASCI after confirmation, enter one charge/multiplicity or lists such as charges
`0 +1 -1 +2 -2` and multiplicities `1 2 3 4` (spaces or commas). Charges are
absolute molecular charges. Set **Electronic states** per allowed sector.
**Review charge / spin combinations** lists every pair, active electron count,
requested/available states, new/reused/running action and any skip/block reason.
Impossible spin pairs are skipped; execution errors block submission. A smaller
valid sector proposes its available state count explicitly. Read the inputs and
per-job resources, then **Submit reviewed calculations**. Each allowed pair is
independent and keeps the same orbital reference and active orbital partition.
The energy diagram shows all compatible completed sectors. **Calculation
history and status** is collapsed below it; its charge/calculation selectors
inspect individual runs without filtering the diagram, changing its energy
zero/limits, or editing the submission lists.
See [the batch rules](casci.md#request-several-chargespin-sectors).

CASCI keeps orbitals fixed; optional CASSCF optimizes a new shared orbital
reference first. [The CASCI guide](casci.md) details its validation,
state counts, resources and common energy reference.

## 4–5. Continue to Dyson and Kondo

Dyson transitions require compatible initial and N±1 final CASCI states.
Kondo channels additionally require a suitable spin-pure local moment and
valid charging costs at the chosen chemical potential. Missing stages offer
explicit actions; the app does not substitute a different spin or compute
extra sectors silently. Cubes, maps and figures are separate optional stages.
See [Dyson](dyson.md) and [Kondo](kondo.md) for their scientific conventions.
