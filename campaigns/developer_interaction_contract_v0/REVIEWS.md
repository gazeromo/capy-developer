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

## Review E — closure delta

Pending. Review E begins only after cross-platform implementation/evidence CI
passes and the evidence and closure commits are immutable.
