# CASSCF: optimize a shared orbital reference

Start from the existing SCF/QRO reference, inspect its orbitals, and confirm the
active space. In **3. Choose energy solver**, choose **Optimize the orbitals
first — CASSCF / SA-CASSCF**. The optional **Optimize orbitals · CASSCF** workspace
also opens this step. Geometry and charge stay fixed.

**One selected state** optimizes the orbitals for one root of one multiplicity.
Root 0 is that sector's lowest state; choosing root 2 computes roots 0–2 and
gives only root 2 a nonzero orbital-optimization weight. Following an excited
root can be difficult when states exchange character: inspect the result.
CAS(3,3) means three active electrons in three orbitals; it does not request
three states. With root 0 selected, one energy is the expected result. To
obtain an energy ladder using those optimized orbitals, inspect and confirm
the new reference, then request several roots in CASCI.

**State average (SA)** optimizes one shared orbital set against the chosen
states. Add multiplicities, set roots per multiplicity and, optionally, enter
one weight per root. Empty weight fields mean equal weights per individual
state across all rows. The review shows the normalized weight of every root.
Different multiplicities can contribute to this objective at the same charge;
the output retains distinct spin-labelled states. This is not a coherent
superposition, a thermal population, a tunnelling selection factor or a
prediction of spectral intensity.

**Resources and convergence** exposes processes, total memory in GiB, wall
time, maximum macro-iterations and the correlation auxiliary basis. The ORCA
code/computer, orbital basis and element overrides follow the selected input
reference. The default orbital optimizer is ORCA's default; the app does not
silently change solvers or loosen convergence. Review both native inputs, then
explicitly **Submit reviewed CASSCF**. Opening or reviewing submits nothing.

One submitted CalcJob runs CASSCF and then independently reads the saved orbitals
with all final orbital subspaces held unchanged. Acceptance requires native
orbital-gradient convergence, all requested CI roots, the original electron and
active-space partition, and agreement of every readback energy within
`1e-7 Hartree`. Energy-only termination or normal termination alone does not pass.
Failures retain their original output on the calculation computer for diagnosis
and cannot become selectable successful references.

**Full files** chooses **Leave on the calculation computer** or **Stash on the
calculation computer**, with an explicit destination for the latter. New jobs
retrieve only two validation summaries (at most 2 MiB each), two diagnostic
tails (64 KiB each), and a size/checksum manifest. Both full native logs and
property files remain in `native_output/`; the optimized GBW remains remotely,
or is stashed without retrieval. The native inputs, state weights, convergence
checks and `1e-7 Hartree` readback tolerance are unchanged. Changing retention
requires review again. Reusing a result keeps its recorded retention, and old
full-output records remain readable without migration.

The configured `orca-tools` runtime must support `compact_output.py`. This is
an application/backend deployment requirement, not a new Python selector or
computer installation performed by the app. Remote originals remain subject
to the calculation computer's cleanup policy.

**Run again even if a matching result exists** forces a new execution of the
same request. Leave it unchecked for normal reuse. Editing the state objective,
active space or other calculation settings already defines a different request.

After success, **Inspect optimized orbitals** selects the new reference and
returns to inspection. Its correlated natural occupations and orbital character
are shown by orbital index, without presenting them as Kohn–Sham eigenvalues.
The usual reduced-cube pipeline visualizes their shapes. Confirm the optimized
space again before continuing. The original orbitals, states and provenance
remain intact.

For Dyson/Kondo, compute every needed fixed-orbital CASCI charge/spin sector
using this one new reference. States from different orbital-reference UUIDs
cannot be combined. Independently optimized charge states would require a
separate nonorthogonal-orbital implementation. For quantum-assisted energies,
export a new Hamiltonian from the optimized reference; an old export belongs
to the original orbitals. A QPU energy result cannot replace the CI state vectors
required by the current Dyson path. For energy corrections, open the separate
[CASSCF → correlation branch](correlation.md): SC/FIC/DLPNO-NEVPT2 or CASPT2.
These return energies and diagnostics, without replacing the current
Dyson/Kondo state vectors. The [stage validation record](release-readiness.md)
distinguishes completed pilots from unvalidated cases.

The scientific input convention follows the [ORCA 6.1 CASSCF manual](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html).
The current general active-space preparation still defines its supported
orbital partition; this feature does not add implicit orbital permutations.

## openBIS companion

The shared adapter in
[aiidalab-openbis#153](https://github.com/nanotech-empa/aiidalab-openbis/pull/153)
includes `CasscfWorkChain` in the entry's export scope. The optimized reference,
complete spin/root table, optimization weights and readback evidence remain
together in one `UNCLASSIFIED_SIMULATION` result with method family `CAS`.
CASSCF orbital cubes use `SPM_SIMULATION`, also with method family `CAS`.
Natural occupations are not exported as an energy DOS. This reuses existing
openBIS types and requires no server schema migration.

That adapter is a separate, unmerged companion: use a revision containing the
CASSCF mapping. The app alone does not install or release the shared exporter.
