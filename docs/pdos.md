# PDOS and orbital character (draft)

Open a completed SCF/geometry result and choose **PDOS & orbital character**
from **Analysis / results**, or the matching tab under **Orbitals & density**.
Prepared QROs, UNOs and restricted spatial orbitals expose the same panel under
**Inspect / confirm active space → PDOS & orbital character**.

## Included by default for new calculations

New SCF/geometry workflows compute orbital character after the converged electronic
reference. New common-orbital preparations do the same for each prepared QRO/UNO
or restricted set. This is a child CalcJob managed by the workflow and continues
when the notebook is closed. The SCF submission's **Compute PDOS / orbital
character** option is checked initially; **PDOS resources** exposes its independent
memory and **PDOS wall time (minutes)**. Defaults remain one process, 30 minutes
and 8 GiB; time is editable from one minute. The main ORCA wall time is separate.
Review shows the selected PDOS limit and changing it invalidates the review;
the parent records it as `character_wallclock_seconds` and passes it to the
analysis CalcJob's `max_wallclock_seconds`. Explicit analysis from **Codes and
recomputation** also has an **Analysis wall time (minutes)** control. Python is
not a user selection.

Only new computations trigger this default. Reusing a reference or opening an
old result never backfills analysis or resubmits SCF. There is no migration of
historical calculations. Inspect already stored character directly, or request
analysis explicitly when needed. An unavailable worker/exporter or failed
projection leaves the valid electronic results intact and records a visible
PDOS status; configure the tools or retry **only** the postprocessing.

## One analysis, then interactive inspection

For an explicit analysis or retry, **Compute / retry orbital character** submits native `orca_2json` and the compact
projection worker in one CalcJob on the wavefunction's computer. It performs
no SCF, orbital rotation or occupation change. Users do not select Python.
Native export and a configured single-purpose character worker are selected
under **Codes and recomputation**. Default resources are one process, 30 minutes
and an 8 GiB memory request. A conservative file-size guard checks the memory
budget before decoding the full export. Increase **Analysis memory (GiB)** for
a larger basis. The dense implementation currently supports up to 6000 AOs;
it rejects unsupported dimensions instead of truncating. This is not a
large-basis performance qualification or a hard-memory-limit guarantee on a
scheduler that cannot enforce one.

Only compact atomic/angular weights, directional p tensors and metadata are
retrieved. The original GBW/QRO/UNO remains at its existing storage location.
The worker removes only its expendable staging copy and temporary full JSON.
Stored character remains readable without SSH or the original GBW. There is
no implicit wavefunction regeneration or new stashing policy.

The standard structure viewer links atom selection to the projections. Click
atoms in 3D or enter one-based atom numbers/ranges such as **1 3..5** and apply
the selection. Selecting an element updates the same atoms; mixed selections
are labelled **Custom atoms**. Two selected atoms show a distance, three an
angle and four a dihedral. Atom numbers start at **1**; ORCA orbital indices
remain **0-based**. Alpha/beta total DOS curves use dashed blue/red lines,
matching the corresponding spin colours in every projection mode. In the angular
view, line patterns distinguish the contributions: s is dotted, p is solid and
d is dash-dot, with additional distinct patterns for higher angular momenta.
Legend samples use the same patterns as the plotted curves.

Choose a projection:

- **Atoms / fragment**: the selected atoms' contribution alongside the total.
- **s / p / d character**: angular contributions, including higher angular
  momenta when present in the basis.
- **Perpendicular p · π-like**: p character normal to the chosen plane.

The initial energy range is HOMO − 1 eV to LUMO + 1 eV, with 0.01 eV input
precision. Gaussian FWHM is a display choice. Occupied and virtual orbitals
both count in the DOS: occupations do not weight a state DOS. A restricted
spatial orbital counts once, rather than twice for its two spin occupations.
UKS alpha/beta channels remain separate. QRO energies are explicitly reference
labels. UNO inspection uses occupations versus orbital index, initially near
fractional occupations; it does not fabricate a KS-energy axis.

