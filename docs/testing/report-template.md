# ORCA GUI acceptance report

Copy to a private working report. Do not commit personal instance details,
raw outputs, secrets or screenshots automatically.

- Run prefix:
- Operator (human / agent; application/model if relevant):
- Date/time and timezone:
- App instance (private reference):
- App/backend revision/version; how identified:
- Guide revision:
- Browser / OS:
- Authorized case IDs and exclusions:
- Local resource limits and actual ORCA/helper code choices:
- Optional remote computer/code, cases and resource limits, if authorized:
- Optional QPU provider/instance alias/backend, cases and job/shot/time budget:
- Optional export destination, creation/upload scope, if authorized:

## Reference register

| Reference | Workflow / prepared-reference UUID | Notes |
| --- | --- | --- |
| L01 original allyl geometry | | |
| L03 allyl SCF | | |
| L06 original prepared orbitals | | |
| L07 original CASCI sectors | | |
| L10 selected-state CASSCF | | |
| L11 state-average CASSCF | | |
| L13 formaldehyde geometry | | |
| L17 water geometry | | |
| L18 Hamiltonian / circuits / samples | | |

## Case register

Initial status is NOT RUN. Use PASS, FAIL, BLOCKED or SKIPPED only with evidence
or a reason. Add separate rows for subcases and individual remote requests.

| Case | Status | Submitted / reused UUID(s) | Observations / evidence |
| --- | --- | --- | --- |
| L00 Launch/context | NOT RUN | | |
| L01 Allyl geometry/PDOS | NOT RUN | | |
| L02 Viewers/PDOS/navigation | NOT RUN | | |
| L02-IMPORT XYZ/saved geometry | NOT RUN | | |
| L03 SCF/review/reuse | NOT RUN | | |
| L04 Constraints | NOT RUN | | |
| L05 KS cubes/views/render | NOT RUN | | |
| L05-DELETE optional cube retention | NOT RUN | | |
| L06 QRO/UNO/CAS | NOT RUN | | |
| L07 CASCI/batch/diagram | NOT RUN | | |
| L08 Dyson/spectra/maps | NOT RUN | | |
| L09 Kondo channels/maps | NOT RUN | | |
| L10 Selected-state CASSCF | NOT RUN | | |
| L11 State-average CASSCF | NOT RUN | | |
| L12-SC | NOT RUN | | |
| L12-FIC | NOT RUN | | |
| L12-DLPNO | NOT RUN | | |
| L12-TIGHT | NOT RUN | | |
| L12-CASPT2 | NOT RUN | | |
| L13 Formaldehyde | NOT RUN | | |
| L14 IR/Raman | NOT RUN | | |
| L15 TDA/NTO | NOT RUN | | |
| L16 TDDFT/triplet controls | NOT RUN | | |
| L17 Water/MP2 core controls | NOT RUN | | |
| L18 Ideal simulator/energy comparison | NOT RUN | | |
| L18-DMRG GUI coverage | NOT RUN | | |
| L19 Output policy/reopening | NOT RUN | | |
| L19-STASH optional local stash | NOT RUN | | |
| R01–R04, separate rows if authorized | NOT RUN | | |
| Q01–Q03, separate rows if authorized | NOT RUN | | |
| E01–E02, separate rows if authorized | NOT RUN | | |

## Evidence for each executed case

### CASE-ID

- Start/end time:
- Prerequisite UUIDs and actual model/settings:
- Review evidence (operation, code/computer/resources, storage):
- Workflow, child/result UUIDs; provider job ID separately if applicable:
- What was observed through the GUI:
- Expected versus observed; warnings and exact diagnostic text:
- Screenshot/download references (private):
- Separate maintainer read-only verification, if performed:
- Outcome and dependent cases stopped:
- How to reopen results (entry point and UUIDs):
- Completed-test tabs closed; any retained test tabs and why:

## Handoff / release assessment

- Last completed case and next authorized case:
- Running jobs to preserve:
- Failures/blockers and reproduction steps:
- Skipped/unverified scopes and why:
- Scientific rejection versus software-guard behavior:
- Decisions needed from user/maintainer:
- Release claims supported by this run; claims it does not establish:
