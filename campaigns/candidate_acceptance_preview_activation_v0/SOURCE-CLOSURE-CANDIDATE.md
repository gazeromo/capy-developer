# Developer source closure candidate

Status: qualified source; final coordinated review and checked merge pending.

- Repository: gazeromo/capy-developer (public).
- Base: `632d2910848ef2f8588cd514504288680a32044d`.
- Implementation: `ce498c6eeff2b8e161d4e544022a3f91e07abd9f`.
- Branch: `astra/candidate-acceptance-preview-activation-v0`.
- Package: Developer0.6.0, SHA-256 `fe92b614136905b3dbd53a3473e3d604536eb744367c98a407607fdc4e9b09f4`, 175887 bytes.

The additive transfer protocol sends only the explicitly selected immutable local
candidate after confirmation. It preserves existing verification, pairing and
handoff records and adds separate transfer history. The original seam document
is retained as a design freeze; accepted implementation and tests govern final
behavior where qualification produced a bounded repair.

Two clean-source builds match byte for byte; all31 package source payloads match.
The offline installed subset passes53 tests outside sibling source imports.
CI34023100344 passes all three Python3.11 jobs (166 collected per job): macOS
zero skips, Linux2 skips, Windows19 skips. Skipped native checks are not passes.
See PACKAGE-RELEASE.json, CI.json and LOCAL-UPGRADE-RECEIPT.json; each records
its observation time/scope, so the earlier pre-install status is historical.

The owner-approved exact local package upgrade is complete; existing handler,
configuration and data fingerprints were preserved. Actual native Chrome/macOS
transfer was qualified separately in the private runtime campaign. Supplemental
control transfers used the installed API with recorded explicit consent and do
not establish additional native gestures. No owner source, conversations,
credentials or private evidence is included in this public closure.

Independent trust review is retained in the private runtime campaign at
70092f0 and subsequent bounded reviews. Source closure does not deploy the new
runtime or publish packages to a registry. Live service remains its prior exact
implementation. Final coordinated handoff records source merge refs separately.
