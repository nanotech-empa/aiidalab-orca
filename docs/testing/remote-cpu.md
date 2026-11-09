# Optional Remote CPU tests

Start with [the test contract](README.md). These cases are separate from the
default localhost route. The user must authorize the named case(s), configured
computer/code, CPU/memory/wall-time limits and maximum number of submissions.
Do not infer permission from a remote code appearing in a dropdown.

For a first smoke test the suggested scope is **R01–R02 only**: one small allyl
optimization/PDOS workflow, two CPU cores, 2 GiB and ten minutes, provided the
configured scheduler supports those requests. Record the actual review.

## R01 — Discovery and resource review

**Submits:** nothing.

1. Select the approved visible remote ORCA code in a new draft.
2. Prepare the L01 allyl model, PBE/def2-SVP, charge 0/multiplicity 2.
3. Set approved resources. Review the effective input, computer/code and
   scheduler-related settings actually exposed by the app.
4. Check that a local/direct-only restriction does not hide an otherwise
   compatible configured code. Do not configure computers or rewrite wrappers.

**PASS:** identifiable configured remote execution can be reviewed. If queue
or account details are not exposed in the GUI, record that limitation; a
maintainer may verify them separately in AiiDA.

## R02 — Remote geometry and stored results

**Needs:** R01 and explicit submission authorization. **Submits:** one remote
geometry workflow and its authorized automatic PDOS child.

1. Label `<prefix>-R02 remote allyl`. Keep full files **Leave on the calculation
   computer**, not an assumed path on the browser user's laptop. Keep 5 MiB output.
2. Confirm the automatic PDOS helper has the correct execution context and
   approved budget. Otherwise record PDOS BLOCKED; do not choose an arbitrary
   Python executable or install one.
3. Submit once, record the UUID and follow status. Distinguish queued/waiting,
   running, transfer and completed/failed states where exposed.
4. Inspect geometry, energy, warnings and PDOS as in L01–L02. Reopen the entry
   in another app session.

**PASS:** execution on the approved computer and durable results. Equal
SMILES-generated conformers need not have identical coordinates: impose exact
local/remote comparisons only for the same fixed geometry and model. Maintainer
checks cover actual scheduler requests and full-file exclusion from retrieved.

## R03 — Remote postprocessing

**Needs:** R02 and authorization for its postprocessing jobs.
**Submits:** one orbital preview and optionally one saved-view render.

1. Open **Orbitals & density** from R02 and select one frontier orbital.
2. Review inherited electronic-file retention and compatible helpers. Keep
   80-point grids and full cubes **Leave**; submit the reviewed cube stage.
3. Inspect/download the reduced preview. If authorized, save a view and render
   a small image using the approved configured renderer.
4. Rendering on another computer needs a supported source-transfer path. Do
   not fetch full cubes to AiiDA as a workaround.

**PASS:** explicit source identity/location and reduced data, with no new
full-file retrieval. Inaccessible SSH/storage must not silently trigger SCF
recomputation or a claim that the wavefunction was deleted. Ask the user to
renew expired authentication instead of changing SSH identities.

## R04 — DMRG and further remote methods

The standard GUI currently has no general DMRG submission route. Record this
as **BLOCKED** if remote DMRG browser acceptance is requested. Terminal-submitted
WorkChains are separate evidence; see [DMRG rules](../dmrg.md). Preserve active
research jobs and do not play historical jobs with full-MPS retrieval plans.

Other local cases may be repeated remotely only when their IDs, helpers and
budgets have been explicitly authorized. This section grants no blanket HPC run.
