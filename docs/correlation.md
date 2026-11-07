# Correlation energies

Open **Correlation energies · MP2 / NEVPT2** from a completed geometry/SCF
entry. These are fixed-geometry energy calculations; original results remain
unchanged.

**HF → RI-MP2** converges a new RHF reference for a singlet or UHF reference for
an open shell, using the selected charge and orbital basis. DFT/QRO/CASSCF
orbitals are not read as a frozen MP2 reference. Results show the HF energy,
correlation correction and total separately. The UHF result also retains S²
and its pure-spin target as diagnostics. MP2 is a single-reference energy
method, not an excited-state solver.

**CASSCF → SC-NEVPT2** requires a successfully verified CASSCF reference.
Prepare and inspect it first, then explicitly select it here. The geometry,
charge, active space, spin/root families and optimization weights are inherited.
The auxiliary basis must match the CASSCF integral model. ORCA performs frozen
CASCI and strongly contracted RI-NEVPT2 with standard per-state canonicalization.
No additional orbital optimization is hidden in the correction step.

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

For several states, switch between reference and corrected excitation diagrams;
each uses its own lowest computed state as zero. Exact reference, correction
and total energies remain together in the downloadable table. Small logs and
structured results are retrieved; full electronic files stay in the calculation
directory. The source CASSCF orbitals are unchanged.

With the matching shared openBIS exporter, entry export discovers these stored
analyses too. RI-MP2 uses the existing energy-calculation category; the complete
SC-NEVPT2 state family stays together as a CAS simulation. No full remote files
are fetched for export.

The `correlation_energies` output is explicitly energy-only. It is not a CASCI
wavefunction, orbital reference or Hamiltonian export. Current Dyson/Kondo
calculations still require compatible shared-orbital CASCI sectors; corrected
energies are not silently substituted into their spectra. DLPNO variants,
CASPT2, QD-NEVPT2 and corrected transition amplitudes are future additions.

Conventions follow ORCA's [MP2](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/MP2.html),
[NEVPT2](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/NEVPT2.html)
and [frozen-core](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/frozencore.html) documentation.
