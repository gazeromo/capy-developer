# Repository rules

This repository owns only the local developer-facing project and development
session layer.

- Preserve deterministic, fail-closed project selection.
- Existing versus new project intent must remain explicit.
- Use ordinary Git through argument arrays; never interpolate shell commands.
- Never modify an imported application checkout.
- Never import Capy runtime packages or read production state.
- Keep lifecycle semantics in one core shared by CLI and MCP adapters.
- Keep project identity independent of machine-local paths.
- Do not silently upgrade or substitute a DevKit lock.
- Treat `interaction.json` as inert plain-text data; validate it only from the
  detached candidate and preserve canonical bytes by digest.
- Keep verification and release-candidate V0 results byte/shape compatible;
  dispatch V1 only from an explicit interaction-aware lock.
- Do not launch a coding agent, accept a release, publish, or deploy software.
- Tests must override all data, cache, repository, and worktree roots.
