# Constant-height Dyson maps

After generating individual Dyson amplitude cubes, open **STM-like constant-height
maps (draft)** below the shared cube viewer. The numerical-map calculation and
figure renderer are independent CalcJobs, using the existing ORCA Dyson tools
code on the full-cube computer. There is no generic Python-code selector.

## Plane and height reference

The initial reference point is the molecular bounding-box centre in x/y and
the **topmost atomic z coordinate** in z. The source slice starts **1.5 Å along
+z above that point**. Its initial footprint occupies 90% of the preview grid's
in-plane span; the full cube is checked before sampling. This is a starting
view, not an inferred experimental surface orientation.

The shared slice viewer's **Center**, **Normal**, **Offset**, **Width**, **Height**
and resolution override those defaults. Center is the reference point; Offset
is the source-slice height measured along the normalized normal. The GUI also
shows the resulting Cartesian centre of the source plane. The reset button
explicitly restores 1.5 Å above the top atom along +z. Camera rotation does not
change the physical source plane.

Observation heights default to **5 and 7 Å** along the selected normal from
the same reference point. They must be at or beyond the source slice. For
example, the default source plane is `z_top + 1.5 Å`; the default observation
planes are `z_top + 5 Å` and `z_top + 7 Å`. After a user moves Center or Normal,
the displayed reference and direction determine these heights. The app does
not silently refit or realign the molecule.

All plane coordinates are stored as CalcJob inputs. The metadata also records
the actual orthonormal in-plane u/v basis, which matches the shared viewer.
An optional 90-degree panel rotation affects only figure presentation.

## Numerical model

The full-resolution **amplitude** is linearly interpolated on the isolated
source plane, preserving the cube origin and spacing matrix. A plane extending
outside the computed cube is rejected, rather than periodically repeated or
filled with artificial data. Reduced cubes are used only for interactive
positioning, never as the numerical map source.

Vacuum propagation follows the Fourier algorithm in
[meqpy's Dyson implementation](https://github.com/nanotech-empa/meqpy/blob/ebc6965e3e01fad739a0c95496c6a32165c7105e/src/meqpy/system/dyson.py),
which credits cp2k-spm-tools. An in-plane Fourier mode with wavevector k decays
in amplitude as `exp(-dz * sqrt(k² + κ²))`. The initial κ is 1.15 Å⁻¹, as in
Andrés's supplied notebook. This small adaptation supports arbitrary explicit
source planes without requiring the molecule to lie in the global xy plane;
its attribution and MIT licence are packaged in `MAPS_LICENSE.txt`.

FFT padding is explicit and defaults to zero, matching the notebook. Finite
footprint, source height, sampling resolution, padding and κ need convergence
checks for scientific use. The periodic Fourier representation of a finite
source plane is a property of this approximation; it does not enable periodic
sampling of the molecular cube.

Each transition is extrapolated separately, **then squared**. Individual maps
include the selected spin-multiplet factor. A spectral blend sums the squared
amplitudes with the existing energy/window Lorentzian and spin weights.
Unnormalized Dyson amplitudes already contain their pole strength, which is
not multiplied in again. An existing three-dimensional intensity-blend cube
cannot substitute for the constituent amplitudes in this step.

Map amplitudes are converted to Å^(-3/2), following meqpy; individual/window
intensities are in Å^(-3), and energy-resolved intensities additionally carry
eV^(-1). Individual maps and energy-resolved blends therefore have separate
figure types and recorded units. These are spin-free STM-like s-tip intensity
maps, not calibrated currents or a reproduction of a full PP-STM calculation.

## Storage and reuse

`empa_orca.dyson_maps` consumes the source cube manifest, matching Dyson
transition table, the actual remote/stash source node, and a parameter Dict.
It produces:

- `maps`: ArrayData with intensity indexed by height/panel/v/u, the u/v
  coordinates, and observation heights.
- `map_metadata`: Dict containing the parameters, units, plane frame,
  transition weights and source-file SHA-256 digests.
- Retrieved compressed numerical maps, metadata JSON and execution log.

`empa_orca.map_figure` consumes that ArrayData, its metadata, and an explicit
styling Dict. It produces PNG and PDF **SinglefileData nodes**. The figures
remain connected through the two CalcJobs to the cubes and electronic states.
They can be reopened from the app and downloaded. The selected map's settings
can also be restored into the viewer for another calculation.

Figures use **one fixed intensity range across all panels and heights**.
The initial range spans all the numerical maps; subsequent edits apply to
every panel. There is no independent per-panel normalization. The raw arrays
are never normalized, clipped or overwritten when the display range changes.
The source-amplitude viewer's colour limits are separate from this intensity
scale. When assembling separate figures externally, use the same limits and
compatible units if brightness comparisons are intended.

Existing numerical maps are found through provenance and reused before
checking expendable full cubes. Rendering a stored map does not need the
cubes. A new plane or height needs the amplitude cubes; missing full cubes
produce an explicit recovery message. Regenerate those cubes from preserved
Dyson coefficients/basis data using the cube controls, without repeating
CASCI. Actual new map/render jobs disable AiiDA caching; explicit reuse works
with caching either enabled or disabled. Input comparisons use AiiDA's stored
floating-point precision to avoid repeating an unchanged request.

## Local validation

Tests cover the top-atom default, isolated oblique-plane sampling with a
nonzero origin and skewed voxel matrix, analytical constant/Fourier-mode decay,
spin weighting and incoherent blends, fixed brightness ratios across combined
panels, full-cube staging, and reuse after full cubes disappear with caching
on/off. The propagation was also compared against the unmodified meqpy method
at the commit above: maximum absolute differences were approximately 1e-18
for the tested padded and unpadded random grids. This is implementation
equivalence evidence, not physical validation of κ or the STM model.

The local NO example exercises app submission, source-plane overrides/reset,
numerical-map storage and PNG/PDF provenance. The model and the pentacene
publication comparison still need the agreed scientific benchmark.
