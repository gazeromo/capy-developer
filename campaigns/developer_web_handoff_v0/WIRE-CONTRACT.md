# Developer Link V0 frozen wire contract

Scope: deliberate local interactive development only. No invocation, acceptance,
installation, binding or deployment authority. HTTPS exact configured origins;
site IDs resolve only through local pairing. No remote paths/commands/prompts.
Canonical JSON: UTF-8, sorted keys, compact separators, finite JSON, no duplicate
keys. SHA-256 of canonical JSON. All closed shapes reject unknown keys.

Identifiers: site_<32hex>, dev_<32hex>, pair_<32hex>, hof_<32hex>.
URI exact ASCII: capy-dev://handoff/hof_<32hex>?site=site_<32hex>&launch=<1..2147483647>.
No escaping, fragments, additional keys, alternate ordering or leading zeroes.

Pair start POST /api/developer-link/pair/start:
{site_id, installation_id:32hex, secret_sha256:64hex, label:plain text <=80}.
Returns {site_id,pair_id,confirmation_code,expires_at,verification_path}.
Poll POST /api/developer-link/pair/poll: {site_id,pair_id}; Authorization Bearer
<64hex local secret>. Returns {status:PENDING|APPROVED,site_id,device_id:null|id,
principal_id:null|id,expires_at}. Local credentials protected, never in outputs.
Browser approval requires login+CSRF+matching confirmation_code, ten-minute
pair expiry, rate limiting. Device expiry finite; revocation checked every call.

Claim POST /api/developer-link/requests/<handoff_id>/claim:
{site_id,device_id,launch_generation}; Bearer local secret. Returns a request:
{schema:'capy.developer-link-request/v0',site_id,handoff_id,device_id,
principal_id,authority_id,workspace_kind:'personal'|'team',workspace_id,
membership_id,intent:'NEW'|'CONTINUE',parent_handoff_id:null|id,
release_candidate_id:null|rc_id,created_at:integer epoch,expires_at:integer epoch,
request_digest:64hex,launch_generation:integer}. Immutable digest excludes
request_digest and launch_generation only. NEW has no parent/candidate.
CONTINUE carries parent; null candidate means reopen active parent session.
Browser creates target from current ActorContext; Team owner only. Browser
create/open/continue/status and device claim/events revalidate current authority.
Browser double-click uses a 32-hex request idempotency key; open retry increments launch
only. Claim wins against cancellation durably; after claim disconnect only.

Snapshot closed fields:
{milestone,project_id:null|prj_id,session_id:null|ses_id,application_id:null|string,
source_commit:null|40hex,dirty:boolean,verification_id:null|ver_id,verification_commit:null|40hex,
verification_status:null|'RUNNING'|'PASSED'|'FAILED'|'INTERRUPTED',
candidate_id:null|rc_id,candidate_verification_id:null|ver_id,verification_commit:null|40hex,candidate_sha256:null|64hex,candidate_size:null|positive int,
candidate_commit:null|40hex,source_fresh:boolean,terminal:null|'COMPLETED'|'CANCELLED'}.
Milestones: PREPARING, WAITING_FOR_HARNESS, HARNESS_ATTACHED, CHANGES_IN_PROGRESS,
VERIFYING, CHECKS_FAILED, CHECKS_PASSED, CANDIDATE_PREPARED, SESSION_FINISHED,
LAUNCH_OUTCOME_UNKNOWN. Candidate binds its own passed verification and all candidate
fields; historical candidate retained with source_fresh false. Model text absent.
Initial website allocated state is server-owned READY_TO_OPEN. Freshness is
separate CONNECTED/STALE/DISCONNECTED/REVOKED based on receive time and authority.

POST /api/developer-link/requests/<handoff_id>/events body {events:[event,...]}:
event={schema:'capy.developer-link-event/v0',site_id,handoff_id,device_id,
sequence:positive integer,snapshot, digest:64hex}; digest excludes digest.
Max event16KiB, batch64 events/256KiB. First seq1; contiguous after ack.
Identical replay acknowledged; conflicting replay or gap rejected (expected next
sequence returned). Stable project/session association per handoff; candidate
and verification associations mandatory. Local authenticated reports not
independent acceptance. Return {ack_sequence}. Same snapshot coalesced locally;
empty batch is heartbeat and returns ack_sequence without history growth.

Local APIs to integrate (not wire): Companion(core).open_uri(uri),
.attach(handoff_id), .inspect(handoff_id), .sync_once(handoff_id=None).
Attach core/CLI/MCP takes handoff_id only, resolves trusted local database and
compares bounded marker; records idempotent HARNESS_ATTACHED.
DeveloperCore.continue_development({release_candidate_id,request,idempotency_key})
returns existing session-result shape. Exact candidate source, same project,
new session/worktree; preserve terminal parent. Dirty/newer source fails without
loss; missing exact object fails. Active continuation reuses parent session.

Desktop CLI delegation: desktop_cli.run(raw_args) handles setup/handoff commands
before ordinary parser. Native handler fixed installed entrypoint; no shell
interpolation. Codex documented threads/new?path= built locally only. Setup owns
only exact MCP entry and native handler with CAS receipts and additive removal.
Runtime must not import Developer. Coordinator owns identical protocol module
copies and parity checks; workers do not modify protocol fields independently.

In-envelope integration amendment: candidate_verification_id binds the historical
validated candidate independently of the latest verification. All candidate
fields are present together or null together. A newer failed check remains
CHECKS_FAILED while the saved candidate is retained with source_fresh false.
CANDIDATE_PREPARED requires latest PASSED verification matching the candidate.

Verification association uses verification_id + verification_commit. Current
source_commit may advance while the latest recorded verification stays fixed.
source_fresh requires clean known source and a verification/candidate fact; it
describes correspondence, never success by itself.
