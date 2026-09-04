# CAPY-DEVELOPER-FOUNDATION-V0

## Cross-harness project identity, DevKit resolution, managed Git workspaces, and `development_start`

**Status:** first bounded implementation task for Codex  
**Effective date:** 2026-09-04  
**Primary product:** Capy Developer  
**Primary user:** a developer using any coding harness that can call MCP tools or ordinary CLI commands  
**New implementation repository:** `gazeromo/capy-developer`  
**Expected local checkout:** `/Users/gazeromo/dev/capy-developer`  
**Implementation branch:** `codex/developer-foundation-v0`  
**Control repository:** `gazeromo/capy-project`  
**Current control main when this plan was written:** `b9451fb382f252430ed89f533dffa8c122482f47`  
**Current runtime main when this plan was written:** `61a71a1067183343504305337128ca0af083542f`  
**Current deployed runtime implementation when this plan was written:** `567044af3b519d5eb4c0871cad21e86fb568b321`  
**Current DevKit main when this plan was written:** `0cf018faa02ade73ab0805aa0617c55ce36fa7b1`  
**Runtime changes authorized by this task:** none  
**Production deployment authorized by this task:** none  
**Application behavior changes authorized by this task:** none  

---

## 1. Executive task

Build the first small, installable **Capy Developer** foundation so that a coding harness can begin Capy application work without the developer first opening, locating, cloning, or initializing a repository.

The exact owner-visible target is:

```text
developer opens any configured coding harness from any directory
→ says that they want to create or change a Capy application
→ harness calls Capy Developer
→ Capy Developer resolves an existing project or initializes a new one
→ Capy Developer chooses the exact source base
→ Capy Developer creates an isolated native-Git development workspace
→ Capy Developer resolves and reports the exact project DevKit/toolchain
→ harness receives one prepared development world
```

The first task proves only this horizontal foundation:

```text
project memory
+ project identity independent of local paths
+ existing-project import
+ new-project initialization
+ managed Git mirrors/worktrees
+ exact DevKit lock resolution
+ durable development sessions
+ MCP stdio tools
+ JSON CLI parity
```

It does **not** yet build the complete developer product.

Do not add in this task:

```text
coding-agent launch or supervision
Codex-specific behavior
full application verification
runtime preview
release acceptance
production publication or activation
builder extraction from capy-outcome-runtime
remote MCP over HTTP
a graphical developer UI
harness marketplace installers
GitHub/Gitea-specific repository provisioning
```

The task passes when the same core behavior can be used through MCP or CLI from an unrelated working directory and returns a truthful, restart-safe prepared project workspace.

---

## 2. Why this is the first implementation slice

The new direction begins with:

```text
any coding harness
→ Capy tools
→ correct project and working environment
→ ordinary software development
```

The first uncertainty is not how to ask Codex to write code. Coding harnesses already know how to work in ordinary repositories.

The missing product boundary is:

```text
Which Capy project is this?
Where is its authoritative source?
Which exact commit should this work begin from?
Does a local checkout already exist?
Where should a new isolated work session live?
Which DevKit version belongs to this project?
How is a new project initialized without developer ceremony?
How can all harnesses invoke the same behavior?
```

Do not begin with full builder orchestration, release publication, or harness-specific launchers. Those depend on a correct project and development-session world.

This slice creates that world first.

---

## 3. Current source truth and allowed archaeology

Before writing code, inspect current machine and repository truth. The exact commits above are starting references, not permission to ignore later current state.

### 3.1 Required current sources

Inspect at least:

```text
gazeromo/capy-project
  CURRENT.md
  work/NOW.md

gazeromo/capy-script-devkit
  README.md
  SUPPORTED-V0.md
  CONTRACT.md
  AGENTS.md
  docs/PRODUCTIZATION.md
  MINIMAL-DEVKIT-PRODUCTIZATION-V0-RELEASE.json

gazeromo/capy-fedex-quote-cleanroom
  DEVKIT.lock
  AGENTS.md
  capability/application layout
  current origin/default branch/current main

gazeromo/capy-proforma-invoice
  capability.toml
  current origin/default branch/current main

gazeromo/capy-git
  README.md
  DIRECTION.md
  native Git and authority boundaries

gazeromo/capy-outcome-runtime
  only enough read-only inspection to understand existing builder residue
  and accepted application source identities
```

