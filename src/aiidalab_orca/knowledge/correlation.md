# Correlation-energy operating guide

Use the installed **Correlation energies · MP2 / NEVPT2** app workspace. The
current chat form adapter does not submit these controls; do not claim an
unexposed tool has done so. Inspect the source, actual form and native output.

RI-MP2 starts from a completed geometry/SCF entry and converges its own HF state
in the submitted CalcJob: RHF for a singlet, UHF for an open shell. It does not
reuse frozen DFT/QRO/CAS orbitals. Report UHF S² and its target; convergence is
not certification of a pure-spin determinant.

SC-NEVPT2 requires a verified CASSCF reference, explicitly selected after
inspection. Preserve geometry, charge, active space and every stored spin/root
and objective weight. Use the same correlation auxiliary basis, frozen CASCI
and standard per-state canonicalization. Do not change orbital optimization,
averaging, quasi-degenerate mixing or correction methods implicitly.

Record the explicit frozen-core policy and actual native count, basis, auxiliary
basis and software version. Preserve scheduler/account context and requested
resources, with at most 12 processes per tigu submission. Native science runs
only in CalcJobs. Full electronic files stay in the work directory; there is
no automatic stash or remote retrieval.

Require native normal completion, no error/nonconvergence/projection/norm warning,
correct electron/spin identity, and finite reference/correction/total energies
with a checked sum. NEVPT2 must reproduce every original CASSCF state within
1e-7 Hartree, retain initial orbital spaces, and use the same native weights.
Match multiplicity/root identities because native block order can change.
Read the labelled per-state corrections; a final scalar average is not a state.

The `correlation_energies` result supplies no orbital reference or CASCI state
vectors. Do not route it into current Dyson/Kondo, replace spectral peaks,
recycle an old QPU Hamiltonian, or describe an energy correction as a corrected
transition amplitude. Retain the independent shared-orbital CASCI path.

Editing invalidates review; submission is explicit. Reuse matching running or
successful requests unless recomputation is selected. Retain failed outputs,
diagnose the cause and never weaken tolerances or optimize a new reference
silently. DLPNO, CASPT2, QD and nonorthogonal transition amplitudes are outside
this increment. See [the user guide](../../../docs/correlation.md).
