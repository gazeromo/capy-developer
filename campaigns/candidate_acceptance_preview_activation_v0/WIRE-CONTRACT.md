If this task encounters a small implementation or environment blocker,
repair it within this task and continue; do not create a new gate or request
owner authorization unless the blocker changes the authorized product/safety
boundary.

# Candidate acceptance V0 — seam freeze revision 1

All JSON is canonical UTF-8, sorted keys, compact separators, no NaN or duplicate
keys. Schema-owned objects are closed. IDs have the indicated prefix plus 32
lowercase hexadecimal characters; hashes are 64 lowercase hex; commits 40 hex.
Integers exclude booleans. Unknown fields/actions fail. No paths, callback URLs,
commands, secrets or prompts are accepted from a browser/native URI.

## Device protocol (additive; existing V0 remains exact)

Separate fixed prefix `/api/candidate-submissions/`. All JSON POST requests have
256 KiB bounds. Binary upload is routed before legacy JSON parsers; maximum
32,000,000 bytes, finite timeout 30 seconds, no transfer-encoding ambiguity.
Same exact paired HTTPS origin, no redirects. Authentication is existing paired
Bearer credential; browser cookies never authorize device operations.

POST `capabilities`: request exactly {schema:"capy.candidate-capabilities/v0",
site_id, device_id}. Response exactly {schema:"capy.candidate-capabilities/v0",
site_id, device_id, supported:true, max_candidate_bytes:32000000}.
404/unsupported => TRANSFER_UPGRADE_REQUIRED; no guessed write fallback.

Native URI grammar (max 256 ASCII bytes):
`capy-dev://submission/sub_<32hex>?site=site_<32hex>&send=<positive integer>`.
No duplicate/reordered/extra query keys, fragments, percent encoding, credentials,
ports or trailing slash. Parsed fields submission_id, site_id, generation.

POST `sub_<id>/grant`: request exactly {schema:"capy.candidate-grant-request/v0",
site_id, device_id, generation}. Response exactly:
{schema:"capy.candidate-transfer-grant/v0",submission_id,site_id,device_id,
generation,expires_at,consent_revision:"source-package-v0",installation_id,
principal_id,authority_id,selection}.
selection exactly {handoff_id,project_id,application_id,session_id,verification_id,
source_commit,candidate_id,candidate_sha256,candidate_size_bytes}.
Grant is a server-held authorization, no bearer in URI/response. Match paired
installation, authoritative local handoff/project/session and immutable candidate
before opening bytes. Do not require reporter online. Confirm site, selection,
size and source-disclosure text locally before any first transfer of this grant.

POST `sub_<id>/bytes`: application/octet-stream, Content-Length exact and bounded;
Authorization paired Bearer, X-Capy-Device device ID, X-Capy-Generation canonical
positive integer. No server-selected upload destination. Stream opened regular
CAS file after rehash and authoritative inspection. Recheck fd metadata/hash;
no path symlinks, latest substitution, verification/build or session mutation.
Response exactly {schema:"capy.candidate-custody/v0",submission_id,candidate_id,
candidate_sha256,candidate_size_bytes,status:"RECEIVED"}.
Exact retry returns same ack; conflicting retry fails. Mid-transfer revocation
fails finalization. Partial bytes cannot publish custody. Local transfer history
is separate additive desktop DB table; terminal development remains terminal.

## Submission and runtime owner authority

Browser submission creation requires current authenticated actor+CSRF+exact
Origin and selected saved handoff candidate. Derive selection from link ledger,
never hidden candidate fields. A submission stores site, original selection,
principal_id,authority_id,membership_id,workspace_id,workspace_kind,device_id,
consent_revision,created_at,expires_at,generation,revision and transfer state.
Max 8 pending submissions per principal, 64 MB received uninstalled payload quota.
Source consent is explicit POST; review GET creates no upload/execution.

Check authorization binds submission ID, candidate hash, profile hash, summary
hash, authority/principal/membership/workspace, consent revision checks-v0 and
idempotency key. Current ownership/membership is rechecked before enqueue,
worker dispatch and result promotion. Client logout alone is not revocation.
Changed exact binding with reused key conflicts. Cancellation is terminal for
promotion, retaining diagnostics. Status dimensions remain separate.

