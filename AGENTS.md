# ORCA application guidance for agents

For browser acceptance testing, start with [the full GUI test guide](docs/testing/README.md)
and [agent handoff](docs/testing/agent-handoff.md). Follow the user's authorized
case IDs and scope. Localhost is the default; Remote CPU, real QPU execution
and connected publication are separate optional permissions. Do not replace
GUI actions with backend/API submissions or mark unobserved cases passed.
Preserve research calculations and report missing GUI routes explicitly.

For user-facing help, start at [the agent guide index](docs/agents/README.md).
Read the app-owned guides supplied by the installed AiiDAlab chat and inspect
its current tools, selected calculation and visible form before giving steps.
The same guidance applies to OpenAI, Claude, Gemini and other providers.

The ORCA manual documents the engine; it does not establish which controls the
app exposes. Keep user navigation, draft preparation, review and submission
distinct. Preserve scientific provenance and existing authorship/credits.
Keep only UUIDs/plain values in durable state and reload ORM nodes per operation.

## Deployment and storage contracts

The app is computer agnostic. Use compatible codes already configured in AiiDA;
computer/code installation, scheduler configuration and wrappers belong to
`aiidalab-empa-setup`. Do not add machine names or scheduler/transport allowlists
to application discovery or workflow validation.

Wavefunctions, integrals, full cubes and large CI exports remain remote/stashed
according to the user's explicit choice. Native text outputs follow a separate
`maxsizeoutput` threshold: default 5 MiB per file, original bytes retrieved at or
below the threshold, otherwise a separate extract and an explicit outputcat
notice. Never present the extract as the original output. Keep all compact PDOS
data needed for interactive projections in AiiDA. Streaming reduces RAM use but
does not replace these storage rules. Preserve historical nodes and scientific
acceptance checks; see `docs/release-readiness.md` for remaining work.
