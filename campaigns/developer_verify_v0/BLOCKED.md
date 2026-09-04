# Capy Developer Verify V0 terminal report

Status: **blocked at an explicit owner-plan stop condition**.

The latest bounded implementation candidate is
`e80b464772edbdde72e3fd47b80c3eb854bc66ac`, tree
`d4167bae520901d8053a51e256de33f0f5c1090c`. It passes all 71 local tests and
is remote-visible on `codex/developer-verify-v0`.

GitHub Actions run `33878099426` passed 71/71 tests on Ubuntu and macOS.
Windows passed the other 65 tests; the six failed expectations all require the
same resource-only verification pass and share the DevKit root cause below.

The accepted DevKit's resource-only application reaches `check` and `test` on
Windows, then its mandatory `conform` command crashes because the Windows
Python host has no `socket.AF_UNIX`. This is the plan's named stop condition,
not an ordinary Capy Developer defect that can be hidden with a platform
exception.

Journey A (MCP) and Journey B (JSON CLI) passed on macOS and preserved their
exact commits, verification IDs, nine-stage results, and archive identity.
They do not override the failed Windows acceptance gate.

No acceptance receipt, promoted 0.2.0 wheel, `main` merge, release action,
runtime mutation, publication, installation, or deployment was performed.