### 3.2 Important accepted DevKit identity

The current accepted Minimal DevKit V0 product release records:

```text
source repository:
  gazeromo/capy-script-devkit

current release-binding main:
  0cf018faa02ade73ab0805aa0617c55ce36fa7b1

implementation commit:
  55fc109b5f494086c03560794e7be74d75f1d93f

contract:
  capy.script/dev-v0

wheel:
  capy_script_devkit-0.0.0-py3-none-any.whl

wheel sha256:
  165faba51b56b667b087228e1c556b1e2369d0e61bb469785ddff1bad9d6e2d0

authoring bundle sha256:
  cb7e4073a99bf8596509af02f466f90b5792d1d8075dffab0f27bbb2df0679e8
```

Do not silently substitute DevKit `main`, an editable checkout, or a newly built unverified wheel for this exact accepted identity.

### 3.3 Known existing application fixtures

Use at least these current repositories as real import fixtures:

```text
gazeromo/capy-fedex-quote-cleanroom
  current main at plan time:
    de79fd1d0c08ab01f85b5d25a7a6d69a672c5b94
  application:
    shipping.fedex_quote
  contains:
    DEVKIT.lock

gazeromo/capy-proforma-invoice
  current main at plan time:
    c21a308ec539898da8b6801ffc54845826bfd6cf
  application:
    documents.proforma_invoice
```

Inspect later current heads before acting.

Do not mutate these application repositories merely to make the new developer tool easier to implement.

---

## 4. Repository and product decision

Create one new private implementation repository:

```text
gazeromo/capy-developer
```

This repository owns the developer-facing project and development-session layer.

The earlier working name `capy-software-builder` is superseded by the broader product boundary **Capy Developer**. Do not create both repositories in this task.

Future deliberate coding-agent supervision and extracted builder behavior may live in `capy-developer`, but they are outside this first slice.

### 4.1 `capy-developer` owns in V0

```text
canonical project catalog
local checkout catalog
exact project aliases and application bindings
DevKit/toolchain lock resolution
content-addressed local toolchain cache
native Git mirrors and isolated worktrees
durable development-session allocation
idempotent start/inspect/finish behavior
MCP stdio adapter
JSON CLI adapter
versioned tool input/output schemas
causal diagnostics
```

### 4.2 It does not own

```text
production Capy runtime state
people/team/workspace authority
application execution
application business state
provider secrets
source-host administration
public repository hosting
coding-agent internals
application acceptance
production release activation
```

### 4.3 Runtime boundary

`capy-outcome-runtime` must remain unchanged in this task.

Do not:

```text
import runtime packages into capy-developer
move builder modules during this task
connect ordinary user chat to Capy Developer
add a Build software action
read or write production runtime databases
install any candidate into production
```

The existing physical builder residue remains a separately acknowledged architectural debt until a later explicit extraction task.

---

## 5. Developer experience contract proved by V0

### 5.1 Existing project

From an arbitrary directory, a tool client calls Capy Developer with an exact existing selector:

```text
application_id = shipping.fedex_quote
request = Add support for a new truthful quote-result field.
```

Capy Developer must:

```text
resolve the one canonical project
resolve the canonical native Git repository
synchronize or truthfully fail
select the exact current base commit
create a unique isolated development branch/worktree
resolve the exact declared DevKit lock
write no application source changes
return the prepared workspace and current facts
```

The developer does not choose a path, branch, checkout, or DevKit version.

### 5.2 New project

From an arbitrary directory, a tool client explicitly requests a new project:

```text
project name = CSV Summary Probe
application_id = demo.csv_summary_probe
request = Create a small Capy application that summarizes a CSV.
```

Capy Developer must:

```text
allocate a stable project identity
initialize one canonical native Git repository
materialize the accepted DevKit template
create project metadata and toolchain lock
make one initial main commit
create an isolated development branch/worktree
return the prepared workspace
```

The developer does not run `mkdir`, `git init`, clone a template, choose a remote, or install the DevKit.

### 5.3 Restart

