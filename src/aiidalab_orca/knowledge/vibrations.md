# ORCA harmonic IR/Raman: choosing the reference geometry

Review **Full files** before submitting: the original Hessian and electronic
files remain on the calculation computer or in its selected stash. Native text
outputs up to **maxsizeoutput** (default 5 MiB per file) are retrieved unchanged;
larger outputs use a separate validation extract and an explicit outputcat
notice, while the original stays remote/stashed. AiiDA retains the exact numeric Hessian
sections required for spectra, animations and durable reuse. The compact Hessian
has a 16 MiB limit; exceeding it fails collection instead of retrieving the
large original. No frequencies, displacement vectors or response tensors are
rounded, rediagonalized or rescaled by this retention step. Reused results keep
their recorded storage policy; historical nodes are unchanged.

Start with `orca.app` for molecule/SCF preparation and chat-tool capabilities.

Check the installed GUI and live calculation UUIDs before advising. A successful
SCF does not establish a stationary geometry, and missing optimization provenance
does not establish that coordinates are unoptimized.

Choose **IR / Raman** as the goal. Opening an existing reference with **Use final
geometry** opens spectroscopy rather than preparing a new SCF. A converged
optimization goes directly to frequency review. An SCF reference offers:

1. **Use a matching saved optimization**, recommended when one has exactly the
   same coordinates, electronic settings and ORCA code. Open the original
   optimization directly; another SCF or optimization is unnecessary. Resource
   counts may differ, and the selected reference's resources are inherited.
2. **Prepare a geometry optimization**, opening the wizard with the existing
   coordinates and settings for review. No calculation is submitted by navigation.
3. **Use this geometry without optimization (advanced)**. The user must explicitly
   acknowledge the assumption before frequency controls appear. This supports
   geometries optimized elsewhere, after preparing an SCF reference in the app.
   For an uploaded geometry, choose IR/Raman and uncheck **Optimize geometry**
   when preparing that SCF reference.

The advanced route keeps coordinates fixed. Stationarity at the chosen method,
basis, charge and spin is unverified; harmonic equilibrium spectra may be
unreliable away from a stationary point. No gradient check or optimization is
performed. The acknowledgement and a persistent result warning are recorded
with new provenance; old scientific nodes are never rewritten. The ordinary
backend path still requires optimization provenance. Neither route bypasses
the geometry/electronic-setting/code compatibility checks.

Frequency review shows the actual input and whether stored data will be reused.
The independent ORCA frequency calculation performs its own SCF, requests
`AnFreq` and optionally `%elprop Polar 1`, and retains the Hessian. Stored
warnings and imaginary modes must be inspected before interpreting IR/Raman;
a completed optimization is not proof of a vibrational minimum. Partial Hessians
and resonance Raman remain outside this workflow.

The current chat form adapter supports geometry/SCF preparation and submission,
not frequency submission. Guide the user to the visible IR/Raman controls;
do not claim a chat action submitted a frequency calculation.

## Official references

Use the manual version matching the actual ORCA executable:

- [Geometry optimization and convergence](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/optimizations.html).
- [Harmonic frequencies and Hessian controls](https://www.faccts.de/docs/orca/6.1/manual/contents/structurereactivity/frequencies.html).
- [IR/Raman and polarizability derivatives](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vibrations.html).
- [Imaginary modes and troubleshooting](https://www.faccts.de/docs/orca/6.1/manual/contents/quickstartguide/troubleshooting.html).

An ORCA feature described in the manual is not necessarily an available app
control. In particular, do not add a gradient check or promise resonance Raman.
