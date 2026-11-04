# ORCA harmonic IR/Raman: choosing the reference geometry

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
