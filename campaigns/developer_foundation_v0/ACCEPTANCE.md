# Capy Developer Foundation V0 acceptance

Status: **accepted**.

The local acceptance receipt is `acceptance-local.json`. It covers exact FedEx
and Proforma source identities, unrelated-directory CLI and MCP operation,
existing-project preparation, exact Git base selection, separate managed
worktrees, new-project initialization from the accepted DevKit bundle,
idempotent retries, restart inspection, terminalization, preserved worktrees,
and zero imported-source change.

The accepted implementation commit is
`6f0bf7b027b8c6036d8eee8fbeb733356755a917`, with tree
`df3997096c5dceaba4da7fd9aaa4fd30c3d9f835`. Its 32-test suite passed on
macOS, Ubuntu, and Windows in run `33868308194`. Two independent reviewers
accepted the exact commit with no P0-P2 findings.

The installable wheel was built twice from the accepted commit with the commit
timestamp as `SOURCE_DATE_EPOCH`; both builds were byte-identical. The wheel
digest is `a57e2aa238297b143d56758d58d226c265cc79f264dfbf4e51e18d5ca1610301`.
It installed without an index into a fresh environment and its `doctor` command
verified the embedded accepted DevKit bundle.

The final machine-readable receipt binds all evidence and non-claims. No
deployment, production mutation, release acceptance, harness installation, or
runtime change is part of this acceptance.
