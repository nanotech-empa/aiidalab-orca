# Fixed-geometry CASCI states (draft)

This milestone adds common spatial-orbital preparation and independent CASCI
charge/spin calculations. It does not optimize atomic positions or CAS orbitals.
It is a pipeline prototype, not a validated spectroscopy protocol.

Open a completed SCF/geometry calculation, then expand **CASCI states · fixed
geometry (draft)** in Results:

1. Review and prepare common orbitals. Restricted SCF orbitals are read without
   iteration; unrestricted orbitals are converted to QROs with ORCA's `UNO`
   procedure. The input explicitly sets `%scf MaxIter 0` because an inherited
   nonzero limit overrides `NoIter`. The parser requires ORCA's confirmation
   that SCF was skipped, that the geometry/basis match, and (for unrestricted
   input) that a QRO file was written.
2. Select the active electron count **in the reference charge state** and the
   number of spatial orbitals. Review the displayed zero-based ORCA indices.
   The initial small values are illustrative and must be chosen for the molecule.
   [Inspect QRO/UNO orbitals](orbital-inspection.md) to examine their shapes and
   occupations; selected contiguous QRO windows can be transferred to the CASCI controls.
3. Select charge, multiplicity and number of roots, review the generated input,
   and submit. Repeat for additional charge/spin sectors. Each is a separate
   WorkChain. A change of charge adjusts active electrons while preserving the
   exact same inactive and active orbital indices.
4. Inspect all compatible completed sectors in the common energy diagram.
   Choose the energy-zero state and plot limits. The calculation selector
   reopens previous active spaces; JSON export includes unshifted energies,
   state identities, model settings and workflow UUIDs.

The reference is associated with the existing SCF result. Geometry optimization
may have used a different method earlier, but all compared CASCI states use the
same final fixed geometry and common orbitals.

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
  preserve QRO and UNO files together, or the restricted GBW; CASCI preserves its output GBW. The
  threshold and stash directory are inherited from the SCF preservation policy.

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
Full output including printed determinant coefficients is retrieved. The
printing threshold is recorded and is not a guarantee that truncated CI data
will be sufficiently accurate for a later Dyson calculation.

All file staging, preparation, CASCI and preservation run through CalcJobs.
The viewer performs only lightweight data queries and plotting. It retains
plain data and UUIDs, not ORM nodes. No Python executable is selected in the UI.

## Reuse and missing files

Reuse is explicit and independent of AiiDA caching. A matching completed CASCI
calculation can supply its durable state energies and CI output even after
scratch is gone. A later Dyson consumer must separately verify the binary/JSON
files it requires; a visible energy diagram does not promise those files exist.

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
  are now separate components. CASSCF orbital optimization, correlated-state
  natural-orbital analysis and the quantitative STM map model remain future work.

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

### Numerical CI controls

The backend and submission service accept optional `ci_solver` (`CSFCI` or
`ACCCI`), `ci_maxiter` and `ci_maxdim` settings. Omitting them preserves the
existing ORCA defaults and input text. Explicit values are saved in the AiiDA
settings and rendered in `%casscf` / its `ci` block. The outer CASCI macro-step
remains fixed at one, every orbital subspace stays unchanged, and CI energy and
residual convergence tolerances are not relaxed. These controls do not change
the active space or the Hamiltonian and do not enable automatic retries.

The app exposes these settings under **CASCI resources and advanced settings**.
Leave either limit blank to use the ORCA default, or enter a positive integer
such as 256 for the CI iteration ceiling. Opening a saved calculation restores
its explicit solver and limits, so reviewing it preserves its request and reuse
identity. Changing a control invalidates the earlier review before submission.
ACCCI is shown as validation pending and cannot be submitted from the GUI until
its native wavefunction export has been validated; the backend remains available
for explicit solver-validation calculations.

`MaxDim` multiplies the number of roots to set the Davidson expansion space;
increasing it can increase memory. Validate a solver change before applying it
to a large calculation, and keep the resource budget explicit. See the
[ORCA CI solver documentation](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html#ci-solvers-csfci-accci-ice).

The optional CI comparison CalcJob checks two preserved native exports in the
same orbital basis. It compares raw CI norms, energies and projectors of
degenerate-state groups without renormalizing coefficients or fitting orbital
phases. The report is stored as an AiiDA output linked to both exports.
