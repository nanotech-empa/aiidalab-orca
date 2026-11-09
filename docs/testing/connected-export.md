# Optional connected-export acceptance

This is separate from localhost science, Remote CPU and Remote QPU. Read
[the common contract](README.md) and [the export guide](../openbis-export.md).
An incompatible/pending exporter release or inaccessible service is BLOCKED;
do not patch another repository or modify a live schema from this browser test.

## E01 — Shared form and whole-entry review

**Needs:** completed local branches, configured read access and authorization to
open the intended test-service selection form. **Publishes:** nothing.

1. From L01 open **Analysis / results → Export to openBIS**.
2. Inspect the common form, workflow identity, related stored analyses and category
   mapping. Do not replace it with an unrelated per-widget export script.
3. Check experiment/molecule/destination selection is present. Use only the
   destination and existing entities supplied by the user.
4. Review the geometry/SCF, orbital/PDOS, CAS/CASSCF, correlation, spectroscopy
   and SPM/Dyson/Kondo results actually present. Separate molecule entries
   remain separate exports; absent analyses must not be invented.
5. External full-file references remain external. Export must not retrieve full
   wavefunctions/cubes/MPS, regenerate properties, or include credentials.
6. Stop before final publication. Distinguish visible checks from maintainer checks.

**PASS:** a usable common form and coherent stored-only whole-entry review.

## E02 — Authorized test-server publication

**Needs:** E01 and explicit destination/entry, object/dataset-creation and upload
authorization. Do not choose an arbitrary production experiment as a test target.

1. Recheck destination, molecule relationships, categories and data scope.
2. Publish once through the common GUI; record permanent identifiers.
3. Open server objects/datasets and inspect relationships/compact file lists.
   Distinguish this from a locally prepared archive.
4. Reopening/reviewing must not silently duplicate objects. Do not interrupt
   uploads or delete server data to test recovery without a dedicated fixture.

**PASS:** one traceable coherent export without unexpected full-file transfers.
