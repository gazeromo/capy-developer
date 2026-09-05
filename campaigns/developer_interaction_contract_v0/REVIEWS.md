# Capy Developer interaction contract V0 independent reviews

## Review C — verification and persistence

Review C accepted exact implementation commit
`7060bc9b96092645cd273364ab9ad5eaebe69753`, tree
`7d532cd1a40d6d8a65c64090b1c3a43a1fbecb9e`, with zero P0-P3 findings.
The final delta preserves pipeline versioning, schema-3 migration, V0/V1
coexistence, durable interaction evidence, interruption/replay behavior, and
no mutable-worktree trust after verification.

## Review D — candidate V1 format and copied-byte oracle

Review D rejected earlier immutable candidates after finding causal-path,
symlink-alias, concurrent-publication, descriptor-profile, receipt-bound,
scalar-type, and production/oracle parity defects. Each finding received a
bounded repair and regression coverage.

Review D then accepted exact implementation commit
`7060bc9b96092645cd273364ab9ad5eaebe69753`, tree
`7d532cd1a40d6d8a65c64090b1c3a43a1fbecb9e`, with zero P0-P3 findings. It
confirmed 57/57 dual-validator tamper rejection, exact positive size and human
contract boundaries, all previously reported coherent mutants, V0 migration,
symlink rejection, content-store races, and separate-session concurrency. Its
independent full suite passed 109/109.

## Supplemental Review C/D — Windows containment repair

Evidence-head CI exposed an intermittent Windows extended-path comparison
failure. The bounded repair at commit
`5b4c40f062f73dcbf1b8d58ae0eb0cdcf63476bc`, tree
`ed492e239c960b50ca2beb02dafe870071030c26`, normalizes Windows extended drive
and UNC prefixes only for containment comparison after resolving both paths.

Independent supplemental Review C/D accepted that exact repair with zero
P0-P3 findings. It verified fail-closed behavior for POSIX descendants,
sibling prefixes, traversal and symlinks, and for Windows normal/extended
drive and UNC paths, case variants, different drives, different shares, and
different servers. Seven targeted verification and release tests passed.

The follow-up commit `13a4594361fac626cdb30fdcba1e7d8b6f4c8171`
changes only the regression test expectation to accept Windows' correct
case-normalized comparison text; packaged source and wheel bytes are unchanged.

## Review E — closure delta

Pending. Review E begins only after cross-platform implementation/evidence CI
passes and the evidence and closure commits are immutable.
