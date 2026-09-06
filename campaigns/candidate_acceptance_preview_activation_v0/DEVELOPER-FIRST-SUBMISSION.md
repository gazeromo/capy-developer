# Developer transfer first submission

Implements the additive submission protocol and explicit macOS local confirmation,
fixed paired-origin HTTPS streaming, exact grant and local handoff/candidate checks,
no-follow descriptor-based CAS access, separate durable transfer history and retry.
Existing native handlers retain their original handoff-open entrypoint; it selects
one strict URI grammar before constructing DeveloperCore. No setup migration or
handler replacement is required for an upgrade within the same Python installation.
New installations report Developer 0.6.0; historical receipts remain untouched.

Synthetic focused qualification: 16 new transfer controls, 32 existing desktop
checks, 5 existing V0 protocol checks and 1 frozen baseline check pass. Controls
cover changed binding, revocation, cancelled confirmation, stale selection, corrupt
and symlink CAS, lost acknowledgment/restart, malformed custody, old-server refusal,
closed URI parsing before initialization and old-handler submission dispatch.
No owner application, profile, source, credentials or machine-local paths are
included in this public evidence. No live setup, pairing, upload or installation
was performed by this submission. Full package and cross-service/native journeys
remain the coordinated task's qualification responsibilities.

One test setup repair resolved temporary roots before strict no-symlink traversal,
because the operating system's temporary-directory alias is a symlink. Product
path checks were preserved and descriptor traversal was strengthened.
