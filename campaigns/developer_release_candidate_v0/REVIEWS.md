# Capy Developer Release Candidate V0 independent reviews

## Review A — identity, format, and trust boundary

The first exact-candidate review returned **NOT ACCEPT** for
`b0f781187ffe3b6ce3482434281e6c4c3b40488f`. It found unbounded nested
DevKit-wheel expansion and insufficient passed-stage exit/fact validation.
The first repair added member/expanded-byte/wheel bounds, exact exit-code and
fact types, and adversarial coverage.

A second pass found that well-typed contradictory facts could still describe a
passed stage. The final repair requires exact fact sets, rejects timeouts and
source mutation on passed stages, and binds reproducible package and preserved
archive facts to the verified application archive in the producer, production
validator, and independent oracle.

Final verdict for implementation commit
`a98b6d54eb5f73b58dffc2b4249f419cd7823113`, tree
`f6e275033bd1606f6aef5599188eb8928dfdac31`: **ACCEPT; no actionable P0-P3
findings**. The isolated release-candidate suite passed 18/18.

## Review B — persistence, interruption, cleanup, and adapters

The first exact-candidate review returned **NOT ACCEPT** for
`b0f781187ffe3b6ce3482434281e6c4c3b40488f`. It found a session-cancellation
race, an unmarked-attempt-directory crash wedge, and a clobber race in
content-addressed publication.

The repair serializes candidate creation with the session lifecycle lock,
rechecks eligibility in the allocation transaction, publishes a fully marked
staging directory atomically, recovers only the legacy empty unmarked root,
and uses no-clobber same-filesystem linking with winner validation.

Final verdict for implementation commit
`a98b6d54eb5f73b58dffc2b4249f419cd7823113`, tree
`f6e275033bd1606f6aef5599188eb8928dfdac31`: **ACCEPT; no actionable P0-P3
findings**. The reviewer confirmed the later receipt-only delta preserved all
recovery and concurrency fixes.
