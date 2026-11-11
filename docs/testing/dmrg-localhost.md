# L20–L21 — Native DMRG GUI acceptance

DMRG is included in the modern app campaign. These cases replace the earlier
`L18-DMRG = BLOCKED (GUI route not exposed)` placeholder when the new workspace
is part of the reviewed installed candidate. They do not adopt an old research
run as GUI acceptance, nor require that run to finish. Preserve its files,
checkpoints and original lifecycle evidence.

Do not start until the maintainer supplies the included canonical heads,
installed/imported manifest, dependency versions, passing release preflight and
source fingerprint, and the user starts the campaign. Missing prerequisites
are BLOCKED. Fixes invalidate affected qualification. All submissions below
must use actual browser controls; the auditor is read-only. Record each UUID,
review, result, exact reopening route and exports, then close the completed
case's browser tabs. Keep active/pending-review and unrelated tabs.

## Local prerequisites and cost

- Configured released **Block2 0.5.4** `block2main`, using the `empa_orca.dmrg`
  plugin, with the deployment's verified `block2.version` metadata. The operator
  selects the actual localhost code. A label or version extra alone is not
  proof of executable/artifact identity; record the reviewed deployment manifest.
- Linux ARM64 CPython 3.12 has an official PyPI 0.5.4 wheel. Installation must be
  included in the reviewed existing-container alignment, without modifying the
  live AiiDA profile or research environment. The app must not install it on click.
- One node, **one native process and one numerical thread**, `mem 2 g`, ten
  minutes per job. The memory control is Block2 stack GB, not a hard total-RAM
  cap. Observe actual RAM, scratch and native time. One native job at a time.
- L20 uses three spatial orbitals and two electrons, M=32/64. These are tiny
  integration cases, with no benchmark launched to estimate performance. Four
  jobs have a forty-minute cumulative ceiling. Admit at least 1 GiB work space
  and retain the campaign's disk reserve; inspect storage after each stage.
  Stop on an actual resource/validation failure rather than automatically retrying.
- Native MPS/full output remain in each work directory; retrieved arrays are
  individually bounded to 2 MiB and text defaults to 5 MiB. Do not clean the
  checkpoint source. Record actual storage and preserve native warnings.