After the Capy Developer process exits and restarts, the same session can be inspected from durable state without recreating the repository or worktree.

### 5.4 Harness neutrality

The exact same core result must be available through:

```text
MCP stdio tools
JSON CLI commands
```

No Codex-specific prompt, process, path, or API is allowed in the core.

---

## 6. Core design decisions

These decisions are part of this task. Exact internal filenames and implementation language are not.

### 6.1 One installable local tool

Expose one command:

```text
capy-dev
```

Required initial modes:

```text
capy-dev doctor
capy-dev projects import ...
capy-dev projects search ... --json
capy-dev development start ... --json
capy-dev development inspect ... --json
capy-dev development finish ... --json
capy-dev mcp
```

Codex may choose the implementation language and packaging mechanism that gives the smallest trustworthy result.

Requirements regardless of language:

```text
one ordinary installable artifact
no shell-only critical path
no required Python/Node package installation inside application projects
no dependency on current working directory
no Capy runtime import
structured stderr diagnostics
machine-readable stdout for --json and MCP
```

A Python wheel, self-contained Python tool, Rust binary, or Go binary is acceptable if it satisfies the behavior and qualification. Do not spend the task on native GUI installers.

### 6.2 One core, two adapters

Implement lifecycle behavior once.

```text
Capy Developer core
      ├── JSON CLI adapter
      └── MCP stdio adapter
```

The adapters may not independently implement project resolution or Git behavior.

### 6.3 Native Git remains native

Use ordinary Git commands and repositories.

Do not create:

```text
Capy source-control semantics
custom commit objects
custom branch protocols
repository state copied into SQLite as source authority
```

Invoke Git without shell-string interpolation.

### 6.4 Project identity is not a path

A project has a stable opaque `project_id`.

A local checkout path is one machine-specific observation.

The same project may have:

```text
one canonical remote
one managed local mirror
several isolated worktrees
other developer-owned checkouts
```

Changing a local path must not create a new project identity.

### 6.5 Deterministic selection only

V0 uses no model call.

Resolution order:

```text
exact project_id
exact application_id
exact normalized repository identity
exact alias/name
otherwise return ambiguous or not_found
```

Do not perform semantic or fuzzy auto-selection that can mutate the wrong repository.

### 6.6 Explicit existing-versus-new intent

`development_start` uses a tagged union:

```text
existing project selector
or
new project specification
```

The tool must not decide to create a repository merely because a text query found no exact match.

The coding harness or human must explicitly request the new-project branch.

### 6.7 No automatic destructive cleanup

V0 terminalizes sessions but does not automatically delete a worktree containing possible developer work.

Cleanup of test-owned roots is required during qualification, but product behavior must fail safe rather than delete an uncertain workspace.

---

## 7. Durable data model

Use one small local SQLite database under an OS-appropriate Capy Developer data root.

The exact schema may evolve during implementation, but it must preserve these truths.

### 7.1 Projects

```text
project_id
human name
normalized canonical repository identity
canonical repository URL/path
default branch
project status
created_at
updated_at
```

Unique constraints must prevent duplicate registration of the same normalized canonical repository.

### 7.2 Project aliases and applications

```text
project_id
alias
application_id
source of the observation
```

At minimum, the importer should be able to discover explicit application identity from the existing Capy capability descriptor where present.

Do not infer application identity from repository name when an explicit descriptor exists.

### 7.3 Local checkouts

```text
checkout_id
project_id
machine identity
native path
path URI
checkout kind
observed commit
observed branch
dirty-state observation
last_seen_at
```

The catalog is an index, not source authority. Current Git inspection outranks a stale checkout row.

### 7.4 Toolchain locks

```text
project_id
contract schema
DevKit source repository
DevKit source commit
wheel filename and digest where declared
authoring-bundle digest where declared
lock source path/status
availability in local cache
```

Do not silently upgrade a legacy project to the current DevKit.

### 7.5 Development sessions

```text
session_id
project_id
idempotency_key
request digest
exact base commit
development branch
managed worktree path/URI
allocated_at
status
terminal disposition
terminal_at
```

Required statuses should remain small, for example:

```text
PREPARING
READY
FAILED
COMPLETED
CANCELLED
```

