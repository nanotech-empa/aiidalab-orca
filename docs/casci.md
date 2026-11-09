# Fixed-geometry CASCI states (draft)

This milestone adds common spatial-orbital preparation and independent CASCI
charge/spin calculations. It does not optimize atomic positions or CAS orbitals.
It is a pipeline prototype, not a validated spectroscopy protocol.

Open a completed SCF/geometry calculation, then choose
the preparation and active-space stages described in
[the guided CAS workflow](cas-workflow.md). **3. CASCI states and multiplicities**
is available once the orbital reference and active space are established:

1. Review and prepare common orbitals. Restricted SCF orbitals are read without
   iteration; unrestricted orbitals are converted to QROs with ORCA's `UNO`
   procedure. The input explicitly sets `%scf MaxIter 0` because an inherited
   nonzero limit overrides `NoIter`. The parser requires ORCA's confirmation
   that SCF was skipped, that the geometry/basis match, and (for unrestricted
   input) that a QRO file was written.
2. Inspect and explicitly confirm the active electron count **in the reference charge state** and the
   number of spatial orbitals. Review the displayed zero-based ORCA indices.
   The initial small values are illustrative and must be chosen for the molecule.
   [Inspect QRO/UNO orbitals](orbital-inspection.md) to examine their shapes and
   occupations; selected contiguous QRO windows can be transferred to the CASCI controls.
3. Enter one or more **Charges** and **Multiplicities (2S+1)**, separated by
   spaces or commas, and choose **Electronic states** per allowed sector.
   Review the charge/spin combinations and inputs, then submit the reviewed
   calculations. Each allowed pair is a separate WorkChain. A change of charge
   adjusts active electrons while preserving the exact same inactive and active
   orbital indices. See the batch rules below.
4. Inspect all compatible completed sectors in the common energy diagram.
   Choose the energy-zero state and plot limits. The collapsed **Calculation
   history and status** section below the diagram inspects individual runs;
   its charge/calculation selectors do not filter the plotted energies or
   change submission settings. JSON export includes unshifted energies,
   state identities, model settings and workflow UUIDs.

The reference is associated with the existing SCF result. Geometry optimization
may have used a different method earlier, but all compared CASCI states use the
same final fixed geometry and common orbitals.

Orbital preparation inherits the original SCF's ORCA code, computer, process
count, memory and wall-time limit. The preparation panel displays those actual
settings. Saved remote/stashed wavefunctions are accessed on that computer.
In the compact-output candidate, the preparation's **Full files** control
chooses remote retention or an explicit stash destination for the full native
log and prepared QRO/UNO (or restricted GBW) files. Only a bounded validation
summary, a 64-KiB diagnostic tail and a checksum manifest are retrieved.
Inspecting the catalog or generating previews inherits that orbital-file
policy; neither operation silently applies an old wavefunction retrieval
threshold. Full cubes retain their separate stash/leave/delete choice, with
only cubehandler-reduced previews retrieved. Reusing older results preserves
their recorded policy. Changing retention invalidates preparation review.

CASCI uses the orbital reference's computer and displays the execution target
in its review. Edit CASCI processes, memory and wall time in **CASCI resources
and advanced settings** before reviewing a new request.

**Common orbitals** are the shared spatial-orbital basis, not electronic states.
An electronic state from the CASCI calculation is also called a **root**.
Requesting one state gives the lowest-energy CASCI state in the selected
charge/spin sector; requesting two also gives the next state. This count is
independent of the number of active orbitals.

## Request several charge/spin sectors

For example, enter charges `0 +1 -1 +2 -2` and multiplicities `1 2 3 4`.
Charges are **absolute molecular charges**, not changes from the selected
reference. Positive charge removes electrons. With reference charge q₀ and
reference active electron count n₀, a sector at charge q has n₀ − (q − q₀)
active electrons. The spatial orbital reference and inactive partition stay fixed.

The review table lists the Cartesian product, including skipped pairs and their
reasons. An even electron count requires odd multiplicity; an odd count requires
even multiplicity. The active-space capacity also limits the spin. No different
spin is silently substituted. Charges beyond N±1 are allowed when they fit the
same active space. This does not change Dyson's one-electron N±1 selection rule.

