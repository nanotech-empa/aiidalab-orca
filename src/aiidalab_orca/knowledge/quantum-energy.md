# ORCA app: guide a user from a confirmed CAS to energy levels

Use this guide when the installed GUI offers **Choose energy solver** and
**Quantum-assisted energy levels**. Check the current GUI and available tool
schemas before advising. An older restricted CAS(2,2) demonstration is not the
general workflow. The shared chat loads this guide for ORCA app context across
providers; it can also be read as `orca.quantum-energy`.

Prerequisites are molecule/geometry → reviewed SCF or optimization → prepared
common spatial orbitals → orbital inspection → explicit active-space confirmation.
Consult `orca.app` and `orca.casci-kondo` for those steps. The standard app uses
QROs from unrestricted references as CAS input. Viewing UNOs does not silently
choose them as CAS input. Confirm orbital character; a CAS label alone does not
establish a scientifically suitable active space.

## Keep the three operations distinct

| User choice | Computation | Solver |
| --- | --- | --- |
| ORCA CASCI | Full selected active space, constructed internally by ORCA | ORCA |
| Full exported Hamiltonian | Optional reference over the complete selected charge/Ms sector | PySCF |
| QPU/simulator-selected subspace | Original exported Hamiltonian projected into the product space selected from quantum samples | PySCF |

At **Choose energy solver**, ORCA CASCI opens the existing charge/spin/root
requests. No separate Hamiltonian export is needed. **Quantum-assisted energy levels
(simulator or QPU)** opens the numbered stages below. Neither full classical
calculation is a prerequisite for the quantum route. The QPU supplies occupation
samples, not a new Hamiltonian, energy eigenvalues or signed CI coefficients.
The standard Dyson/Kondo route still uses ORCA state bundles; these quantum
energy results are not silently substituted for them.

## Guide one next action at a time

Start from the user's current stage and saved results. Do not restart SCF,
optimization, export or circuit generation when their compatible outputs can
be reused. Explain whether the next action navigates, reviews or submits.

| Stage | Controls and action | Expected result |
| --- | --- | --- |
| 1. Export | **Review Hamiltonian export**, choose a compatible worker, then **Submit reviewed stage** | Finished, validated entry under **Hamiltonian** |
| 2. Prepare circuits | Choose target charge and minimum multiplicity, review **Circuit parameters and guidance**, then **Review circuit generation → Submit reviewed stage** | Finished entry under **Prepared circuits** |
| 3. Sample | Choose **Ideal QPU simulator** or explicitly configured real hardware, set **Shots per circuit**, then **Review sampling / retrieve hardware job → Submit reviewed stage** | Finished result with counts under **Samples to analyze** |
| 4. Solve sampled space | Choose the number of levels (default 4), review **Classical solver and resource limits**, then **Review sampled-subspace solve (PySCF) → Submit reviewed stage** | Coverage notice, energy diagram and exact-energy table |
| Compare saved ORCA | Select a compatible calculation under **Saved ORCA comparison** | ORCA overlay and total-energy differences; no new calculation |
| Optional full reference | Open **Optional reference: full exported Hamiltonian (PySCF)**, review and submit its full solve | Separate full-reference column; no ORCA or quantum sampling job |

Each review has **Refresh status and saved results** beside Submit. Refresh
updates this workspace, including status, saved-output selectors and plots.
It does not reload Chrome or submit a job. Opening a workspace or changing a
setting also submits nothing. Changed calculation inputs invalidate the review;
review again before submitting. Read the operation and submitted UUID in the
status, since a previous stage's submission message may still be visible.

If user tool access is available, inspect the actual selected/submitted node
and its stored inputs. A field edited after submission does not establish what
the job ran. Otherwise ask for the UUID/status needed to resolve uncertainty.
Do not invent tool names, job completion, access to the user's Mac or GitHub.
An external agent cannot assume it has the chat app's tools.

## Explain the inputs that matter

**Resources and location.** CPU limits are per stage. ORCA export runs on the
Computer holding the saved wavefunction. Portable Hamiltonian, circuit and
sample artifacts can be copied to a configured localhost or tigu worker. Choose
a worker advertising the required capability; do not substitute an unrelated
Code or install packages without checking the instance. A Code's name alone
does not prove its capability or available resources.

