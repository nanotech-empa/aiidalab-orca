# Wavefunctions, orbital levels and cubes

This local prototype connects the existing SCF/geometry result to small,
independent preservation and orbital-property components. It currently targets
ORCA 6.1, a local direct scheduler, and HF/DFT references. These are ordinary
reference orbitals, not natural or Dyson orbitals.

## Wavefunction policy

The submission panel enables **Preserve wavefunction files** when a local Python
code is configured. The default threshold is **100 MiB for the complete bundle**:
`aiida.gbw`, `aiida.densities`, and `aiida.densitiesinfo`. Smaller bundles are
retrieved into AiiDA; larger ones use native AiiDA `stash_mode=copy`. The user can
change the threshold and stash directory, initially `~/orca-stash` on localhost.
The application records file sizes and SHA-256 checksums in a manifest.

Preservation is an independent `empa_orca.electronic_storage` CalcJob, linked to
the actual producing calculation's `RemoteData`. Both geometry and SCF WorkChains
accept optional `storage_policy` and `storage_code` inputs. Python callers can use
`aiida_empa_orca.artifacts.storage_builder(remote, python_code, policy)`; it sets
native stash options before AiiDA stores the node. The runtime rechecks the size
decision and fails if files changed before copying.

Stashing creates a separate copy. It does **not** delete the original files or
clean the calculation directory. Choose a stash filesystem with an appropriate
retention policy; a stash on the same disposable scratch filesystem does not
protect against that filesystem being cleaned. This local milestone does not
configure Daint or copy data between computers.

Reuse searches provenance and checks the files, independently of AiiDA caching.
Repository copies are checksum-verified. Stashed files are checked for presence
and size, then checksum-verified after staging for use. If original scratch has
disappeared, a valid repository or stash copy can supply the property calculation.
An inaccessible storage system is reported as unavailable, not treated as proof
of deletion. Preservation failure does not hide already completed scientific
results; those results carry an explicit storage warning.

## Orbital energy viewer

SCF and geometry results show horizontal bars: blue for alpha, red for beta,
solid for occupied and dashed for unoccupied levels. Restricted references use
one spatial-orbital column. Counts identify bars that overlap within the line
width at the current vertical scale; they do not assert exact degeneracy.
Changing the energy limits recomputes the groups. Individual indices, energies
and occupations remain available in an expandable table and hover text.

The initial limits are always **HOMO − 1 eV to LUMO + 1 eV**, using the highest
occupied and lowest unoccupied levels across spin channels. These are ORCA orbital
energies, not excitation or electron-addition/removal energies. New calculations
request all orbital energies using `%output Print[P_OrbEn] 2 end`. Existing outputs
remain unchanged; the viewer identifies older tables containing only a subset of
virtual levels. ORCA orbital indices start at zero.

## Orbital and spin-density properties

Open **Orbitals and spin density** in a completed result. Select orbitals directly
or select those in the displayed energy range. Spin density is offered for an
unrestricted reference. Review the plan, then submit. The independent
`empa_orca.orbitals` WorkChain:

1. Validates source provenance, settings, orbital selection and current files.
2. Reuses matching complete property outputs when available.
3. Otherwise preserves/restores the electronic bundle and runs `orca_plot`.
4. Passes every generated cube through the shared **cubehandler CLI**.
5. Retrieves only reduced previews, manifests and logs, with the selected full
   cube retention policy.

If all electronic copies are missing, the reviewed plan explicitly proposes SCF
at the saved final geometry with the original electronic settings. The backend
requires that regeneration choice before submitting it and bypasses calculation
caching when needed. Optimization is not repeated. If files disappear after a
review that did not include regeneration, submission fails with a request to
review again. This recovery rule is specific to the present HF/DFT reference;
future correlated calculations must also validate common-orbital-basis identity.

The full cube choices are:

| Choice | Full-resolution data | AiiDA repository |
| --- | --- | --- |
| Stash (default) | Native stash copy plus working-directory original | Reduced cubes, manifest, logs |
| Leave | Calculation directory only | Reduced cubes, manifest, logs |
| Delete | This job's full cubes deleted after every preview validates | Reduced cubes, manifest, logs |

The source wavefunction is never deleted by the cube policy. Only expendable
wavefunction staging copies in the property job are removed after success.
Full-cube reuse checks the required stash/working files as well as the retrieved
previews. A preview can still be opened after the full data is lost; asking for
the full-data retention policy again requires regeneration.

The adjustable grid has 40–256 points on each axis (default 80). ORCA determines
the bounding box. A fixed point count is not an accuracy guarantee for large
molecules; inspect spatial resolution before quantitative work. The driver checks
estimated disk requirements before generating cubes. Previews use cubehandler's
`slicing` reduction and `--no-low-precision`, retaining physical amplitude units
instead of its compact format's amplitude rescaling. Coarse previews are intended
for visual inspection; use full cubes for quantitative post-processing.

