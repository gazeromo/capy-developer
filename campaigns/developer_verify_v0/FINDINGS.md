# Capy Developer Verify V0 findings

## Implemented capability

The branch implements the shared exact-commit verification core, SQLite schema
1→2 migration, fixed nine-stage pipeline, exact accepted-DevKit binding,
content-addressed archives, durable replay, stale-state inspection, JSON CLI
`verify`, and MCP `capy_development_verify`.

Local qualification passes 78 tests. Two clean coding-harness journeys proved
causal fail/repair/retry behavior through MCP and JSON CLI. Both produced the
same candidate tree and same-host archive digest
`00dea5251ec84fd9ff727b31c6067ea4601c06f8af7d4a28f5e659952780cf13`.

## Review-driven repairs

Successive fresh reviews found and drove bounded repairs for:

- exact release-binding validation in addition to wheel/bundle digests;
- Windows process-tree ownership with suspended start and a Job Object;
- POSIX TERM/KILL escalation and bounded streaming output capture;
- failed/missing Git worktree cleanup and durable cleanup-failure downgrade;
- owned short temporary paths for the accepted DevKit's Unix socket;
- finish locking, import-timeout classification, and abandoned-attempt repair;
- bounded Git execution and output capture;
- rejection of candidate lock symlinks and containment escapes;
- exact candidate HEAD/tree/detached/clean revalidation after each executable stage;
- reconciliation of all abandoned RUNNING attempts before a new key allocates.
- pack-time rejection of committed-source mutation;
- large dirty-tree status handling as a bounded boolean probe;
- same-commit branch-drift invalidation; and
- recovery that records external cleanup failure without breaking inspect or
  finish.

Review requests for hostile-code filesystem/network sandboxes and comprehensive
memory/process/disk quotas were not adopted. The owner plan explicitly states
that application code is developer-authorized code under the developer's OS
identity, and lists network isolation and malicious third-party safety as
non-claims. No such safety claim is made here.

## Resolved platform blocker

Windows qualification proved that the exact accepted DevKit cannot conform its
own resource-only template on the target runner. The traceback terminates at:

```text
capy_script/simulator.py, ConnectionSimulator.__exit__
AttributeError: module 'socket' has no attribute 'AF_UNIX'
```

This occurred with `connections = []`; it is not a connection-bearing test.
The owner plan names this exact situation as a stop condition: “the current
DevKit cannot run the resource-only acceptance app on a target OS.” The
protected DevKit release was therefore not patched, replaced, or shimmed.

The separately authorized DevKit Windows resource-only compatibility task
removed that unnecessary zero-connection transport coupling without changing
`capy.script/dev-v0`. The resumed developer qualification passes 78 tests on
macOS, Ubuntu, and Windows against the new exact release, while the historical
DevKit remains embedded and resolvable by its old lock.

Fresh MCP and JSON-CLI journeys both reached `VERIFIED`, independently produced
tree `85bf72f6aa58f719261d8230445bcb3f63eae5af` and the same 4,003-byte archive,
and ended with clean completed sessions. A hidden resource oracle passed its
valid, invalid, and empty cases against the preserved Journey A archive.

The final source commit also passed a separate exact-wheel MCP smoke journey.
That agent-authored candidate reached all nine stages, though its application
did not satisfy the two negative hidden-oracle cases; this is recorded as
application-level journey friction and is not used as acceptance evidence.

Independent source review found three material verifier defects—large status
output, cleanup exception propagation, and same-commit branch drift. Commit
`034ee45c36616267596b97d1a91fbcab36e628fa` repairs all three. A focused fresh
review of that delta found no remaining P0-P3 issue.

## Zero-change controls

Protected repository checks retain these exact heads:

```text
DevKit main:   8c4fec7f814a62ded441786b8eba28af14d1aa2d
FedEx main:    de79fd1d0c08ab01f85b5d25a7a6d69a672c5b94
Proforma main: c21a308ec539898da8b6801ffc54845826bfd6cf
Runtime main:  61a71a1067183343504305337128ca0af083542f
```

Capy Developer `main` advances only after the resumed evidence and closure-head
CI are accepted.
