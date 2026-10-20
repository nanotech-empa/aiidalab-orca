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
root manifold before claiming reproduction. The planned molecular run is
on **tigu**, initially **6 processes per job**, no stashing. Twelve processes
is only an upper limit; performance scaling has not been measured. No ETRI
electronic calculation has been submitted by this draft.

Original XV SHA-256: `f598970244fcf8f84d428897c14a8913db12595b9c85aab9d0e66b8fce9eac51`.
