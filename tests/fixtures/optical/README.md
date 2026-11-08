# Native response excerpts

Pyridine excerpts were generated with ORCA 6.1.1 from the exact fixed-geometry
PBE/def2-SVP example in the [ORCA 6.1 manual](https://www.faccts.de/docs/orca/6.1/manual/contents/spectroscopyproperties/tddft.html#natural-transition-orbitals).
The TDA example supplies an independent published numerical reference. Full
TDDFT and singlet/triplet variants test separate methods and output identities.

The allyl UKS excerpt tests open-shell native tables and alpha/beta NTO identity
at the app's existing PBE/def2-SVP optimized doublet geometry. It is an integration
case, not an exact reproduction of literature geometry, method or excitation
energies. The independent numerical benchmark for this stage remains pyridine.
Trailing line whitespace is stripped. Only parser-relevant output is retained; full native outputs stay with their
AiiDA CalcJobs. No engine binary, personal paths or complete program banner is
included. Ordinary tests do not execute ORCA.
