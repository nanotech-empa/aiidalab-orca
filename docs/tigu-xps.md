# Fixed-geometry XPS on tigu

The ORCA SCF and geometry workflows accept local/direct execution and Slurm
through SSH. The initial tigu deployment uses the existing ORCA 6.1.1 x86-64
installation. The queueing check completed a two-process native ORCA CalcJob;
this is an installation check, not validation of a complete molecular spectrum.

## Fresh electronic calculations from an existing geometry

Select an optimized `StructureData`, choose `orca@tigu`, and disable geometry
optimization. The new SCF uses that exact stored structure as an input. It
creates a new tigu electronic reference; no local GBW or CAS reference needs to
be transferred. Results retain the link to the original optimized geometry.
Further XPS preparation uses only this new reference and its actual files.

For the CoPc test, the prepared resources are one node, **12 MPI processes**,
24 GiB memory and four hours for each native ORCA calculation. Serial helper
CalcJobs use one process. The ORCA driver runs once; ORCA's PAL block starts the
MPI modules. The prepared stages run sequentially. The current Slurm default
partition is `debug`; no Daint account or QoS is copied into this setup.

1. Fresh PBE/def2-TZVP UKS single point, neutral doublet, at the stored geometry.
2. Fresh common orbitals, AVAS character checks and SA-CASSCF(9,6), with the
   existing fixed-grid Co protocol and 70 doublets / 20 quartets.
3. Energy-preserving natural orbitals, Co core assignment and RAS-CI/SOC.
4. Nitrogen 1s convergence pilot with both spin-removal branches, followed by
   the previously selected C/N representatives. This is not complete atom-site
   coverage. Successful tigu branches can be reused by provenance and actual
   file availability.

The numerical/reference guards remain active. The doublet/quartet ordering is
still a model question; a spectrum based on the selected doublet is provisional
until that question is assessed. See [the Co protocol](cobalt-xps.md).

## Leave electronic files where they were generated

Choose **Leave files in calculation directories** in the wavefunction storage
controls. The corresponding backend policy is `{"mode": "remote"}`. The
existing size-dependent retrieval/stash policy remains the default.

A serial helper CalcJob hashes the original files and retrieves a small
manifest. It makes no electronic-file copy and configures no AiiDA stash.
Original GBW/density files remain in their producing calculation directories;
only text, parsed data and manifests are retrieved. A new optional
`electronic_remote` output identifies the original folder. Downstream steps
use normal AiiDA remote staging and retain their working files as well.
The Dyson export step follows this policy too: its compressed wavefunction
export stays in the export CalcJob directory, with only the compact artifact
metadata retrieved. Automatic preservation retains its existing behaviour.

Reuse checks the original files. A manifest alone is not evidence that a lost
scratch file is still available. Missing files require regeneration; an
inaccessible host remains an availability error rather than evidence of file
loss. Existing immutable records are not modified.

## Helper runtime and readiness

The `orca-tools` code is a narrow runner for allowlisted CalcJob scripts,
not a generic PythonJob or a user-selected Python executable. On tigu, it uses
an isolated standalone CPython 3.12 runtime because the system Python is 3.8.
No AiiDA installation is needed on tigu. Software setup and read-only checks
are separate from scientific submissions.

Cube inspection additionally needs NumPy and ASE. The versioned numerical
runtime provides these alongside Dyson processing and cubehandler. The
`orca-tools-numerical@tigu` code uses that runtime; the earlier standard-library
helper is hidden from new selections but remains available to its historical
CalcJobs. Hidden helper codes are excluded from automatic runtime selection.

The prepared CoPc plan requires explicit user approval before any molecular
submission. It does not automatically launch jobs when imported or reviewed.
A concurrent assistant-panel checkout is retained unchanged. For this prepared
run, the validated checkout can be selected with a command-scoped `PYTHONPATH`
and an AiiDA runner without broker submission; child WorkChains and CalcJobs
then run with the same source, without changing another session's live app or
daemon. The resulting provenance nodes remain visible through the ordinary
ORCA app search and result services.

## Job-local MPI backing files

A geometry job failed with a missing MPI shared-memory backing file. Another
running job had mappings to deleted `/dev/shm/osc_sm...` files. The host's
`RemoveIPC` configuration makes cleanup on the last logout a plausible cause;
the exact cause of the crash is not established.

The separate `orca-job-scratch@tigu` code uses the same ORCA 6.1.1 executable
and Open MPI 4.1.1 as `orca@tigu`, with these additional prepend commands:

```sh
ORCA_MPI_DIRECTORY="$PWD/.mpi-shm"
mkdir -m 700 -p "$ORCA_MPI_DIRECTORY"
export OMPI_MCA_osc_sm_backing_directory="$ORCA_MPI_DIRECTORY"
export OMPI_MCA_btl_vader_backing_directory="$ORCA_MPI_DIRECTORY"
export OMPI_MCA_shmem_mmap_backing_file_base_dir="$ORCA_MPI_DIRECTORY"
export OMPI_MCA_shmem_mmap_relocate_backing_file=1
```

These parameter names were checked against the installed `ompi_info`. The
directory is private to each CalcJob and remains inside its working directory.
The original code, system configuration and scientific inputs are unchanged.
This is a host-specific runtime configuration; check the installed MPI
parameters and scratch filesystem before adopting it elsewhere.

A six-process water HF/def2-SVP CalcJob terminated normally and reproduced
the earlier two-process energy exactly at the printed precision:
−75.959340313442 Hartree. Its AiiDA UUID is
`f2fe092d-8030-4dac-bb1d-3e67d5536338`. The approved ETRI triplet optimization
uses this separate code; longer-run validation is still in progress.

Independent remote NO postprocessing also completed through submitted
CalcJobs: exchange analysis, Kondo cubes, cubehandler reduction, constant-height
maps and PNG/PDF figures. The remote/local intensity-array relative L2
difference was `2.22e-16` for that test. This checks the remote numerical
pipeline, not the physical applicability of a Kondo model to NO or convergence
of a larger molecule's charged-state manifold.