**Export.** Geometry and orbitals stay fixed. Export constructs integrals and
one diagnostic configuration, without SCF iterations or a full CAS solve.
The displayed diagnostic multiplicity is not the later solver-spin choice.
The raw native export is retained; any portable spin-header correction is
recorded separately. The native inactive/nuclear scalar is included once.
Native energy reconstruction must pass before use. Keep a suitable correlation
auxiliary basis and the same RI/core convention when comparing with ORCA.

Review **Full files** before export: leave full files on the calculation
computer, or stash them there. Native text outputs up to **maxsizeoutput**
(default 5 MiB per file) are retrieved unchanged; larger ones have a separate
validation extract and an explicit outputcat notice. New Hamiltonian outputs are external-file
descriptors with checksums, not retrieved integral files. Old repository-backed
Hamiltonians remain usable. Subsequent worker stages copy the same file locally
on its Computer or use a checksum-verified temporary relay between Computers;
the relay is excluded from the AiiDA input repository. Review shows the size
when local staging is needed. Missing/altered files and insufficient temporary
space block the stage without changing the Hamiltonian or restarting ORCA.
Use stash/durable remote storage before real-hardware work: even later request
retrieval needs its Hamiltonian. Restore missing files; never resubmit a QPU job
merely to work around storage loss.

**Charge and spin.** Choose these at stage 2; changing them reuses the same
fixed-orbital Hamiltonian and selects compatible circuits/samples. The minimum
multiplicity sets Ms through 2Ms = multiplicity − 1. It does not constrain every
root to that total spin. Fixed Ms does not determine total S. Higher-spin roots
may appear. Inspect S²; electron
parity identifies allowed multiplicities, not the ground-state spin.

**Circuit parameters.** Evolution times control the sampling evolution; the
field accepts spaces or commas. Circuits per time gives the randomizations at
each time: three times × 50 randomizations means 150 circuits. More groups
usually deepen a circuit. The seed controls reproducibility, not accuracy.
These are starting settings to examine convergence, not a universal protocol.

**Initial occupations.** Blank alpha/beta fields fill the lowest-indexed active
orbitals for each spin. Optional fields accept original selected ORCA indices,
including spaces, commas and ranges such as `10 12..14`. They change the initial
determinant, not the active space. Counts must match the chosen electron sector.
Some state characters or disconnected symmetry sectors need other starting
configurations. An arbitrary determinant need not be spin-pure.

**Diagonal terms.** The checked omission option changes only the sampling
generator. All energy solves still use the original full physical Hamiltonian.
Do not describe the modified generator as exact full-Hamiltonian time evolution.
Occupation-dependent rejection filtering and implicit orbital reordering are
not enabled.

**Shots.** Shots per circuit × circuit count gives total shots. Increasing shots
can recover rare configurations without generating new circuits or exporting
again. It cannot recover configurations unreachable from the chosen circuits.
The ideal simulator generates actual statevector samples and includes no device
noise. More circuits/shots do not add hardware realism or prove quantum advantage.
IBM server-side dry-run/mock counts are not molecular simulation data.

## Read results before claiming success

Postselection checks alpha/beta electron counts. Selected spin strings define a
Cartesian product space, which may include determinant combinations not directly
observed. Distinguish observed configurations from retained product-space size.
Frequencies select support; they are not signed wavefunction coefficients.

Check the coverage notice, requested/computed levels, retained dimension,
truncation and S². One sampled configuration and one projected level do not
establish a converged CAS spectrum. Increase shots, diversify times/circuits or
review initial occupations, then repeat sampling and the sampled-space solve.
Do not mask disagreement by shifting energies, renormalizing results or silently
changing the active space. Even good coverage is not a validation of the chosen
physical model. Projected residuals certify the projected eigensolve, not full-CAS
convergence. Quantized S² alone is not a general higher-spin purity certificate.

The standard exporter supports a contiguous active window up to 32 spatial
orbitals. Root count is configurable, with four as a starting default; available
states, the reviewed determinant cap and a conservative memory-workspace check
bound the actual solve. More roots need no new Hamiltonian, circuits or quantum
samples. A reduced count due to retained-space size is explicit in the result.

Updated workers support fully polarized sectors using a selected single-spin
Slater–Condon matrix rather than mixed-spin SCI. They also support the vacuum
and one-electron cases, preserving the same integrals and inactive/nuclear scalar.
Do not change the intended spin merely to avoid an old implementation limit.
If review identifies a legacy worker with the former four-root or spin-sector
restriction, choose an upgraded solver Code. Keep old Codes available for
existing jobs and hardware request retrieval; never repoint them in place. Larger than CAS(7,7) triggers feasibility review,
not a universal ban. The simulator scales exponentially and full CAS grows
combinatorially. The new standard workspace has no circuit visualizer yet.

