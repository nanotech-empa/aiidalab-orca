# Agent instructions

Before submitting, modifying or diagnosing XPS calculations, read
[docs/agents/xps.md](docs/agents/xps.md). Consult the linked method documentation
before changing a physical model or interpreting the resulting spectrum.

Keep scientific provenance immutable. Store UUIDs and plain values in durable
state, and reload AiiDA ORM nodes at the point of use. Check for concurrent
worktree edits before committing or changing the deployed app.
