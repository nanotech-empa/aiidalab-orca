# ETRI starting geometry for the planned tigu benchmark

`etri-source-siesta-triplet.xyz` is the isolated C36H16 ETRI monomer, 52 atoms,
neutral triplet, taken from the published SIESTA-relaxed geometry in:

J. Li, S. Sanz, J. Castro-Esteban, M. Vilas-Varela, N. Friedrich,
T. Frederiksen, D. Peña and J. I. Pascual, *Uncovering the Triplet Ground State
of Triangular Graphene Nanoflakes Engineered with Atomic Precision on a Metal
Surface*, Phys. Rev. Lett. 124, 177201 (2020).
[Open data and licence: CC BY 4.0](https://doi.org/10.5281/zenodo.4243077).
The dataset credits the simulations to S. Sanz and T. Frederiksen.

Archive: `triangulene-like_graphene_systems.zip`, MD5
`bbecc4437f9639fad0dd926ccf1330d7`.
Original member: `theory/monomer/SPIN2/molecule.XV`.
Its SHA-256 is recorded below. Positions were converted from SIESTA XV Bohr
to Å using ASE; no atoms, orientations or geometries were changed. The
isolated molecular graph is connected.

This is a sourced **starting geometry**, not established as the exact
PBE0/FHI-aims geometry used by Calvo-Fernández et al., PRB 110, 165113 (2024).
See [the Kondo guide](../../docs/kondo.md). Match geometry preparation and
confirm the orbital reference, basis, integral approximations and charged
root manifold before claiming reproduction.

The agreed ORCA comparison proceeds in this order:

1. Optimize the neutral triplet with PBE0/def2-TZVP and TightOpt.
2. Compute restricted PBE/def2-TZVP orbitals at that converged geometry.
3. Inspect the proposed twelve frontier orbitals before selecting CAS(12,12).
   For 232 electrons the contiguous candidate window is ORCA indices 110–121,
   counting from zero; its orbital character must still be checked.
4. Compute frozen-orbital neutral triplet/singlet states and both charged
   doublet/quartet sectors, initially with 24 roots per charged sector.
   Use a conservative CI printing threshold (`TPrintWF 1e-12`) and independently
   check the retained CI norm against the `1e-5` missing-norm limit. Printed
   vectors are not renormalized to conceal truncation.
5. Verify common active orbitals across sectors, then compare the exchange
   matrices with 4, 8, 12, 16 and 24 charged roots per sector. Choose an explicit
   chemical potential inside the charge-stability interval. The paper's
   Figure 7 uses 4 eV; its Table 3 caption says that value is already included
   in the printed costs, so it must not be applied twice to those values.

Calculations run on **tigu**, initially **6 processes per job**, without
stashing; full electronic files stay in their calculation directories.
Twelve processes is only an upper limit; performance scaling has not been
measured. These instructions describe the benchmark protocol, not a claim
that its molecular calculation or Figure 7 reproduction is complete.

The first maps are individual normalized exchange eigenchannels. They do
not include NRG spectral weights or the paper's PP-STM tip model, and are
not a prediction of the measured combined zero-bias intensity.

Original XV SHA-256: `f598970244fcf8f84d428897c14a8913db12595b9c85aab9d0e66b8fce9eac51`.
