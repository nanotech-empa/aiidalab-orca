# Candidate dependency and publication status

This is an exact-source qualification candidate, not a stable dependency release.
External dependencies use official immutable releases whenever the required API
exists. Application publication must replace the explicitly accepted temporary
qualification candidates below with official releases. No release/tag publication
is implied by merging this application change.

| Dependency | Qualification source | Release status / next action |
| --- | --- | --- |
| widgets-base | official PyPI 3.0.1; wheel SHA256 `617d54cc1f01affa98b1bea688e2b8f8b67b836cea62aaf47b0153f7dc058208` | Released. [aiidalab/aiidalab-widgets-base#832](https://github.com/aiidalab/aiidalab-widgets-base/pull/832) remains optional, open for maintainer review and uninstalled; same-node geometry/style reload has a known limitation. |
| dyson-orca-tools | official 0.1.1; wheel SHA256 `1899efc1369a7e9ac2a33f634e3264f61a6245abae7e3787f37f2646d5d03d81` | Released. The real producer supplies `mult`; old synthetic fixtures now reflect that contract. |
| aiida-orca | reviewed `36abfa6917819c3e9ff454cfa89d9fd013634d12` | Official 0.7.0 lacks `render_blocks_after_coordinates`; actual application collection fails on that missing API. Temporary exact-source qualification is user-approved. An official release with the API is required before app publication; [ezpzbz/aiida-orca#89](https://github.com/ezpzbz/aiida-orca/pull/89) tracks the work. |
| aiidalab-qe-vibroscopy | reviewed `8d5d9c51192dbd2bf8dcf585c6ae1a8ca23ab6b4` | Official 1.3.1 lacks mode participation. Include the candidate in final GUI tests; the user handles its future official release. Existing 13 C1/C2 atom-index conversion tests and Andrés's resolved answer remain completed evidence. [aiidalab/aiidalab-qe-vibroscopy#189](https://github.com/aiidalab/aiidalab-qe-vibroscopy/pull/189) was merged prematurely; [revert192](https://github.com/aiidalab/aiidalab-qe-vibroscopy/pull/192) is open/unmerged. Resolve that intended tree before publication, without silently changing either PR. |
| EMPA widgets | merged canonical main `8a97ed1ab7b448217ec165df3a3ba48a7495e9dc` | Own component candidate retains CDXML and supplies shared cube/slice/opacity/tempfile fixes. Publish a corresponding version after qualification. |
| cubehandler | merged canonical master `51cd2bc0349ef2eae404592ff167078d416b01ec` | Own component candidate includes oblique row-vector grids and JSON rendering-contract normalization. Publish a corresponding version after qualification. |

Development PRs start from current canonical main/master independently of the
released-runtime rule. CI checks both the existing declared boundary (core 2.9.2,
AiiDAlab 26.9) and selected alignment target (core 2.9.4, AiiDAlab 26.10), with
widgets-base 3.0.1 and released Dyson tools. Keep the target interpreter/profile
unchanged until the concrete existing-container upgrade plan is reviewed.
No GUI/scientific acceptance starts automatically after a source merge.
