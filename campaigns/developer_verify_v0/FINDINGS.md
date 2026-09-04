# Capy Developer Verify V0 findings

## Implemented capability

The branch implements the shared exact-commit verification core, SQLite schema
1→2 migration, fixed nine-stage pipeline, exact accepted-DevKit binding,
content-addressed archives, durable replay, stale-state inspection, JSON CLI
`verify`, and MCP `capy_development_verify`.

Local qualification passes 71 tests. Two clean coding-harness journeys proved
causal fail/repair/retry behavior through MCP and JSON CLI. Both produced the
same candidate tree and same-host archive digest
`4710bed6cf346e1f38cec837ada60ad2ec7555ab9364a80c72b52d9480a2acf7`.

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

Review requests for hostile-code filesystem/network sandboxes and comprehensive
memory/process/disk quotas were not adopted. The owner plan explicitly states
that application code is developer-authorized code under the developer's OS
identity, and lists network isolation and malicious third-party safety as
non-claims. No such safety claim is made here.

## Terminal blocker

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

Because the Windows resource-only gate cannot pass, this branch is not accepted,
no 0.2.0 release wheel is promoted, and `main` is not advanced.

## Zero-change controls

Final remote checks retained these exact protected heads:

```text
DevKit main:   0cf018faa02ade73ab0805aa0617c55ce36fa7b1
FedEx main:    de79fd1d0c08ab01f85b5d25a7a6d69a672c5b94
Proforma main: c21a308ec539898da8b6801ffc54845826bfd6cf
Runtime main:  61a71a1067183343504305337128ca0af083542f
```

Capy Developer `main` remains at the accepted Foundation V0 head
`124bf634ec023f064ebd7f051d049de65ff3228f`.