Once a session ID is durably allocated, every path must reach a durable truthful state.

### 7.6 Session events or receipts

Preserve enough append-only evidence to explain:

```text
project resolved
repository synchronized
base selected
worktree created
toolchain resolved
session became ready
session failed or finished
```

Do not store private model reasoning because no model belongs in this path.

---

## 8. Project metadata for new repositories

New projects created by Capy Developer must contain two small Capy Developer metadata files in addition to the accepted DevKit template.

### 8.1 `capy.project.toml`

Provisional schema:

```toml
schema = "capy.project/v0"
project_id = "prj_..."
name = "CSV Summary Probe"

[repository]
default_branch = "main"

[applications]
ids = ["demo.csv_summary_probe"]
```

Do not store a machine-local path in this file.

### 8.2 `capy.lock`

Provisional schema:

```toml
schema = "capy.toolchain-lock/v0"
contract = "capy.script/dev-v0"
devkit_repository = "gazeromo/capy-script-devkit"
devkit_commit = "0cf018faa02ade73ab0805aa0617c55ce36fa7b1"
wheel = "capy_script_devkit-0.0.0-py3-none-any.whl"
wheel_sha256 = "165faba51b56b667b087228e1c556b1e2369d0e61bb469785ddff1bad9d6e2d0"
authoring_bundle_sha256 = "cb7e4073a99bf8596509af02f466f90b5792d1d8075dffab0f27bbb2df0679e8"
```

The exact accepted values must be read from current trusted release metadata during implementation rather than duplicated blindly if current truth has changed.

### 8.3 `CAPY.md`

Create one concise canonical project-development page.

It should state only:

```text
this is a Capy application project
project and application identity
the declared DevKit/toolchain lock
where the application contract is
ordinary project-native test commands where known
that Capy runtime source and production data are outside the project
that release and production activation are not part of this V0 task
```

Do not copy Capy’s historical architecture sources into every application repository.

### 8.4 Accepted DevKit template

Materialize the application template from the exact accepted authoring bundle.

Do not hand-recreate a competing template in `capy-developer`.

---

## 9. DevKit/toolchain cache

### 9.1 Cache identity

Cache immutable DevKit material by content digest, not by mutable branch name.

Conceptually:

```text
<capy-developer-cache>/toolchains/sha256/<digest>/...
```

### 9.2 Bootstrap

At implementation/qualification time:

```text
inspect the current machine for the accepted authoring bundle
if present, verify exact digest before use
if absent, reproduce it from the exact accepted DevKit source and documented build process
verify wheel, package tree, and bundle digests
place only verified bytes into the content-addressed cache
```

Do not modify `capy-script-devkit` merely to make this work.

### 9.3 Legacy locks

Support reading the existing legacy `DEVKIT.lock` format used by the FedEx application.

For an imported project:

```text
preserve its declared exact lock
report AVAILABLE only when exact matching bytes are verified in cache
report MISSING or UNBOUND truthfully otherwise
never substitute the latest DevKit automatically
```

A missing legacy toolchain must not prevent safe project/worktree preparation, but the returned result must make the missing toolchain explicit.

### 9.4 New projects

New projects use the current accepted DevKit release identity and must begin with toolchain status `AVAILABLE` in the V0 acceptance environment.

---

## 10. Git and workspace behavior

### 10.1 Managed roots

Use OS-appropriate configurable roots for:

```text
state/database
Git mirrors or canonical local repositories
managed development worktrees
content-addressed toolchain cache
logs/evidence
```

Tests must override every root. No test may write to the owner’s real production or home state unintentionally.

### 10.2 Existing projects

For an imported remote repository:

```text
maintain or create one managed bare mirror/cache
fetch current refs from the canonical remote
resolve the exact default-branch commit
create one isolated branch/worktree for the session
never use or modify the developer’s unrelated current checkout as the work area
```

If the remote cannot be synchronized, fail truthfully by default. Do not silently claim the stale local checkout is current.

A later explicit offline mode may permit a stale base; it is not part of V0.

### 10.3 New projects

V0 may use a managed local bare repository as the canonical native-Git repository for a newly initialized project.