## Bridge control boundary

One private package, SQLite/content root and bounded worker; runtime never imports
acceptor/Developer. Unix socket with filesystem permissions AND SO_PEERCRED
Linux UID verification; runtime and maintainer callers have distinct configured
UID roles. No browser header asserts bridge peer identity. Configuration paths
and UIDs are operator inputs, never wire payload fields.

Framing: four-byte big-endian canonical JSON header length (max 262144), header,
then declared payload bytes (0 except submission.receive/profile.register).
Request header exactly {schema:"capy.release-bridge-call/v0",operation,payload,
body_size}; response same framing, header exactly {schema:
"capy.release-bridge-reply/v0",ok,result,error,body_size}. error is null or bounded
constant code. Typed closed operation payloads; no generic command/SQL/path API.
Operations: submission.begin/receive/inspect/cancel, profile.register/inspect,
pilot.enroll, test.authorize, acceptance.enqueue/inspect/cancel,
accepted-release.export. Maintainer-only profile.register and pilot.enroll.
Runtime-only owner-action operations/export. Received source immutable in private
CAS; no extraction or execution by gateway. Bridge read_candidate validation is
non-executing and uses installed exact protected acceptor wheel.

Profile registration binds canonical bundle bytes, readable summary bytes,
owner-intent provenance hash, independent author/reviewer IDs; summary includes
actual ordered case IDs and expected projections plus reviewed behavior prose.
Registration cannot come from upload/pair identity. Pilot enrollment separately
binds exact candidate hash to reviewed synthetic stateless connection-free scope.
Owner click cannot register a profile, enroll a candidate or assert acceptance.

One OS-locked worker, fenced generation, explicit QUEUED/RUNNING/terminal ledger.
Disposable Linux adapter receives only copied exact candidate/profile/toolchain,
no controller ledger/approvals/credentials. Parent controller owns promotion.
Lost/crashed execution becomes INTERRUPTED after confirmed cleanup; no automatic
rerun or inferred success. Explicit retry is a new authorized attempt. Late or
cancelled worker cannot promote. Exact terminal replay never executes.

Accepted export: response JSON result {record} followed by a deterministic ZIP
containing candidate.capyrc and acceptance.json ONLY. record schema
capy.trusted-accepted-release/v0 binds submission owner/context and selection,
profile_sha256,summary_sha256,authorization identity, enrollment identity,
acceptor package/implementation identity, candidate+receipt digest/size,
source/application/toolchain projections, ordered expected_cases and their digest.
Ordered expected cases come from registered profile, never receipt enumeration.
Controller compares complete ordered cases, observed==expected, matched=true,
CASE_MATCHED, exact ACCEPTED identity, PASSED secret scan and CONFIRMED cleanup
before immutable publication. Export is authenticated custody, no signature claim.

## Admission, preview and activation

New release_admission API consumes export ONLY from configured trusted client.
No public dict-based trust override. Validate complete bindings and namespace
under import OS lock before publishing immutable application/environment/evidence.
Namespace is (authority,principal,project); existing legacy or foreign app ID
conflicts. Normal runtime root needs no preview marker or special basename.
Create new admission tables; old import_release/prepare_preview guards unchanged.
Admission receipt always UNBOUND. Runtime lookup supports both proven paths.
Exact computed version with different descriptor/interaction/environment fails.
Recovery reuses exact published files, never app execution.

Preview maps live authenticated owner through an internal context adapter into
one private test-owned RuntimeStore and real OutcomeRuntime/Workbench. Do not
create organization-visible membership. Every route rechecks current owner and
membership, exact release, expiry and preview-local resources/artifacts. Default
24 hours, bounded resource bytes and active work. Expiry blocks work before
cleanup; retain minimal identity/history. No source/worktree fallback. A real
successful exact preview invocation is required before Add.

