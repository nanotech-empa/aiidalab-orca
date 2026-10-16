# QRO and UNO inspection

Open a completed SCF/geometry result, expand **CASCI states · fixed geometry
(draft)**, and open **Inspect QRO / UNO orbitals**.

1. **Read orbital information** submits a small AiiDA workflow. It preserves
   available orbital files and exports metadata using the registered
   `orca_2json` code. Existing durable metadata are reused. **Read metadata
   again** in the advanced controls requests a new export.
2. Choose **QRO** or **UNO**. The list, occupation plot and expandable table
   show the zero-based indices of that particular set. The JSON download
   records the original occupations, source file digest and reference UUID.
3. Select one or more orbitals, review the cube request, and submit it.
   The configured `orca_plot` and cubehandler run through a CalcJob on the
   reference computer. The EMPA cube viewer provides isosurfaces, slices,
   saved visualizations and subsequent CalcJob rendering.
4. Full cubes are **stashed by default** in the editable cube-stash directory.
   Leave/delete options match the KS orbital workflow. Only validated
   cubehandler-reduced previews are retrieved into AiiDA. Retained full cubes
   can be used for subsequent high-quality rendering.

This is orbital inspection and review of the current CASCI active window.
Selecting UNOs for inspection does not change the orbital reference used by
existing or new CASCI sectors. A later preparation component can make an
explicit choice of another shared orbital reference.

## What the occupations mean

- **QRO reference occupations** are the integer 2/1/0 occupations stored with
  the quasi-restricted reference. Its displayed orbital-energy labels are
  not the many-electron CASCI state energies, and need not have a global
  Aufbau ordering across the occupation classes.
- **UNO natural occupations** diagonalize the original unrestricted SCF
  spin-summed density matrix. They are fractional diagnostics of that SCF
  reference, not correlated CASCI natural occupations. Tiny negative or
  above-two round-off values are clipped only for display; exported metadata
  retain the original values. UNO orbital energies are deliberately not
  presented as canonical KS eigenvalues.
- Restricted references have their original restricted spatial orbitals;
  no artificial UNO/QRO transformation is applied.

QRO and UNO indices refer to different orbital orderings. Equal indices do
not establish a one-to-one orbital correspondence. Only the QRO/restricted
list marks the current CASCI active window. **Use selected QRO window for
CASCI** transfers an explicitly selected contiguous window after validating
its inactive/active electron count. This does not reorder orbitals. Arbitrary
orbital selection/reordering and correlated natural-orbital preparation remain
separate scientific extensions.

## Provenance, preservation and missing files

New unrestricted common-orbital preparations preserve both `aiida.qro` and
`aiida.uno` under the inherited SCF wavefunction policy: retrieve a small
bundle, or use native AiiDA stashing above the threshold. Inspection of an
older preparation can separately preserve an existing UNO file without
changing its common-orbital reference or existing CASCI states.

Metadata and preview reuse are explicit and do not depend on AiiDA caching.
A catalog remains readable after scratch disappears. New cubes require their
specific binary file; repository/stash/scratch availability is checked, and
the CalcJob verifies the staged SHA-256 digest against the inspected catalog.
Already stored previews can be reopened even if full cubes disappear. A new
request for the same retained full cubes checks their availability before
reuse; it cannot silently claim a lost full cube is preserved.

If an older preparation has lost its UNO file, inspection still exposes any
available QRO data and explains that UNO regeneration needs a new reference.
Use **Common-orbital regeneration → Prepare a new common-orbital reference**,
then review and submit the preparation. The saved SCF wavefunction must be
available. No SCF is silently launched. Regeneration or a different orbital basis must
be a new provenance-linked preparation; historical nodes are never modified.

## Backend and code setup

The new independent components are:

- `empa_orca.orbital_catalog`: preserve available files and export/validate
  compact metadata, using a dedicated CalcJob and parser.
- `empa_orca.common_orbital_cubes`: request selected spatial orbitals from a
  catalog, reuse verified existing cubes or call the shared
  `empa_orca.orbital_cubes` CalcJob.

Register **orca_2json** on the same computer as ORCA and `orca_plot`, with
`default_calc_job_plugin='empa_orca.orbital_catalog'`. Point it at the utility
from the matching ORCA installation. The inspection panel selects this code
under **Inspection grid and codes**. The existing ORCA tools application code
is resolved automatically; there is no Python executable selector or PythonJob.
The remote ORCA tools installation must include this backend revision and its
`compact_orbitals.py` script. Scheduler account/queue settings are inherited
from the reference CalcJob. ORCA deployment on tigu remains a separate test.

The ORCA 6.1 exporter requires `MOCoefficients: true` to export its MO records.
The export CalcJob removes coefficient arrays with a bounded-memory pass,
validates the remaining JSON, and retrieves compact metadata and logs only.
Temporary coefficient JSON and staged orbital copies are deleted after
successful compaction. Integral and density exports are not requested.

References: [ORCA UNO/QRO generation](https://www.faccts.de/docs/orca/6.1/manual/contents/modelchemistries/hftype.html#uno-uco-and-qros-input)
and [ORCA JSON export](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/orca_2json.html).

## Validation

The local ORCA 6.1.1 ARM64 NO/def2-SVP doublet reference was inspected without
new SCF iterations. Both sets contained 28 spatial orbitals with occupations
summing to 15 electrons. QROs 6–8 had reference occupations 2, 1 and 0;
the UNO occupations at these indices were approximately 1.99972346, 1 and
0.00027654. These values diagnose this small test reference, not a converged
multireference protocol.

For both sets, three 80³ orbital cubes were generated through CalcJobs and
reduced with cubehandler to 16³ previews. Each full cube was about 7.26 MB;
retrieved previews were about 54–56 kB. The full cubes were verified in native
AiiDA stashes. Repeating each request reused the outputs without new children.

The browser check reopened QRO and UNO previews, submitted a new UNO cube
request, refreshed orbital metadata, and confirmed that unchanged files still
reused existing cubes. A full-resolution UNO was then rendered directly from
its stash through the shared viewer and rendering CalcJob. All 123 automated
checks passed in Python 3.12.11, AiiDA 2.9.2, AiiDAlab 26.9.0 and ipywidgets
8.1.8. Remote tigu execution and large-molecule accuracy/performance have not
been established by these local smoke tests.
