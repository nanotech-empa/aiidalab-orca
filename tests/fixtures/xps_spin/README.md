Native ORCA 6.1.1 ARM64 regression output.

- `no-*`: neutral NO, fixed bond length 1.151 Angstrom, PBE/def2-TZVP;
  source `6df5b64d-a57e-4330-991a-f865379d1547`, complete XPS workflow
  `78919f42-4f70-406e-ba0f-f0a68392f125`. `reference.json` records the
  difference from the published core-flexible basis. No experimental data
  or fitted results are substituted for native output.
- `copc-avas-excerpt.out`: diagnostics and native orbital-population columns
  138–149 from CoPc AVAS calculation `21e6b794-8727-4a0c-b1ee-0629517e9ce1`.
  This is a labelled excerpt, used to reject the extra bonding orbital.
- `co-17-state-format.out`: reduced cobalt-atom RAS-CI/SOC **format smoke test**,
  `6a272ee0-21f8-4a73-a062-98b5786bbbdd`, with four triplets/five singlets.
  It is not a CoPc spectrum or an atomic accuracy benchmark. The neutral
  format-test reference is `60d508a5-7c8d-4af3-985a-48425ae26eba`.
  Native ORCA terminated normally; the generic upstream parser is not
  CAS-aware and marked that generic CalcJob 311. The application uses its
  own validated parser. Production parsing rejects this reduced state space.
- `co-natural-one-pass.out` and `co-natural-finalization.out`: native cobalt-atom
  representation-only checks, respectively
  `ff326bcb-6eee-4d87-a184-379c84488e86` and
  `58a4f089-37e4-4f4a-a7ec-ab743c1790ea`. ORCA overrides `ActOrbs NatOrbs`
  at `MaxIter=1`. The corrected two-pass finalization skips orbital optimization
  with an intentionally loose gradient threshold; native control flow and
  unchanged CAS energy are independently checked. Its explicit CASSCF controls
  follow `TightSCF` so that the approved gradient threshold is honoured. These are format/control
  checks, not atomic accuracy benchmarks; the generic upstream parser is not
  CAS-aware (exit 311), while native ORCA terminated normally.
- `copc-natural-excerpt.out`: native CoPc calculation
  `b0543a93-2153-4361-8dda-c3aa21044291`, containing control flow, CAS energies,
  state composition and population columns 138–149. The rotation preserves its
  CAS energy without optimization, but its neutral energy differs from the
  preceding SA-CASSCF result `a35c56dc-2916-4aa7-ac08-958d3ccd5b94` by
  −0.0004942938 Hartree (−0.0134504 eV). The application rejects this reference
  and does not start the spectrum. This fixture tests that failure explicitly.

No ORCA executable or wavefunction is included.

# Fixed-grid validation

`copc-fixed-cosx-grids.out` contains only the native generated COSX grid section
from diagnostic CalcJob `658608c9-114a-4139-9bea-24eaec2cef15` (ORCA 6.1.1 ARM64).
All three grids have 183,635 points and default radial accuracy 4.338. This is
grid-parser evidence, not a reconverged orbital or Co 2p spectrum benchmark.

`copc-fixed-natural-excerpt.out` and `copc-fixed-neutral-reference.json` retain
the native generated grids, finalization control flow, energies, state composition
and population columns 138–149 from `d5f2b6de-4f0e-43b0-aca2-c5137b761de0`.
The parent neutral reference was reconverged through the app in workflow
`13f2c6c4-ad1e-4a88-b32c-ed7921687942`. Both the frozen-restart and active-only
natural-rotation energy checks pass the unchanged 1e−7 Hartree guard. This is
a reference-preparation regression, not a full Co 2p spectrum validation.
