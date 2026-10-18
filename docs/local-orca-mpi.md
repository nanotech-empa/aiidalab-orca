# Local ORCA MPI installation and validation

Use the Open MPI version named by the licensed ORCA distribution. The local
Linux ARM64 ORCA 6.1.1 package requires Open MPI 4.1.8. Install that runtime
with **Fortran support enabled** and use its `mpirun` and shared libraries
together. This does not require access to ORCA source code.

## Why Fortran support is required

ORCA's parallel startup calls `MPI_Type_match_size`. Open MPI resolves this
operation using its Fortran numeric datatypes, including when the caller is
C or C++. Disabling Fortran support can make otherwise ordinary numeric-type
requests fail with `MPI_ERR_ARG`. See the
[Open MPI documentation](https://docs.open-mpi.org/en/main/man-openmpi/man3/MPI_Type_match_size.3.html).

The original local runtime was built with `--disable-mpi-fortran`. A small
HF water test passed, but the 8-process pentacene PBE0/def2-SVP calculation
failed during RI-J integral startup, before SCF iterations. A standalone
probe independently reproduced missing integer, real and complex datatypes.
Memory availability and the molecular input did not explain that startup
failure. The failed AiiDA run must remain preserved as historical evidence.

## Build the matching runtime

Use a native C, C++ and Fortran toolchain, for example Ubuntu's `gcc`, `g++`
and `gfortran` from the same compiler release. Confirm that each targets
`aarch64` in a native Apple Silicon Linux container. Remove inherited Conda
compiler/linker flags for this build; do not change global shell defaults.
Install to a new prefix instead of overwriting a runtime used by saved jobs.

For an unpacked Open MPI 4.1.8 source tree, an example build is:

```bash
mkdir build-orca-mpi
cd build-orca-mpi
env -u AR -u AS -u BUILD -u CFLAGS -u CPPFLAGS -u HOST -u LD -u LDFLAGS \
  -u FFLAGS -u FCFLAGS -u LIBRARY_PATH -u CPATH \
  CC=/usr/bin/gcc CXX=/usr/bin/g++ FC=/usr/bin/gfortran F77=/usr/bin/gfortran \
  ../openmpi-4.1.8/configure --prefix=/absolute/path/openmpi-4.1.8-orca \
  --enable-mpi-fortran --disable-oshmem --without-verbs --without-ucx \
  --without-libfabric --with-hwloc=internal --with-libevent=internal \
  --with-pmix=internal
make -j4
make install
```

Adapt paths to the installation. If using extracted Ubuntu compiler packages
without root access, verify the Fortran frontend, linker search paths and a
compiled Fortran executable first. Record the package versions and hashes.
Do not substitute a different AiiDA/Python environment to build MPI.

## Validate before enabling the code

Set `PATH`, `OPAL_PREFIX` and the platform's shared-library path for the new
MPI prefix in a command-scoped environment. On Linux use `LD_LIBRARY_PATH`.
Check the full resolved dependencies with `ldd` on `orca_startup_mpi`.
`mpirun` and `libmpi` must resolve to the same matching installation.

Compile the repository's numeric-type probe with that installation's `mpicc`:

```bash
/absolute/path/openmpi-4.1.8-orca/bin/mpicc -std=c99 -Wall -Wextra \
  scripts/check_orca_mpi.c -o /tmp/check-orca-mpi
/absolute/path/openmpi-4.1.8-orca/bin/mpirun -np 8 /tmp/check-orca-mpi
```

The probe must exit successfully on every rank. Also inspect `ompi_info` to
confirm that Fortran was enabled. Version strings alone are insufficient.

Register a new AiiDA `InstalledCode` with the corrected environment, preserving
the old code and runtime. Run equivalent serial and 8-process **PBE0/def2-SVP
RIJCOSX** water calculations through the app submission service and daemon.
Require normal termination, parsed energies matching raw output, preserved
wavefunction files, correct process counts and serial/parallel energy agreement
within 1e-7 Hartree. This small-system agreement validates the installation,
not convergence of a molecular spectroscopy protocol.

The reusable app-submission check performs these serial and parallel runs,
stores their UUIDs and measured energies in JSON, and fails on an incomplete
or inconsistent result:

```bash
python scripts/validate_orca_installation.py --code orca-mpi418-fortran@localhost \
  --processes 8 --output /absolute/path/new-orca-validation.json
```

Run it with the existing AiiDAlab interpreter and profile, with the daemon
running and the ORCA tools code configured on the same computer. The output
path must be new. A timeout records the workflow UUID and does not kill a
calculation; inspect its state before starting another validation attempt.

Only after these checks should the corrected code become the default local
ORCA choice. Keep `withmpi=False` in the AiiDA calculation: ORCA launches its
own MPI processes from `%pal`. Set BLAS/OpenMP threads explicitly to avoid
oversubscription. Retry pentacene as a new app workflow with unchanged
scientific settings and caching bypassed; never rewrite the failed run.

For future installations, retain the configure command, compiler and MPI
versions, probe results, AiiDA UUIDs and energy comparison. Include the RI-J
startup path in installation checks rather than relying solely on an HF run.

## Verified local repair, 2026-10-18

On Linux ARM64 with ORCA 6.1.1, Open MPI 4.1.8, native GCC/GFortran 13.3.0,
Python 3.12.11 and AiiDA 2.9.2:

- The numeric-type probe rejected the original no-Fortran runtime and passed
  with the corrected runtime on 8 ranks.
- Serial water workflow `5e692e08-8e2d-4f25-8714-eacc858d4e9b` and 8-process
  water workflow `e54eb797-76e3-4d92-94e4-3f19749bec89` both gave
  -76.275307512612 Hartree. Raw/parsed differences were about 2e-12 Hartree;
  wavefunctions were preserved in the repository and no CalcJob came from cache.
- Pentacene workflow `14cb1608-28e5-4eb7-9b51-d02918731749` finished with the
  same geometry and scientific settings as failed workflow
  `8b9d58f6-c092-4902-a6aa-4c5c3e10c6c8`: neutral singlet, frozen geometry,
  PBE0/def2-SVP RIJCOSX, 378 basis functions, 8 processes and a 16 GiB budget.
  It converged to -845.189358392250 Hartree in 22.661 seconds of ORCA time
  (27.251 seconds for the app workflow including preservation), with a
  4,785,314-byte wavefunction bundle preserved in the repository. Normal app
  search and Results, including the orbital energy-level viewer, were checked
  in the browser. This validates the repaired startup, not CASCI/Dyson spectra
  or reproduction of the reference publication.

The live instance currently reports AiiDAlab 26.6.0, below the app's declared
26.9.0 floor; `pip check` reports that mismatch. The MPI repair did not change
Python packages or that requirement. This observed environment limitation
must not be interpreted as a supported-platform policy change.
