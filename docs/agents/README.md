# Helping a user through the ORCA app

This is the GitHub entry point for agents assisting with the ORCA app. The
maintained instructions are Markdown resources in the application package,
also readable here on GitHub. Do not maintain a separate copy for each model.

| Read in this order | Installed guide ID | Markdown source |
| --- | --- | --- |
| App orientation, geometry/SCF, step-by-step routes and official references | `orca.app` | [Start here](../../src/aiidalab_orca/knowledge/orca.md) |
| Common orbitals, CASCI, Dyson, Kondo and scientific acceptance | `orca.casci-kondo` | [Electronic-analysis guide](../../src/aiidalab_orca/knowledge/casci-kondo.md) |
| Harmonic IR/Raman, geometry selection and the acknowledged fixed-geometry route | `orca.vibrations` | [Vibrations guide](../../src/aiidalab_orca/knowledge/vibrations.md) |
| ORCA CASCI versus full exported or QPU/simulator-selected Hamiltonian solves, sampling checks and saved ORCA comparisons | `orca.quantum-energy` | [Quantum-assisted energy guide](../../src/aiidalab_orca/knowledge/quantum-energy.md) |

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

The guides describe the assembled standard-app preview. Its constituent
navigation, batch CASCI, spectral-map, resource and vibration changes can be
open PRs rather than merged releases. Check the installed GUI before promising
a control. XPS is a **Work in progress** placeholder. The standard quantum-assisted energy
route is covered by `orca.quantum-energy`; separate QPU/DMRG research extensions
must not be disturbed by navigation.

The [correlation-energy guide](../correlation.md), available as
`orca.correlation`, describes fresh-HF RI-MP2 and verified-CASSCF SC-NEVPT2.
Their energy-only outputs cannot replace Dyson/Kondo wavefunctions.

The optional [CASSCF route](../casscf.md) creates a new shared orbital reference
after explicit active-space confirmation. Its state-specific/state-average
weights optimize orbitals; they are not populations or tunnelling factors.
Require successful optimization and frozen readback, then inspect/reconfirm
the new orbitals before CASCI/Dyson or a new quantum Hamiltonian export.
