# Fixed-orbital energy levels: ORCA, simulator or QPU

Start with a molecular geometry, a completed SCF reference, prepared common
spatial orbitals and an explicitly confirmed active space. The **Choose energy
solver** workspace is the branch point:

- **ORCA CASCI** opens the existing charge/multiplicity/root review and batch
  submission. ORCA constructs its integrals internally. No separate export or
  quantum installation is required.
- **Quantum-assisted energy levels** opens the numbered export, circuit,
  sampling and classical-analysis stages. Each stage has an independent review;
  opening or navigating the workspace submits nothing. A full classical solve
  of the exported Hamiltonian is an optional comparison.

Three independent operations must remain distinct:

| Operation | What is diagonalized | Solver |
| --- | --- | --- |
| ORCA CASCI | Full selected active space, constructed internally by ORCA | ORCA |
| Full exported Hamiltonian (optional reference) | Exported integrals over the complete selected charge/Ms sector | PySCF |
| QPU/simulator-selected subspace (main quantum route) | The same exported Hamiltonian projected into the product space selected from quantum samples | PySCF |

The QPU supplies configuration samples; it does not return a new Hamiltonian.
The quantum route does not require either full classical calculation first.

The standard Dyson/Kondo path continues through ORCA CASCI. Quantum energy
results are not silently substituted for the ORCA state bundles used there.

## Hamiltonian and spin conventions

Review **Full files** at export: leave native files on the calculation computer,
or stash them in an explicitly chosen directory there. New exports store a
checksum/size descriptor in the `hamiltonian` output instead of a binary
`SinglefileData`. Native and portable FCIDUMPs, full logs and electronic files
remain outside the AiiDA repository; only bounded validation text, a diagnostic
tail and manifests are retrieved. Existing stored `SinglefileData` Hamiltonians
remain valid inputs without migration.

Worker stages consume the exact portable file. On the same AiiDA Computer it
is copied directly; across Computers it is temporarily relayed through the
AiiDAlab host and checksum-verified. AiiDA's `provenance_exclude_list` uploads
that temporary input while excluding it from the CalcJob input repository.
Review shows its size and the source computer. Missing/altered files or
insufficient staging space stop the stage; they never trigger a new electronic
calculation or a different Hamiltonian. Stashed files remain usable if the
original calculation directory disappears.

New stages require the external Hamiltonian to remain available. Prefer stash
or durable remote storage before real-hardware work, including later retrieval
of an existing provider job. Restore unavailable inputs rather than submitting
another QPU job. No hardware is run by the retention validation.

