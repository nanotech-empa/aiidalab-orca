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

No ORCA executable or wavefunction is included.