Click an orbital mark or select multiple **Orbital candidates**. The table gives
the largest atomic contributions, with atom numbers matching the geometry
viewer. **Inspect selected orbital shapes** forwards the exact indices/spins
to the existing cube/inspection controls. Reduced previews retain the existing
cubehandler pipeline, review and full-cube storage choices. Selection does not
automatically submit cubes or CASCI. CAS preparation remains responsible for
validating and applying candidates; PDOS does not simulate reordering by
renaming indices. Existing research permutation workflows remain separate.

The CSV contains every orbital's selected-fragment angular weights and
perpendicular p contribution. View JSON records the CalcJob/array UUIDs,
selected atoms, plane normal, range and display broadening.

Geometry input and the result overview use the same shared structure viewer.
The overview starts with the exact stored final coordinates and can inspect
individual optimization frames with the same measurements and selected atoms.
**Optimization trajectory** retains separate, lazily loaded playback controls;
leaving playback pauses it. Frame inspection never changes the geometry used
for PDOS or a subsequent calculation.

## Scientific convention and checks

For each real native coefficient block C and AO overlap S, form
`Q = S^(1/2) C` with the symmetric positive-definite square root. Atom/angular
weight for orbital i is the sum of `Q[mu,i]^2` in that native AO-label group.
Require finite symmetric positive-definite S, matching dimensions and
`max(abs(C.T S C − I)) <= 1e−7`, with no overlap regularization. Each complete
partition must sum to one. Occupations must reproduce the electron count;
UKS blocks also reproduce the requested spin projection. Native ORCA 6.1's
repeated alpha/beta AO-label blocks are accepted only when identical.
File hashes, geometry, atom order, charge and multiplicity must match the
request. The parser independently checks compact shapes, partitions, orbital
identities and directional tensor traces. ECP and unsupported formats stop.

For each atom and radial p shell, the worker retains the real x/y/z outer
product. Summed tensors give `n.T P n` for an arbitrary normalized normal,
without another export. The initial normal fits the molecular plane. Linear
geometries explicitly have no unique plane; nonplanar molecules require the
user to assess the fit and choose a useful normal.

This is perpendicular **p** character, not a complete π/σ symmetry assignment.
Metal dπ contributions and mixed orbitals need chemical interpretation.
Löwdin weights depend on the basis and partition. Inspect occupations,
symmetry, bonding character and orbital shapes together before choosing CAS.

## Deployment and qualification

The helper requires NumPy on the native export's computer. After a reviewed
localhost installation, `python scripts/register_character_worker.py` creates
an immutable wrapper and dedicated Code, preserving existing ORCA-tools and
quantum workers. A remote deployment must use a qualified existing NumPy
runtime and Code role `aiidalab_orca_role=orbital_character`; the registration
script refuses to guess a remote interpreter. The CalcJob supports queued
execution, but tigu is not yet qualified for this draft.

Native ORCA 6.1.1 Linux ARM64 checks exported existing NO UKS, methane
restricted, and phenalenyl QRO/UNO files in isolated AiiDA test storage. No SCF
or geometry was repeated. Reconstructed NO atomic charges/spin populations
agree with the printed native Löwdin table within 3.7e−7 electrons. These checks
qualify the tested exports and convention, not large-system performance or
CAS quality. A separate browser review uses those snapshots; it is not proof
of installation into the shared app or submission through the deployed GUI.

An additional opt-in test creates a fresh **allyl radical, C3H5, neutral doublet**
at PBE/def2-SVP and follows geometry optimization → automatic SCF character →
QRO/UNO preparation with automatic character → three doublet CAS(3,3) roots.
The QRO window (zero-based indices 10–12) is accepted only after all three
orbitals have dominant perpendicular-carbon-p character. The native test uses
one process per CalcJob and retains its AiiDA archive on request. This exercises
the new default on purpose-made data, without modifying historical results.
It validates the data flow and an interpretable small active space, not the
quantitative accuracy of this molecular protocol.

References: [ORCA JSON export](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/orca_2json.html),
[ORCA population analysis](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/population.html).
