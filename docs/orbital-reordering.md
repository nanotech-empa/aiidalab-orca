# Noncontiguous CAS preparation candidate

This isolated candidate is **not deployed or natively qualified**. Existing
contiguous CASCI/CASSCF/export guards remain intact. Synthetic roundtrips do
not establish that the installed native converter accepts a file representation.

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

| Source/use | Candidate scope |
| --- | --- |
| Original QRO / restricted SCF | Explicit permutation; native GUI pilot pending |
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

## GUI pilot after activation is agreed

1. Open the original allyl QRO reference → **2. Inspect / confirm active space**.
   Reuse its existing catalog. Set 3 active electrons; select 10,11,12 and
   **Review selected CAS orbitals**. Confirm through the existing path with no
   new orbital preparation or scientific calculation.
2. Return to the original QRO reference, select `9 11 13`, click **Review selected
   CAS orbitals**. In **Prepare a noncontiguous CAS selection**, retain 3 active
   electrons, Leave, 5 MiB and **2 GiB / 10 minutes**.
3. **Review selected CAS orbital preparation** must show the complete mapping
   above and one serial CalcJob. Change indices/electrons/exporter/resources/
   retention: submit must require a fresh review. Reuse instead reports the
   original budget/policy and explicitly submits no new CalcJob.
4. Submit **Prepare reordered common orbitals** once. Stop on failure without
   loosening tolerances. Success opens the new reference's inspection without
   confirming it automatically. Read its catalog with its separate 2 GiB/600 s
   budget, inspect source identities/shapes and explicitly confirm 10,11,12.
5. Through separate GUI submissions compute neutral doublet and at least one
   ionic singlet CASCI sector from this **same new reference**. Each remains
   within 2 processes / 2 GiB / 600 s, one native job at a time. Old states must
   not appear in the new-reference state list or Dyson choices.
6. Export/validate/solve the same active Hamiltonian through the existing energy
   route. Compare independent CASCI/solver energies within 1e-7 Ha, check SHA,
   spin sector, ordering, residuals and constant added once. Preserve old models.
7. Reopen from the homepage; check UUID, complete mapping and retained results,
   with no reopen jobs and no modifications to original files/nodes.

The converter/browser pilot and independent Hamiltonian comparison are pending
acceptance gates. Do not activate or claim scientific qualification from these
automatic tests. XPS remains paused. No historical node migration is required.