This proves repository initialization without introducing GitHub-, Gitea-, or provider-specific provisioning.

Required sequence:

```text
allocate project
create canonical bare Git repository
materialize exact template and project metadata in a temporary seed checkout
create initial main commit
push main into the canonical bare repository
create isolated development branch/worktree
record exact identities
```

Remote repository-provider adapters are later work.

### 10.4 Branches

Use generated safe branch names derived from the session ID, not raw user text.

Example only:

```text
capy/dev/<session-id>
```

### 10.5 Worktree safety

Before reporting `READY`, verify:

```text
worktree exists
worktree belongs to the intended project/session
HEAD equals recorded base commit before development begins
branch is exact
repository metadata is valid
no path escapes the managed root
```

### 10.6 Idempotency

Repeating `development_start` with the same idempotency key and equivalent normalized input must return the same session and workspace.

A retry may not create:

```text
a second project
a second canonical repository
a second branch
a second worktree
```

Using the same idempotency key with materially different input must fail causally.

---

## 11. Tool contracts

All inputs and outputs must use versioned JSON-compatible schemas shared by CLI and MCP.

Exact field names may be repaired during implementation, but the semantics below are required.

### 11.1 `capy_projects_search`

Input:

```json
{
  "query": "shipping.fedex_quote",
  "limit": 10
}
```

Output includes only current bounded facts:

```text
project_id
name
application IDs
canonical repository identity/default branch
access/import status
known local checkout availability
exact-match reason
```

Search is read-only.

### 11.2 `capy_development_start`

Input is one of:

```json
{
  "idempotency_key": "...",
  "request": "Add a truthful result field.",
  "existing": {
    "application_id": "shipping.fedex_quote"
  }
}
```

or:

```json
{
  "idempotency_key": "...",
  "request": "Create a small CSV summary application.",
  "new": {
    "name": "CSV Summary Probe",
    "application_id": "demo.csv_summary_probe"
  }
}
```

A successful output must include:

```text
schema and status
session_id
project identity
canonical repository identity
exact base commit
development branch
workspace path URI and native path
toolchain lock and availability
canonical instruction file
truthful next actions
```

Do not expose:

```text
raw credentials
private-key paths
production paths
unrelated local checkouts
other projects’ private metadata
```

### 11.3 `capy_development_inspect`

Returns durable current state for one session after revalidating current filesystem/Git facts.

If the worktree was externally removed or changed, report the discrepancy. Do not recreate it silently during inspection.

### 11.4 `capy_development_finish`

Terminalizes a session with one explicit disposition:

```text
COMPLETED
CANCELLED
```

It records the current commit/dirty observation but does not claim verification, release, or publication.

It does not delete a possibly valuable worktree in V0.

### 11.5 CLI parity

The JSON CLI and MCP tools must call the same core functions and return equivalent versioned result values.

Human CLI rendering may be added, but `--json` is authoritative for automation.

### 11.6 MCP stdio

Required behavior:

```text
server launched as `capy-dev mcp`
protocol traffic only on stdout
logs only on stderr
tools/list exposes the four tools above
tools/call executes the shared core
process working directory has no semantic effect
restart preserves durable state
```

Do not require MCP prompts or resources for the essential path.

---

## 12. Cross-platform requirements

This product direction is cross-platform. V0 must not accidentally hard-code the current Mac.

### 12.1 Required implementation discipline

```text
use platform-native path APIs
return file URIs plus native display paths
never split paths on `/` manually
never use shell-string command composition
use argument arrays for Git/process execution
avoid mandatory executable-bit semantics for project correctness
avoid Bash-only scripts in the core journey
use OS-appropriate state/cache roots
use file and database locking appropriate to supported platforms
```

### 12.2 Qualification matrix

Run the source test suite in clean environments for:

```text
macOS
Linux
Windows
```

A hosted no-secret CI matrix is acceptable for this proof.

At minimum, each platform must prove with temporary local Git repositories:

```text
install/launch command
SQLite initialization
project import
new local bare repository initialization
managed worktree creation
idempotent restart/inspection
CLI JSON path
MCP tools/list and one tools/call
```

If Windows cannot be executed, do not claim cross-platform acceptance. Record a bounded blocker and close only as Mac/Linux-supported.

