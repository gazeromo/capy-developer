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

## Resume an existing unlinked session for publication

Use `capy_work_begin` (or `capy-dev work begin`) with exactly `client_id`,
`intent_id`, `request`, and `session_id`. The explicit session selector links the
same clean READY managed session through the normal approved connection and site
claim. It creates neither a project nor a development session. Durable intent
replay retains the same handoff; another existing handoff, a terminal or dirty
workspace, and a mismatched claimed project are refused. Use the original linked
handoff when one already exists.

V1 verification and candidate responses include one `next_action`. Passed
verification points to candidate creation. An unlinked candidate points to linking
its existing READY session; an ended unlinked session points to exact candidate
continuation in the same project. A linked candidate includes its exact handoff
and review URL, with normal status sync, website approval and native source
consent still required. Expired or replaced connections require restoration.
These are local continuation instructions, not proof of site acceptance,
publication or installation. V0 responses and immutable V1 candidate bytes are
unchanged.

## Discover managed connection input and result contracts

Call `capy_connection_contracts` with the exact configured `client_id` and an
optional `contract` identifier. The authenticated Capy site returns its finite
supported contract metadata, including required request fields, result shape and
synthetic examples. Developer contains no provider-specific schema or routing.
The transport uses one fixed authenticated harness route; contract identifiers
cannot select a path or remote URL. Responses are size/depth bounded and reject
external schema references, unexpected top-level fields, URLs and credential
references.

`credential: managed_by_capy` and `binding: team_configuration` describe the
boundary. `availability: not_checked` is not evidence that a grant exists or
that a provider is usable. Use the returned exact schemas, collect required
inputs and retain normal human configuration, source consent and acceptance.
