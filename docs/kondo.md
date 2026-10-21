# Kondo orbitals and individual channel maps (draft)

The **States & Dyson → Kondo orbitals & maps** view starts from a completed
fixed-orbital CASCI Dyson calculation. It runs three independent stages:

1. `empa_orca.kondo`: exchange matrix, eigenvalues and active-orbital eigenvectors.
2. `empa_orca.kondo_cubes`: signed linear combinations of native ORCA orbital
   grids, with cubehandler-reduced previews retrieved. Reference grids come
   from the exact initial CASCI checkpoint, checked against the preserved GBW
   checksum, and are reused across chemical potentials. The original AO
   evaluator remains available for previously submitted workflows.
3. `empa_orca.kondo_maps`: individual constant-height intensity maps from full
   amplitude cubes. The existing separate figure CalcJob stores PNG/PDF nodes.

All stages have AiiDA provenance. The exchange stage needs only the durable
transition table, not a surviving GBW. Cube generation checks the preserved
basis export. Existing compatible channels, previews, numerical maps and
figures are reused explicitly, independently of AiiDA caching. Missing full
cubes or exports give a recovery error; electronic calculations are never
silently repeated. Full cubes can remain in place (the initial UI default), be
stashed, or be deleted after reduced-preview validation. Deletion means later
full-resolution maps require cube regeneration, not new CASCI calculations.
Native reference orbital grids are retained separately for reuse. The channel
cube retention control applies to the resulting channel cubes. Native grids
must share their origin, spacing, dimensions and atom geometry; no interpolation,
phase fitting or numerical grid renormalization is performed during combination.

## Scientific definition

The model follows Calvo-Fernández et al., [Phys. Rev. B 110, 165113 (2024)](
https://doi.org/10.1103/PhysRevB.110.165113), Eqs. 7–8. Its first scope is
spin-pure, spin-free states with a selected initial spin S > 0, a shared orbital
basis, and an equal scalar substrate hybridization V for all active orbitals.
The output is J/V² in eV⁻¹. Positive eigenvalues label AFM channels; negative
ones label FM channels. This classification does not establish observable
screening at a particular temperature.

Our Dyson table stores unnormalized highest-Ms amplitudes d. Converting the
paper's reduced matrix elements and Clebsch–Gordan factors to that convention
gives, for either electron addition or removal:

```
J/V² = sum_c f_c outer(d_c, d_c) / Delta_c
f_c = +1/S          when S_c = S - 1/2
f_c = -1/(S + 1/2)  when S_c = S + 1/2
```

These are exchange factors, not the spin-summed spectral factors. Raw signed
orbital coefficients retain interference within a virtual channel. Do not
multiply by the Dyson strength again. The independent tests evaluate virtual
spin flips in Fock space for both charging directions and both spin branches;
the single-level Anderson limit gives J/V² = 2(1/Delta_minus + 1/Delta_plus).

The explicit chemical-potential convention is the paper's
`epsilon_M = E_M + (N_M - N_0) mu`. Thus the charging costs are
`Delta_minus = -removal_pole - mu` and `Delta_plus = addition_pole + mu`.
Both must be positive. The displayed interval tests only the supplied roots;
it does not prove global charge stability. A small charging gap warns that the
local-moment perturbative approximation may fail. The spectral viewer's rigid
display offset is not reused as a physical chemical potential.

The selected roots and missing charge/spin sectors are recorded. Completeness
and convergence with the charged-state manifold remain scientific checks.
A singlet initial state is rejected: an excited triplet population or a
singlet–triplet Kondo mechanism needs a different model. For degenerate
eigenvalues the individual orbital shapes are basis-dependent; only the
degenerate subspace is invariant, and this warning accompanies their maps.

## What the images mean

Each map is the squared amplitude of one unit-normalized Kondo orbital,
optionally propagated using the existing s-tip Fourier vacuum model. The
initial source plane is 1.5 Å above the highest atom along +z and can be
overridden through the shared 3D slicing controls. Observation heights retain
that reference. Shared explicit colour limits apply to every figure panel.

Exchange eigenvalues are **not** used as image brightness weights. No combined
experimental Kondo map, Kondo temperature, linewidth, Fano profile or
non-equilibrium population is inferred. NRG and a defined tip/substrate model
are separate future steps. These channel maps do not reproduce the paper's
PP-STM CO-tip maps quantitatively.

## Benchmarks

- Existing NO CAS(3,3) results exercise the app/CalcJob/cube/map path locally
  without new electronic calculations. This is an integration test, not a
  claim of experimental Kondo screening in NO.
- The ETRI example is a neutral triplet C36H16 molecule (52 atoms). Its
  CAS(12,12) protocol is a substantive molecular benchmark. PBE0-optimized
  FHI-aims geometries and restricted PBE orbitals were used in the Kondo paper;
  basis/grid details and the exact geometry must be matched or differences
  recorded before submitting a reproduction.
- The CC BY 4.0 [2020 experimental dataset](https://doi.org/10.5281/zenodo.4243077)
  includes SIESTA-relaxed ETRI coordinates. Those are a sourced starting point,
  not verified as the exact 2024 PBE0 geometry. No idealized geometry is passed
  off as a matched reference. The [example geometry](../examples/etri/README.md)
  preserves its source member, checksum, conversion and scientific credit.
- `tests/fixtures/kondo/etri-tabulated.json` transcribes Tables 3 and 7 of
  the 2024 paper. Six rounded orbital components and two doublets per charging
  direction check the reduced-amplitude conversion. This truncated excerpt
  cannot reproduce all channels or the full chemical-potential curves in
  Figure 7. The table caption says mu is already included; it must not be
  applied a second time. Full original energies/amplitudes are required for
  a quantitative comparison of those curves.

## Executed draft checks

The existing NO CAS(3,3) data completed exchange, three 80³ amplitude cubes,
cubehandler reduction, individual channel maps at observation heights 3 and
5 Å, and shared-scale PNG/PDF rendering through the app services and AiiDA
daemon. Full cubes remained in their original working directory. A repeated
exchange workflow returned the same stored channel node with no child
CalcJobs. No new electronic calculation was submitted for this test.

The reference exchange test yields one AFM and two FM eigenchannels at μ=0;
this is internal execution evidence, not a prediction of an experimental
Kondo resonance in NO.

The ETRI ORCA comparison completed the geometry, restricted-PBE reference,
frozen CAS(12,12), four 24-root charged sectors and 96 Dyson transitions on
**tigu**, using six processes for electronic work and no stashing. At μ=4 eV,
the leading exchange eigenvalues are 1.743 and 1.140 eV⁻¹, compared with the
paper's Figure 10 values 1.824 and 1.178 eV⁻¹. Their 16→24-root changes are
below 0.25%; the full exchange matrix changes 6.74%. This supports a qualitative
leading-channel comparison; weak channels remain unconverged. The ORCA
PBE0/def2-TZVP geometry/basis approximation to the paper's FHI-aims preparation
is explicit. Optional 48-root refinement was stopped to prioritize A2n maps.
Twelve processes remain the authorized limit, without a claim of optimal scaling.

The AO evaluator's real f(±3) phase correction passes the unchanged 1e-7 overlap
guard (native ORCA fixture residual 5.73×10⁻⁹). A 9,661-point native ORCA orbital
cube comparison agrees to 0.0021% in amplitude without fitted normalization.
The app's preferred Kondo cube route uses native ORCA grids directly.

Prepared with the assistance of Codex. Scientific attribution remains with
the cited authors; existing Dyson, cubehandler and map-engine credits apply.
