# CASSCF and correlation stage: validation and remaining gates

This record describes the development stage reviewed on 8 November 2026.
It distinguishes available code, native small-system checks and release
acceptance. It is not a statement of accuracy for an arbitrary molecule.

## Delivery scope

The maintained components are:

- [ORCA #39](https://github.com/nanotech-empa/aiidalab-orca/pull/39): verified
  state-specific and state-averaged CASSCF orbital references.
- [ORCA #40](https://github.com/nanotech-empa/aiidalab-orca/pull/40), based on
  #39: fresh-HF RI-MP2 and verified-CASSCF SC/FIC/DLPNO-NEVPT2 and CASPT2.
- [Shared exporter #153](https://github.com/nanotech-empa/aiidalab-openbis/pull/153):
  stored-only whole-entry export, including these analyses. It is based on
  the exporter's separate product/CXSMILES development series, not its released
  default branch. Its prerequisite review and release holds still apply.

The standard PDOS, orbital inspection, CASCI, quantum-assisted energy,
Dyson/Kondo and vibrational routes remain available. Research QPU/DMRG/XPS
extensions in an assembled preview are not extra release claims for this stage.
The maintained component branches and the live research checkout have distinct
roles; a dirty research preview must not be reset to make a component look clean.

## Evidence and its limits

| Route | Completed native check | What this establishes / remaining limit |
| --- | --- | --- |
| CASSCF | Allyl CAS(3,3), selected-state and four-state average; independent frozen-orbital readback | Saved-reference identity, convergence and per-state energy agreement; not active-space/basis convergence for another molecule |
| CASSCF downstream reuse | Small allyl fixed-orbital states, Dyson sum rules and independent Hamiltonian comparison | Compatibility of the saved reference with the existing state-vector and energy-export paths; not a new hardware-QPU benchmark |
| RI-MP2 | Water with and without frozen core; open-shell allyl | Fresh-HF route, native model identity and separated energies; UHF spin contamination remains visible |
| SC-NEVPT2 | Allyl selected state and four-state average, frozen-core controls | Source-energy readback and labelled state corrections for these pilots |
| FIC/DLPNO-NEVPT2 | Allyl selected state, FIC and Normal/Tight PNO | Both DLPNO/FIC differences below the reviewed 0.01 eV pilot target; no universal PNO error bound |
| FIC state average | Allyl four-state pilot, repeated without RDM prescreening | Negative Koopmans eigenvalues persist: rejected, dependent pilot branch stopped; a validated remedy remains open |
| CASPT2 | Allyl selected state, unshifted and one real/imaginary/IPEA shift at a time | Native shifts, reference energy, weights, denominators and residual convergence; not multistate excitation accuracy or a universal shifted protocol |
| Shared openBIS adapter | Local archive/mapping, common-form and recovery regression checks | Stored-only scope and categories; live-server upload/import acceptance is still outstanding |

The automated suite exercises request validation, native parsing, scientific
failure gates, reference/provenance handling, reuse and interface behavior.
Normal ORCA termination is insufficient for scientific acceptance. Native
examples are submitted CalcJobs and are not run by ordinary unit tests.

The consolidation check on this date passed **404 ORCA tests** (five optional
cases skipped) and **230 shared-exporter regression tests**, including review,
retry and recovery paths. Both ORCA wheels built without installing dependencies;
their packaged workflow guides and calculation/parser entry points were checked.
These counts identify this development checkpoint, not a permanent CI target.

## Contracts that must remain explicit

1. CASSCF state-average weights optimize orbitals. They are not thermal
   populations, Clebsch–Gordan coefficients or spectral intensities.
2. Verified CASSCF reuse requires an independent frozen-orbital readback of
   every requested state within `1e-7 Hartree`. Failure cannot become a
   selectable successful reference.
3. MP2 converges its own HF reference. NEVPT2/CASPT2 preserve the selected
   CASSCF state family, model and frozen-core choice. No silent reference,
   solver, shift or active-space changes are allowed to rescue a failed result.
4. Correlation outputs are energy-only. Current Dyson/Kondo calculations use
   compatible shared-orbital CASCI vectors, with no corrected-energy or
   transition-amplitude substitution. A QPU energy is not a CI-vector source.
5. CASPT2 shifts, reference weights and denominators remain explicit. A lower
   total energy, a positive diagnostic, or normal termination alone does not
   establish greater physical accuracy. Compare consistent energy differences.
6. The general CAS input supports a contiguous window in the prepared ordering.
   Arbitrary orbital-preview selections do not implement CAS reordering. Atoms
   use one-based viewer indices; ORCA orbitals use zero-based indices.
7. Export uses only AiiDA-stored data. Remote/stashed full files remain external
   references. One reviewed entry can produce several scientific result types;
   it does not acquire an invented synthetic workflow parent.

## Before release

### Native-log retention cleanup

Large files must remain remote or be stashed after an explicit user choice;
the AiiDA repository receives compact results, bounded diagnostics, manifests
and reduced previews. This includes large CI logs and exports, not only GBW
and full-resolution cubes. Computer/code setup belongs to `aiidalab-empa-setup`;
the application must use compatible configured codes without machine-specific
or scheduler/transport allowlists.

The compact-output candidates address new SCF/geometry, common-orbital, CASCI/CASSCF and correlation native files,
including wavefunctions and Dyson CI exports:
it retrieves bounded summaries/manifests and requires explicit remote/stash
retention. The configured `orca-tools` runtime must support `compact_output.py`;
source implementation is not deployment qualification. Historical full-output
records remain readable without migration.

The CASSCF collector retains both optimization and frozen-readback validation
summaries, including the native state-average objective and final state families;
it does not weaken the orbital-gradient or individual-state readback checks.

SCF/geometry reuses aiida-orca's cclib reader on the calculation computer. The
compact result excludes large AO/MO coefficient/overlap data, records omitted
fields, and retains the final orbital table verbatim. Summaries/JSON/final XYZ
are bounded at 2 MiB each; trajectory XYZ is bounded at 8 MiB. An exceeded
budget fails collection instead of retrieving or silently truncating the full
file. Geometry convergence, final-frame consistency and SCF checks remain.

Common-orbital preparation retains the existing NoIter/read-source checks in
a bounded validation summary. Catalogs and orbital previews inherit its
remote/stash policy instead of implicitly retrieving orbital files under an old
size threshold. Combined catalog metadata is bounded at 2 MiB; coefficient
arrays and original orbital files do not enter that metadata.

Correlation summaries preserve all existing native checks, including every
CASPT2 residual/denominator table and DLPNO amplitude solve. Full generated
electronic files are bundled with the native logs for the reviewed remote/stash
choice; they do not become Dyson/Kondo orbital references. Correlation and
optical resource review no longer impose process limits by computer label.

Native `aiida.out` retrieval in optical, vibration and other calculation classes is not yet uniformly size bounded.
Before release, extract and validate compact
results on the calculation computer, preserve large originals through the
reviewed remote/stash policy, and update consumers that currently parse the
retrieved full log. Existing streaming fixes address memory use but do not close
this retention gate. Do not simply omit a file required by a parser or change
scientific acceptance checks, and do not alter stored historical nodes.

### Remaining acceptance

- Run the affected ORCA and shared-exporter regression suites and package checks
  against the intended revisions. Keep their exact commands and results in the
  delivery record; check the packaged agent guides and AiiDA entry points too.
- Review and merge the canonical components in dependency order. A locally
  activated feature or green CI is not a published application release.
- Check the declared Python ≥3.12, AiiDA ≥2.9.2, AiiDAlab ≥26.9.0 and ipywidgets
  8 baseline, plus the pinned shared viewer/vibrational dependencies. An older
  live preview does not extend the support policy. Do not change dependency
  constraints or migrate a live profile as part of documentation cleanup.
- For openBIS, use a revision containing the companion mappings and complete
  the separate modern-stack review. With an approved destination, test the
  common experiment/molecule selection, publish, retry and stored-data import
  round trip. Local tests do not establish live-server acceptance. These
  mappings use existing object types and require no schema migration.

XPS, XAS, resonance Raman, CASPT2-K, QD-NEVPT2, F12, nonorthogonal transition
amplitudes and NRG-based Kondo spectra remain outside this stage. Their absence
does not block the scoped energy methods, but they must not be advertised as
implemented or validated by this record. No new numerical calculation, server
upload, merge, dependency change or release is authorized by this document.
