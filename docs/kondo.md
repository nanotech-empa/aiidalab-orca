# Kondo orbitals and individual channel maps (draft)

The **States & Dyson → Kondo orbitals & maps** view starts from a completed
fixed-orbital CASCI Dyson calculation. It runs three independent stages:

1. `empa_orca.kondo`: exchange matrix, eigenvalues and active-orbital eigenvectors.
2. `empa_orca.kondo_cubes`: normalized channel amplitudes evaluated in the
   original exported AO basis, with cubehandler-reduced previews retrieved.
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
  off as a matched reference.
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
Kondo resonance in NO. The ETRI molecular benchmark is reserved for **tigu**,
at most 12 processes per submission, with no stashing. It has not been run.

Prepared with the assistance of Codex. Scientific attribution remains with
the cited authors; existing Dyson, cubehandler and map-engine credits apply.
