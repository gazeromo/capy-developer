# Repair the configured Developer package

The installed package version alone does not establish its toolset. Compare the
configured interpreter's actual MCP tool list and `capy_developer_status` source
and toolset digests with the exact reviewed wheel.

Run the `capy_developer.installation_repair` module from the reviewed Developer
source or wheel, supplying `--config` with the exact owned Codex configuration,
`--wheel` with the reviewed 0.7.0 wheel and `--sha256` with its exact SHA-256. The
default is a read-only plan. It validates the historical ownership receipt,
recorded roots and catalog, interpreter, bounded installed RECORD, and incoming
wheel identity. Conflicting global CLI installations are not selected or changed.

After the package is qualified and repair is authorized, repeat with `--apply`
and `--backup` naming a new directory under an existing owned parent, outside
the environment and Developer state. The repair retains the exact configured
interpreter. It snapshots only the Developer package, distribution metadata and
console entrypoint, verifies snapshot digests, force-installs the exact local
wheel with no index or dependencies, and compares installed bytes to the wheel.
An installation or verification failure automatically restores the package.

For explicit rollback, run the same reviewed helper with the same configuration,
wheel and digest, replacing `--apply` with `--rollback` and naming the same backup.
The rollback refuses changed snapshot bytes or changed owned configuration.
Retain the reviewed helper and wheel outside the repaired environment until
qualification finishes.

Neither repair nor rollback changes project/session catalogs, worktrees, pairing
state, credential stores, MCP configuration, or setup receipts. Normal authority
and state checks still apply when the tools subsequently run. Reconnect the
configured MCP process after repair, then verify the tools actually exposed to
the model and their status digest. An already running process retains its loaded
code until restarted.

The read-only plan also probes `pip` and `ensurepip` in the exact owned
interpreter. Missing `pip` returns `REPAIR_PREREQUISITE_REQUIRED` with the exact
bundled `ensurepip` action; apply refuses before creating a package snapshot or
running pip. Enabling this standard-library prerequisite is a separate explicit
step in the same private interpreter. The repair never installs prerequisites
silently or falls back to the global CLI.
