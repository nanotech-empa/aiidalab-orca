# Molecular vibrational spectroscopy

Open a converged optimization in **Results → Vibrational spectroscopy · IR and
Raman**. The section is independent of orbital cubes and CASCI. Review the
inherited method, basis, charge, spin and resources in the generated ORCA input,
then submit. Existing calculations can be reopened from the same section.

The initial implementation requires a converged ORCA geometry optimization.
An SCF calculation alone does not establish a stationary geometry. A constrained
optimization is accepted with a warning: free-molecule normal modes at that
geometry may not describe a minimum. Imported optimized geometries and partial
Hessians will need explicit preparation/validation interfaces in a later step.

## Small workflow and retained data

`empa_orca.vibrations` is a separately callable WorkChain with one normal ORCA
CalcJob. It inherits the reference's electronic-structure settings, removes
optimization directives, and requests analytical frequencies (`AnFreq`). IR is
included automatically. The Raman option adds `%elprop Polar 1` for ORCA 6.1
analytical polarizability derivatives. No empirical frequency scaling is added.
The frequency job performs its own SCF; it does not require the reference's
scratch wavefunction to survive.

Outputs include:

- `vibrational_data`: arrays containing all frequencies, Cartesian normal-mode
  vectors, vibrational mode indices, masses, the Cartesian Hessian, IR
  intensities and transition dipoles, and optional polarizability derivatives,
  Raman tensors, activities and depolarization ratios.
- `hessian`: the original `.hess` file as a durable `SinglefileData`.
- `summary`: units, mode count, linear/nonlinear classification, the actual
  frequency scale, coordinate-origin offset, and significant imaginary modes.
- `retrieved`: the original ORCA output and Hessian. Electronic checkpoint
  files and cubes are not retrieved by this step.

ORCA centres the Hessian coordinates. The parser checks that they differ from
the selected optimized geometry only by a translation; it does not guess a
rotation. The stored vectors and tensors therefore keep the reference's
Cartesian axes. Raman tensor normalization and units are checked by
reconstructing ORCA's activities and depolarization ratios. Invalid/incomplete
output fails explicitly. Vibrational frequencies below −20 cm⁻¹ produce a
minimum-validity warning; zero/negative modes are excluded from the positive
frequency optical-spectrum viewer, while remaining in the stored data.

Reuse compares the actual geometry, code and effective scientific inputs and
checks the retained Hessian and numerical arrays against the original ORCA
output. A completed IR+Raman calculation also satisfies an IR-only request.
Unavailable results are reported before recomputation. AiiDA caching is not the
reuse mechanism: newly requested CalcJobs explicitly bypass it. Scratch deletion
does not prevent inspection or reuse of the retained vibrational data.

## Reused viewer

The spectra, mode controls, atom-participation display and WEAS animation reuse
`RamanWidget`/`RamanModel` from
[AiiDAlab QE vibroscopy](https://github.com/aiidalab/aiidalab-qe-vibroscopy),
including [PR 189](https://github.com/aiidalab/aiidalab-qe-vibroscopy/pull/189).
The dependency is pinned to the tested PR head because these internal widget
interfaces and atom-participation controls are not yet a released shared API.
The companion update in PR 189 makes the optical model independent of the QE
host and loads the QE property entry point lazily. ORCA therefore reuses the
actual widget without requiring the QE app or its calculation plugins. A
backend-independent shared API remains a useful later cleanup.

The molecular adapter uses ORCA's arrays directly. It creates no phonopy cell,
Born-charge model or periodic nonanalytical correction. Controls provide IR and
Raman tabs, orientation averages or fixed polarizations, Raman activity versus
Stokes intensity, temperature, laser wavelength, broadening, display range and
clickable mode markers. The animation uses the original Cartesian mode vectors.
It starts automatically; use **Pause animation / Play animation** beside the
mode selector. Changing mode or amplitude updates the molecule and preserves
the paused/playing choice. Amplitude controls only the illustrated motion.
Activity is distinct from intensity; displayed intensities use a relative
scale. Polarized/depolarized channels and selected-atom participation share
their total spectrum's normalization. Atom participation is a mechanical mode
weight, not an additive decomposition of the optical transition amplitude.
The data download contains raw arrays, units, source UUIDs and view settings.

## Development checks

The main example is **neutral singlet formaldehyde, H₂CO**, optimized with
PBE0/def2-SVP, RIJCOSX/def2-J, TightSCF and TightOpt. The local four-process run
has six positive harmonic frequencies:

| Mode (ORCA index) | Frequency (cm⁻¹) |
| --- | ---: |
| 6 | 1199.86 |
| 7 | 1269.26 |
| 8 | 1533.00 |
| 9 | 1896.72 |
| 10 | 2901.73 |
| 11 | 2967.29 |

The regression fixture retains the real ORCA 6.1.1 Hessian and relevant output
tables. Tests check parsing, units, response invariants, coordinate checks,
polarizations, shared intensity normalization and reuse after scratch loss.
A separate CO optimization/frequency calculation checks the linear-molecule
case: one vibrational mode after five rigid translations/rotations, at
2274.49 cm⁻¹ with the same electronic protocol. These checks validate the
implementation against ORCA's output, not experimental accuracy or an
anharmonic treatment.

## Next component: resonance Raman

Resonance Raman will be a separate workflow using the retained ground-state
Hessian plus an explicitly selected electronic excitation and excited-state
derivatives. ORCA's ESD module supports this. Electronic-state selection, laser
energy/detuning, linewidths and the excited-state surface approximation must
be recorded as scientific inputs. Derivatives should be reusable when laser
energies change. ORCA 6.1 ESD resonance Raman is limited to 0 K; the ordinary
Raman temperature control must not imply otherwise.

References: [ORCA vibrational spectroscopy](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/vibrations.html)
and [ORCA ESD resonance Raman](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/esd.html).
