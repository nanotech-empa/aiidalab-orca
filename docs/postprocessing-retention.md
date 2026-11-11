# Postprocessing storage audit

This audit accompanies the Kohn–Sham retention fix. It identifies remaining
release work; it does not claim that the following paths already enforce a
uniform repository-size budget. The owners below are modules in this repository.
Setup owns installed tools and wrappers, not result collection policy.

The user clarified the storage contract after this audit: ordinary native text
output is retained unchanged up to a configurable `maxsizeoutput` (default 5 MiB
per file). Only larger outputs use a distinct extract and explicit notice.
Complete compact PDOS projections are scientific results to keep for interactive
plots. They must not be discarded under a generic diagnostic-file cap. The
remaining work below concerns measured excess, avoidable copies and diagnostic
failure paths; it is not a blanket requirement to externalize useful results.

## Closed in the Kohn–Sham component

`orbitals.py` now inherits the producing reference's remote/stash policy.
Remote wavefunctions are no longer implicitly retrieved below a legacy size
threshold. Existing repository/stash copies remain usable. Missing-file recovery
passes the configured ORCA tools helper and inherited policy into the unchanged
reference builder. Full-cube stash/leave/delete remains independent.

This does not change cube interpolation, reduction, orbital amplitudes, spin
density, reference settings or scientific acceptance tolerances.

## Remaining collection paths

| Owner | Current permanent retrieval | Existing guards | Remaining storage work |
| --- | --- | --- | --- |
| `pdos.py`, `scripts/orbital_character.py` | `character.json`, `character.npz`, `export.log`, `character.log` | At most 6000 AOs; native-export memory estimate; complete normalized orbital partitions and directional tensors | Retain complete PDOS data for interactive projections. Check avoidable NPZ/ArrayData duplication and abnormal diagnostic growth; large coefficient/overlap exports stay external. |
| `orbital_inspection.py`, `scripts/compact_orbitals.py` | `orbital_metadata.json`, inspection and per-set export logs | Combined metadata limited to 2 MiB; full orbital files remote/stashed | Bound the logs, including native export failures. |
| `orbitals.py`, `orbital_inspection.py`, `optical.py`, `dyson.py`, `kondo.py` | `previews/`, `manifest.json`, `plot.log`, `driver.log` for orbital/NTO/Dyson/Kondo cubes | Shared selection limit of 64 orbitals; full-grid bounds; disk estimates; finite grids; preview smaller than full; full-cube retention | Bound the aggregate previews, manifests and logs before retrieval. Per-file reduction alone does not bound the sum. |
| `dyson.py`, `scripts/export_dyson.py` | `artifact.json`, `export.log`, `driver.log` | Complete native CI exports external with identity/norm checks | Bound descriptor and export/driver diagnostics. |
| `dyson.py`, `scripts/compute_dyson.py` | `transitions.json`, `coefficients.npz`, `driver.log` | Selection, state identity and transition normalization checks | Bound complete compact transition results and diagnostics. Do not omit amplitudes or roots to fit a budget. |
| `kondo.py`, `scripts/compute_kondo.py` | `channels.json`, `kondo.log` | Charging-energy, exchange-matrix and eigenchannel checks | Bound complete channel results and diagnostics. |
| `maps.py`, `maps_data.py`, `scripts/dyson_maps.py` | `maps.npz`, `map-metadata.json`, `maps.log` | 32–512 points/axis, 1–8 heights, at most 32 transitions/channels and 32 million intensity samples; shape/finiteness checks | Establish a compact byte budget before retrieval. The existing sample cap still permits approximately 256 MB of float64 intensity alone, then stored `ArrayData` in addition to retrieved NPZ. |
| `maps.py`, `scripts/render_maps.py` | `maps.png`, `maps.pdf`, `figure.log` | Explicit shared scale; 72–600 DPI | Bound image/PDF totals and diagnostics; retain full-quality originals externally if they exceed the compact contract. |
| `rendering.py` | `render.png`, `render.log` | 320–4096 image pixels/axis; bounded slice resolution; exact recorded source selection | Bound encoded image and diagnostics; retain the requested full-quality render externally when needed. |

Native Hamiltonian files are externalized in the energy component. Its separate
energy-stage result, circuit, sample and state artifacts and driver diagnostics
also need a dedicated output-budget review; native FCIDUMP retention alone does
not establish that every quantum-assisted stage is bounded.

## Implementation order and acceptance

First add a shared collection mechanism that runs on the calculation computer,
then adapt each owner with explicit result/diagnostic budgets. Failure paths
matter: an exporter or renderer can emit a large log before its later collector
starts. Merely adding a success-path size check does not bound failed-job
retrieval. AiiDA scheduler stdout/stderr and explicitly retrieved logs need to
be included in the inventory.

Keep complete scientific result files separate from bounded diagnostic summaries.
Do not silently truncate arrays, discard states, alter amplitudes, change grid
resolution or change normalization to satisfy a storage budget. Reject an
oversized compact result with an actionable message; preserve the original on
the calculation computer under the reviewed remote/stash choice. A diagnostic
summary must identify omitted material and link to the full original.

Test normal and oversized outputs, native-tool failures before collection,
missing/inaccessible sources, both retention modes and historical readers.
Measure all newly stored repository artifacts, not just the largest named file.
Keep the exact source hashes and numerical validators unchanged. No existing
scientific node is migrated or rewritten by this cleanup.
