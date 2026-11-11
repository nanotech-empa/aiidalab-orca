# Helping a user through the ORCA app

This is the GitHub entry point for agents assisting with the ORCA app. The
maintained instructions are Markdown resources in the application package,
also readable here on GitHub. Do not maintain a separate copy for each model.

For an observed browser test, follow [the full GUI acceptance guide](../testing/README.md)
and [browser-agent handoff](../testing/agent-handoff.md). Humans and agents use
the same case IDs, evidence and stop rules. Localhost is the default; optional
Remote CPU, Remote QPU and connected-export scopes need separate authorization.

| Read in this order | Installed guide ID | Markdown source |
| --- | --- | --- |
| App orientation, geometry/SCF, step-by-step routes and official references | `orca.app` | [Start here](../../src/aiidalab_orca/knowledge/orca.md) |
| Fixed-geometry TDA/TDDFT, optical spectra and NTO hole/particle inspection | `orca.optical` | [Optical operating guide](../../src/aiidalab_orca/knowledge/optical.md) |
| Common orbitals, CASCI, Dyson, Kondo and scientific acceptance | `orca.casci-kondo` | [Electronic-analysis guide](../../src/aiidalab_orca/knowledge/casci-kondo.md) |
| Harmonic IR/Raman, geometry selection and the acknowledged fixed-geometry route | `orca.vibrations` | [Vibrations guide](../../src/aiidalab_orca/knowledge/vibrations.md) |
| ORCA CASCI versus full exported or QPU/simulator-selected Hamiltonian solves, sampling checks and saved ORCA comparisons | `orca.quantum-energy` | [Quantum-assisted energy guide](../../src/aiidalab_orca/knowledge/quantum-energy.md) |
| Fresh-HF MP2, verified-CASSCF NEVPT2/CASPT2, native rejection checks and energy-only limits | `orca.correlation` | [Correlation operating guide](../../src/aiidalab_orca/knowledge/correlation.md) |

In the AiiDAlab chat, consult the guides delivered in the current instructions
or use `read_workflow_guide(guide_id)`. The shared assistant discovers them
through `aiidalab_assistant.workflow_guides`, supplies their text before calling
any provider, and records their SHA-256. Prefer the installed guide and live
capabilities when they differ from a different Git branch or an old example.
The ORCA registration includes `orca.quantum-energy` under the ORCA app identity,
so a generic next-step question in ORCA context also receives that guide.
Reading a guide does not submit a calculation or authorize an action.

When working outside that chat, follow the relative links above and inspect
the intended installed/release revision. An agent must not claim to have read
GitHub or an official manual page if its environment cannot retrieve it. The
embedded chat currently has no web-search/browser tool; it can supply the
checked official links and the packaged instructions without pretending to
have performed a fresh literature search.

## What a useful answer looks like

Identify the user's goal and current stage, explain one next action using the
actual visible control name, describe whether it navigates, prepares a draft,
reviews inputs or submits a job, and say what result to inspect afterwards.
Ask for the workflow UUID or missing scientific choice only when the current
selection and available tools do not supply it. Never invent completed jobs,
active spaces, capabilities or a molecule-specific recipe for a new system.

The guides describe the standard app and the CASSCF/correlation candidate.
Use the [stage validation record](../release-readiness.md) to distinguish
implemented paths, native pilots and remaining release/server acceptance.
Verify the installed revision and GUI before promising a control; an assembled
preview can contain unmerged components. XPS is a **Work in progress** placeholder.
The standard quantum-assisted energy
route is covered by `orca.quantum-energy`; separate QPU/DMRG research extensions
must not be disturbed by navigation.

For native DMRG, use the packaged `orca.dmrg` guide, [manual cases](../testing/dmrg-localhost.md) and [checkpoint and restart rules](../dmrg.md)
before resuming a job. New MPS checkpoints stay remote; historical paused jobs
retain their old retrieval plans and require a new continuation to adopt this policy.

The [correlation-energy guide](../correlation.md), available as
`orca.correlation`, describes fresh-HF RI-MP2 and verified-CASSCF NEVPT2/CASPT2,
including explicit CASPT2 shifts and reference-weight/residual diagnostics.
Their energy-only outputs cannot replace Dyson/Kondo wavefunctions.

The optional [CASSCF route](../casscf.md) creates a new shared orbital reference
after explicit active-space confirmation. Its state-specific/state-average
weights optimize orbitals; they are not populations or tunnelling factors.
Require successful optimization and frozen readback, then inspect/reconfirm
the new orbitals before CASCI/Dyson or a new quantum Hamiltonian export.

The [noncontiguous-CAS preparation candidate](../orbital-reordering.md) documents
explicit source/prepared mapping, signed checks, supported source types and the
pending native/browser pilot. Check installed controls and acceptance status;
the branch and preview selector alone do not establish deployment.
