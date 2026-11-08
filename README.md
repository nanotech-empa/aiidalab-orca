# AiiDAlab ORCA · Molecular analysis

Prepare molecular structures, calculate electronic states and spectroscopy,
and inspect results with AiiDA provenance. Each analysis has its own reviewed
inputs, resource settings and reusable results. Choose the calculations needed
for a scientific goal; no single workflow runs every property.

This is a development-stage application. The CASSCF and correlation-energy
stage is implemented and tested in [ORCA #39](https://github.com/nanotech-empa/aiidalab-orca/pull/39)
and [#40](https://github.com/nanotech-empa/aiidalab-orca/pull/40). Implementation,
small-system validation and release acceptance are distinguished in the
[stage validation record](docs/release-readiness.md).

## Choose a scientific goal

| Goal | Starting point and path | Results |
| --- | --- | --- |
| Geometry or HF/DFT energy | Import a structure; keep its geometry or optimize it, with optional constraints | Structure, total energy, optimization history |
| Orbital character and density | Completed SCF → PDOS/orbital inspection → optional cube calculation | Spin-resolved levels, atomic/angular projections, orbitals and spin density |
| Many-electron energy levels | Shared spatial orbitals → inspect/confirm CAS → optional CASSCF/SA-CASSCF → CASCI charge/spin sectors | Individually labelled states on a common energy scale |
| Quantum-assisted energy levels | Confirmed spatial reference and CAS → export Hamiltonian → circuits → sampling → classical subspace solve | Energies and spin diagnostics from the selected Hamiltonian subspace |
| Dynamical correlation | Fresh HF → RI-MP2; or verified CASSCF → SC/FIC/DLPNO-NEVPT2 or CASPT2 | Reference, correlation correction and total energy; explicit model diagnostics |
| Dyson spectra and Kondo channels | Compatible shared-reference CASCI sectors → Dyson transitions → optional Kondo analysis | Linked state/spectrum plots, amplitudes, channel cubes and maps |
| Harmonic IR/Raman | Completed optimized geometry → independent frequency calculation | Spectra, Hessian, animated normal modes |
| Archive an app entry | Completed geometry/SCF entry → common openBIS review | Related stored analyses split into their scientific categories |

Use **New calculation**, **Search calculations** and **Results** as the main
entry points. In Results, choose **Analysis / results**. Missing prerequisites
offer the relevant preparation step. Navigation, inspection and review do not
submit a calculation. Editing invalidates its review; submission is explicit.
Matching results can be reused without repeating unaffected calculations.

## User and agent guides

- [Geometry/SCF and local setup](docs/geometry.md), [reference workflow](docs/reference.md).
- [Results navigation](docs/results.md), [PDOS](docs/pdos.md), [orbital/cube storage and rendering](docs/orbitals.md).
- [Guided CAS path](docs/cas-workflow.md), [QRO/UNO inspection](docs/orbital-inspection.md), [CASSCF/SA-CASSCF](docs/casscf.md), [CASCI](docs/casci.md).
- [MP2, NEVPT2 and CASPT2 energies](docs/correlation.md), [quantum-assisted energies](docs/quantum-energy.md).
- [Dyson spectra](docs/dyson.md), [transition explorer](docs/transition-explorer.md), [constant-height maps](docs/maps.md), [Kondo channels](docs/kondo.md).
- [IR/Raman](docs/vibrations.md), [whole-entry openBIS export](docs/openbis-export.md).

Agents helping inside or outside AiiDAlab must start with the
[agent guide index](docs/agents/README.md) and consult the installed workflow
guides and actual controls. A manual page describes ORCA's engine, not the
capabilities of a particular installed app revision.

## Scientific boundaries

CASSCF optimizes an explicitly chosen orbital reference, for one state or a
weighted state average. The saved orbitals must pass an independent energy
readback before reuse. State-average weights are optimization choices, not
thermal populations or tunnelling intensities.

Correlation energies are a separate branch. MP2 uses newly converged HF;
NEVPT2/CASPT2 require verified CASSCF. Corrected energies do not supply the
current Dyson/Kondo transition amplitudes and are not substituted into their
spectra. SC, FIC, DLPNO and CASPT2 are distinct approximations; a lower total
energy is not an automatic accuracy ranking. Compare physically relevant
energy differences with consistent inputs and model conventions.

The standard CAS path uses a contiguous window in the prepared orbital
ordering. The inspector can preview arbitrary orbital indices; that preview
selection alone does not reorder the CAS. Orbital indices start at 0; atom
indices in the structure viewer start at 1.

XPS remains a separate work in progress. XAS, resonance Raman, CASPT2-K,
QD-NEVPT2, F12 and corrected transition-amplitude methods are outside this
stage. Research QPU/DMRG/XPS extensions are preserved separately.

## Runtime and validation

The declared platform is **Python ≥3.12, AiiDA ≥2.9.2, AiiDAlab ≥26.9.0** with
ipywidgets 8. ORCA and optional postprocessing programs must be installed and
registered on the calculation computer. The backend is separately installable
from `backend/`; source packages and exact optional dependency revisions are
declared in the project metadata.

The standard checks are:

```bash
python -m pip check
PYTHONPATH=src:backend/src OPENBLAS_NUM_THREADS=1 python -m pytest -q
```

Tests use isolated test storage. Native examples and scientific checks require
separate explicit calculation setup; the ordinary test command submits no
real ORCA or QPU job. The [validation record](docs/release-readiness.md) lists
the native checks already completed, rejected cases and remaining acceptance
gates. A successful small example is not a universal molecular protocol or a
publication-level accuracy benchmark.

## Design, attribution and scientific credit

The [original design discussion](docs/design-discussion.md) preserves the
motivating pentacene example, scientific references, architecture discussion
and initial review questions. Current capabilities are described above and in
the maintained guides. Development follows the
[design-review issue](https://github.com/nanotech-empa/aiidalab-orca/issues/1)
with scientific input from [Andrés Ortega-Guerrero](https://github.com/AndresOrtegaGuerrero).

Credit [aiidalab-orca and its contributors](https://github.com/nanotech-empa/aiidalab-orca/graphs/contributors)
and identify the release or immutable revision used. Preserve the separate
authorship, licences and citation instructions of
[aiida-orca](https://github.com/ezpzbz/aiida-orca),
[dyson-orca-tools](https://github.com/AndresOrtegaGuerrero/dyson-orca-tools),
[meqpy](https://github.com/nanotech-empa/meqpy), and the shared AiiDAlab widgets.
The motivating spectroscopy reference is
[Kumar et al., JACS 147, 24993–25003 (2025)](https://doi.org/10.1021/jacs.5c08166).

Acknowledge [AiiDA](https://github.com/nanotech-empa/.github/blob/main/CITATION_GUIDANCE.md#aiida)
and [AiiDAlab](https://github.com/nanotech-empa/.github/blob/main/CITATION_GUIDANCE.md#aiidalab)
when each platform was used, following its citation guidance. Existing author,
contributor and funding acknowledgements remain authoritative. See the
[shared credit guide](https://github.com/nanotech-empa/.github/blob/main/CITATION_GUIDANCE.md)
for the distinction between software attribution, licence compliance and
scientific citation requests. Citation requests are not additional MIT licence
conditions. This development stage was prepared with Codex assistance.
