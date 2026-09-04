# CAPY-DEVELOPER-VERIFY-V0

Status: qualified and ready for strict fast-forward acceptance.

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
- Control authorization/resumption head: `056515d2d2162af2c87b20de15c7cca17634fae5`
- DevKit release binding: `8c4fec7f814a62ded441786b8eba28af14d1aa2d`
- DevKit implementation: `e4462973d94584a75a1596f1b06a425a8da7f20d`
- DevKit bundle: `dc2c27611d12ecb12e1a929252a51e177537d8f0e4fba86de5ed93edae886d5c`
- DevKit wheel: `46f0b7865491054991b855d3bf709a445b7cc730077aaca2059cc095c685b30d`
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
