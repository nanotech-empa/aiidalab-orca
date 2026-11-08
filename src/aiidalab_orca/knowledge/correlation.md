# Correlation-energy operating guide

Use the installed **Correlation energies · MP2 / NEVPT2 / CASPT2** app workspace. The
current chat form adapter does not submit these controls; do not claim an
unexposed tool has done so. Inspect the source, actual form and native output.

RI-MP2 starts from a completed geometry/SCF entry and converges its own HF state
in the submitted CalcJob: RHF for a singlet, UHF for an open shell. It does not
reuse frozen DFT/QRO/CAS orbitals. Report UHF S² and its target; convergence is
not certification of a pure-spin determinant.

SC/FIC/DLPNO-NEVPT2 requires a verified CASSCF reference, explicitly selected after
inspection. Preserve geometry, charge, active space and every stored spin/root
and objective weight. Use the same correlation auxiliary basis, frozen CASCI
and native per-state canonicalization. SC is strongly contracted; FIC is fully
internally contracted. DLPNO approximates FIC, so its comparison parent is FIC,
not SC. NormalPNO and TightPNO are explicit choices, not universal error bounds.
Do not copy SC-only CanonStep controls into the other variants. Native DLPNO
localization/PNO construction is part of its approximation. Do not change orbital optimization,
averaging, quasi-degenerate mixing or correction methods implicitly.

Record the explicit frozen-core policy and actual native count, basis, auxiliary
basis and software version. Preserve scheduler/account context and requested
resources, respecting the user's limits and the configured scheduler policy.
Do not infer resource limits from a computer label. Native science runs
only in CalcJobs. In the compact-output candidate, **Full files** explicitly
chooses remote retention or stashing. Full logs/properties and generated
electronic files remain in `native_output/` remotely or in its stash; no full
electronic file is retrieved. Only a bounded validation summary, diagnostic
tail and checksum manifest enter AiiDA. Inputs and the parent reference stay
intact. Verify installed helper support before promising the controls.

Require native normal completion, no error/nonconvergence/projection/norm warning,
correct electron/spin identity, and finite reference/correction/total energies
with a checked sum. NEVPT2 must reproduce every original CASSCF state within
1e-7 Hartree, retain initial orbital spaces, and use the same native weights.
Match multiplicity/root identities because native block order can change.
Read the labelled per-state corrections; a final scalar average is not a state.
For DLPNO, retain resolved native thresholds and verify each iterative amplitude
solve. Reject negative-denominator/Koopmans warnings despite normal termination.
The failure reason is visible in the process result. Do not silently add shifts
or change RDM approximations, reference orbitals, roots or weights to pass checks.
The allyl single-state pilot passes; its four-state-average FIC pilot retains
negative Koopmans warnings even without RDM prescreening and is rejected.
Its dependent pilot branch is stopped; do not describe it as a validated spectrum.

The `correlation_energies` result supplies no orbital reference or CASCI state
vectors. Do not route it into current Dyson/Kondo, replace spectral peaks,
recycle an old QPU Hamiltonian, or describe an energy correction as a corrected
transition amplitude. Retain the independent shared-orbital CASCI path.

CASPT2 is available in the same CASSCF correlation branch as a different
perturbation model. Review explicit real/imaginary/IPEA shifts in Hartree;
all default to zero, and ORCA's IPEA convention differs from OpenMolcas.
Do not introduce a shift automatically or use CASPT2 as a silent remedy for
a failed NEVPT2 result. Record reference weights and each excitation-class
denominator, verify native shift readback and every residual iteration solve.
ORCA may finish without aborting an unconverged CASPT2 solve. Native normal
termination is insufficient. Distinguish reference weights from CASSCF
state-average weights. Small weights/denominators require inspection, not a
claim of validity from a single diagnostic. Full first-order wavefunction
storage increases memory/disk needs on larger systems. The single-state
one-shift-at-a-time checks test implementation, not universal protocol accuracy.

Interpret corrections through consistent energy differences. A large total
correlation correction can largely cancel between states; a corrected gap
changes by the final-state correction minus the initial-state correction.
SC, FIC and CASPT2 are different approximations, so a lower total energy does
not by itself establish greater accuracy. The current single-state CASPT2
pilot does not establish excitation-gap accuracy for a state average.

Editing invalidates review; submission is explicit. Reuse matching running or
successful requests unless recomputation is selected. Retain failed outputs,
diagnose the cause and never weaken tolerances or optimize a new reference
silently. CASPT2-K, F12, QD and nonorthogonal transition amplitudes are outside
this increment. See [the user guide](../../../docs/correlation.md).
