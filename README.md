# Capy Developer

Capy Developer prepares an exact Capy application project for any coding
harness that can call an ordinary JSON CLI or MCP stdio server. It owns local
project identity, pinned DevKit resolution, managed native-Git mirrors and
isolated worktrees, and durable development-session state.

Install from this repository with Python 3.11 or newer:

```text
python3 -m pip install .
capy-dev doctor --json
```

Core automation commands:

```text
capy-dev projects import --path /explicit/admin/checkout --json
capy-dev projects search --query shipping.fedex_quote --json
capy-dev development start --input request.json --json
capy-dev development inspect --session-id ses_... --json
capy-dev development finish --session-id ses_... --disposition COMPLETED --json
capy-dev mcp
```

The process working directory is never a project-selection input. Existing and
new project intent are explicit. Capy runtime source, application execution,
release acceptance, production deployment, and coding-agent launch are outside
this repository.

See [docs/DIRECTION.md](docs/DIRECTION.md) and
[campaigns/developer_foundation_v0/PLAN.md](campaigns/developer_foundation_v0/PLAN.md).