Export retains the geometry and spatial orbitals. The native ORCA input uses
`NoIter`, unchanged internal/active/external orbital spaces and one explicit
configuration through the documented [`refs` sub-block](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html#arbitrary-references).
It does not enumerate and solve the complete CAS. The diagnostic energy is
labelled accordingly. Export can still require substantial integral-transformation
work; one configuration does not make that work free.

The native inactive-electron/nuclear scalar is included exactly once. The
correlation auxiliary basis controls ORCA's RI transformation; use matching
settings for ORCA comparisons. Keep the native treatment of inactive/core and
active terms: rebuilding all terms with a different integral approximation can
produce a different Hamiltonian even with the same CAS label.

This first app route uses the contiguous active window confirmed by the current
standard common-orbital form, with at most 32 spatial orbitals, matching the
selected-space adapter's supported range. The separate research permutation,
import and DMRG workflows are not replaced by this component.

Export runs once at the reference charge, using the lowest parity-allowed spin
for its one-configuration diagnostic. The source QRO spin does not determine
the later CAS spin. Charge and spin-projection choices belong to the solvers,
not to repeated exports of the same fixed-orbital integrals. In the tested ORCA 6.1.1
`DumpActInts` exports, `MS2` was zero even for triplet CH2 and doublet phenalenyl.
The parser retains the original file in the retrieved repository and emits a
separate portable file with the verified export-reference `MS2 = Nalpha-Nbeta`. All integral
records remain byte-for-byte unchanged. Both checksums and the declared sector
are recorded. A second stage verifies the one-configuration energy from the
integrals before the app offers the model for quantum/classical use.

At stage 2 choose the target charge and minimum multiplicity. The worker computes
explicit `(Nalpha, Nbeta)` counts from this choice and the reference electron
count, independently of the reference sector in the FCIDUMP header. The same
integral file and inactive/nuclear constant are reused across charge/spin sectors.
Circuits, samples and energy results are bound to both the Hamiltonian checksum
and that solver sector. Changing the sector selects a different state family
and requires corresponding circuits/samples, not a new Hamiltonian export.

In this first fixed-Ms route the multiplicity field selects the **minimum** total
spin in the solver sector, not a pure-spin constraint on every resulting level.
Higher-spin roots may appear; inspect the reported S². Raising the minimum
allows investigation of higher-spin families without including lower-Ms states.

This follows the explicit electron-sector convention in [PySCF's FCIDUMP
writer](https://pyscf.org/_modules/pyscf/tools/fcidump.html#write_head). PySCF's
`get_h1eff`, `get_h2eff` and `from_mcscf` also allow integral export without
calling a CASCI solver. A class named CASCI can serve as an integral container;
its construction is distinct from calling its solver.

[ORCA's `orca_2json` interface](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/orca_2json.html)
provides a documented alternative integral interface, and [ASH uses it for
FCIDUMP export](https://ash.readthedocs.io/en/latest/ORCA-interface.html#creating-fcidump-file-from-orca).
Replacing the native route requires checking orbital ordering, inactive/core
terms and RI conventions, rather than assuming these exporters are identical.

## Circuit preparation and sampling

The first adapter uses public [Qiskit Fermions SqDRIFT](https://quantum.cloud.ibm.com/docs/en/addons/qiskit-fermions/guides/sqdrift).
It records the evolution times, number of randomizations, excitation-group
budget, seeds, circuit depths and two-qubit gate counts. The default small
ensemble is a starting example, not a converged protocol for every molecule.

The default initial determinant fills the lowest-indexed orbitals of each spin
sector. Advanced fields accept another alpha/beta occupation pattern in the
original selected ORCA indices; they do not change the active orbital space.
Different state characters or disconnected symmetry sectors may require other
initial configurations. Every pattern must retain the target electron counts;
an arbitrary initial determinant need not be spin-pure.

Occupation-diagonal terms are omitted from the **sampling generator** by
default, as recommended for this sampling use case in the implementation guide.
Turning this option off is available for comparison. Energies always use the
original full Hamiltonian. This is not a claim to exact time evolution under
the full Hamiltonian. Occupation-dependent rejection filtering and implicit
orbital/mode reordering are not enabled.

The ideal simulator uses actual Qiskit statevector sampling. It is distinct from
IBM's server-side dry-run/mock facility, whose random results are not molecular
simulation data. The simulator has a reviewed qubit/memory cap. Above CAS(7,7),
the interface prompts a feasibility review; seven orbitals is a learning
threshold, not a universal hardware limit.

Real hardware first requires compiling the logical circuits for the selected
backend. Preparation submits no QPU job. Review the compiled circuit depths,
two-qubit gate counts, shots, execution limit and campaign budget. Execution
requires the explicit hardware action. The adapter records the provider job ID
in a durable per-host ledger and resumes that request on later retrievals. A
lost provider response blocks blind resubmission. Preparation and execution use
the same immutable Code/host so that they share the ledger.

The collapsed **QPU credentials** panel below the app tabs initializes named
IBM Quantum accounts on the AiiDAlab server. Supply the API key in its masked
field and the explicit instance CRN provided by IBM or the project. Saving
uses the native Qiskit account format, owner-only files, and an explicit
replacement action. Other saved accounts are preserved. The key travels in
a transient widget message; it is never a synchronized widget attribute or
notebook cell. The field clears on submission. **Check connection (no QPU job)**
is a separate read-only action; opening the panel or saving submits nothing.

Credentials remain in the worker's saved Qiskit Runtime account. The selected
local account name is stored in `~/.config/aiidalab-orca/qpu.json`. An explicit
`QUANTUM_ENERGY_ACCOUNT` on the worker retains precedence. Remote workers need
their own configuration; keys are never transferred via AiiDA. Tokens do not
belong in AiiDA inputs, notebooks, agent conversations, plans or receipts.
The legacy IBM Open research pilots retain their separate local key-file
configuration. Phoenix access must use the assigned provider/instance details
when granted; this panel does not establish that allocation or select a device.

## Classical analysis and the diagram

The quantum device supplies occupation samples, not energy eigenvalues or CI
coefficients. Postselection checks alpha/beta electron counts. Selected spin
strings define a Cartesian product space, including combinations not directly
observed, and PySCF diagonalizes the Hamiltonian projected into it.

The requested root count is configurable, with four as a starting default.
Both solvers retain the reviewed determinant-dimension limit and check a
conservative eigensolver workspace estimate before allocation. The estimate
includes the root vectors, Davidson search/images and effective matrix, integral
copies and runtime overhead. It is not an OS-level guarantee. Requested counts
larger than the retained space are reduced explicitly to available states. The full comparison
solver is bounded by an independently reviewed determinant dimension and uses
matrix-free FCI. Fully polarized alpha-only or beta-only sampled sectors use a selected
Slater–Condon matrix, avoiding the mixed-spin SCI routine's division by an empty
spin population. It constructs only the sampled determinant matrix, with the
same one-/two-electron integrals and inactive/nuclear scalar. One-electron,
vacuum and fully occupied single-spin sectors follow the same path. Matrix
elements, not only eigenvalues, are checked against independent full-CI
contractions. The spin is exactly S=N/2 in this fully polarized sector.

Every result records total Hartree energies and S². Fixed Ms allows several
total spins. Incomplete sampled spaces may be spin-contaminated; the viewer
flags this rather than presenting them as validated pure-spin multiplets.
Increase/diversify sampling and retained support, and check stability before
interpreting gaps. See the [SQD open-shell guidance](https://qiskit.github.io/qiskit-addon-sqd/guides/select_open_closed_shell.html).

The diagram compares the latest full, simulator-derived and hardware-derived
results for one selected Hamiltonian and solver sector using a shared energy zero. Exact total
energies and diagnostics remain available in the tables and AiiDA outputs.
A coverage notice appears before the diagram. A sampled space too small to
supply the requested spectrum is flagged explicitly, with guidance to increase
or diversify sampling. A one-dimensional projected result must not be presented
as a converged CAS spectrum. Reuse the existing circuits for a shots increase;
a new Hamiltonian export is unnecessary. The optional full reference is clearly
labelled PySCF, separately from ORCA CASCI. The SVG diagram can be downloaded. Full small-space coverage is an
implementation/learning check, not evidence of quantum advantage.

## Compare directly with saved ORCA CASCI

Below the sampled-space solve, **Saved ORCA comparison** offers completed stored
CASCI calculations with the identical prepared orbital-reference UUID, geometry,
active space, target charge, ORCA Code and RI/auxiliary-basis model. The selector
is read-only: it submits no job and does not require a full PySCF reference.
Its initial choice prefers the lowest compatible multiplicity and a stored run
with more roots. Choose another compatible spin family explicitly when needed,
or select **Do not overlay saved ORCA results**.

ORCA appears as its own diagram column, with declared multiplicities rather
than measured S². Every column uses the same energy zero. The comparison table
also shows absolute total-energy differences without fitted shifts, pairing
energy-ordered levels with matching spin expectation. Truncated sampled spaces
still require convergence and spin checks before physical root assignments.
A similar CAS label alone never establishes compatible wavefunctions.

A manual localhost exercise passed with CAS(7,7), target charge 0 and Ms=1/2:
three evolution times (1, 2, 3 Hartree⁻¹), 50 randomized circuits per time,
20 groups per circuit, seed 42, default occupations, diagonal-generator terms
omitted, and 5,000 shots per circuit. The 150 ideal-simulator circuits supplied
750,000 valid shots and all 1,225 sector configurations. Four projected levels
agreed with the matching stored ORCA doublets within 5e-11 Hartree. This tests
the app/data flow; the settings are an example, not a universal convergence
prescription or a validation of an arbitrary molecule's active-space choice.

The provider-neutral `orca.quantum-energy` agent helper is registered together
with the existing ORCA guides under the ORCA app entry point. It is therefore
included for ORCA app context even when the question is simply “what next?”.
The helper gives one next step at a time, exact review/submit/refresh controls,
sampling diagnostics, the three solver definitions and official references.
The shared chat's `read_workflow_guide` tool also exposes it by ID with a content
hash. Its instructions do not grant permission to submit calculations.

## Localhost and tigu setup

`quantum-tools` is an independently installable worker package; it does not
depend on AiiDA. Install the same pure-Python wheel into a new versioned prefix
on each execution host. Install dependencies for that host's architecture;
do not copy a container's native NumPy/PySCF/SDK libraries onto tigu.

CPU roles need NumPy, SciPy and PySCF. Circuit generation needs the `quantum`
extra; hardware needs `hardware`. Qiskit Fermions 0.3.1 declares
`qiskit~=2.5.0`; keep that SDK in the worker prefix, independent of the app's SDK.
No change to the app interpreter is required for the scientific worker.

For an existing immutable dependency prefix, a new worker wheel can also be
installed with `--no-deps --target NEW_PREFIX`. Prepend that new prefix and the
compatible dependency prefix in the Code's `PYTHONPATH`. Never overwrite the
source or dependencies of a Code used by running calculations.

Run the deployed `quantum-energy manifest` on the target host and retain its
JSON. It records the source hash, capabilities and dependency versions. Register
a new AiiDA Code using `scripts/register_energy_worker.py`, an existing
configured Computer (`localhost` or `tigu`), the deployed executable and that
manifest. The helper refuses to repoint an existing differently configured Code.
Use this prepend setting for every worker:

```bash
export AIIDA_PATH="$PWD/isolated-aiida"
```

The app discovers roles from each Code's manifest. ORCA export runs beside the
saved wavefunction; the portable Hamiltonian, circuits and samples can be copied
by AiiDA to a different configured CPU or hardware-access host. Resource limits
are reviewed in the app, not tied to a particular machine name.

Worker manifests advertise `resource_bounded_roots`,
`polarized_sampled_sectors` and `empty_sampled_sector`. The app checks these
before offering an unsupported request to an older Code. Older immutable workers
remain available for historical jobs and hardware-ledger retrieval. Upgrading
only the CPU solver can reuse a compatible stored Hamiltonian and sample file;
no new circuits or quantum execution is needed merely to request more roots.

Installing the new AiiDA entry points and activating the GUI is a separate
deployment step. Existing research jobs and versioned workers do not need to
be replaced for source preparation or isolated validation. Verify worker
discovery before submitting from the live instance.

The adapter boundaries are Hamiltonian + model/sector metadata, QPY + circuit
manifest, counts + measurement mapping, and energies/eigenstates + diagnostics.
Future IBM workflows can replace circuit/sampling adapters without changing
the orbital-selection UI or scientific source artifacts. No unreleased IBM API
is assumed here.