### 12.3 Explicit non-claim

V0 does not prove:

```text
native signed installers
all coding harnesses
remote/cloud harness execution
remote MCP authentication
provider-specific Git creation
```

---

## 13. Implementation sequence

Codex should work continuously through ordinary integration defects. Do not freeze a campaign around the first trivial bug.

### Stage 0 — activate and inventory

```text
inspect current control/runtime/DevKit/application/Git truth
confirm no successor task is already active
record deviations from the plan-time commits
create/update the control work record for this exact task
inventory existing accepted DevKit bundle bytes and application checkouts
```

Do not modify runtime or production.

### Stage 1 — create the clean repository

```text
create private gazeromo/capy-developer
create /Users/gazeromo/dev/capy-developer
create a minimal main baseline with README, AGENTS, direction, and tests
create branch codex/developer-foundation-v0
```

Preserve provenance to this plan and current source repositories. Do not copy historical campaign trees.

### Stage 2 — build the local core and state roots

Implement:

```text
configuration and OS roots
SQLite schema/migrations
stable IDs
versioned input/output models
causal error model
locking and restart behavior
```

### Stage 3 — implement project import and search

Implement bounded import from an explicit local Git checkout.

The importer should inspect:

```text
Git origin/default branch/current commit
capy.project.toml when present
capy.lock or legacy DEVKIT.lock
explicit capability descriptor/application ID where present
```

Import the current FedEx and Proforma repositories into an isolated acceptance catalog.

Do not recursively crawl the whole home directory in V0.

### Stage 4 — implement exact DevKit resolution/cache

```text
locate or reproduce exact accepted authoring bundle
verify all exact digests
cache by content identity
parse current and legacy locks
report AVAILABLE/MISSING/UNBOUND truthfully
```

### Stage 5 — implement existing-project development start

```text
resolve exact application/project
synchronize managed Git mirror
select exact base
allocate durable session
create branch/worktree
validate workspace
return READY result
```

### Stage 6 — implement new-project initialization

```text
allocate project and canonical local bare repository
materialize accepted template
write capy.project.toml, capy.lock, CAPY.md
create initial main commit
create session branch/worktree
return READY result
```

### Stage 7 — implement inspect and finish

Prove durable restart, discrepancy reporting, and terminalization.

### Stage 8 — implement JSON CLI

Expose the required commands and causal exit statuses.

### Stage 9 — implement MCP stdio adapter

Expose the same core as the four required tools.

No harness-specific implementation is allowed.

### Stage 10 — qualification and independent review

Run all automated, cross-platform, negative, restart, and parity controls. Then use fresh independent reviewers.

### Stage 11 — closure only

If accepted:

```text
merge capy-developer branch to main
record exact source/tree/package identities
record the control closure
leave runtime and production untouched
```

No deployment is part of this task.

---

## 14. Required automated tests and negative controls

### 14.1 Project identity

```text
same canonical repository imported twice → one project
SSH and HTTPS forms of the same recognized remote → no duplicate where normalization is supported
different repositories with the same basename → remain distinct
local checkout moved to another path → project identity unchanged
```

### 14.2 Import safety

```text
non-Git directory → causal rejection
Git repository without Capy application marker → explicit unsupported/import decision
malformed project manifest → causal rejection
malformed lock → project may be imported but lock status is invalid and explicit
symlink/path escape → rejected
```

### 14.3 Existing-project start

```text
exact application ID resolves one project
ambiguous name resolves none and mutates nothing
remote synchronization failure → no READY claim
exact base commit recorded
worktree HEAD equals base before development
original developer checkout remains byte/status unchanged
```

### 14.4 New-project start

```text
one explicit request creates one project/repository/main commit/worktree
same idempotency replay creates no duplicate
different payload with same key → conflict
unsafe name/application ID → rejected before allocation
template bytes originate from verified accepted bundle
project lock binds exact accepted toolchain
```

### 14.5 Sessions

```text
process dies after session allocation but before READY → recovery terminalizes or resumes truthfully
READY session survives restart
external worktree removal is reported
finish is idempotent
finished session is not reported as active
```

### 14.6 Concurrency

