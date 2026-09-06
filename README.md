# Capy Developer

Capy Developer prepares an exact Capy application project for any coding
harness that can call an ordinary JSON CLI or MCP stdio server. It owns local
project identity, pinned DevKit resolution, managed native-Git mirrors and
isolated worktrees, and durable development-session state.

Install from this repository with Python 3.11 or newer:

```text
python3 -m pip install .
capy-dev doctor --json
```

Core automation commands:

```text
capy-dev projects import --path /explicit/admin/checkout --json
capy-dev projects search --query shipping.fedex_quote --json
capy-dev development start --input request.json --json
capy-dev development inspect --session-id ses_... --json
capy-dev development verify --session-id ses_... --application-id demo.app --candidate-commit 0123... --idempotency-key verify-1 --json
capy-dev release-candidate create --verification-id ver_... --json
capy-dev release-candidate inspect --release-candidate-id rc_... --json
capy-dev development finish --session-id ses_... --disposition COMPLETED --json
capy-dev mcp
```

The process working directory is never a project-selection input. Existing and
new project intent are explicit. Verification is bound to one exact clean
commit and runs the project's exact locally available locked DevKit offline.
New projects use `capy.toolchain-lock/v1`: verification adds deterministic
cross-contract validation of root `interaction.json`, preserves its canonical
bytes, and returns the path-free V1 interaction identity. Legacy and V0 locks
retain their exact nine-stage behavior and are never silently upgraded;
it does not accept, publish, install, or deploy the candidate. Capy runtime
source and production deployment are outside this repository. User-initiated
local interactive-harness opening is provided by a replaceable desktop adapter;
autonomous coding-agent supervision is excluded.

A passed verification can be converted into one deterministic, self-contained
`.capyrc` handoff object using only its verification ID. Interaction-aware V1
candidates have exactly five members and carry both source-form
`interaction.json` inside the unchanged application archive and a separately
addressable canonical interaction projection. That object remains an
unaccepted release candidate: Capy Developer does not accept, publish, install,
bind, or deploy it.

See [docs/DIRECTION.md](docs/DIRECTION.md) and the frozen interaction-contract
campaign plan in `campaigns/developer_interaction_contract_v0/PLAN.md`.

### Selected candidate transfer (0.6.0)

A paired site's **Send this version** action opens the existing native handler
for a separate candidate-submission URI. The companion checks the site's transfer
capability, exact local handoff and immutable V1 candidate, then displays a local
source-disclosure confirmation. It sends only the selected `.capyrc` bytes to the
fixed paired HTTPS endpoint. It does not launch Codex or run verification.

Transfer history is separate from completed development sessions:

```sh
capy-dev handoff transfers --json
```

An interrupted transfer can be retried through the same site action. Exact retries
reuse confirmed selection and custody acknowledgment; changed generations require
new local confirmation. Old servers report `TRANSFER_UPGRADE_REQUIRED`. The native
handler's existing `handoff open` entrypoint supports both closed URI grammars;
upgrading the package in the same Python installation needs no handler replacement.
Changing the Python installation still requires ownership-checked desktop setup.
Local confirmation/native transfer is qualified for macOS; other platforms fail
closed when that confirmation is unavailable. Source transfer does not accept or
install an application. Existing Developer Link V0 message shapes are unchanged.

### Harness-first source preview

The current source branch adds `capy-dev connect --site <HTTPS origin> --client
muse` for a site implementing the harness-first protocol. This is unfinished
source work; it is not included in the published 0.6.0 package.

Muse guidance is installed through the native `muse skills` commands. Setup
records exact ownership, preserves existing skills, and verifies native discovery.
Setup also adds an owned stdio MCP entry to Muse's documented settings file,
preserving unrelated settings and other servers. The shared guide and MCP entry
retain the installation's five original roots. Muse runs trusted MCP helpers
outside its shell sandbox, with normal native tool approvals; setup does not
change sandbox or provider settings.
A fresh Muse session may be needed to load guidance and tools. A configured integration is
not ready until an actual tool check reaches the paired site.

`capy-dev client list`, `client inspect --client-id <id>` and
`client check --client-id <id>` read existing local connection storage without
migrating the catalog. Development operations still require write access.

`capy-dev client remove --client muse` removes only the unchanged, owned native
Muse skill and MCP entry. It retains shared guidance, the catalog, projects, candidates, Codex
configuration and computer pairing. Revoke computer access separately on the site
when that is the intended action. Modified or unowned native files stop removal.

Linked work returns an explicit **Continue in prepared workspace** launcher on
macOS when a client needs to reopen. The launcher resolves the saved objective
and exact managed session locally; it never runs automatically. Completed work
requires an exact candidate continuation. Other native reopen platforms remain
unqualified.

After finishing, `capy_work_sync` (or `capy-dev work sync --handoff-id <id>`)
retries only the linked report and returns its acknowledgment and review URL.
Pending/offline reporting does not rerun application checks or send source.

For terminal-only source sending, the owner first selects **Send this version**
on Capy. `capy_candidate_pending` / `capy-dev work pending --handoff-id <id>` lists
the current approved intents for that work. On the user's explicit request,
`capy_candidate_send` / `capy-dev work send --handoff-id <id>` reuses the existing
sender and native local disclosure confirmation. Multiple pending intents require
an exact `submission_id` / `--submission-id` selection. This does not approve
independent checks, prepare a semantic acceptance profile, or install an app.
