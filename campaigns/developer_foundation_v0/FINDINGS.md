# Capy Developer Foundation V0 findings

## Frozen inputs

All plan-time source identities remained current at implementation start:

```text
control main:   b9451fb382f252430ed89f533dffa8c122482f47
runtime main:   61a71a1067183343504305337128ca0af083542f
DevKit main:    0cf018faa02ade73ab0805aa0617c55ce36fa7b1
FedEx main:     de79fd1d0c08ab01f85b5d25a7a6d69a672c5b94
Proforma main:  c21a308ec539898da8b6801ffc54845826bfd6cf
```

The new private repository did not exist and was created only after the control
authorization record became remote-visible.

## Bounded implementation repairs

- The first DevKit bundle reproduction used the abbreviated build-tool identity
  shown in the documentation example and produced digest `3eb9d7d1...`. The
  accepted qualification receipt includes `wheel 0.45.1`; using that complete
  identity reproduced exact accepted digest `cb7e4073...`. The mismatched bytes
  were replaced before use.
- The first new-project smoke exposed an SQLite placeholder-count defect. The
  failed session remained recorded and the insert was corrected.
- The next smoke exposed a Git branch-existence probe that trusted `rev-parse`
  stdout after a nonzero exit. It was replaced with exact `show-ref --verify`.
- macOS `/tmp` resolves through `/private/tmp`; managed-root containment now
  compares resolved roots and targets instead of rejecting a platform-owned
  symlinked ancestor.
- Managed remote refs and local session branches now occupy separate namespaces
  so a later fetch cannot prune a live development branch.

These were ordinary implementation/environment repairs inside the authorized
boundary. Failed smoke sessions were test-owned and no product, application, or
production state was involved.

## Current qualification facts

- The exact accepted authoring bundle and wheel are embedded in the installable
  package and copied only after digest verification into a content-addressed
  cache.
- Legacy FedEx lock parsing reports its historical wheel as `MISSING`; it is not
  silently replaced by the accepted current wheel.
- Proforma imports with truthful `UNBOUND` toolchain state.
- Real exact FedEx and Proforma source heads were imported through isolated
  local canonical Git fixtures. The source checkouts remained byte/status
  unchanged.
- The machine's native Git is not configured to authenticate private GitHub
  HTTPS fetches non-interactively. That provider credential setup is outside V0;
  a direct attempt failed causally rather than using stale source. The protocol
  and acceptance paths use ordinary native Git against canonical local remotes.
- CLI and MCP execute the same core and return the same versioned result values.
- No runtime import, production database access, model/provider call, coding
  agent launch, release action, or deployment exists in the source.

Cross-platform CI and independent reviews are recorded separately before
terminal closure.

## Review-driven repairs

Fresh independent review exposed and closed bounded defects before acceptance:

- MCP now publishes explicit existing-project selector fields, malformed CLI
  invocations stay JSON, malformed MCP method shapes return JSON-RPC errors,
  and failed-session replay preserves its causal error.
- Git execution strips inherited Git configuration variables, disables hooks
  such as `core.fsmonitor`, applies an explicit protocol allowlist, preserves
  non-default ports and arbitrary SCP usernames, and rejects originless or
  remote-helper identities.
- Operation serialization uses kernel-owned byte-range locks on every platform;
  failed Windows opens and lock attempts close their handles, and abrupt process
  exit releases the lock without timestamp theft.
- Legacy toolchain availability hashes the actual wheel member rather than
  trusting its manifest claim.
- Import validates local path safety but derives manifest, application, and
  toolchain metadata from a synchronized detached snapshot of the canonical
  remote default branch. Start reconciles that metadata again against the exact
  fetched base before returning `READY`.

The final immutable implementation candidate passed 32 tests on each of macOS,
Ubuntu, and Windows in GitHub Actions run `33868308194`. Both independent gates
accepted that exact commit with no P0-P2 findings.