```text
two distinct sessions for one project receive separate branches/worktrees
same idempotency key racing concurrently yields one session
SQLite and filesystem state remain consistent
```

### 14.7 Toolchain

```text
exact digest match → AVAILABLE
digest mismatch → rejected and never used
missing legacy lock bytes → MISSING, never substituted
new project current accepted bundle → AVAILABLE
```

### 14.8 CLI/MCP parity

```text
same normalized request through CLI and MCP → equivalent semantic result
MCP stdout contains no logs
invalid MCP payload returns causal tool error
current working directory changes no result
```

### 14.9 Security and boundaries

```text
no production runtime/database access
no raw secret in database/logs/results
Git invocation cannot be argument-injected through project/request text
managed path cannot escape configured root
no automatic deletion of non-test developer work
no network/provider call except explicit Git synchronization and DevKit source retrieval
```

---

## 15. Acceptance journeys

Use temporary isolated state roots for all formal acceptance.

### Journey A — existing FedEx project from unrelated directory

```text
start CLI or MCP client in an unrelated empty directory
import or use the pre-imported FedEx project
call development_start by exact application ID
receive one READY session
verify exact project, base, branch, worktree, and DevKit lock
verify the original checkout is unchanged
repeat with the same idempotency key
verify no duplicate anything
```

### Journey B — second harness/transport equivalence

```text
use the other adapter from another unrelated directory
start another development session for the same FedEx project
receive a separate branch/worktree
verify the same project identity and toolchain truth
```

This is a protocol-level cross-harness proof. No Codex-specific client is required.

### Journey C — ambiguous existing request

```text
search with a deliberately ambiguous alias
receive bounded alternatives
create zero project/session/worktree mutation
```

### Journey D — new project initialization

```text
call development_start with explicit new-project input
create one local canonical bare repository
create one initial main commit from exact template
create one isolated session worktree
verify capy.project.toml, capy.lock, CAPY.md
verify current accepted DevKit is available
replay same idempotency key
verify no duplicate project/repository/worktree
```

### Journey E — restart and inspect

```text
stop Capy Developer process
start a new process
inspect prior READY sessions
verify no repository, worktree, or model replay
```

### Journey F — finish

```text
make one harmless test-owned source edit in the new-project worktree
finish the session as COMPLETED
verify current Git facts recorded
verify worktree remains intact
repeat finish idempotently
```

### Journey G — cross-platform clean matrix

Run the bounded local-repository version of journeys D and E on macOS, Linux, and Windows.

---

## 16. Acceptance criteria

A strong pass requires all of the following.

### Product behavior

```text
coding-harness starting directory: irrelevant
existing project selected without developer path choice
new project initialized without developer Git commands
stable project identity independent of path
durable restart-safe sessions
exact DevKit identity reported
new project exact DevKit available
```

### Harness neutrality

```text
MCP tools: passed
JSON CLI: passed
semantic parity: passed
Codex-specific runtime code: zero
harness-specific project semantics: zero
```

### Developer ceremony

```text
developer-selected repository path: 0
developer Git initialization actions: 0
developer branch/worktree decisions: 0
developer DevKit version decisions: 0
developer manual template copy actions: 0
```

### Git safety

```text
original imported application source changes: 0
original checkout status changes: 0
duplicate project on replay: 0
duplicate worktree on same-key replay: 0
wrong-project mutation on ambiguity: 0
```

### Boundaries

```text
capy-outcome-runtime source changes: 0
production database mutations: 0
production release changes: 0
provider secrets accessed: 0
builder/Codex process launches: 0
```

### Quality

```text
complete source test suite passes
macOS/Linux/Windows matrix passes or unsupported platform remains an explicit blocker
fresh independent source/safety review accepts
fresh independent developer-product/protocol review accepts
repository clean after evidence commit
```

---

## 17. Independent review questions

Use at least two fresh reviewers with different focuses.

### Reviewer A — source, Git, and authority

Ask:

```text
Can a malformed or ambiguous request mutate the wrong project?
Can idempotency create duplicate repositories or worktrees?
Does the tool ever modify an imported developer checkout?
Are Git commands injection-safe?
Can managed paths escape their configured roots?
Does any runtime/production/builder authority leak in?
Are sessions terminal and restart-safe?
```