**Electronic states** is a per-sector request. If a valid sector has fewer
spin-adapted states, the table explicitly proposes its available count beside
the requested count. Confirm that reduction before submission. Saved matching
calculations are reused, and matching running requests are not submitted again
unless explicit recomputation was selected. Missing wavefunctions, invalid
resources and other execution errors block the batch rather than masquerading
as forbidden spin combinations.

The summary includes each generated ORCA input, job count and per-job resources.
The reviewed sectors run sequentially in a persistent AiiDA batch, one at a time.
Each waits for the previous workflow and its CalcJobs to terminate, including
failed sectors; the queue continues after closing the browser. Submission starts only after the reviewed action is
clicked. If one submission fails, the remaining requests stop; accepted UUIDs
remain visible and those calculations continue. Closing the page stops its
status polling, not the AiiDA calculations. Browsing saved charges/calculations
does not overwrite the draft request lists or confirmed active space.
History browsing also preserves the diagram's selected energy zero and limits.

## Components and provenance

- `empa_orca.common_orbitals`: a WorkChain with a separate ORCA preparation
  CalcJob and electronic-file preservation CalcJob. It reuses a validated
  preparation associated with the same SCF output and ORCA code.
- `empa_orca.casci`: one charge, one multiplicity and the requested roots. The
  CalcJob reads the prepared spatial orbitals, runs one CASCI macro iteration,
  and keeps internal, active and external orbitals unchanged. The parser
  requires these settings to be confirmed in ORCA output.
- `empa_orca.electronic_storage`: supports explicit file bundles. Existing
  SCF/geometry callers retain their original GBW/density bundle. Common orbitals
  preserve QRO and UNO files together, or the restricted GBW. New CASCI requests
  instead have an explicit **Full files** choice: leave the native log/GBW on the
  calculation computer, or stash them at the reviewed directory. CASCI GBWs are
  not retrieved; the stash route uses the storage CalcJob with a zero threshold.

CASCI uses the electronic Hamiltonian in the prepared orbital basis; the DFT
functional is not a CASCI Hamiltonian keyword. The source basis and element
basis overrides are retained. RI integral transformation uses the selected
correlation auxiliary basis, with def2-SVP/C, def2-TZVP/C or def2-TZVPP/C
suggested for those matching orbital bases. Other bases initially suggest
AutoAux; this is editable and requires scientific review.

`state_energies` contains each root's total energy in Hartree, charge,
multiplicity, root number, common-orbital reference UUID, geometry UUID, exact
active-orbital indices, active electron count and RI auxiliary-basis model.
The final state-averaged ORCA energy is **not** used as an individual root energy.
New CASCI output is collected on the calculation computer by the configured
`orca-tools` runtime. A compact `aiida.out`, a 64-KiB diagnostic tail and
`native_output.json` are retrieved. The summary budget is 2 MiB; exceeding it
rejects collection rather than accepting a truncated state table. All matching
validation markers, including late warnings and repeated blocks, are retained.
The full log remains at `native_output/aiida.out`; its size/checksum and the
reviewed remote/stash policy are saved in `native_output_manifest`. Native
property output is retained in the same directory. The
printing threshold is recorded and is not a guarantee that truncated CI data
will be sufficiently accurate for a later Dyson calculation.

All file staging, preparation, CASCI and preservation run through CalcJobs.
The viewer performs only lightweight data queries and plotting. It retains
plain data and UUIDs, not ORM nodes. No Python executable is selected in the UI.

## Reuse and missing files

Reuse is explicit and independent of AiiDA caching. A matching completed CASCI
calculation can supply its durable state energies even after scratch is gone.
Historical records with full retrieved output remain readable without migration.
A later Dyson consumer must separately verify the full CI log and binary/JSON
files it requires; a visible energy diagram does not promise those files exist.

New GUI submissions require an ORCA tools runtime supporting `compact_output.py`.
Computer/code/runtime configuration belongs to `aiidalab-empa-setup`. No Python
selector or PythonJob is introduced. Retention edits invalidate the reviewed
request; reused/running calculations keep their original retention policy.

