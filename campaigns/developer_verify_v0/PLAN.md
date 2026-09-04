# CAPY-DEVELOPER-VERIFY-V0

Status: active bounded implementation task.

If this task encounters a small implementation or environment blocker,
repair it within this task and continue; do not create a new gate or request
owner authorization unless the blocker changes the authorized product/safety
boundary.

The authoritative implementation contract is the owner-provided plan
`CAPY-DEVELOPER-VERIFY-V0-CODEX-IMPLEMENTATION-PLAN-2026-09-04.md`, SHA-256
`461b3a89742b8b94160d7ec88db19cdec3ede34e9bc937f2b4f23f075f51c534`.

## Frozen source truth

- Repository: `gazeromo/capy-developer`
- Required base: `124bf634ec023f064ebd7f051d049de65ff3228f`
- Base tree: `fd119733c5219c0d7c50544eeaad351f66abc44a`
- Branch: `codex/developer-verify-v0`
- Control authorization branch/head: `codex/developer-verify-v0` / `6e50de3`
- DevKit release binding: `0cf018faa02ade73ab0805aa0617c55ce36fa7b1`
- DevKit implementation: `55fc109b5f494086c03560794e7be74d75f1d93f`
- DevKit bundle: `cb7e4073a99bf8596509af02f466f90b5792d1d8075dffab0f27bbb2df0679e8`
- DevKit wheel: `165faba51b56b667b087228e1c556b1e2369d0e61bb469785ddff1bad9d6e2d0`
- FedEx main: `de79fd1d0c08ab01f85b5d25a7a6d69a672c5b94`
- Proforma main: `c21a308ec539898da8b6801ffc54845826bfd6cf`
- Runtime main: `61a71a1067183343504305337128ca0af083542f`

Foundation baseline passed 32/32 tests and the accepted Capy Developer wheel
installed offline with a passing doctor result before implementation.

## Capability and boundary

Implement one shared session-bound exact-commit verification core exposed by
MCP and JSON CLI. It must migrate SQLite 1→2, resolve exact locally available
locked DevKit bytes, run check/test/conform in a fresh offline environment,
detect source mutation, package from two independent clean snapshots, preserve
a content-addressed archive, and persist causal bounded stage evidence with
idempotency, concurrency, interruption recovery, and stale-state inspection.

Verified is not accepted, published, installed, or deployed. Runtime,
production, provider secrets, DevKit source/API, coding-agent launch, and all
existing application repositories remain unchanged.
