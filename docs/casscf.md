# CASSCF: optimize a shared orbital reference

Start from the existing SCF/QRO reference, inspect its orbitals, and confirm the
active space. In **3. Choose energy solver**, choose **Optimize the orbitals
first — CASSCF / SA-CASSCF**. The optional **Optimize orbitals · CASSCF** workspace
also opens this step. Geometry and charge stay fixed.

**One selected state** optimizes the orbitals for one root of one multiplicity.
Root 0 is that sector's lowest state; choosing root 2 computes roots 0–2 and
gives only root 2 a nonzero orbital-optimization weight. Following an excited
root can be difficult when states exchange character: inspect the result.

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
Failures retain their output for diagnosis and cannot become selectable successful
references. Wavefunction storage inherits the selected reference's policy.

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
required by the current Dyson path. NEVPT2 and other correlation corrections
are separate future steps.

The scientific input convention follows the [ORCA 6.1 CASSCF manual](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/CASSCF.html).
The current general active-space preparation still defines its supported
orbital partition; this feature does not add implicit orbital permutations.

## Integration boundary

The shared openBIS adapter in
[aiidalab-openbis#153](https://github.com/nanotech-empa/aiidalab-openbis/pull/153)
does not yet recognize `CasscfWorkChain` as a separately classified result.
That companion adapter must be extended before advertising CASSCF whole-entry
export as complete. It can use the existing CAS-method simulation category;
this draft defines no new openBIS object types and makes no changes to that
repository or a deployed schema. The stored outputs remain ordinary AiiDA data.
