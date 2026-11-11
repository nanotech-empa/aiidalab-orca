# ORCA full GUI acceptance test

This is the shared test route for a person or an AI agent operating the app in
a browser. Start here, select an authorized scope, and execute one numbered
case at a time. These instructions test the application that is actually
installed, not a notebook recreated with Python. Reading this guide does not
authorize every calculation it describes.

The first observed Desktop/Chrome run should execute **L00 and L01 only**, then
stop for review. Use [the agent handoff](agent-handoff.md) to start it.

## Close completed-test tabs

After each completed case, record its outcome, UUIDs and how to reopen it in
the existing report or chat, then close browser tabs belonging only to that
case. Include temporary image/export tabs and superseded ORCA sessions. Reuse
the current session for the next case when appropriate. Keep tabs needed by
active tests, unsaved drafts, job monitoring or pending user review; preserve
unrelated tabs. Check the remaining tabs before continuing and state why any
completed-test tab is retained. Closing a tab must not cancel a job or shut
down a kernel. This housekeeping does not require creating another report.

## Choose the scope

| Section | Default? | Execution and authorization |
| --- | --- | --- |
| [Localhost](localhost.md) | Yes, for the explicitly requested case(s) | Small molecules; normally one calculation at a time, at most two CPU cores and 2 GiB requested memory per calculation. No real QPU access. |
| [Remote CPU](remote-cpu.md) | Optional | Requires the user's named computer/code, resource limits and approved cases. A local failure never authorizes moving work to a remote computer. |
| [Remote QPU](remote-qpu.md) | Optional | Requires separate provider/backend, shot, job-count and time-budget authorization. A simulator test is not permission to use hardware. |
| [Connected export](connected-export.md) | Optional | Reviewing the configured openBIS form and publishing data are separate scopes. Real publication needs an approved destination and explicit authorization. |

XPS is excluded from this acceptance campaign. Resonance Raman and other
unimplemented routes are not implied by the full-test title. DMRG and QPU are
included in the coverage matrix; a missing GUI route must be recorded as
blocked, not replaced by a backend script.

## Before the first click

1. Agree on a unique run prefix, e.g. `GUI-20261109-DESKTOP-A`, the cases to run,
   and the resource limits. Use labels `<prefix>-L01 allyl geometry + PDOS`, etc.
2. Open a fresh app session from the AiiDAlab homepage. Preserve existing drafts,
   calculations and browser sessions. Do not edit numbered notebook copies.
3. Record the installation/revision supplied by the maintainer, browser, date,
   available local codes and requested scope in a copy of
   [the report template](report-template.md). If a revision is not exposed in
   the GUI, record that it was supplied externally or remains unknown.
4. Use visible configured codes whose review identifies the local computer.
   `orca@localhost` is an example on the development instance, not a required
   code label. Record the actual choice. Installation, computer configuration
   and scheduler wrappers belong to setup, not this browser test.
5. Keep full files **Leave on the calculation computer** unless a case explicitly
   tests stashing. Keep **Output retrieval → maxsizeoutput (MiB) = 5** except in
   L19. These policies are independent of the compact PDOS data retained in AiiDA.

Memory fields are requests, not hard operating-system limits on every local
scheduler. The cases deliberately use small systems. Do not run other benchmark
jobs in parallel or increase resources because a job seems slow. If the approved
wall time is reached, preserve the result, record the failure and stop that branch.

## Test molecules and branches

| Model | SMILES | Charge / multiplicity | Purpose |
| --- | --- | --- | --- |
| Allyl radical, C3H5, 8 atoms | `C=C[CH2]` | 0 / 2 | Geometry, PDOS, KS/QRO/UNO, CAS(3,3), Dyson/Kondo, CASSCF, correlation and ideal-simulator integration |
| Formaldehyde, CH2O, 4 atoms | `C=O` | 0 / 1 | Independent closed-shell geometry, six vibrational modes, IR/Raman, optical response/NTO integration |
| Water, H2O, 3 atoms | `O` | 0 / 1 | Fresh-HF RI-MP2 and frozen-core controls |

