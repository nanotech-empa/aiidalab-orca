# Correlation energies

Open **Correlation energies · MP2 / NEVPT2 / CASPT2** from a completed geometry/SCF
entry. These are fixed-geometry energy calculations; original results remain
unchanged.

**HF → RI-MP2** converges a new RHF reference for a singlet or UHF reference for
an open shell, using the selected charge and orbital basis. DFT/QRO/CASSCF
orbitals are not read as a frozen MP2 reference. Results show the HF energy,
correlation correction and total separately. The UHF result also retains S²
and its pure-spin target as diagnostics. MP2 is a single-reference energy
method, not an excited-state solver.

**CASSCF → correlation** requires a successfully verified CASSCF reference.
Prepare and inspect it first, then explicitly select it here. The geometry,
charge, active space, spin/root families and optimization weights are inherited.
The auxiliary basis must match the CASSCF integral model. Choose the contraction
explicitly: strongly contracted **SC-NEVPT2**, fully internally contracted
**FIC-NEVPT2**, or **DLPNO-NEVPT2**, a local approximation to FIC. SC remains the
default. These are different methods, not three levels of the same accuracy knob.
For DLPNO, choose NormalPNO or TightPNO; check sensitivity and compare with FIC
where feasible. A PNO preset is not a universal error bound.

ORCA performs frozen CASCI followed by the selected RI-NEVPT2 correction with
per-state canonicalization. DLPNO's intrinsic PNO construction belongs to that
method; it is distinct from optimizing a new CASSCF reference.
No additional orbital optimization is hidden in the correction step.

**CASPT2** is a separate fully internally contracted RI correction using the
same verified source. Real, imaginary and IPEA shifts are explicit in Hartree,
under the closed CASPT2-settings section; all start at zero. ORCA's IPEA
convention differs from OpenMolcas. No shift is chosen automatically and CASPT2
is not an automatic fallback for a rejected NEVPT2 calculation. It uses more
memory/disk for the full first-order wavefunction, which matters on larger systems.

Each CASPT2 residual solve must converge. Its reference weight, smallest
denominators, final residual norm and shift readback are retained per state.
Reference weight is a perturbation diagnostic, distinct from state-average
weights. Small weights or problematic denominators need inspection; normal
termination or one diagnostic alone does not certify physical validity.
The small single-state validation changes one shift at a time to check the
controls; it does not define a universal shifted molecular protocol.

The frozen-core checkbox chooses `FC_ELECTRONS` or `FC_NONE`. The result records
the actual native frozen-electron count. Resources, auxiliary basis and forced
recomputation are under the closed advanced accordion. Code/computer and
scheduler context follow the source; no Python selection is needed. Opening,
selecting or reviewing submits nothing. Editing invalidates review. Matching
running/successful requests are reused unless recomputation is explicitly chosen.

Acceptance requires native completion without convergence/projection/norm
failure, electron/spin identity and consistent finite energy sums. NEVPT2 must
reproduce every original CASSCF energy within 1e-7 Hartree before correction,
with unchanged initial orbital spaces, matching weights and complete labelled
spin/root tables. A final scalar state-average energy is not an individual state.
DLPNO also requires recorded native PNO thresholds and convergence of every
iterative amplitude solve. Negative-denominator or negative-Koopmans-eigenvalue
warnings reject a result even if ORCA terminates normally. The app reports the
reason; it does not add shifts, change the CAS, or replace the reference silently.

The small allyl single-state FIC/DLPNO pilot passes. Its four-state-average FIC
reference produces negative Koopmans warnings, also with RDM prescreening
disabled; that pilot is rejected and its dependent calculations are stopped.
This does not establish that every state-averaged reference is unsuitable.
Inspect the affected states and reference before separately reviewing a remedy.

For several states, switch between reference and corrected excitation diagrams;
each uses its own lowest computed state as zero. Exact reference, correction
and total energies remain together in the downloadable table. Small logs and
structured results are retrieved; full electronic files stay in the calculation
directory. The source CASSCF orbitals are unchanged.

With the matching shared openBIS exporter, entry export discovers these stored
analyses too. RI-MP2 uses the existing energy-calculation category; the complete
NEVPT2/CASPT2 state family stays together as a CAS simulation. No full remote files
are fetched for export.

The `correlation_energies` output is explicitly energy-only. It is not a CASCI
wavefunction, orbital reference or Hamiltonian export. Current Dyson/Kondo
calculations still require compatible shared-orbital CASCI sectors; corrected
energies are not silently substituted into their spectra. CASPT2-K, F12,
QD-NEVPT2 and corrected transition amplitudes are future additions.

Conventions follow ORCA's [MP2](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/MP2.html),
[NEVPT2](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/NEVPT2.html)
and [frozen-core](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/frozencore.html) documentation.
The [CASPT2 documentation](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/caspt2.html)
also explains shift conventions and the need to verify every residual solve.
