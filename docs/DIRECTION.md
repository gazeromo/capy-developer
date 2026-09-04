# Direction

Capy Developer removes repository preparation from a developer's responsibility
without replacing it with guesses. A generic harness asks for one exact known
project or explicitly asks to create one. Capy Developer returns a durable
session bound to one project, one exact Git base, one generated branch, one
isolated worktree, and one truthful DevKit lock state.

V0 is local and harness-neutral. Its interfaces are a versioned JSON CLI and
four MCP stdio tools backed by the same core. Native Git remains source
authority; SQLite is only a durable catalog and session journal.

Application verification, runtime preview, release acceptance, production
publication, remote MCP, repository-provider provisioning, coding-agent
supervision, and extraction of runtime builder residue are later decisions.