Activation locks current authority and serializes DB mutation. Use canonical
Personal scope and TeamSoftwareStore semantics. Add nested RuntimeStore transaction
support if needed so share/reconciliation/binding/activation receipt commit as
ONE transaction, with regression proof; no partial visible binding. Current target
is server-resolved at POST. Exact release/preview/target/idempotency binding;
conflicting version returns UPDATE_REQUIRES_SEPARATE_FLOW. Team owner only, new
source-sharing confirmation for target. Remove canonical share/bindings atomically;
restart cannot re-add. Preview files/results never move to destination.

## Dependency/ownership map

Coordinator: shared wire freeze, runtime web/status/preview/admission/activation.
Developer worker: additive device protocol, transfer state/transport/CLI/local
confirmation and ownership-checked setup; no runtime code.
Bridge worker: controller, custody, profile/pilot authorization, queue and trusted
export; no runtime code or profile-author expected values.
Independent profile author: private profile-author directory only; no candidate
implementation/tests/output. Separate fresh review checks frozen oracle.
Isolation worker: new task-owned execution environment/preflight only.
No parallel source edits before these seams are frozen and Phase 0 prerequisites
are met. Changes to seams are coordinated explicitly, not guessed by workers.

## Closed bridge payloads (revision 1)

`owner` is exactly {principal_id,authority_id,membership_id,workspace_id,
workspace_kind}; those values are asserted only by the configured runtime peer
following Access checks. `selection` is the device selection object above.
Bridge records revision numbers; mutations use expected_revision where listed.

- submission.begin: {submission_id,site_id,device_id,owner,selection,
  consent_revision,created_at,expires_at,generation}. Runtime stores/derives full
  immutable intent before call; identical begin replay returns same record.
- submission.receive: {submission_id,owner,expected_revision}; body candidate
  bytes. Runtime holds current device/owner authority through final bridge call;
  receiving after revoked grant is forbidden even if bytes match.
- submission.inspect/cancel: {submission_id,owner}; cancel repeat idempotent.
- profile.register: {summary,provenance}; body canonical .capya. summary is exact
  canonical JSON {schema:"capy.check-summary/v0",title,does,does_not,examples},
  examples ordered {case_id,explanation,expected}; expected is full .capya expect
  object. Controller derives/checks every example case/expect against profile;
  readable prose requires independent review in provenance. provenance exactly
  {intent_sha256,author_id,reviewer_id,review_sha256}; author!=reviewer.
- profile.inspect: {profile_sha256}; runtime may query only for an owned received
  submission through runtime policy. Internal peer response includes summary.
- pilot.enroll: {candidate_sha256,reviewer_id,review_sha256,policy_revision};
  policy_revision is reviewed-synthetic-stateless-v0; exact candidate only.
- test.authorize: {submission_id,owner,profile_sha256,summary_sha256,
  consent_revision,idempotency_key}. checks-v0; received+profile required.
- acceptance.enqueue: {submission_id,owner,authorization_id,idempotency_key}.
- acceptance.inspect/cancel: {submission_id,owner,attempt_id}.
- accepted-release.export: {submission_id,owner,attempt_id}.

IDs returned by controller are content/random generated per operation and never
accepted as evidence from a device. Bridge submissions retain owner authority
fingerprint. Runtime rechecks durable principal/membership at each mutation and
before worker dispatch/promotion through explicit fixed peer authority check;
when unavailable job is BLOCKED, not assumed valid. Socket roles include a
controller-to-runtime current-authority endpoint if processes are separated; it
must carry only stored owner context, not candidate-selected fields. Authority
fencing may alternatively use a runtime-issued short-lived dispatch/promotion
permit refreshed through current Access, never a permanent boolean enrollment.
Implementation must choose and record one before worker integration.

## Staging association and local consent clarification

Grant installation_id/principal_id/authority_id must match the approved local
pair and handoff request. Staging uses an isolated catalog/CAS/config copy and
a fresh staged pairing/validated handoff association; it never edits the live
association. Original candidate/project/session/verification/handoff identities
are preserved and separately recorded as source provenance; site/device/owner
authority are explicitly new test-context associations. An existing candidate
may be associated to the test-owned completed handoff via normal validated
association/events, never by injecting transfer or acceptance success. Local
confirmation record binds submission+generation+site+candidate hash+consent
revision, and is never manufactured by a native URI alone.
