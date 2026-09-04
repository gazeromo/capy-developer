# CAPY-DEVELOPER-RELEASE-CANDIDATE-V0

Status: implementation in progress.

If this task encounters a small implementation or environment blocker,
repair it within this task and continue; do not create a new gate or request
owner authorization unless the blocker changes the authorized product/safety
boundary.

The authoritative owner plan is
`CAPY-DEVELOPER-RELEASE-CANDIDATE-V0-CODEX-IMPLEMENTATION-PLAN-2026-09-05.md`,
SHA-256 `4514d0ca5ce29a1d279689d0821d72fa317be61cb30404fc01a11b8d1668ea79`.

## Frozen source truth

- Repository: `gazeromo/capy-developer`
- Base commit: `e684fd601fabe8b072d7a309be44b71abe8b5d53`
- Base tree: `6e20b4a15e61b59c14058fa7a786e34d8ff97670`
- Branch: `codex/developer-release-candidate-v0`
- Control authorization: D-196, remote-visible at `46eeee59eb2181950f8107aad07d12dde685bcda`
- Accepted DevKit release binding: `8c4fec7f814a62ded441786b8eba28af14d1aa2d`
- Accepted DevKit source: `e4462973d94584a75a1596f1b06a425a8da7f20d`
- Accepted authoring bundle: `dc2c27611d12ecb12e1a929252a51e177537d8f0e4fba86de5ed93edae886d5c`
- Accepted wheel: `46f0b7865491054991b855d3bf709a445b7cc730077aaca2059cc095c685b30d`

## Capability

One successful verification ID produces one deterministic, durable,
self-contained `.capyrc` bundle. It contains exactly a canonical manifest, the
verified application archive, a path-free verification receipt, and the exact
verification-recorded DevKit authoring bundle. Shared core behavior is exposed
through JSON CLI and MCP create and inspect operations.

The candidate is unaccepted evidence. Independent acceptance, runtime import,
installation, binding, publication, signing, deployment, provider access, and
coding-agent launch are not implemented or authorized.
