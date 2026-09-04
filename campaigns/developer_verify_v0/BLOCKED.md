# Capy Developer Verify V0 historical blocker

Status: **resolved**.

The earlier candidate stopped because the then-accepted DevKit used
`socket.AF_UNIX` even for a resource-only application on Windows. The
separately authorized `CAPY-DEVKIT-WINDOWS-RESOURCE-ONLY-COMPATIBILITY-V0`
release removed that zero-connection coupling without changing
`capy.script/dev-v0` or making a Windows connection-bearing claim.

The final Developer source commit
`034ee45c36616267596b97d1a91fbcab36e628fa`, tree
`f813cbf3a96e0fb4b9f393a638fcbe125b0699ae`, passes 78 tests on Ubuntu,
macOS, and Windows in GitHub Actions run `33892609472`. Journey A and Journey B
both passed all nine stages against the accepted DevKit release and produced
the same candidate tree and archive digest.

This file remains as the historical stop/resumption record. There is no
remaining acceptance blocker.
