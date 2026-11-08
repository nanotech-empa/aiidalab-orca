# ORCA app: an agent's route from a molecule to results

Guide ID: `orca.app`. Read this first, then `orca.casci-kondo` for electronic
analysis or `orca.vibrations` for IR/Raman. These are application-owned guides,
versioned with [the ORCA app](https://github.com/nanotech-empa/aiidalab-orca).
The installed guides and current tool schemas describe the user's instance;
a manual page or another Git branch does not prove an app feature is available.

## Establish the goal and current state

Ask whether the user wants geometry/SCF, ordinary orbitals, CASCI, Dyson,
Kondo, or IR/Raman. In **New calculation**, choose **Calculation goal** first.
Use **Open an existing reference instead** to find completed work in **Search
calculations → View results**. **Results → Analysis / results** selects one
workspace; there is no need to prepare CASCI for ordinary orbitals or IR/Raman.

Read the selected workflow UUID, type, date, settings, status and available
outputs before explaining that result. **Converged** on a stored SCF means
electronic convergence. It does not imply an optimization, a vibrational minimum
or that anything ran when the user opened the page. A waiting AiiDA process can
be monitoring a running scheduler job or transferring files. Inspect its actual
status/report before diagnosing a stall or starting a duplicate calculation.

Navigation and review do not submit simulations. The app's explicit **Submit**
or **Compute…** actions do. Reading history must not trigger another calculation.

## 1. Prepare a molecule, geometry optimization or single-point SCF

Use File/XYZ, SMILES, CDXML or a saved AiiDA structure. Imported/conformer-built
coordinates are starting structures, not evidence of quantum optimization.
Inspect connectivity, hydrogens, stereochemistry, formal charge and open shells.
For a genuinely new molecule, respect a request to skip historical searches.

Confirm structure, then review method, basis, charge, multiplicity and the
**Optimize geometry** choice. Method and basis accept typed ORCA names; the
suggestion list is not the complete library. Starting protocols are editable
examples. Validate orbital and auxiliary bases/element overrides rather than
assuming a typed name is supported for every element.

Multiplicity is `2S+1`. Its lowest-allowed initial value follows electron parity,
not a prediction of the ground state. Let the user choose and justify other
allowed values. There is no automatic-multiplicity checkbox in the current
preview. In Resources, review code/computer, process count, wall time, memory
and electronic-file retention. Memory displays GiB; the chat/API field
`memory_mb` remains integer MiB: 2 GiB = 2048 MiB.

**Optimize geometry** moves atoms; single-point SCF holds supplied coordinates
fixed. SCF and geometry convergence are separate. Inspect native optimization
convergence and any constraints; normal program termination alone is insufficient.
Opening existing results, copying settings and using coordinates are different
actions. Editing a new draft never changes a stored reference or its settings.

## 2. Ordinary orbitals, or preparation for CASCI

For DFT orbitals/density, open **Orbitals & density**. A listed orbital is not
necessarily a stored cube: select it, review the visualization request and
generate a preview if absent. Cubes are additional calculations, not new SCF
optimizations. Full numerical cubes and reduced interactive previews have
different roles and retention policies.

For CASCI/Dyson/Kondo follow **1. Prepare orbital reference → 2. Inspect / confirm
active space → 3. Choose energy solver → ORCA CASCI states and multiplicities**.
Restricted references retain
restricted spatial orbitals. Unrestricted references provide QROs for the
current general CASCI input and spin-summed UNOs for inspection. UNO occupations
lie between 0 and 2; UNOs are not separate alpha/beta lists. A restricted
single determinant alone cannot supply correlated fractional natural occupations.
Theoretical suitability of UNOs as a CAS starting basis does not mean this GUI
currently exposes that input route. Optional **Optimize orbitals · CASSCF**
does provide correlated natural orbitals from a selected state or state average;
it creates a new reference, not a conversion of the original SCF density.
Do not promise arbitrary orbital reordering.

Use **View orbitals and choose active space**, read orbital information and
inspect occupations/shapes. Zero-based orbital indices accept spaces, commas
and inclusive ranges such as `1 3..10 14,18`. Highlighting and typed selection
are synchronized. Preview selection does not itself confirm the CAS. General
CASCI currently needs its supported contiguous window and explicit electron/
orbital confirmation; a QPU-specific permutation is not that general interface.
Small initial CAS values are examples, not validated choices for the molecule.

## 3. CASCI states and charge/spin batches

After active-space confirmation, **3. Choose energy solver** offers fixed-orbital
CASCI, optional CASSCF orbital optimization, or quantum-assisted energies.
For a Dyson/Kondo goal, only the compatible ORCA state-vector route is offered.
CASSCF can optimize one root, or average explicitly weighted roots and
multiplicities at one charge and geometry. The review lists normalized
optimization weights; they are unrelated to populations or spectral weights.
Successful optimization requires a passing independent frozen-orbital readback.
Inspect and confirm the new natural-orbital reference before requesting CASCI
sectors or a new QPU Hamiltonian export. Never mix old and new references.

The separate **Correlation energies · MP2 / NEVPT2 / CASPT2** workspace offers
fresh-HF RI-MP2 and verified-CASSCF SC/FIC/DLPNO-NEVPT2 or CASPT2. Consult
`orca.correlation` before guiding that route. These are energy-only results;
they do not replace the CI vectors or peak energies of current Dyson/Kondo
calculations. A lower corrected total energy is not an automatic accuracy ranking.

Use the same fixed geometry and common orbitals for compatible charge/spin
sectors. **Charges** accepts absolute molecular charges, e.g. `0 +1 -1`;
**Multiplicities (2S+1)** accepts lists. These are examples, not a universal
choice of physical states. For reference charge q0, the active electron count
at charge q is `n_active(q0) - (q-q0)`.

**Electronic states** counts roots within each sector, including its lowest
state: 6 means roots 0–5; six excited states plus that sector's lowest require
7 states. A sector's root 0 need not be the overall molecular ground state.
The batch review lists valid/skipped pairs, reasons, actual state counts,
resource cost, existing/running matches and ORCA inputs. A count reduced to
the sector's capacity must be visible before submission. Do not silently
replace the user's spin or call a file error a forbidden spin combination.

Orbital preparation inherits the SCF computer/resources. CASCI retains the
orbital computer while exposing resources for review. A batch can start several
independent jobs concurrently. Compatible state energies appear together; the
collapsed calculation-history selector inspects individual jobs, not a different
energy diagram. Review CI convergence and export norms before using the states.

## 4. Dyson transitions, spectra and maps

Select one initial CASCI state and compatible N−1/N+1 final states on that same
orbital reference. **Select all compatible final states** selects the available
computed manifold, not uncomputed states. Review and compute the transitions;
amplitude cubes and constant-height maps remain separate stages.

The default **Spin averaged · unpolarized** convention and explicit initial-state
populations have different roles. Consult `orca.casci-kondo` for factors and
normalization; a 50/50 mixture is a reviewed physical choice, not a default for
every molecule. Spectral energy shifts are not Kondo chemical potentials.

For a peak map, choose **Spectral maximum → Prepare spectral map at this peak**.
Peak detection uses the displayed broadened spectrum; prominence/height filters
are exposed settings, not filters on contributing transitions. The peak action
carries the precise energy, broadening, convention and complete computed
transition sum into preparation, including off-resonant tails. It submits no job.
Review/generate the complete amplitude cubes if missing, then review/compute
the numerical spectral map. Retain full cubes for numerical maps. The separate
**Inspect selected transition orbitals / maps** action is for individual selections.

If a map is finished but no image appears, open **Figure appearance / export →
Render shared-scale figure**, then select **Stored figures**. Numerical arrays
and rendered figures are separate saved products. Compare panels on a shared
scale and keep source planes, heights and coordinate frames explicit.

## 5. Kondo orbitals and maps

Start from accepted Dyson transitions for a spin-pure initial S > 0 and both
charged sectors allowed by the model. Review the supplied-root manifold and
positive addition/removal costs before **Review Kondo orbitals → Compute Kondo
orbitals**. Enter an explicit chemical potential; no new SCF/CASCI/Dyson run
is needed for exchange. Use the sign convention and charge-stability interval
in `orca.casci-kondo`; a raw DFT Fermi energy cannot be pasted unexamined.

Generate/reuse the Kondo channel cubes, then compute numerical maps and render
figures as above. AFM channels can be preselected; explain their actual
eigenvalues rather than interpreting selection as evidence of four visible
resonances. Individual maps show normalized eigenchannels. Exchange eigenvalues
are not brightness weights; these maps do not predict Kondo temperature,
linewidth, Fano profiles or a combined experimental Kondo image.

## 6. IR/Raman independently of CASCI

Read `orca.vibrations`. With IR/Raman selected, **Use final geometry** opens
spectroscopy rather than another SCF draft. Use a matching saved optimization
when available, prepare an optimization, or explicitly acknowledge **Use this
geometry without optimization (advanced)**. The latter preserves coordinates
and records unverified stationarity; there is no gradient-check option.

Changing functional, basis, charge/spin or geometry prevents an old optimization
being offered as a compatible match. The current UI excludes the match; it
does not yet show a dedicated "functional/basis changed" diagnostic. IR/Raman
inherits the displayed reference's stored settings, not a separately edited
new-calculation draft. Inspect imaginary modes, retained warnings and the
actual frequency calculation before interpreting the spectra. Ordinary harmonic
Raman is supported; resonance Raman is not implemented in this route.

## What the chat can do

Inspect the actual tool schemas. The current adapter provides `orca_get_state`,
`orca_import_smiles`, `orca_load_structure`, `orca_update_draft`,
`orca_open_calculation`, `orca_review`, `orca_submit` and `orca_undo`.
Read the current revision before an edit and read back the resulting form.
The adapter's current edit/submission scope is geometry/SCF; guide the user
through visible CASCI/Dyson/Kondo/IR/Raman controls instead of inventing tools
or claiming those calculations were submitted. There is no `orca_set_goal`
tool. Ask the user to select the visible goal when necessary.

The embedded chat has no web-search/browser tool at present. Offer the official
links below and use packaged facts; do not claim fresh page retrieval or a
literature search without a real tool. XPS is **Work in progress** in the standard
GUI. QPU/DMRG demonstrators and research recovery jobs are separate work and
must not be reset, restarted or repurposed while guiding these app steps.

## Official ORCA documentation and model sources

Use the manual matching the actual executable (the tested app examples use
ORCA 6.1.1). These checked 6.1 links explain the engine, not an extra GUI feature:

| Question | Official reference |
| --- | --- |
| Method choice and scope | [General recommendations](https://www.faccts.de/docs/orca/6.1/manual/contents/quickstartguide/recommendations.html) |
| Orbital/auxiliary bases and element overrides | [Basis sets](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basisset.html) |
| Restricted/unrestricted references, UNOs and QROs | [Wavefunction types](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/hftype.html) |
| Optimization thresholds and native convergence | [Geometry optimizations](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/optimizations.html) |
| Active spaces, multiplicities and roots; CASCI versus CASSCF | [CASSCF module](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html) |
| Cube generation and orbital plots | [Orbital and density plots](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/plots.html) |
| Harmonic frequencies and Hessians | [Vibrational frequencies](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/frequencies.html) |
| IR/Raman and analytical polarizability derivatives | [Vibrational spectroscopy](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vibrations.html) |
| SCF/geometry failures and imaginary modes | [Troubleshooting](https://www.faccts.de/docs/orca/6.1/manual/contents/quickstartguide/troubleshooting.html) |

The app's Dyson post-processing and Kondo model need their own documented
conventions. Use the app's [Dyson guide](../../../docs/dyson.md),
[Kondo guide](https://github.com/nanotech-empa/aiidalab-orca/blob/8d4549e6177586b60a18dbd68a5a63759d9a6cf4/docs/kondo.md) and
[Calvo-Fernández et al., PRB 110, 165113](https://doi.org/10.1103/PhysRevB.110.165113).
Do not describe the whole app pipeline as a single built-in ORCA command.
