# Exporting stored ORCA results to openBIS

Open **Export to openBIS** in the Results navigation. ORCA passes the entry's
geometry/SCF workflow UUID directly to the common exporter, as in the QE app.
The experiment, molecule and material selectors are part of that same form.
There is no separate ORCA result picker or intermediate review button.

Choose the destination and review the complete entry together: geometry/SCF,
PDOS, orbital references, CASCI, vibrations, Dyson/Kondo results, cubes, maps and
saved figures where available. The exporter follows stored AiiDA provenance at
the exact final geometry, including independent analysis workflows. A different
optimized geometry is a separate entry; matching formulae or names do not link
calculations. **Refresh entry results** refreshes the combined review. If the
result set changes after review, export stops and asks for a fresh review.

Each result uses its pertinent scientific category. One explicit **Export to
openBIS** action publishes the reviewed entry with the shared experiment and
molecule selections, provenance mapping, preview, duplicate and retry controls.
Opening the workspace, choosing a destination and refreshing the review do not
publish anything.

The exporter publishes what is already stored in the AiiDA database/repository.
Reduced cubes, numerical maps, figures and any already-retrieved wavefunctions
are preserved in the archive. Full files left on scratch or in a stash remain
external references. Export does not retrieve, stash, regenerate or calculate
anything. Import restores the stored data and UUIDs; remote dependencies may
still be unavailable on the receiving machine.

Geometry/SCF, DOS and harmonic IR/Raman use the existing dedicated openBIS types.
Orbital cubes and spatial maps, including **Dyson and Kondo**, use
`SPM_SIMULATION` with orbital-kind/source settings preserved. UNO occupations
are not an energy DOS. Complete CASCI state tables, Dyson transition data and
Kondo exchange matrices use the labelled `UNCLASSIFIED_SIMULATION` fallback
until a separate searchable schema is reviewed. XPS/research workflows without
an exporter are not advertised as supported.

The optional shared component must contain `aiida_openbis.export` and its ORCA
adapters. ORCA can also load this bridge directly from the installed
`apps/aiidalab-openbis` checkout, without reinstalling its legacy chatbot stack.
No openBIS dependency is required to run ORCA calculations. The existing
modern openBIS development stack remains separate from this ORCA component;
installing ORCA alone does not deploy or migrate the openBIS server schema.

The authoritative target model is maintained in
[aiidalab-openbis/docs/openBIS_schema_documentation.md](https://github.com/nanotech-empa/aiidalab-openbis/blob/feature/orca-simulation-export/docs/openBIS_schema_documentation.md).
Schema additions must update that document together with the simulation guide,
Python/LinkML definitions, provisioner and agent instructions. This first adapter
uses existing object/property types and does not require a schema migration.

Each main workflow retains its own single-root archive and scalar `WFMS_UUID`.
The whole-entry action creates or reuses all these records together. For a
complete workspace on import, select the entry's source geometry, references,
states and spatial records together. Shared AiiDA UUIDs reconnect their archived
provenance; exporting a whole entry does not invent a synthetic workflow parent.
