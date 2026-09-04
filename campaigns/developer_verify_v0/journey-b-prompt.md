Repair the deterministic defect in the existing test-owned Capy application
prepared as development session
`ses_4c91ed4ed1254c7987c1ab421da32a8f` at workspace
`/private/tmp/capy-verify-journey-b-20260904/worktrees/prj_ad04dda43471485f9cc11589299de715/ses_4c91ed4ed1254c7987c1ab421da32a8f`.

Use only the configured `capy-dev` JSON CLI interface and the prepared
workspace. Begin by verifying its exact current commit so the defect is
diagnosed authoritatively. Repair the failure, commit a new exact candidate,
verify it with a new idempotency key, and finish the session when it passes.
Do not inspect unrelated repositories.
