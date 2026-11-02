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

Preparation reads the saved wavefunction without SCF iterations. A new orbital
reference has a new identity; existing CASCI states remain tied to their
original reference. If the reference already exists, reuse it. Click
**Next: inspect / select active orbitals** when it is available.

## 2. Inspect and confirm the active space

Choose **2. Inspect / confirm active space**. **Read orbital information**
explicitly submits a metadata-export job when no reusable catalog exists.
Inspect orbital occupations and, when useful, request orbital-shape previews.
See [the inspection guide](orbital-inspection.md) for those controls.

Select a contiguous orbital window and use its selection button, or enter the
active electron/orbital counts and click **Confirm this active space**.
The app validates the inactive/active partition and records your confirmation
for that exact orbital reference and active space. Editing draft counts alone
does not change the confirmed CAS input. Changing the reference requires a
new confirmation unless compatible saved CASCI states already define it.

The current GUI supports contiguous windows in the prepared orbital ordering.
UNO inspection is diagnostic: it does not switch the CAS input from QROs to
UNOs, and equal QRO/UNO indices do not identify the same orbital. Correlated
natural-orbital preparation, general orbital reordering and orbital-optimized
CASSCF need separate implementations; they are not implicit options here.

## 3. Request CASCI states and multiplicities

After confirmation, choose charge, multiplicity and the number of electronic
states for each request. Repeat for the spin/charge sectors needed by your
goal, keeping the same orbital reference and active space. The number of
available states depends on that space and multiplicity. Read the generated
input and reuse/new-calculation decision before submission.

CASCI keeps orbitals fixed; CASSCF would optimize them. The current general
app path implements CASCI. [The CASCI guide](casci.md) details its validation,
state counts, resources and common energy reference.

## 4–5. Continue to Dyson and Kondo

Dyson transitions require compatible initial and N±1 final CASCI states.
Kondo channels additionally require a suitable spin-pure local moment and
valid charging costs at the chosen chemical potential. Missing stages offer
explicit actions; the app does not substitute a different spin or compute
extra sectors silently. Cubes, maps and figures are separate optional stages.
See [Dyson](dyson.md) and [Kondo](kondo.md) for their scientific conventions.
