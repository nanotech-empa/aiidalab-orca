# ORCA application guidance for agents

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

Large artifacts must remain remotely or be stashed according to the user's
explicit retention choice. Retrieve only compact results, bounded diagnostics,
manifests and reduced previews into AiiDA. Apply this to logs and CI exports as
well as wavefunctions, integrals and full cubes. Streaming reduces RAM use; it
does not make permanent retrieval of large files acceptable. Preserve historical
nodes and scientific acceptance checks. The remaining unbounded native-log
retrieval is a release gate documented in `docs/release-readiness.md`.