[Block2 input documentation](https://block2.readthedocs.io/en/latest/user/keywords.html)
explains that `mem` controls stack memory and dynamic allocations use additional
RAM. Numerical threads come from `num_thrds`; the app does not treat these as MPI.

## L20A — Entry, fixture and guards (zero native jobs)

1. Open a fresh app → **Native DMRG**. Verify opening/refreshing submits nothing.
2. Click **Load analytic CAS(2,3) example**. Record the new FCIDUMP UUID. Inspect
   the review's NORB=3, NELEC=2, MS2=0, C1 singlet restriction and checksum.
3. Select the configured local Block2 code, one root, M=32, ordering `none`,
   32 maximum sweeps, one thread, stack memory 2 GB and wall time 10 minutes.
   Label `<prefix>-L20B analytic ground` and click **Review native DMRG**.
4. Change M to 64. Submit must become disabled. Restore M=32 and review again.
   Clear the source UUID, review, and require a helpful unavailable-source error
   with Submit disabled. Restore the exact fixture UUID.
5. Through file upload, test an empty FCIDUMP and an odd-electron MS2=1 fixture.
   **Use uploaded FCIDUMP** must reject them before any native submission.
   A missing Block2 code must produce an explicit prerequisite, not an ORCA/QPU
   fallback. Restore the valid source and all resource values.

PASS requires the observed guards and invalidation. Backend tests alone do not
pass L20A. The analytic file has one-body orbital energies −1.0, −0.2, +0.8 Ha,
zero two-electron integrals and zero core constant. It tests plumbing and singlet
root selection; it does not validate a correlated molecular result.

## L20B — Ground state, native audit and durable reopening (one job)

1. Review the restored L20A settings and submit **once**. Record the native UUID.
   A second click must create no second job. Re-reviewing identical settings
   must reopen the identical request rather than silently resubmit.
2. Use **Native DMRG results** or **Open native result UUID → Open result /
   refresh**. Require energy **−2.0 Ha ± 10⁻⁸ Ha**, electron trace
   **2 ± 10⁻⁷**, finite occupations between 0 and 2, and sweep convergence.
   Ground-state occupations should be 2,0,0 within numerical tolerance.
3. Independently audit the exact FCIDUMP checksum, SU(2)/spin 0, requested roots,
   final M schedule, native termination, per-root sweep/expectation differences,
   1-RDM normalization and original input. No scientific claim follows just from
   Finished 0. A sweep cap/failure is FAIL for convergence, while its usable GUI
   status and retained evidence may separately pass functional inspection.
4. Download sweep CSV and SVG. Compare CSV values to native compact arrays,
   units and sweep count. Close/reopen the app; open the same UUID. Energies,
   verdicts, exports and checkpoint UUID must match and no new job may appear.
5. Verify retrieved contains compact arrays/manifest, no recursive MPS copy.
   Record the retained remote checkpoint. Bond-dimension convergence must remain
   explicitly separate from sweep convergence.

## L20C — Three singlet roots (one separate job)

1. Select the same FCIDUMP, clear the checkpoint field, retain M=32 and set
   **Singlet roots = 3**. Keep the local budget. Label `<prefix>-L20C three roots`.
2. Review/submit once. The first three **singlet** energies are
   **−2.0, −1.2, −0.4 Ha**, each within 10⁻⁸ Ha. Excitations are
   **0, 21.769108997, 43.538217994 eV**. Require all three densities to trace to 2,
   finite occupations and per-root convergence. Do not count triplet states from
   an unrestricted Mₛ=0 reference as the requested singlet roots.
3. Confirm separate source/result history and intact L20B. Download/reopen as
   in L20B. Do not rename this noninteracting control as molecular validation.

## L20D — M refinement, fixed-M continuation and output summary (two jobs)

1. Open L20C → **Use this result as checkpoint**. Require the original source,
   three roots, ordering `none` and M=32. Set M=64, leave fixed-M continuation
   OFF, review and submit `<prefix>-L20D M64 restart` once.
2. Verify a same-computer copy of MPS, matching checksum manifest, original
   Hamiltonian, unchanged root energies within 10⁻⁸ Ha and normalized densities.
   Inspect the submitted restart schedule. Originals remain immutable.
3. Open the M=64 result → **Use this result as checkpoint**. Select **Continue
   one-site sweeps at the same M** and set **Native output retrieval (MiB) = 0**.
   Keep roots/order/M/budget, review and submit `<prefix>-L20D fixed M summary`.
   Verify `onedot`, zero-noise fixed-M continuation, no hidden M increase, energy
   agreement and a separate result UUID. No automatic extension loop is expected.
4. Audit `dmrg.out`'s explicit summary notice, separate `dmrg_summary.out`, compact
   scientific arrays and retained full native output/MPS. No raw file is overwritten.
5. Draft-only controls: change M with fixed-M continuation ON, change ordering
   or roots, or choose a foreign-computer checkpoint. Review must reject the
   incompatible checkpoint. Do not submit these controls.

PASS requires GUI, native and independent identity/restart checks. This tiny
finite model's agreement at M=32/64 does not establish convergence for a larger
molecular Hamiltonian. Exit 311 is visibly unconverged, with valid partial data
and checkpoint available; do not convert it to a scientific PASS.

## L21 — Molecular integration through the existing export route

This case additionally needs local ORCA, electronic-storage and energy-validation
helpers. It is distinct from the analytic L20 control. Use a neutral H2 singlet
at fixed 0.74 Å geometry, PBE/def2-SVP, two electrons in three explicitly inspected
spatial orbitals. Create/import the geometry through the GUI; record coordinates
and actual reference identity. The tiny reference SCF, orbital preparation,
Hamiltonian export/validation, full-space comparator and DMRG are serial stages,
each capped at one/two CPU cores, 2 GiB requested where that stage exposes it,
and ten minutes. Observe the actual allocations; do not run them concurrently.

1. Complete the fixed-geometry molecular reference and prepare its common
   restricted orbitals using the standard app workflow. Inspect and confirm
   CAS(2,3). Do not reuse odd-electron allyl as a singlet.
2. **Choose energy solver → Native DMRG → Export the confirmed active-space
   Hamiltonian**. Use only the existing export/validation stage. Record active
   orbital indices, integral approximation, orbital UUID and Hamiltonian SHA256.
   Export must not optimize orbitals, run a full CASCI or submit a QPU job.
3. In the existing energy workspace, obtain a **full exported Hamiltonian
   (PySCF)** ground-state reference with the same checksum/sector. Verify its
   spin diagnostic is a singlet. This is a separate comparator calculation,
   not permission to compare unrelated ORCA CASCI integral approximations.
4. Return **Native DMRG**, refresh exports and select that completed model.
   Review one singlet, M=32, ordering `none`, one thread, `mem 2 g`, 32 sweeps,
   ten minutes. Submit once. The native job must stage the existing external
   Hamiltonian without importing its large integral payload into AiiDA.
5. Compare the converged DMRG ground-state energy with the same-Hamiltonian
   full-space reference, tolerance **10⁻⁷ Ha**. Require the existing expectation,
   root-density and electron-count checks, then inspect plot/export/reopen.
   Record functional and physical verdicts separately. If the two solvers use
   different sector/checksum/approximation, comparison is BLOCKED, not PASS.

Large-system accuracy, optimized DMRG orbitals, general spin, quantum hardware,
remote HPC, and recovery of the earlier interrupted research run remain outside
these local cases. XPS stays excluded.
