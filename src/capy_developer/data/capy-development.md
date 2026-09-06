---
name: capy-development
description: Create or continue a Capy app through the connected local Developer tools and return its website review link. Use for Capy application development, not Capy platform maintenance or unrelated coding.
---

Resolve website-linked work through Capy before creating application files.
Use the installed local entrypoint recorded below; its helper preserves the shared
catalog and roots. Inspect `client list` and `work list` to recover saved clients
and work without relying on an earlier conversation. Multiple plausible sites or
projects require a clear selection; never guess from the current directory.

For a new app, call `work begin` with a local JSON object containing `client_id`,
a new 32-character hexadecimal `intent_id`, the user's `request`, and `new`
with `name` and `application_id`. Persist and reuse that input for retries.
For a completed linked candidate, use `parent_handoff_id` instead of `new`.
Native MCP exposes the same operation as `capy_work_begin`.

Use only the returned managed workspace and exact session. Read its `CAPY.md`
and contract references. A returned path is not permission to edit it: use the
client's normal workspace switch or one supported continuation in that workspace.
When an in-session switch is unavailable, offer the returned continuation launcher
as one explicit action. It reopens the same client with the saved objective; do not
run it silently or ask the user to reconstruct a command or copy session IDs.
Preserve the user's objective. Attach the returned handoff through
`development attach` once the client is working there. Do not select a repository,
initialize Git, substitute a toolchain, or silently take over active work.

Write ordinary application code and tests. Commit exact source through normal
Git approvals. Run authoritative `development verify` for that commit. A failed
verification remains evidence; a new commit needs a new verification. Create a
`release-candidate` only after verification passes, then finish the session and
run `work sync --handoff-id <returned handoff>` or `capy_work_sync` to confirm
the linked status acknowledgment and recover the exact review URL. If reporting
is offline, preserve the pending report and retry sync; do not rerun verification
or claim that Capy has acknowledged it.

Return the Capy review URL and describe the result as a prepared candidate.
Source sending, independent checks, preview and Personal activation retain their
existing human approvals. Never manufacture consent or claim the app is installed.
Missing acceptance-profile preparation is a real pending step.