**Saved ORCA comparison** offers only completed calculations matching the exact
orbital-reference UUID, geometry, active space, target charge, ORCA Code and
integral model. Its initial selection prefers the lowest compatible multiplicity
and more stored roots. Select another compatible spin family when needed.
The selector updates the display only; do not ask the user to run a full PySCF
reference merely to see ORCA. If no compatible results appear, inspect their
actual stored context instead of forcing similarly named CAS calculations to
match. ORCA labels show declared multiplicity; PySCF labels show S².

Diagram columns share an energy zero. Difference tables use raw total energies,
without fitted alignment shifts, and pair energy-ordered levels with matching
spin expectation. Check state/spin assignments and convergence before drawing
physical conclusions about approximate roots. SVG export is available.

## Tested localhost examples, not universal defaults

For CH2 CAS(2,2), four circuits at time 1 with 1,000 shots each sampled only one
configuration in the tested seeded run. Resampling the same circuits with
10,000 shots each recovered the missing support, and the four levels matched
the full reference and saved ORCA singlet/triplet states.

For a CAS(7,7), charge-0, Ms=1/2 exercise: times `1, 2, 3`, 50 circuits per time,
20 groups, seed 42, default occupations, diagonal terms omitted and 5,000 shots
per circuit gave 150 circuits and 750,000 valid shots. All 1,225 sector
configurations were sampled; four levels agreed with saved ORCA doublets within
5e-11 Hartree. This tests the GUI and data flow. Confirm active-orbital suitability
independently and inspect convergence for every new system.

## Hardware and recovery

Real hardware first requires a configured account and backend, compiled circuit
preparation, and review of depth, two-qubit gates, shots and budget. Preparation
submits no QPU job. Actual execution requires explicit hardware authorization.
Localhost ideal-simulator validation is not real-device or tigu validation.
Credentials belong in the worker's saved account, never chat or AiiDA inputs.
Use the collapsed **QPU credentials** panel below the app tabs to save/select
a local IBM account with its explicit instance CRN. Its masked key field is
transient and excluded from notebook state. Saving submits nothing; checking
the connection is a separate read-only action. A remote worker needs its own
credentials. `QUANTUM_ENERGY_ACCOUNT` configured on the worker takes precedence
over the locally selected account. Existing IBM Open research pilots retain
their separate key-file setup. Wait for assigned project/provider details
before configuring Phoenix; project access is not implied by an Open account.

After a timeout or lost provider response, retrieve the existing request using
its recorded identity/ledger; never suggest blind resubmission. A disconnected
browser does not erase stored results or cancel independently running jobs.
Inspect the actual status before retrying. The new standard energy workflow
must not overwrite or interrupt existing DMRG/QPU research jobs, their immutable
artifacts or their versioned worker deployments.

## Official references and further help

- [Full workflow, conventions and worker setup](https://github.com/nanotech-empa/aiidalab-orca/blob/feature/cas-energy-workflow/docs/quantum-energy.md).
- [ORCA CASSCF/CASCI and arbitrary references](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html).
- [ORCA integral export interface](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/orca_2json.html).
- [PySCF active-space and CI solvers](https://pyscf.org/user/ci.html).
- [PySCF integral export and spin headers](https://pyscf.org/_modules/pyscf/tools/fcidump.html).
- [Public SqDRIFT circuit preparation and parameters](https://quantum.cloud.ibm.com/docs/en/addons/qiskit-fermions/guides/sqdrift).
- [SQD open-shell and spin conventions](https://qiskit.github.io/qiskit-addon-sqd/guides/select_open_closed_shell.html).

Use the relevant official page for a scientific detail beyond these operating
instructions. Do not claim a fresh literature/web search unless the current
agent has actually retrieved the source. This guide supplies guidance, not
calculation authorization or additional tool capabilities.


For native DMRG convergence, consult the app's `docs/dmrg.md` before resuming.
New MPS checkpoints stay on the calculation computer and restart through
same-computer copies with SHA256 checks; only compact arrays, manifests and
bounded output are retrieved. Existing paused jobs retain their immutable
retrieval plans: adopting the remote policy requires a new linked continuation.
Never clean a remote MPS directory that is still needed. Complete sweeps at
fixed M before increasing M; interrupted checkpoints are not validated states.
