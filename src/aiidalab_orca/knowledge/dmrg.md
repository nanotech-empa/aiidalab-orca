# Native DMRG in the ORCA app

Open the app's **Native DMRG** tab. From a molecular result you can instead use
**Choose energy solver → Native DMRG** after confirming an even-electron active
space with at least three orbitals. Opening either route submits nothing.

This is native Block2 DMRG-CI, with fixed spatial orbitals, C1 orbital symmetry
and SU(2) singlets. It is separate from the Model Hamiltonians/ITensor app and
from QPU sampling. The neutral allyl CAS(3,3) is not supported by this singlet
recipe. Do not change its electron count or label it a singlet to pass a guard.

Select a completed validated Hamiltonian export, enter its UUID, or upload an
FCIDUMP and click **Use uploaded FCIDUMP**. An upload is limited to 16 MiB;
existing external exports keep their integrals outside the AiiDA repository.
**Load analytic CAS(2,3) example** stores an explicitly labelled noninteracting
fixture. Its lowest singlet energies are −2.0, −1.2 and −0.4 Ha. It is an
integration example, not a benchmark for strongly correlated molecules.

For a molecular result, **Export the confirmed active-space Hamiltonian** opens
the existing Hamiltonian-export form. Submit only its export/validation stage,
then return to DMRG and refresh the completed exports. No circuit or QPU step is
needed. Do not compare to an unrelated Hamiltonian with the same CAS size.

A configured Block2 **0.5.4** `block2main` code is required. Installation and code
registration belong to setup, rather than the molecular calculation form.
Choose the computer explicitly. Missing local software does not authorize a
remote submission. Resources are one native process with the selected number
of numerical threads, not multiple MPI ranks. The memory input is Block2's
`mem ... g` stack allocation; dynamic allocations also consume RAM.

Click **Review native DMRG** and inspect the CAS, roots, Hamiltonian checksum,
computer, M, ordering, threads, memory, wall time and exact Block2 input.
Changing a control invalidates review. **Submit reviewed DMRG** consumes that
review once. An identical active request is reopened; a completed identical
request is reused unless recomputation was explicitly selected. Another active
native job on that computer blocks dispatch.

Use **Native DMRG results** or **Open native result UUID**, then **Open result /
refresh**. Inspect root energies, excitation units, the 1-RDM electron trace,
sweep history and the separate convergence verdicts. Download the sweep SVG
and CSV. Exit 311 retains validated partial results and checkpoints but means
sweeps need further convergence. Exit 0 or a flat graph does not by itself
establish convergence with bond dimension. This GUI reports no rigorous
full-CAS error bound.

**Use this result as checkpoint** copies its Hamiltonian and settings into a
new draft, without modifying the old calculation. Retain/increase M for a
normal restart. Select **Continue one-site sweeps at the same M** only for a
completed one-site checkpoint, retaining roots, ordering and Hamiltonian.
Review and submit every continuation separately. Interrupted or unvalidated
MPS files are not promoted to valid checkpoints. Checkpoints must remain on the
same computer and must match the saved SHA256 manifest.

MPS files and full native output remain in their original calculation directory.
Only bounded sweep/density arrays, the manifest and the selected text-output
policy enter the retrieved folder. Keep the remote directory while its
checkpoint is needed. Setting **Native output retrieval (MiB) = 0** requests an
explicit summary/notice; it does not delete or truncate the native output.
Reopening a result or closing its browser tab must not restart it.

Manual cases L20–L21 are in `docs/testing/dmrg-localhost.md`. Follow the
campaign's source/preflight and start authorization. A unit test or backend
script cannot replace browser acceptance. Do not resume or edit old research
processes, install software, remove files, or change lifecycle flags merely to
make the GUI appear ready. Research recovery remains a separate explicit action.
