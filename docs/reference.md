# Single-point SCF and reusable electronic states

The **ORCA · Electronic structure** app offers two modes:

| Optimize geometry | Action |
| --- | --- |
| Checked | Optimize the nuclei and report the final electronic energy. |
| Unchecked | Run a single-point HF/DFT SCF at exactly the supplied coordinates. |

Both modes require a code and computational resources and allow review of the
generated ORCA input before submission. A compatible available result can be
reused. Older structure-only records remain readable and separately identified
in search; they are never presented as SCF calculations.

## Independent components

`empa_orca.reference` is a separate `ReferenceWorkChain`, usable outside the app.
It runs `empa_orca.reference_base`, a thin subclass of the upstream
[`aiida-orca`](https://github.com/ezpzbz/aiida-orca) base WorkChain, and
`empa_orca.single_point`, a CalcJob using the same reviewed input renderer as the
geometry calculation. The upstream cclib-based parser supplies the detailed
electronic output; the added parser requires explicit final SCF convergence,
normal termination and a finite final energy. Upstream's current handlers abort
SCF failures; automatic scientific convergence remedies are not provided.

The input requests `SP` and omits `Opt`, optimization thresholds and `%geom`.
The same method, basis, reference, RI, electronic convergence, dispersion, grid
and element-specific controls are available. Geometry constraints and scalar
`geom` parameters are inactive in SCF mode. The workflow returns its input
`StructureData` unchanged; it does not create a fictitious optimized geometry.
See ORCA's [basic calculation settings](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/basics.html)
and [SCF documentation](https://www.faccts.de/docs/orca/6.1/manual/contents/essentialelements/scf.html).

## Outputs and reuse

Durable outputs are `structure`, `reference_summary` (convergence, total energy
in Hartree and eV, and spin diagnostic when printed), `output_parameters` and
`retrieved` (ORCA stdout plus scheduler output). `remote_folder` points to the
original electronic files. For the current ORCA 6.1 contract, these are
`aiida.gbw`, `aiida.densities` and `aiida.densitiesinfo`. They are kept on the
calculation computer. Optional size-aware preservation additionally retrieves or
stashes the complete bundle; see [the storage and orbital guide](orbitals.md). The
energy remains viewable even if those remote files later disappear.

Discovery uses provenance and compares the exact ordered atomic coordinates,
code UUID, effective electronic inputs and resource settings. Optimization-only
settings are excluded from this electronic comparison. Sources may be a prior
reference workflow or the final electronic state of a successful optimization.
For an optimization, the final structure must match, and the retrieved-data
creator identifies the actual producing CalcJob and its remote folder. Reuse
links the existing summary, electronic parameters, retrieved data and remote
folder as inputs to the new reference WorkChain; no ORCA calculation is needed.

Before reuse, the stored energy is checked against the retrieved output, and
the artifact resolver checks preserved repository/stash copies before the original
remote files. Repository checks include SHA-256; original remote-file checks verify
nonempty regular files. Stashed copies are size-checked and their checksums verified
when staged for consumption. Scratch locations are not permanent archives.

- Missing required files produce a reviewed recomputation plan and disable
  AiiDA caching on the producing CalcJob.
- Forced recomputation skips manual reuse and disables that CalcJob's cache.
- A cache hit with missing electronic data is regenerated once with caching
  disabled, then checked again.
- Unreachable storage blocks the availability decision; it is not treated as
  deleted data. A reviewed reuse plan whose files subsequently disappear fails
  with a request for a new review, instead of silently starting replacement work.

The GUI shows the distinction between geometry reuse and electronic-state reuse.
Search supports both workflow types, and Results reports energy, ⟨S²⟩, the fixed
structure, actual producing input and current electronic-file availability.
When reusing an optimization, the actual producing input correctly still shows
the original optimization; the new reference workflow records the reuse links.

## Python usage

```python
from aiida import load_profile, orm
from aiida.engine import submit
from ase.io import read
from aiida_empa_orca.protocols import protocol_settings
from aiida_empa_orca.reference import plan_reference, get_reference_builder

load_profile()
structure = orm.StructureData(ase=read("examples/no/no.xyz"))
settings = protocol_settings("pbe-v1", {"charge": 0, "multiplicity": 2})
code = orm.load_code("orca@localhost")
plan = plan_reference(structure, settings, code)
print(plan)
builder = get_reference_builder(structure, settings, code, plan=plan)
node = submit(builder)
print(node.uuid)
```

This milestone uses local direct scheduling and ORCA 6.1. The geometry backend's
historical `get_builder(..., optimize=False)` still means structure only; use
`get_reference_builder` to request SCF explicitly.

## Validation and next boundary

The isolated test suite covers SCF convergence, input-preview agreement,
fixed coordinates, geometry-to-reference reuse, missing files, unavailable
storage, stale cache regeneration, spin validation and search across both
workflow types. The initial SCF milestone passed with 66 tests; subsequent
property/storage validation is documented in [the orbital guide](orbitals.md).

A fresh browser submitted NO (neutral doublet, PBE/def2-SVP, VeryTightSCF) on
ORCA 6.1.1 ARM64: workflow `7ece169a-902b-47af-b26f-c06014ce9020` completed in
one uncached CalcJob. The same input structure was returned with the N–O bond
unchanged at 1.300 Å; the energy was −129.6334542334 Hartree and ⟨S²⟩ = 0.75229.
All three electronic files were present. Preview matched actual input, copying
settings offered reuse, and SCF search reopened the result. A second browser
test reused the final state of an existing CAM-B3LYP optimization: workflow
`10590f34-0feb-4ba2-b731-83518bcd8924` completed with no child calculation.

Orbital/spin-density cube generation, viewing, cubehandler previews, full-cube
retention policies and restoration from preserved wavefunctions are now available
in the [next component](orbitals.md). External wavefunction imports remain future
work. CASCI and Dyson analysis still require their own shared-orbital
basis and state contracts; a newly recomputed SCF is not automatically compatible
with previously calculated CASCI states.
