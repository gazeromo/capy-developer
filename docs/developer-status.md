# Configured Developer status

Call `capy_developer_status` without arguments, or run `capy-dev developer-status`,
to inspect the configured local installation. Both use the same read-only status
function. Optional `session_id` (`--session-id` in CLI) returns stored exact
session facts and linked handoff IDs. Revalidate Git facts with
`capy_development_inspect` before editing; stored status does not authorize taking
over another editor.

The response includes the running package version, SHA-256 of sorted Python
source paths and bytes, and SHA-256 of the canonical serialized MCP tool list.
The Python digest is a source identity, not a wheel or deployment attestation.
It exposes paired installation/site IDs and locally recorded client versions and
channels, but no credentials, credential references, private configuration paths,
requests, source content, or database paths. It does not initialize or migrate
storage. Remote readiness and client challenge freshness remain `NOT_CHECKED`;
use the exact listed client ID with `capy_client_status` for remote status.
Missing setup and ambiguous active installation identities produce a causal next
action rather than silently choosing or allocating a different installation.

`capy_development_start` and `capy_work_begin` publish ordinary top-level object
properties, without a top-level union that some client adapters erase. Their
shared implementation remains authoritative: exactly one intent must be supplied.
For example:

```json
{"idempotency_key":"weather-app-1","request":"Build a weather viewer","new":{"name":"Weather Viewer","application_id":"weather-viewer"}}
```

For an existing application, replace `new` with exactly one catalog selector such
as `"existing":{"application_id":"weather-viewer"}`. Missing intent, both
intents, unknown fields, or ambiguous catalog selection fail closed.