A new charge/spin sector requires the original common orbitals. The resolver
checks retrieved storage, native AiiDA stash, and the calculation directory.
Repository copies are checked against stored sizes and SHA-256 checksums;
remote/stashed paths are checked for regular nonempty files and expected size.
The native stash is a separate copy, not an immutable content-addressed store.

Missing common orbitals can be prepared again from the saved SCF wavefunction,
with an explicit new orbital-reference identity. New and old sectors are never
silently combined across those identities. If both the common orbitals and the
SCF wavefunction are lost, this draft stops and asks for a new SCF/reference
instead of automatically launching an expensive replacement. Inaccessible
storage is reported as unavailable, not as deleted.

Real artifact-producing jobs use `metadata.disable_cache=True`; explicit reuse
handles existing valid results. The **Recompute this CASCI sector** control
skips reuse for that sector. No timestamp enters the scientific input.

## Energy conventions

For a selected state with total energy E_ref, every displayed level uses
`(E_state − E_ref) × 27.211386245988` eV. The default zero is the lowest computed
state at the reference charge (it is not assumed to be the true ground state
if important multiplicities or roots have not been calculated). No multiplicity
or charge sector is independently zeroed. Comparisons require the same geometry,
common orbitals, active space and CASCI integral model.

The diagram is a **total many-electron state-energy diagram**, not the signed
Dyson transition spectrum. Later spectral poles will use E_N − E_(N−1) for
removal and E_(N+1) − E_N for addition. Fermi-level alignment is not inferred
from an isolated molecule.

## Current boundaries and next steps

- One contiguous active-orbital window in the common reference ordering.
  QRO/UNO inspection is available; arbitrary orbital selection/reordering needs
  a further preparation component. Do not infer a physically appropriate active space
  from CAS(n,m) alone.
- All-electron molecules through Kr; explicit or detected ECP electron-count
  changes are rejected pending core-electron accounting.
- One spin multiplicity per small WorkChain, with the reference charge and
  its N±1 neighbours. Requested roots are checked against the spin-sector
  dimension. These are spin-free states; SOC is not included.
- Exact request reuse; extending the root count runs a new calculation for
  that sector. There is no monolithic all-charge workflow.
- Local ORCA 6.1.1 integration is tested; tigu deployment remains separate.
- [Dyson transitions, wavefunction export, spectra and intensity blends](dyson.md)
  are now separate components. Optional [CASSCF orbital optimization](casscf.md)
  supplies a new shared natural-orbital reference; a quantitative STM model
  remains a separate validation task.

The input follows the fixed-orbital CASCI strategy in Andrés's supplied
`setup_dyson.sh`, with explicit provenance and storage. See the
[ORCA CASSCF/CASCI documentation](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html)
and [dyson-orca-tools](https://github.com/AndresOrtegaGuerrero/dyson-orca-tools).
Pentacene remains the spectroscopy benchmark target; the small NO/ethylene
runs validate execution and data handling, not reproduction of its spectrum.

## Validation of this draft

Tested locally with Python 3.12.11, AiiDA 2.9.2, AiiDAlab 26.9.0 and ORCA 6.1.1
ARM64. The automated suite contains 102 passing tests, including active-space
and root-count validation, rejection of unexpected SCF/orbital optimization,
per-root parsing, shared energy-zero signs, compatibility rejection, file staging,
explicit bundle preservation, and reuse with caching both enabled and disabled.

A fixed-geometry NO test used QROs from the saved PBE/def2-SVP reference and a
three-orbital space with three electrons at neutral charge. Independent runs
produced three neutral doublets, one neutral quartet, three cation singlets,
two cation triplets, three anion singlets and two anion triplets. All 14 energies
were read from individual roots. Repeated common-orbital and CASCI requests
returned existing data without calculation children. A browser test reopened
all six sectors and changed the common zero to a neutral quartet.

A separate browser test started from saved restricted PBE/def2-SVP ethylene,
prepared common orbitals and submitted CASCI(2,2) with three singlet roots
through the app and daemon. It displayed the results and then offered explicit
reuse of the same request. These tests establish pipeline behavior; neither
small active space is presented as a converged molecular spectrum.