### Reviewer B — developer product and protocol

Ask:

```text
Can a generic MCP-capable harness understand the tools without hidden oral context?
Can a shell-capable harness use the same behavior through JSON CLI?
Does the developer still need to select a repository path, branch, or DevKit?
Are existing and new projects distinguished explicitly?
Are errors causal enough for another coding harness to repair or ask the human?
Does the work remain useful from an unrelated starting directory?
```

No reviewer should rely only on implementation-written tests.

---

## 18. Evidence and closure artifacts

Preserve in `capy-developer` at minimum:

```text
docs/DIRECTION.md
campaigns/developer_foundation_v0/PLAN.md
campaigns/developer_foundation_v0/FINDINGS.md
campaigns/developer_foundation_v0/ACCEPTANCE.md
campaigns/developer_foundation_v0/receipt.json
campaigns/developer_foundation_v0/cross-platform receipt(s)
campaigns/developer_foundation_v0/independent-review-a.md
campaigns/developer_foundation_v0/independent-review-b.md
```

The machine-readable receipt should bind:

```text
source base and accepted commit/tree
package/binary identity
schema versions
SQLite schema version
exact DevKit release identities
fixture application repository heads
all test counts
all acceptance-journey dispositions
CLI/MCP parity result
cross-platform result
runtime/application/production changes: zero
remaining blockers and non-claims
```

Update `capy-project` only with the active work record and terminal closure summary. Do not copy the full campaign evidence into the control repository.

---

## 19. Stop and failure rules

Stop and report truthfully rather than broadening the task when:

```text
current source state conflicts materially with this plan
a different task is already authorized
the accepted DevKit artifact cannot be reproduced or verified
the new repository cannot be created safely
native Git worktree behavior cannot be made cross-platform within the boundary
MCP and CLI cannot share one core without duplicating semantics
an imported application would need source modification to participate
```

Do not respond to a blocker by:

```text
modifying production runtime
rewriting the DevKit contract
upgrading legacy applications silently
adding a Git-provider control plane
launching Codex from Capy Developer
building release publication
```

Those are separate decisions.

---

## 20. Explicit non-goals and non-claims

A successful V0 does not prove:

```text
complete inventory of every historical Capy repository
a final public Capy Developer API
automatic installation into every coding harness
actual Codex, Claude Code, Cursor, or Copilot end-to-end use
remote MCP
cloud workspaces
remote repository provisioning
full app build/test/conformance orchestration
application UI preview
release acceptance or production import
complete extraction of builder residue from runtime
malicious untrusted-code safety
public multi-user developer service
```

It proves only:

> A generic coding harness can call Capy Developer from anywhere and receive the correct existing or newly initialized Capy project, exact source base, isolated Git workspace, and truthful pinned DevKit state through MCP or JSON CLI without developer repository ceremony.

---

## 21. Expected next tasks, not authorized now

If this foundation is accepted, likely next slices are:

```text
Capy Developer Verify V0
  project-native tests
  DevKit conformance
  runtime integration harness
  precise diagnostics

Capy Developer Release Candidate V0
  exact commit/tree/artifact binding
  independent acceptance handoff
  no direct production write

Capy Developer Harness Setup V0
  installable local package/binary
  harness detection
  MCP and Agent Skill configuration

Capy Builder Complete Extraction V0
  move all remaining builder implementation and authority out of runtime
  into the established Capy Developer boundary
```

Do not start them during this task.

---

## 22. Final Codex directive

Implement the smallest trustworthy system that makes this statement true:

```text
A coding harness does not need to know where Capy projects live.
It asks Capy Developer for one project.
Capy Developer returns one exact prepared development world.
```

Optimize for:

```text
ordinary Git
small durable state
exact identity
idempotency
causal diagnostics
cross-platform behavior
MCP/CLI parity
no hidden runtime coupling
```

Do not optimize for:

```text
feature count
a final SDK
a public platform
a specific coding harness
an impressive architecture diagram
```

The first implementation succeeds when project discovery and preparation disappear from the developer’s responsibility without becoming hidden guesses inside the tool.
