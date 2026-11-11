# DMRG checkpoints and convergence

Native Block2 0.5.4 runs through a submitted CalcJob on a configured computer.
The current recipe uses a preserved restricted-orbital FCIDUMP, SU(2) singlets,
and one or three roots. It does not optimize the orbitals. Hamiltonian identity,
root densities, saved-state expectations and individual-root sweep convergence
are checked independently of convergence with bond dimension.

## Browser entry and local qualification

Use **Native DMRG** in the main app, or **Choose energy solver → Native DMRG**
after confirming a supported molecular active space. The form accepts an explicit
FCIDUMP upload/data UUID or a completed validated exported-model UUID. New
external Hamiltonians use the shared immutable descriptor/staging contract;
integrals stay outside the AiiDA repository. Historical SinglefileData callers
remain supported. Review/submission and each continuation are separate actions.
See [the GUI guide and scientific checks](testing/dmrg-localhost.md) and the
packaged `orca.dmrg` assistant guide. The analytic control does not establish
large-system convergence. Runtime installation/registration belongs to setup.

## Storage and restart

New jobs leave full MPS checkpoints and the complete native output in their
remote calculation directory. The retrieved folder contains only whitelisted
energy/sweep/density arrays, a storage record, and the native text output.
Each array is limited to 2 MiB. Text output up to `maxsizeoutput` (default
5 MiB) is retrieved unchanged. Larger output uses an explicit notice under
`dmrg.out` and a separate `dmrg_summary.out`; the original remains remote.
`verdi calcjob outputcat` shows the original or that notice. Scientific arrays
are never truncated. Missing/oversized arrays or a failed collector stop
acceptance. The collector needs POSIX utilities, with no Python-job selection.

The CalcJob's `remote_folder` is the checkpoint reference. A continuation takes
this RemoteData as `parent_states` and copies `mps` within the same computer.
A small SHA256 manifest identifies all MPS files. Before Block2 starts, the
copied files must match the source manifest. Historical checkpoints derive
this manifest from their immutable AiiDA repository hashes. Cross-computer copying is rejected. Its creator must be a completed native DMRG
calculation with validated results; Hamiltonian, roots, ordering and Block2
format must match. Fixed-M sweep continuation additionally requires a completed
one-site checkpoint and the same M. An interrupted sweep is not accepted as a
validated restart state.

Convergence WorkChains return `states` as RemoteData for new runs. Historical
FolderData checkpoints remain valid inputs; old scientific nodes are not
rewritten. WorkChains never clean a new remote checkpoint, even if their
legacy `clean_workdirs` input is true. Remote retention depends on the host's
scratch-cleanup policy; preserve the directory while it is needed. This route
leaves files in place and does not configure stashing automatically.

Existing paused jobs keep their original immutable retrieval plans. To adopt
the new policy, create a provenance-linked continuation from the last validated
checkpoint and preserve the old paused processes. Do not play a legacy job
that would recursively retrieve MPS under the new storage policy.

## Acceptance before continuing a large system

Compare a small native result with the established reference, then restart
from its RemoteData. Require unchanged energies, the original normalization
and expectation checks, no MPS files in retrieved, and a same-computer remote
copy in the continuation. An explicit forced-summary control also checks the
output-size policy. Sweep convergence at fixed M is required before increasing
M; exhausting the extension budget stops with the retained checkpoint.

## Native runtime helper

Run `python scripts/check_dmrg_runtime.py` with the intended Block2 interpreter
(or provide `--executable` for its exact launcher). It reads distribution metadata
and hashes the owned launcher without importing Block2, running a calculation,
opening an AiiDA profile or installing/registering anything. `METADATA_OK` is
only a packaging prerequisite. Record the official wheel/tag checksum separately;
a matching version string does not establish artifact identity, ABI compatibility
or a successful native run. Actual L20/L21 browser results supply that evidence.
