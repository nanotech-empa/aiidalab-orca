# Importing an external frozen-CASCI reference

Existing ORCA calculations can supply fixed orbitals for new native CASCI
calculations without repeating their geometry optimization or orbital
generation. This import has its own process type and appears in Search as
**Imported fixed orbitals**. It does not represent the original calculation
as an AiiDA execution or invent an SCF energy-level diagram.

The small `empa_orca.import_fixed_orbitals` WorkChain accepts a `StructureData`,
an external `RemoteData` directory, a source manifest, future ORCA settings,
and the export/helper codes on that computer. The manifest identifies three
original files by plain filename, byte count and SHA256: GBW, input and output.
It also records the original contiguous active space, every source root
energy, root count, and a description crediting the external calculation.
The reported orbital-generator method is supplied metadata; the importer
checks the basis against the native output, rather than claiming to recover
the preceding DFT calculation from a CASCI GBW.

A submitted CalcJob copies the three files into its own directory, exports
the GBW with ORCA, and checks the copies against the manifest. It verifies:

- molecular geometry, charge, multiplicity and all-electron basis metadata;
- one spatial orbital set, electron count and active-orbital orthonormality;
- normal termination, solved CASCI, unchanged active/internal/external
  orbitals, matching basis dimension and every original root energy.

Original files remain untouched. The imported GBW stays in the import job's
working directory; large JSON exports are removed after validation. Compact
validation metadata and the original input/output text are retrieved. A
separate storage CalcJob records the retained GBW's identity. Reuse checks
actual file availability and does not depend on AiiDA caching.

The app's result service opens the import as a reference with independent
orbital inspection and **States & Dyson** sections. New CASCI runs use the
same imported orbital ordering and the ordinary native workflows. Imported
CASCI occupations are labelled as source density-matrix diagonal elements;
they are not shown as DFT energies or automatically called natural orbitals.
New imported-reference CASCI forms start with a tighter `TPrintWF=1e-9`.
The subsequent Dyson CI-normalization checks remain strict.

An initial command-line/service entry point is available through
`aiidalab_orca.fixed_orbital_services.prepare_import` and `submit_import`.
An interactive external-file import form is future work. The current scope
requires an all-electron molecule through Kr, a contiguous frozen active
space, and remote working-directory storage. Re-import the original source
if the imported working files disappear; this reference has no native SCF
step that can be silently regenerated.

Andrés Ortega-Guerrero's A2n dataset is the intended larger test. Neutral and
anion orbital families remain separate references. The benchmark first
validates the ETRI recipe; no A2n spectrum is accepted solely because the
import or its software tests succeed.
