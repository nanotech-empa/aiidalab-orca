# Noncontiguous CAS preparation and GUI pilot

This workflow is merged through [PR70](https://github.com/nanotech-empa/aiidalab-orca/pull/70)
and is available in the selected modern application. Earlier native pilots passed
the original-QRO and restricted-source cases described below. Their dated local
receipts remain evidence for those tested sources; they do not replace a manual
GUI qualification of a new installed assembly. The merged PR description retains
intermediate, dated pending gates and is not the current qualification ledger.

Use this existing pilot as a separate **Noncontiguous CAS** campaign group. A
campaign covering L00–L21 has 22 numbered L groups; including this pilot makes
23 groups. Record the subcases below separately. Existing contiguous
CASCI/CASSCF/export guards remain intact. No source activation is needed when
the installed, passing preflight already includes the merged workflow.

## Scientific contract

Select zero-based **source MO indices** and an explicit active electron count.
The preview text selector retains its existing range/duplicate normalization.
The backend requires unique indices in an explicit order. Unselected doubly
occupied MOs remain inactive; unselected empty MOs remain virtual. Excluding a
SOMO or fractionally occupied MO is rejected. Electron counts are not adjusted
silently. Both inverse maps, source UUID/file SHA-256, occupations and reviewed
metadata hash are recorded. Identity permutations keep the original reference.

For allyl QROs (23 electrons, 67 spatial MOs), CAS(3,3) selecting **9,11,13**:

| Subspace | Source indices | Prepared indices |
| --- | --- | --- |
| Inactive | 0–8, 10 | 0–9 |
| Active | 9, 11, 13 | 10–12 |
| Virtual | 12, 14–66 | 13–66 |

This is a different model from selecting 10,11,12. Do not interpret their
energy difference as a permutation error.

One serial CalcJob performs native export → copy complete MO rows → GBW write
→ native re-export → signed verification. This follows the existing research
permutation approach and the official [ORCA JSON/GBW utility](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/orca_2json.html).
It copies coefficients, occupations, source energy labels and symmetry data.
It does not use the separate [Rotate facility](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/initialguess.html#changing-the-order-of-initial-guess-mos-and-breaking-the-initial-guess-symmetry),
perform SCF/CASCI or optimize orbitals. Array verification checks signed
coefficients/metadata at 1e-10 and complete orthonormality at 1e-7. **Every entry**
of `C_source.T @ S @ C_prepared` must match the permutation matrix; occupation-
weighted spatial density is checked too. No phase fitting, absolute-overlap-only
test, regularization or hidden correction is allowed. A phase change is rejected.

A successful parser creates a separate provenance-linked reference. Its
report distinguishes array verification from a native frozen-CASCI readback;
the preparation produces no state energies. Downstream native jobs verify the
staged GBW checksum before exposing `reference.gbw` to ORCA. A checksum failure
leaves that name unavailable even if the scheduler script continues.

## Supported boundaries

| Source/use | Supported boundary |
| --- | --- |
| Original QRO / restricted SCF | Explicit permutation; use the separate NC-Q and NC-R GUI subcases below |
| CASCI and charged/spin sectors | Existing prepared contiguous window, shared new reference; no per-sector permutation |
| CASSCF from the new reference | Existing optimization/readback; mapping becomes starting-guess history afterwards, not identity of optimized orbitals |
| Hamiltonian export | Existing model/ordering/constant checks on the new reference |
| Dyson/Kondo | Exact same new reference/space/model required; original states cannot mix in |
| Reordering CASSCF/imported/already reordered sources | Rejected by this first native adapter; natural-occupation planning alone is not qualification |
| Existing verified imports | Preserve their component's marker, successful producer/parent and declared ORCA-code guards |
| UNO, UHF spin blocks, spinors, ECPs, reduced-rank bases | Rejected; no implicit conversion |

Budget controls default to **1 process / 2 GiB / 600 seconds**. Stages are
serial, OMP/BLAS threads are one, and a requested stash job follows with the same
budget. No automatic PDOS job is added; catalog/previews/optional PDOS remain
separately reviewed. This JSON operation uses memory proportional to the full
coefficient/overlap tables; large bases may exceed a small requested allocation.
The scheduler budget is a limit, not a convergence or memory-use guarantee.
Full GBW and temporary coefficient/overlap JSON never enter the AiiDA repository.
Temporary JSON is removed on success; GBW follows Leave/Stash. Logs follow
maxsizeoutput (default 5 MiB); only compact mapping/checks are retrieved.
The legacy-shaped `storage_policy` input is derived from this new choice,
not copied from the source: threshold 0, no stash destination for Leave, or
the newly selected directory for Stash. Current consumers use the explicit
`native_output_policy` for execution; the source policy remains in its original
provenance. Reuse displays and preserves the already stored policy/resources.

## Qualification evidence and current run identity

Earlier retained native evidence includes:

- Allyl QRO source 9,11,13 → prepared 10,11,12: signed preparation, catalog/previews,
  neutral-doublet and ionic-singlet CASCI, and independent same-Hamiltonian
  comparison. The recorded same-spin energy differences were below 1e-7 Ha.
- Restricted formaldehyde source 6,8 → prepared 7,8: signed preparation, catalog,
  and a state-specific CASSCF with independent frozen readback (zero recorded
  readback difference).

Keep these earlier records and any correctly rejected attempts. Do not rewrite
an immutable preparation's `native_readback_qualified` field: it says whether
that preparation itself ran a correlated readback. Later CASCI/CASSCF evidence
has its own provenance. A preparation creates no state energies.

For the current campaign, record fresh GUI observations on the exact selected
main/imported sources and passing release-manifest fingerprints. Reuse current
L01/L06 allyl and L13 formaldehyde fixtures. Historical UUIDs, geometries and
absolute energies must not be transplanted into a new fixture. If an earlier
current-baseline subcase is already qualified, reopen its exact result instead
of submitting a duplicate. Preserve original sources, old contiguous results,
failed attempts and every new model separately.

The operator uses Chrome for every submission. The maintainer only audits
retained files/data. Keep one native job at a time. Review local allocations at
each stage: preparation/catalog/plot helpers normally 1 process and one thread,
2 GiB / 600 s; native CASCI/CASSCF normally 2 processes / 2 GiB / 600 s; the full-space worker
normally 2 CPU threads / 2 GiB / 600 s. Keep Leave and 5 MiB unless a selected case tests
another policy. Record actual RAM, file growth and native times at the campaign's
observational cadence. These are reviewed native ceilings, not measured peak
usage or a hard total-RAM guarantee. Use an already-authorized longer wall time
explicitly in review if needed; do not silently retry, relax scientific checks
or move work to remote compute. Stop/report serious faults under the campaign
instructions. No new blanket approval gate is introduced by this guide.

## NC-00 — Entry, original contiguous route and guards

1. Reopen the original L01 allyl result → **2. Inspect / confirm active space**.
   In **Common orbitals**, explicitly select its original L06 QRO reference and
   reuse the matching catalog. Do not select a CASSCF or already reordered source.
2. Set 3 active electrons and source 10,11,12. **Review selected CAS orbitals** must
   retain the original reference through the contiguous route, without a new
   preparation. Return to the same original QRO before the noncontiguous case.
3. In draft-only controls, try a selection excluding the singly occupied MO11
   or an active electron count inconsistent with the selected occupations.
   Require an explicit rejection and disabled preparation submission. Restore
   source 9,11,13 and 3 electrons. Do not submit invalid drafts.

## NC-Q — Original allyl QRO 9/11/13

### NC-Q1 — Review and prepare the new shared reference

1. On the original QRO, enter `9 11 13`, 3 active electrons and click
   **Review selected CAS orbitals**. The separate **Prepare a noncontiguous CAS
   selection** panel must appear. Choose the configured exporter on the source
   localhost computer, Leave, 5 MiB and the reviewed preparation budget.
2. **Review selected CAS orbital preparation** must show the complete mapping
   above: inactive 0–8,10 →0–9; active 9,11,13 →10–12; virtual 12,14–66 →13–66.
   Record source reference/file hashes, both inverse maps and plan hash.
3. Change indices, electrons, exporter, resources or retention and require fresh
   review before submission. Restore/review the valid request. Submit
   **Prepare reordered common orbitals** once. A disabled second click must not
   create another job. Re-reviewing a reusable request must explicitly retain
   its original resources/policy and create no new CalcJob.
4. Native auditing checks the signed coefficient/metadata/overlap/density
   contract above, complete source preservation, external GBW retention and
   absence of SCF/CASCI in preparation. A successful banner alone is insufficient.

### NC-Q2 — Inspect and explicitly confirm the prepared source

1. Success opens the new reference's inspection; it must not confirm the CAS
   automatically. Read the new catalog with its own reviewed helper budget.
2. Inspect prepared 10,11,12, occupations 2/1/0 and their three distinct spatial
   previews with rotation. Match the recorded original 9/11/13 mapping and
   source identities. Use existing source previews when available; do not claim
   a visual comparison to source images that were never viewed. Signed identity
   is established independently from retained arrays, not from lobe resemblance.
3. Explicitly click **Review selected CAS orbitals** for prepared 10,11,12 and
   confirm CAS(3,3). Original L07 states must not appear as results of this new
   reference. Record the new preparation/reference UUIDs and prepared-file hash.

### NC-Q3 — Neutral and ionic frozen CASCI

1. From the confirmed new reference, use the existing ORCA CASCI route. Reset
   any inherited charge/spin fields: neutral charge 0, multiplicity 2, 1 root, RI def2-SVP/C,
   fixed orbitals/geometry. Review and submit once with the agreed local budget.
2. After completion, separately review/submit cation charge +1, multiplicity 1, 1 root from
   this exact same new reference and prepared window. Keep the native jobs serial.
3. Audit native convergence, active/core electron counts, unchanged GBW checksum
   and reference/integral identities. Old-reference sectors must not leak into
   the new state/Dyson choices. Do not request Dyson/Kondo merely to prove the
   selector is separated; record unsupported/unattempted routes honestly.
4. This selection is a different physical model from original 10/11/12. Do not
   compare its absolute energies with L07 as a permutation-accuracy test.

### NC-Q4 — Same-Hamiltonian independent comparison

1. Select the same new reference/window and the existing quantum-assisted
   energy route. Review/submit export and validation once with RI def2-SVP/C.
   Require one diagnostic CSF, no SCF/optimization/full-CASCI during export,
   unchanged order, exact source hash and inactive+nuclear constant added once.
2. Use the separate full exported-Hamiltonian PySCF reference, neutral charge 0 / minimum multiplicity 2 (2 Mₛ = 1),
   1 root and a bounded determinant cap (the CAS(3,3) fixed-Ms dimension is9).
   This comparison needs no circuits, sampling, real QPU or projected solve.
3. Pair only displayed states with the CASCI doublet spin. The one-root pilot
   compares the matching ground state; additional roots are optional scope, not
   a prerequisite. Compare matching
   energy-ordered roots within 1e-7 Ha without alignment shifts. A higher-spin
   root may appear in the fixed-Ms result; do not pair it as a doublet or claim
   coverage of uncomputed roots. Audit retained-vector residuals where available.
4. Preserve old exports. A changed hash, source, ordering or approximation is
   BLOCKED for comparison, not permission to alter the original calculation.

## NC-R — Required original restricted-source route

Use the existing L13 formaldehyde RKS source, not allyl recast as a singlet.
This is the restricted CAS(2,2) 6/8 route from the earlier native pilot.

### NC-R1 — Restricted preparation and inspection

1. Reopen L13 → common-orbital preparation. Reuse its original restricted
   reference if already present; otherwise separately review/prepare it through
   the normal GUI without SCF iterations and record its serial PDOS helper.
2. Read the matching restricted catalog. Verify 16 electrons / 38 spatial MOs for
   this PBE/def2-SVP fixture, charge 0 / multiplicity 1. Inspect source 6 and 8 and
   confirm the intended pi/pi* character from their actual previews rather
   than assuming character from indices alone.
3. Select source `6 8`, 2 active electrons. Review the noncontiguous preparation:
   inactive 0–5,7 →0–6; active 6,8 →7,8; remaining virtuals retain explicit maps.
   Use the same review-invalidation, serial budget and duplicate guards as NC-Q1.
4. Submit once, audit signed/native invariants and source preservation, inspect
   the new restricted catalog/previews and explicitly confirm prepared 7,8 as
   CAS(2,2). Do not mix this source with the QRO preparation.

### NC-R2 — Restricted-source CASSCF and frozen readback

1. From this new restricted reference, choose **One selected state CASSCF**,
   neutral singlet root 0, CAS(2,2), RI def2-SVP/C and the normal reviewed local
   optimization/readback/PDOS budgets. Retain the normal convergence controls.
2. Submit once. Require native orbital optimization convergence and the
   independent frozen readback of that optimized reference to agree within
   1e-7 Ha. Inspect the result and separate optimized-reference identity, PDOS,
   occupations and retained checkpoint/electronic files.
3. The permutation is now starting-guess history. Optimized CASSCF orbitals are
   not required to be the original signed source functions. Keep the source
   restricted preparation and optimized reference separately reopenable.

Restricted-source CASCI/export are separate supported routes, but NC-R2 does
not qualify them. Mark them NOT RUN unless separately executed. Reordering an
optimized CASSCF, imported or already reordered source, UNO, UHF blocks,
spinors and the other excluded inputs in the boundary table must be rejected.
Do not launch extra routes merely to remove an honest scope limit.

## NC-P — Durable reopen and independent final audit

1. Close the completed pilot tabs after recording results and reopening routes.
   Open a fresh app, find each original molecular result, and use **Common
   orbitals** to select the saved new preparation/optimized reference. Record
   exact UUIDs; use **Refresh states** if needed. Inspect the complete mapping,
   catalog, states and export results without new jobs.
2. Independent auditing verifies original hashes/nodes, both inverse maps,
   signed invariants, source-qualified downstream files, same-model energy
   comparison, retained resources/storage and absence of duplicate submissions.
   Preserve any failed attempt and report its exact scientific/software reason.
3. Mark NC-00, NC-Q1–Q4, NC-R1–R2 and NC-P individually PASS/FAIL/BLOCKED/NOT RUN
   with evidence. The group passes only its actually qualified scope; never
   replace a missing GUI step with a backend script or transfer old native PASS
   to a new source fingerprint without the explicit reconciliation.

XPS remains excluded. No historical node migration, source activation,
dependency installation or external-core patch is needed to execute this pilot
on a preflight-qualified installation that already includes the workflow.
