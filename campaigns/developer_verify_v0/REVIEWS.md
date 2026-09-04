# Capy Developer Verify V0 independent reviews

## Full candidate review

A fresh read-only review of the implementation found three actionable defects:

1. Large `git status` output could exceed the bounded capture limit instead of
   remaining a boolean cleanliness probe.
2. Recovery cleanup exceptions could escape `inspect` or `finish` instead of
   being durably recorded.
3. Moving the session branch to another branch name at the same commit did not
   make a passed verification stale.

All three were repaired in
`034ee45c36616267596b97d1a91fbcab36e628fa` with targeted regression tests.

## Final fix-delta review

Scope: `a9d0d141da967a269870bd3444164f6148303295..034ee45c36616267596b97d1a91fbcab36e628fa`

Result: **no actionable P0-P3 findings; no P0-P2 finding remains**.

The reviewer explicitly confirmed the bounded boolean status probe, contained
and recorded cleanup failures, same-commit branch-drift staleness, and the
platform-correct temporary-path test. Its read-only sandbox had no writable
temporary directory, so execution there was unavailable; the exact commit was
separately covered by the 78-test local run and Windows/macOS/Ubuntu CI.

## Evidence-head release review

Scope: exact evidence commit `c1dee28a7241d789a830ee5b274858b0a29cde7f`.

The reviewer confirmed the wheel digest and Journey A/B receipts were internally
consistent, but returned `NOT ACCEPT` with two P1 findings because the evidence
commit was newer than the implementation source commit and its own CI result
had not yet been recorded. GitHub Actions run `33895734089` subsequently passed
all 78 tests on Ubuntu, macOS, and Windows at that exact evidence commit.

The receipt model now names both immutable roles explicitly: `034ee45...` is
the implementation source that produced the wheel and primary qualification;
`c1dee28...` is the evidence commit that adds only qualification artifacts and
the promoted wheel. The closure commit adds only this reconciliation record.