SMILES generates starting conformers; it does not supply an optimized or
literature geometry. In particular, these generated optical examples are
integration checks. The exact pyridine/manual reference remains separately
documented in [the optical fixtures](../../tests/fixtures/optical/README.md).
Do not claim a literature reproduction from a different geometry.

The allyl KS, prepared-orbital and CASSCF references are distinct. Keep their
UUIDs in the report. Use the original L01 geometry for its property branches;
L04 constraints and L19 retention controls create separate entries. For current
Dyson/Kondo, all charge sectors must share the selected orbital reference.

## What to record for every case

- Case ID, scope, actual settings/code/computer, result and observation time.
- Submitted workflow UUID and relevant child/result UUIDs when visible. Do not
  confuse a local PK, an orbital index or an external provider job ID with a UUID.
- One useful screenshot of review/result, or the exact visible error. Save
  downloads and screenshots under the private test report, not automatically in Git.
- Expected versus observed behavior, warnings, and whether a new calculation
  ran or an existing result was reused. A copied historical result is not a new
  submission test.

| Status | Meaning |
| --- | --- |
| NOT RUN | No attempt yet. This is the initial status for all cases. |
| PASS | All case criteria were actually observed. |
| FAIL | Observed behavior contradicts a criterion; include evidence. |
| BLOCKED | A prerequisite, configured code, GUI feature or access is missing. |
| SKIPPED | Deliberately outside the agreed scope; give the reason. |

A scientific rejection and a software failure are different observations. For
an explicitly expected-rejection test, PASS means the correct guard rejected
the input and explained why; it does not validate that scientific result.
Unexpected native warnings must not be relabelled as an expected rejection.

## Rules while executing

- Operate calculation setup, review, submission, selection and downloads through
  the visible GUI. For browser acceptance, do not call services, AiiDA APIs or
  Python scripts to manufacture the result. Do not use a browser console to
  bypass a disabled control. Maintainer checks below are a separate layer.
- Reading the source/guide is allowed; changing code, dependencies, profiles,
  branches, daemon state or remote files is outside this test. Stop and report
  a discrepancy between the guide and the installed UI.
- Review before submission. Editing inputs must invalidate review. Navigation,
  filtering, changing plot ranges and refreshing must not submit calculations.
- Use the app's refresh controls, normally every 15–30 seconds while waiting.
  Do not repeatedly submit or reload Chrome to force progress. An uncertain
  submission must be resolved by its recorded UUID before retrying.
- If a case fails, preserve it and stop dependent cases. Independent molecule
  branches may continue only within the scope already authorized. Never loosen
  validation, add shifts, choose a different state or rerun repeatedly to obtain PASS.
- Never put an API key into chat, code, report, notebook cells or screenshots.
  Credential entry is a user action in its dedicated form; see Remote QPU.

## Coverage and release interpretation

The local route covers the ordinary geometry/electronic/spectroscopy paths,
viewers, a simulator, storage controls and reuse. Remote CPU qualifies a
different configured execution environment. Remote QPU qualifies provider
integration and measurement handling, not quantum advantage or universal accuracy.

DMRG workflow tests currently exist, including remote-checkpoint controls, but
the standard energy-solver GUI does not yet expose a general DMRG submission
route. L18 therefore records that GUI gap. It cannot be counted as a completed
browser test merely because a maintainer ran a DMRG WorkChain.

An unexecuted optional section is not a failure of the local route, and is also
not coverage of that feature. If a release advertises a feature, its unresolved
FAIL/BLOCKED cases need an explicit release decision. Browser PASS does not
replace the automated/native scientific checks or a fresh-install qualification.
Consult [release readiness](../release-readiness.md) for those separate gates.

## Separate maintainer verification

After the browser operator supplies a UUID, a maintainer may inspect AiiDA
read-only to verify native convergence, parsed/raw agreement, actual scheduler
resources, provenance and absence of full electronic/cube/MPS files in retrieved.
Check original-versus-summary manifests and preserved compact arrays. Record
these observations separately in the report; do not attribute them to Chrome.
If GUI-only evidence cannot establish something, write **not verified in GUI**.
Existing scientific nodes, repositories and their provenance must remain unchanged.