The NGL viewer displays positive and negative isosurfaces, an adjustable isovalue,
the molecule, and a reduced-cube download. The result records the location of
retained full cubes. A future property component can consume that recorded stash;
there is no HQ-cube post-processing app in this milestone.

## Local setup and validation

Register installed codes on the same local computer for Python, `orca_plot`, and
`cubehandler`; the app discovers these executable names. The Python used by the
cube job must have NumPy and ASE. The tested tools are ORCA 6.1.1 and cubehandler
0.2.1. ORCA binaries remain user-installed licensed software. Cubehandler runs as
an external code; the ORCA backend does not depend on the CP2K workflow package.

Real neutral-doublet NO tests cover SCF submission and preservation from a fresh
app session, export from both retrieved and stashed wavefunctions, and all three
full-cube policies. At 80³ points, tested full orbital norms were approximately
1 and integrated spin density approximately 1 electron. A full cube was about
7.3 MB, versus roughly 55 kB for its 16³ preview. These numbers validate this small
example and are not estimates for a 150-atom molecule. Automated tests cover
scratch-loss reuse, checksum failures, deletion only after valid previews, cache
bypass for missing references, and energy-range/grouping behavior.

Official input and plotting references:
[ORCA output control](https://orca-manual.mpi-muelheim.mpg.de/contents/essentialelements/output.html)
and [ORCA 6.1 plotting](https://www.faccts.de/docs/orca/6.1/manual/contents/utilitiesvisualization/plots.html).

## Shared viewer and render jobs

The result panel uses `aiidalab_widgets_empa.cube.CubeViewer`, extracted from
Surfaces' Handle cube files viewer. It provides editable signed isosurfaces,
colours, a linked arbitrary 2D plane and PNG slice export. ORCA selects isolated
boundaries: cube origins are preserved and pixels outside the grid are empty.
No wavefunction or full cube is read by the interactive viewer.

The Render tab submits `empa_orca.cube_render` through AiiDA. Select the retrieved
preview or the full-resolution cube recorded in scratch/stash, then use the
current 3D camera, isovalues, colours, image dimensions and opacity. Full cubes
are checked and staged on their storage computer; only the PNG and log are
retrieved. Deleted or missing full cubes produce an actionable error instead of
silently substituting a preview. Previously rendered images can be reopened.
The linked slicing plane is exported separately; it is not part of the 3D render.

Rendering uses the existing cubehandler rendering PR:
<https://github.com/nanotech-empa/cubehandler/pull/14>. This draft adds its image
size/background/opacity CLI options. The Python package pin selects an unreleased
API needed by this feature; released cubehandler 0.2.1 has no `render` command.

## Application codes and remote execution

Users do not choose a generic Python interpreter. Setup must register one ORCA
helper application code per computer, pointing at the installed `orca-tools`
console command (or an environment-loading wrapper), with default plugin
`empa_orca.electronic_storage`. The historical WorkChain input name `python_code`
is retained for compatibility with saved processes; the application now supplies
the configured ORCA tools code. It executes the input script captured in each
CalcJob repository. There is no PythonJob dependency and no notebook-side
subprocess for storage, cube generation/reduction, or rendering.

Register a separate cubehandler render code with default plugin
`empa_orca.cube_render`. It must provide the rendering-enabled cubehandler CLI,
PyVista/VTK, and headless EGL or OSMesa on the **execution nodes**. The localhost
test uses OSMesa and `VTK_DEFAULT_OPENGL_WINDOW=vtkOSOpenGLRenderWindow` in its
wrapper. A wrapper that works only on the login node is insufficient.

ORCA plot and cubehandler reduction codes remain explicit scientific tool
choices. Wrapper names can be arbitrary when the code extra
`aiidalab_orca_role` is `plot`, `cubehandler`, or `python` (the compatibility role
for ORCA tools). All codes must belong to the source calculation computer.
The configured wrapper must establish its own runtime when called by the
ORCA tools process; do not rely on another Code's prepend text being applied
to subprocesses. The helper requires NumPy and ASE; ORCA plot requires the
matching ORCA libraries.

Storage, cube and render CalcJobs use serial resources and inherit account,
queue, QoS and custom scheduler commands from the producing calculation.
They use normal AiiDA transports/staging/stashing, with no localhost restriction
on these property jobs. Configure an absolute persistent stash path on the
remote machine. WFN policies recorded with the reference are inherited; cube
retention has its own directory and is never used to overwrite that policy.

**Validation boundary:** local direct execution and browser submission have
been exercised. Daint execution has not yet been tested. The initial SCF/GEO_OPT
workflows still have their local-only milestone guard; lifting that guard,
exposing Slurm allocation settings there, and installing/testing the matching
ORCA/ORCA tools/render wrappers through `aiidalab-alps-files` and the setup app
are prerequisites for a full Daint deployment. This change does not claim a
working Daint installation or modify existing remote codes.
