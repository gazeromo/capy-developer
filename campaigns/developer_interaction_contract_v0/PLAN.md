# CAPY-DEVELOPER-INTERACTION-CONTRACT-V0

## One portable application, one developer-authored human contract, deterministic cross-contract verification, and release-candidate V1

**Status:** proposed bounded two-stage implementation task for Codex  
**Effective date:** 2026-09-05  
**Primary product:** Capy Developer  
**Supporting developer product:** Capy Script DevKit  
**Primary user:** a developer using any coding harness that can call MCP tools or ordinary JSON CLI commands  
**Primary implementation repository:** `gazeromo/capy-developer`  
**Supporting implementation repository:** `gazeromo/capy-script-devkit`  
**Required Capy Developer base / current merged main:** `5a950b1a1b73ce6f99018261f0846bda2f3a5fea`  
**Required Capy Developer branch:** `codex/developer-interaction-contract-v0`  
**Required DevKit base / current merged main:** `8c4fec7f814a62ded441786b8eba28af14d1aa2d`  
**Required DevKit branch:** `codex/application-interaction-contract-v0`  
**Current accepted Capy Developer version:** `0.3.0`  
**Current accepted Capy Developer wheel SHA-256:** `e69eb720a214d6cf1e960e19a0207ada5695664374412f0ec61380d6fb2e3a3c`  
**Target Capy Developer version:** `0.4.0`  
**Current DevKit release-binding commit:** `8c4fec7f814a62ded441786b8eba28af14d1aa2d`  
**Current DevKit implementation/source commit:** `e4462973d94584a75a1596f1b06a425a8da7f20d`  
**Current DevKit authoring-bundle SHA-256:** `dc2c27611d12ecb12e1a929252a51e177537d8f0e4fba86de5ed93edae886d5c`  
**Current DevKit wheel SHA-256:** `46f0b7865491054991b855d3bf709a445b7cc730077aaca2059cc095c685b30d`  
**Current DevKit execution contract:** `capy.script/dev-v0`  
**Expected new DevKit package version:** `0.1.0`  
**Control repository:** `gazeromo/capy-project`  
**Current control main:** `a87513aab945602cca15df4340234d459f2f401a`  
**Current control state:** Release Candidate V0 is accepted and closed; no successor is currently authorized  
**Runtime reference repository:** `gazeromo/capy-outcome-runtime`  
**Current runtime main reference:** `61a71a1067183343504305337128ca0af083542f`  
**Runtime changes authorized:** none  
**Production changes authorized:** none  
**Application installation, acceptance, publication, binding, or deployment authorized:** none  
**Application repository changes authorized:** only task-owned qualification repositories and worktrees  
**Existing FedEx, Proforma, Watcher, and other accepted application changes authorized:** none  
**Provider calls or provider-secret access authorized:** none  
**Coding-agent launch inside Capy Developer authorized:** none  

---

## 1. Executive task

Extend the accepted developer-side pipeline so that a portable Capy application carries not only its executable contract and software bytes, but also one exact, developer-authored **human interaction contract**.

The target journey is:

```text
developer opens any configured coding harness from any directory
→ Capy Developer prepares the exact existing or explicitly new project
→ the project carries an exact interaction-aware DevKit lock
→ the harness writes ordinary application source, tests, fixtures,
  capability.toml, and interaction.json
→ the harness commits one exact candidate
→ capy_development_verify runs the exact locked DevKit offline
→ the DevKit validates the human contract against capability.toml
→ application tests and conformance run
→ one canonical interaction-contract projection is preserved by digest
→ one deterministic application archive is preserved by digest
→ a passed verification becomes a deterministic release-candidate V1
→ the candidate carries the exact application archive, canonical human
  contract, portable verification receipt, and exact DevKit authoring bundle
→ a fresh copied-byte oracle validates all identities without project,
  database, worktree, cache, runtime, or previous harness context
```

The product claim to establish is:

> A fresh coding harness can author a portable Capy application's human-facing contract in the same ordinary project as its software, and Capy Developer can deterministically reject structural overstatement, bind the exact human contract to the exact verified source, and carry both in one immutable release candidate for later independent acceptance.

The task has two hard-gated implementation stages:

```text
Stage A
  Capy Script DevKit gains the provisional interaction authoring contract,
  validator, command, template, tests, and one independently accepted release.

Stage B
  Capy Developer consumes only that exact accepted DevKit release,
  adds interaction-aware verification and release-candidate V1,
  preserves all historical V0 behavior, and is independently accepted.
```

Stage B must not begin from mutable or merely passing DevKit source. It may begin only after Stage A produces an exact accepted DevKit release identity.

The boundary ends at:

```text
verified executable software
+ verified structural human contract
→ immutable release candidate awaiting independent acceptance
```

It does **not** continue to:

```text
semantic/business acceptance
runtime interaction-contract import
application installation
application operation registration
Luna exposure
Workbench UI rendering
Personal/Team workspace binding
publication
production activation
deployment
```

The decisive invariant is:

> **The developer and verifier may describe and bind software. They may not accept their own claims or activate software in Capy.**

---

## 2. Why this is the next slice

Capy Developer now truthfully owns:

```text
project discovery and identity
repository initialization
exact Git base selection
isolated development worktrees
project-pinned DevKit resolution
exact committed application verification
deterministic transferable .capyrc construction
MCP and JSON CLI parity
```

The accepted developer lifecycle currently reaches:

```text
intent
→ exact project
→ exact worktree
→ ordinary code
→ exact commit/tree
→ DevKit verification
→ deterministic application archive
→ deterministic .capyrc
```

But Release Candidate V0 explicitly records:

```text
interaction_contract = not_included
```

That omission was correct for V0. It is now the next real gap.

Current Capy is a closed-world, contract-aware workbench. Its accepted user path depends on a human contract that says:

```text
what the installed application is for
what it is not for
which operation the person can request
which human fields and files are required
which defaults are safe
which results and artifacts are returned
which nearby requests are unsupported
```

Today those contracts are private runtime integration code. The Encar Watcher and Proforma Invoice contracts are constructed inside `capy-outcome-runtime`, bound to exact application versions, and checked against current execution truth.

A newly developed portable application therefore cannot yet arrive as a complete human-usable application. A runtime maintainer would have to recreate its human semantics through another integration side channel.

This task closes that developer-side gap without prematurely changing runtime.

The dependency order is:

```text
Capy Developer Foundation V0                 accepted
→ Capy Developer Verify V0                   accepted
→ Capy Developer Release Candidate V0        accepted
→ Capy Developer Interaction Contract V0     this task
→ Independent Application Acceptance V0      later
→ Runtime Import and Preview V0               later
→ Harness Setup V0                            separately authorized
→ Builder Complete Extraction V0              separately authorized
```

Do not skip directly to runtime import. The object to be accepted and imported should first contain the complete bounded developer-authored application meaning.

---

## 3. Current accepted truth that must remain preserved

### 3.1 Capy Developer

Current accepted main:

```text
5a950b1a1b73ce6f99018261f0846bda2f3a5fea
```

Accepted Release Candidate V0 established:

```text
96/96 local tests
96/96 Ubuntu tests
96/96 macOS tests
96/96 Windows tests
installed-wheel MCP Journey A
installed-wheel JSON CLI Journey B
one deterministic self-contained .capyrc
copied-byte independent oracle pass
26/26 tampered candidates rejected
two byte-identical Capy Developer wheel builds
fresh offline install and doctor/CLI/MCP smoke
independent implementation, evidence, and closure ACCEPT
post-merge CI on all three platforms
```

The accepted V0 release candidate carries exactly:

```text
RELEASE-CANDIDATE.json
application/application.zip
evidence/verification.json
toolchain/authoring-bundle.zip
```

Its manifest schema is:

```text
capy.application-release-candidate/v0
```

Its verification pipeline has nine stages and its portable receipt schema is:

```text
capy.development-verification-receipt/v0
```

Historical V0 candidate inspection and validation are accepted behavior and must remain supported.

### 3.2 Capy Script DevKit

Current accepted release-binding main:

```text
8c4fec7f814a62ded441786b8eba28af14d1aa2d
```

The current contract remains:

```text
capy.script/dev-v0
```

Its supported application surface is:

```text
ctx.request
ctx.resource(...)
ctx.connection(...).call(...)
ctx.state_dir
ctx.artifact(...)
ctx.complete(...)
ctx.fail(...)
```

Its supported commands are currently:

```text
doctor
new
check
run
test
conform
pack
```

The Windows compatibility release correctly distinguishes core resource-only support from optional Unix-domain-socket connection simulation.

This task must not change the runtime helper calls above.

### 3.3 Current runtime interaction contracts

Current runtime main contains a private schema:

```text
capy.application-interaction/v0
```

The runtime's current contracts establish useful categories:

```text
application title and purpose
not-for statements
operations
human fields
safe defaults
examples
common misunderstandings
result facts and artifacts
unsupported boundaries and nearest operations
exact application-version binding
cross-checks against executable fields, effects, and result schema
```

The current implementation also contains application-specific and runtime-owned concerns:

```text
watch selectors
current-workspace context fields
team/creator authority text
state-effect policy
source behavior
multiple stateful operations
application-specific profile branches
```

Those runtime-private concerns are **not** automatically a developer SDK.

This task reuses the proven categories but creates a smaller portable authoring subset for one-shot `capy.script/dev-v0` applications.

### 3.4 Current control state

The current control repository records:

```text
No Capy implementation task is currently authorized.
```

Implementation must not begin until this plan is explicitly authorized and recorded as current work.

---

## 4. Claim discipline

Keep these claims separate.

### 4.1 Structural contract verification

This task may prove:

```text
interaction JSON has the exact supported shape
application ID matches capability.toml
one interaction operation is declared
human request fields map exactly to executable input-schema leaves
requiredness and safe defaults match executable input truth
resource fields map exactly to declared resource slots and counts
result facts exist in the result schema
artifact labels map to exact declared artifact filenames
read-only/artifact effect claims are not structurally contradicted
exact human-contract bytes are bound to exact source and package bytes
```

### 4.2 Semantic/business acceptance

This task does **not** prove that prose such as:

```text
purpose
not_for
field descriptions
examples
common misunderstandings
boundary explanations
result labels
```

is factually complete, domain-correct, legally sufficient, or desirable for users.

That judgment belongs to later independent application acceptance.

The deterministic validator should prevent machine-evident contradiction. It must not pretend it can understand whether arbitrary prose is honest.

### 4.3 Runtime compatibility

This task does not prove that current runtime can import or render the new portable contract.

It creates an exact candidate input for the later runtime-import task.

### 4.4 Interaction authoring schema status

The new schema is provisional:

```text
capy.application-interaction/dev-v0
```

It is not a public stable SDK promise and does not replace the runtime-private:

```text
capy.application-interaction/v0
```

A later import adapter may validate and project the portable schema into runtime-owned interaction truth.

---

## 5. Two-stage repository and authority boundary

### 5.1 Stage A — DevKit

Repository:

```text
gazeromo/capy-script-devkit
```

Branch:

```text
codex/application-interaction-contract-v0
```

Stage A owns:

```text
portable interaction-contract source schema
interaction.json parser and validator
cross-contract validation against capability.toml
canonical JSON projection
interaction-check command
interaction-aware starter template
Codex/harness authoring instructions
conformance and negative controls
new exact DevKit wheel and authoring bundle
```

Stage A does not own:

```text
Capy Developer database or sessions
release-candidate construction
runtime import
application acceptance
UI rendering
production
```

### 5.2 Stage A acceptance gate

Before Stage B begins, Stage A must produce and independently accept:

```text
exact source commit and tree
exact release-binding commit
exact wheel filename and SHA-256
exact authoring-bundle filename and SHA-256
exact contract schemas
cross-platform qualification
fresh offline installation
reproducible wheel and authoring-bundle bytes
```

Do not point Capy Developer at an implementation branch or mutable `main` before the release-binding closure exists.

### 5.3 Stage B — Capy Developer

Repository:

```text
gazeromo/capy-developer
```

Branch:

```text
codex/developer-interaction-contract-v0
```

Stage B owns:

```text
new exact DevKit trust binding
new-project lock/template selection
interaction-aware verification pipeline
portable interaction evidence
release-candidate V1 construction and inspection
historical V0 compatibility
SQLite migration and durable identities
MCP/JSON CLI parity
```

Stage B does not own:

```text
runtime interaction-contract registry
independent application acceptance
application installation
workspace binding
publication or deployment
```

### 5.4 Runtime remains read-only archaeology

Runtime source may be read only to understand proven contract categories and current private validation.

Do not:

```text
import capy-outcome-runtime into either package
copy runtime application-specific branches into the DevKit
change runtime source or tests
write runtime databases
install a candidate into runtime
```

---

## 6. Developer experience contract

### 6.1 New project

From an unrelated directory, a coding harness explicitly requests a new app:

```text
Create a Capy application that summarizes one CSV file.
```

Capy Developer must prepare a project that already contains:

```text
capability.toml
interaction.json
ordinary source
ordinary tests
conformance fixtures
capy.project.toml
capy.lock
CAPY.md
```

The exact lock must select the newly accepted interaction-aware DevKit.

The harness should need only to edit the application and its human contract.

### 6.2 Existing interaction-aware project

From another machine or later session, the harness asks to update the same app.

Capy Developer resolves the project and exact current source, and the harness receives the same contract/tooling without prior conversation.

### 6.3 Verification

The harness commits one exact candidate and calls:

```text
capy_development_verify
```

No extra interaction-specific MCP call is required.

The result is either:

```text
FAILED
  with a causal interaction-contract diagnostic and no package/candidate claim

or

PASSED / VERIFIED
  with exact executable and interaction identities
```

### 6.4 Release candidate

The harness then calls:

```text
capy_release_candidate_create({verification_id})
```

It does not repeat:

```text
interaction path
interaction schema
operation ID
application ID
source commit/tree
DevKit identity
output path
```

The release candidate carries the exact canonical interaction contract automatically.

---

## 7. Portable interaction contract file

The source file is exactly:

```text
interaction.json
```

It lives at the root of one portable application beside:

```text
capability.toml
```

For this V0:

```text
one capability.toml
+ one interaction.json
+ one operation
```

The file may be human-formatted JSON in source.

The validated portable projection is canonical JSON:

```text
UTF-8
sorted object keys
compact separators
no NaN or Infinity
no trailing newline
```

The validator must never rewrite the source file during `check`, `test`, `conform`, or verification.

---

## 8. Provisional source schema

Schema identifier:

```text
capy.application-interaction/dev-v0
```

The exact top-level key set is:

```text
schema
application_id
title
purpose
not_for
operation
boundaries
```

Example:

```json
{
  "schema": "capy.application-interaction/dev-v0",
  "application_id": "demo.csv_summary",
  "title": "CSV summary",
  "purpose": "Summarize one CSV resource and return verified row and column facts.",
  "not_for": [
    "editing the source CSV",
    "sending data to an external service"
  ],
  "operation": {
    "operation_id": "csv.summarize",
    "title": "Summarize a CSV",
    "user_outcome": "Get a concise summary of one CSV file.",
    "description": "Read one CSV and return its row and column counts.",
    "request_fields": [
      {
        "field_id": "include_header",
        "label": "First row contains headers",
        "description": "Treat the first row as column names.",
        "required": false,
        "input_kind": "boolean",
        "safe_default": true,
        "examples": ["Yes"],
        "clarification_question": "Does the first row contain column names?"
      }
    ],
    "resource_fields": [
      {
        "slot": "source_csv",
        "label": "CSV file",
        "description": "The CSV file to summarize.",
        "required": true,
        "minimum_count": 1,
        "maximum_count": 1,
        "input_kind": "file",
        "examples": ["products.csv"],
        "clarification_question": "Which CSV file should I summarize?"
      }
    ],
    "examples": [
      "Summarize this product CSV."
    ],
    "common_misunderstandings": [
      "The source file is read but not edited."
    ],
    "result": {
      "presentation": "facts",
      "facts": [
        {"path": "row_count", "label": "Rows"},
        {"path": "column_count", "label": "Columns"}
      ],
      "artifacts": []
    }
  },
  "boundaries": [
    {
      "boundary_id": "csv.edit",
      "request_class": "editing or correcting the CSV",
      "explanation": "This application reads the file but does not change it.",
      "nearest_operation_ids": ["csv.summarize"]
    }
  ]
}
```

Do not add optional top-level extension maps in V0.

Unknown keys fail closed.

---

## 9. Operation shape

The exact operation key set is:

```text
operation_id
title
user_outcome
description
request_fields
resource_fields
examples
common_misunderstandings
result
```

### 9.1 Operation ID

`operation_id` uses the same bounded dotted-lowercase family as application IDs:

```text
[a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)+
```

It is a human/interaction operation identity.

It does not create a second executable entry point. In portable V0, it maps to the one application capability.

### 9.2 One operation only

Do not support operation arrays in this authoring schema.

Multiple operations belong to later stateful/team-application evidence.

### 9.3 No developer-authored capability ID

The operation does not repeat `capability_id`.

It is derived as:

```text
capability_id = application_id = capability.toml id
```

This avoids a mechanically unnecessary duplicate field.

---

## 10. Request-field shape

Each request field has exactly:

```text
field_id
label
description
required
input_kind
safe_default
examples
clarification_question
```

### 10.1 Field identity

`field_id` is an exact dotted path into the executable input schema.

Examples:

```text
currency
options.include_header
filters.minimum_year
```

### 10.2 Requiredness

The declared `required` boolean must equal executable effective requiredness.

A leaf is effectively required only when every object path segment from the input root to that leaf is required by its parent schema.

Example:

```text
optional parent object
└── internally required child

human field is still optional overall
```

### 10.3 Input kinds

V0 allows:

```text
text
long_text
number
boolean
choice
```

Mapping rules:

```text
JSON string without enum → text or long_text
JSON string with enum    → choice
JSON integer             → number
JSON number              → number
JSON boolean             → boolean
```

Arrays and free-form objects are not human request fields in V0.

If the input contract cannot be represented through scalar leaf fields, interaction verification fails truthfully instead of inventing a UI.

### 10.4 Safe defaults

`safe_default` is always present.

It is either:

```text
null
or one JSON scalar valid under the exact field schema
```

Rules:

```text
required field → safe_default must be null
optional field → null or a schema-valid scalar
choice field → default must be a declared enum item
```

The validator must not infer or add defaults.

### 10.5 Complete coverage

Every scalar input leaf must appear exactly once in `request_fields`.

Reject:

```text
unknown field
missing input field
duplicate field
parent and child both declared
open additionalProperties object
unsupported array/object leaf
```

This ensures the human contract cannot hide an executable input field.

---

## 11. Resource-field shape

Each resource field has exactly:

```text
slot
label
description
required
minimum_count
maximum_count
input_kind
examples
clarification_question
```

Rules:

```text
input_kind must be file
slot must exactly match one capability.toml resource requirement
required must match descriptor requiredness
minimum_count must match descriptor min_items
maximum_count must match descriptor max_items
all descriptor resource slots must be declared exactly once
no extra resource field is allowed
```

Descriptions and examples are human claims and remain subject to later independent acceptance.

V0 does not add MIME type, file-extension, or media-schema claims because the current executable descriptor does not prove those facts generically.

---

## 12. Result shape

The exact result key set is:

```text
presentation
facts
artifacts
```

### 12.1 Presentation kinds

V0 allows:

```text
facts
artifact_result
```

Rules:

```text
no declared artifacts → presentation must be facts
one or more declared artifacts → presentation must be artifact_result
```

### 12.2 Facts

Each fact has exactly:

```text
path
label
```

`path` must resolve to a scalar leaf in the exact executable result schema.

Allowed leaf types:

```text
string
integer
number
boolean
```

Facts must be unique.

At least one fact or one artifact must be declared.

The interaction contract may select a truthful subset of result fields for ordinary presentation. It need not expose every technical result field.

### 12.3 Artifacts

Each artifact has exactly:

```text
filename
label
```

The executable result schema must declare fixed artifact filenames through the accepted V0 convention:

```text
result_schema.properties.artifact_filenames.items.enum
```

Rules:

```text
read_only side effect → artifacts must be empty
artifact_generation → interaction artifact filenames must equal the executable enum exactly
no dynamic artifact filenames in interaction V0
no artifact filename absent from result schema
```

Order is preserved and must be deterministic.

---

## 13. Boundaries

Every boundary has exactly:

```text
boundary_id
request_class
explanation
nearest_operation_ids
```

Rules:

```text
boundary_id is unique and dotted lowercase
request_class is non-empty plain text
explanation is non-empty plain text
nearest_operation_ids is a non-empty array
in V0 every nearest operation must equal the one declared operation_id
```

At least one boundary is required.

Boundaries explain unsupported nearby requests. They do not authorize another application or create a build request.

---

## 14. Text and size rules

All human text is treated as plain text by contract consumers.

No field permits arbitrary HTML, CSS, JavaScript, Markdown execution, template expressions, or code.

Recommended hard limits:

```text
interaction.json source bytes             <= 64 KiB
title                                      1..120 Unicode characters
purpose                                    1..1000 characters
operation title                            1..120 characters
user_outcome                               1..500 characters
description / field description            1..1000 characters
label                                      1..120 characters
clarification question                     1..500 characters
example                                    1..500 characters
not_for entries                            1..500 characters
boundary request/explanation               1..1000 characters
not_for items                              1..32
request fields                             0..64
resource fields                            0..16
facts                                      0..64
artifacts                                  0..32
examples per list                          1..16 where required
boundaries                                 1..32
```

Reject:

```text
NUL
unpaired/non-decodable UTF-8
leading or trailing whitespace in scalar text
empty list entries
non-finite numbers
excessive nesting
unknown keys
```

Do not attempt language policing or semantic moderation in this validator.

---

## 15. V0 executable eligibility

The portable interaction authoring contract supports only capabilities satisfying:

```text
schema = capy.script/dev-v0
state_required = false
connections = []
side_effect in {read_only, artifact_generation}
closed, finitely enumerable input object schema
one root capability.toml
one root interaction.json
```

Reject with causal codes:

```text
INTERACTION_STATE_UNSUPPORTED
INTERACTION_CONNECTIONS_UNSUPPORTED
INTERACTION_SIDE_EFFECT_UNSUPPORTED
INTERACTION_INPUT_SHAPE_UNSUPPORTED
```

This does not remove existing DevKit support for connections, state, or other side effects.

It means only that this first human-contract profile does not yet claim to describe those application shapes.

Existing connected FedEx software remains pinned to its historical exact DevKit and is unchanged.

---

## 16. DevKit validator

Implement one small dependency-free module, for example:

```text
src/capy_script/interaction.py
```

It owns:

```text
source loading
exact key and type validation
bounded text validation
canonical JSON construction
application/operation ID validation
input-schema path enumeration
requiredness derivation
input-kind compatibility
safe-default validation
resource cross-checks
result fact/artifact cross-checks
side-effect/state/connection eligibility
stable diagnostic codes
```

It must not:

```text
import Capy Developer
import Capy runtime
call a model
call a provider
read outside the application root
mutate source
execute the application
```

### 16.1 Canonical projection

The validator returns canonical bytes for the exact validated source object.

It does not add runtime-owned fields such as:

```text
digest
authority policy
workspace membership
source behavior
state-effect policy
application version
installation identity
```

Those belong to later trust/runtime boundaries.

---

## 17. DevKit command

Add exactly one authoring command:

```text
python -m capy_script interaction-check <application-path> [--output <canonical-json-path>]
```

Equivalent installed command behavior through `capy-script` is acceptable.

Required behavior:

```text
load capability.toml
load interaction.json
validate exact source schema
validate cross-contract consistency
compute canonical JSON bytes
optionally write canonical bytes atomically to --output
print a bounded success line containing application ID, operation ID, and SHA-256
return 0 on success
return 2 with a stable diagnostic on validation failure
```

The command must not modify anything below `<application-path>`.

If `--output` is omitted, validation still runs and no file is created.

The command is not:

```text
an application run
a runtime preview
an acceptance decision
a UI generator
```

---

## 18. DevKit diagnostics

At minimum preserve causal distinctions for:

```text
INTERACTION_FILE_MISSING
INTERACTION_FILE_INVALID
INTERACTION_SCHEMA_UNSUPPORTED
INTERACTION_APPLICATION_MISMATCH
INTERACTION_OPERATION_INVALID
INTERACTION_FIELD_UNKNOWN
INTERACTION_FIELD_DUPLICATE
INTERACTION_FIELD_MISSING
INTERACTION_REQUIRED_MISMATCH
INTERACTION_INPUT_KIND_MISMATCH
INTERACTION_DEFAULT_INVALID
INTERACTION_RESOURCE_UNKNOWN
INTERACTION_RESOURCE_DUPLICATE
INTERACTION_RESOURCE_MISSING
INTERACTION_RESOURCE_CONTRACT_MISMATCH
INTERACTION_RESULT_FACT_UNKNOWN
INTERACTION_RESULT_FACT_DUPLICATE
INTERACTION_ARTIFACT_MISMATCH
INTERACTION_PRESENTATION_MISMATCH
INTERACTION_BOUNDARY_INVALID
INTERACTION_STATE_UNSUPPORTED
INTERACTION_CONNECTIONS_UNSUPPORTED
INTERACTION_SIDE_EFFECT_UNSUPPORTED
INTERACTION_INPUT_SHAPE_UNSUPPORTED
```

Diagnostics should include bounded safe context such as:

```text
field_id
resource slot
result path
expected requiredness
observed input kind
```

Do not include source file bytes or environment values in error output.

---

## 19. DevKit template and authoring docs

The interaction-aware Python template must include:

```text
capability.toml
interaction.json
main.py
tests/
conformance/
README.md
```

The default `demo.hello` interaction contract should be valid and minimal:

```text
no request fields
no resource fields
one result fact: message
read-only presentation
one boundary explaining that it does not send or mutate anything
```

Update the curated authoring guidance:

```text
AGENTS.md
README.md
SUPPORTED-V0.md
CONTRACT.md
new INTERACTION-CONTRACT.md or equivalent concise source
```

The fresh harness instruction must say:

```text
capability.toml defines executable truth
interaction.json defines provisional human meaning
never make interaction.json claim a field, artifact, effect, or operation
that capability.toml does not support
run interaction-check before completion
```

Do not copy runtime history or application-specific watcher/proforma prose into the bundle.

---

## 20. DevKit package and authoring-bundle versioning

### 20.1 Execution contract remains unchanged

Keep:

```text
capy.script/dev-v0
```

No runtime helper API changes are allowed.

### 20.2 New interaction schema

Add:

```text
capy.application-interaction/dev-v0
```

### 20.3 New authoring-bundle schema

Use a new exact bundle schema:

```text
capy.devkit-authoring-bundle/v1
```

Do not silently add fields under the accepted V0 authoring-bundle schema.

The V1 release manifest must bind:

```text
source repository
source commit and tree
execution contract
interaction contract
wheel filename and SHA-256
package-tree SHA-256
build Python and tools
qualification receipt digest
exact template member set
```

### 20.4 Expected package version

Use:

```text
capy-script-devkit 0.1.0
```

unless current package truth reveals a non-conflicting version already exists. Record any necessary deviation explicitly before implementation.

### 20.5 Historical immutability

Do not modify or replace prior release bytes:

```text
current Windows-compatible V0 bundle/wheel
historical Minimal DevKit V0 bundle/wheel
```

A new release is a new exact identity.

---

## 21. Stage A tests

Add focused tests for:

```text
valid zero-input read-only interaction
valid scalar request fields
valid nested scalar request paths
valid requiredness through nested optional objects
valid enum choice
valid optional safe default
valid resource field and count mapping
valid artifact-generation result
canonical output determinism
pretty source JSON → exact canonical output
no application-source mutation
```

Negative truth table must include at least:

```text
missing interaction.json
malformed JSON
unknown top-level key
wrong schema
wrong application ID
duplicate/invalid operation ID
missing required input leaf
unknown input leaf
parent and child both declared
duplicate request field
requiredness weakened
requiredness strengthened incorrectly
kind mismatch
default on required field
default outside enum/default type
open additionalProperties input
array input leaf
missing resource slot
unknown resource slot
wrong resource counts
read-only app declaring artifacts
artifact app omitting artifact
unknown result fact
object/array result fact
wrong presentation
unknown nearest operation
empty not_for
empty boundaries
stateful capability
connected capability
scope_state_mutation
external_effect
oversized source/text/list
NUL or untrimmed text
```

The hidden oracle should mutate one valid interaction contract across each independent invariant and require the exact expected diagnostic family.

---

## 22. Stage A cross-platform qualification

Run the complete DevKit suite on:

```text
Ubuntu
macOS
Windows
```

The interaction fixture must be resource-only or zero-resource and connection-free on all platforms.

Do not claim Windows connection simulation.

Required package checks:

```text
two clean wheel builds are byte-identical
two clean authoring-bundle builds are byte-identical
fresh offline wheel install passes
installed doctor passes
installed interaction-check passes
installed template creates a valid interaction-aware app
bundle contains only curated authoring material
no evaluation/campaign history in authoring bundle
```

Two independent Stage A reviewers should examine:

```text
schema exactness and cross-contract validation
package/bundle identity and historical immutability
```

No P0-P2 finding may remain. Address actionable P3 findings or record why they are non-actionable before acceptance.

---

## 23. Stage A stop conditions

Stop before Stage B if any of these occur:

```text
the interaction validator requires capy-outcome-runtime imports
the validator requires application-specific names or branches
the schema must support multiple operations to pass the chosen fixture
the schema must support state, connections, or external effects to pass the fixture
resource-only interaction verification fails on a required OS
historical DevKit release bytes or identities change
the authoring bundle cannot be reproduced
independent review finds an unresolved contradiction or unsafe path
```

Do not weaken the gate by adding OS exceptions or copying runtime code.

---

## 24. Exact Stage A handoff to Capy Developer

After Stage A acceptance, record:

```text
DevKit accepted source commit
DevKit accepted source tree
DevKit release-binding commit
wheel filename
wheel SHA-256
authoring-bundle filename
authoring-bundle SHA-256
bundle schema
execution contract
interaction contract
qualification receipt SHA-256
```

Stage B must embed and trust those exact bytes.

No field in the Stage B plan should continue using the placeholder values from this document after exact Stage A release truth exists.

---

## 25. Capy toolchain lock V1

New interaction-aware projects use:

```text
capy.toolchain-lock/v1
```

Provisional exact shape:

```toml
schema = "capy.toolchain-lock/v1"
contract = "capy.script/dev-v0"
interaction_contract = "capy.application-interaction/dev-v0"
devkit_repository = "gazeromo/capy-script-devkit"
devkit_commit = "<accepted Stage A release-binding commit>"
wheel = "capy_script_devkit-0.1.0-py3-none-any.whl"
wheel_sha256 = "<accepted Stage A wheel digest>"
authoring_bundle_sha256 = "<accepted Stage A bundle digest>"
```

Rules:

```text
legacy DEVKIT.lock remains supported
capy.toolchain-lock/v0 remains supported
capy.toolchain-lock/v1 requires interaction_contract
unknown lock schema fails closed
no silent upgrade of existing project lock
new project initialization uses V1
```

The trusted DevKit release map must bind the interaction schema and authoring-bundle schema in addition to current wheel/source identities.

---

## 26. Capy Developer database migration

Advance:

```text
SQLite schema 3 → 4
```

Preserve every existing:

```text
project
alias
application binding
checkout
toolchain lock
development session
session event
verification attempt and stage
release candidate and member
```

### 26.1 Verification pipeline identity

Add an explicit pipeline/schema identity to verification attempts, for example:

```text
capy.development-verification-pipeline/v0
capy.development-verification-pipeline/v1
```

Backfill all current rows as V0.

Do not infer historical pipeline shape from current code at read time.

### 26.2 Toolchain interaction field

Persist the exact optional interaction-contract schema resolved from the lock/release.

Historical toolchains record no interaction contract.

### 26.3 Verification interaction evidence

Add one child table keyed by `verification_id`, preserving at least:

```text
verification_id
schema
source_member
source_sha256
canonical_sha256
canonical_size_bytes
canonical_path
operation_id
created_at
```

The canonical path is local storage metadata and must not enter portable receipts.

### 26.4 Release candidate format identity

Add/backfill an explicit release-candidate format schema:

```text
capy.application-release-candidate/v0
capy.application-release-candidate/v1
```

Existing rows become V0.

V1 interaction facts may be stored in a separate child table or exact columns. Preserve:

```text
interaction schema
source member and digest
canonical member and digest
operation ID
```

### 26.5 Migration proof

Create a real schema-3 database with:

```text
Foundation rows
passed/failed Verify V0 rows
one accepted V0 release-candidate row and member set
```

Open it under new code and prove:

```text
all counts preserved
all V0 results reread identically
V0 copied candidate still validates
new V1 rows can coexist
rollback backup is preserved for qualification
```

---

## 27. Verification pipeline V1

A toolchain lock declaring:

```text
interaction_contract = capy.application-interaction/dev-v0
```

selects:

```text
capy.development-verification-pipeline/v1
```

The V1 exact ordered stages are:

```text
1. toolchain_install
2. check
3. interaction_check
4. test
5. conform
6. source_mutation_check
7. pack_a
8. pack_b
9. package_compare
10. archive_preserve
11. interaction_preserve
```

Historical V0 remains exactly nine stages.

### 27.1 Interaction-check stage

Run the exact installed DevKit:

```text
python -m capy_script interaction-check <application-root> --output <attempt-owned canonical path>
```

Require:

```text
exit 0
canonical output file exists
bounded size
valid canonical JSON
schema matches resolved toolchain interaction schema
application ID matches verification application
source candidate remains unchanged
```

Capture bounded stdout/stderr through the existing process boundary.

### 27.2 Interaction source identity

From the exact detached candidate checkout, compute:

```text
source member = interaction.json
source SHA-256
```

Do not use the mutable managed worktree after prevalidation.

### 27.3 Interaction preserve stage

After every executable stage and package comparison passes:

```text
re-read source interaction.json from exact candidate snapshot
re-run or revalidate canonical identity without model/provider access
require source digest unchanged
require canonical digest unchanged
preserve canonical bytes content-addressed
record exact schema, operation ID, source digest, canonical digest, and size
```

Suggested durable path:

```text
<cache>/verification-interactions/sha256/<canonical digest>/interaction.json
```

If a conflicting file exists at the content-addressed path, fail closed.

### 27.4 Terminal behavior

Any interaction failure must produce:

```text
verification status = FAILED
causal classification = INTERACTION_CONTRACT_FAILED
exact failing stage = interaction_check or interaction_preserve
remaining stages = SKIPPED where appropriate
candidate archive claim = absent
release candidate creation = denied
```

The verification tool call itself remains a valid completed result rather than an MCP transport error.

Preflight failures such as unsupported toolchain remain tool errors as in accepted Verify V0.

---

## 28. Verification result V1

New successful attempts return:

```text
capy.development-verification-result/v1
```

Preserve the V0 shape and add:

```json
{
  "pipeline": "capy.development-verification-pipeline/v1",
  "interaction_contract": {
    "schema": "capy.application-interaction/dev-v0",
    "source_member": "interaction.json",
    "source_sha256": "<64 hex>",
    "canonical_sha256": "<64 hex>",
    "canonical_size_bytes": 1234,
    "operation_id": "csv.summarize",
    "available": true
  }
}
```

Do not return the local canonical path in the portable-facing result.

An inspect or replay after restart must recompute `available` by digest-checking the stored canonical bytes.

Historical verification results continue to use:

```text
capy.development-verification-result/v0
```

Do not add nullable interaction fields to the accepted V0 result schema.

---

## 29. Verification concurrency and recovery

Preserve Verify V0 rules:

```text
one active verification per development session
parallel verification allowed for separate sessions
idempotent key replays exact terminal result
same key with changed input conflicts
process interruption becomes durable INTERRUPTED
attempt-owned worktrees and temp paths are cleaned by ownership
stored verified archives and canonical interaction bytes survive restart
```

Additional V1 controls:

```text
interaction canonical output path must be attempt-owned before preservation
interrupted interaction stage leaves no successful interaction record
candidate edits after verification make latest state STALE
release candidate creation uses durable verification evidence, not current source
```

---

## 30. Release Candidate V1

A V1 verification produces:

```text
capy.application-release-candidate/v1
```

The outer file remains an ordinary deterministic ZIP with `.capyrc` suffix.

Exact member set and order:

```text
RELEASE-CANDIDATE.json
application/application.zip
application/interaction.json
evidence/verification.json
toolchain/authoring-bundle.zip
```

No other member is allowed.

### 30.1 Interaction member

`application/interaction.json` is the exact canonical JSON preserved by verification.

It is not rebuilt from current worktree source during release-candidate creation.

Before construction, revalidate:

```text
verification is PASSED / VERIFIED
verification pipeline is V1
interaction record exists
canonical file exists
canonical file digest and size match record
canonical JSON schema and application ID match record
application archive contains one root interaction.json
source interaction bytes match recorded source digest
canonical JSON of source object equals the preserved canonical member bytes
```

### 30.2 Application archive remains unchanged

Copy `application/application.zip` byte-for-byte from verification.

Do not remove or rewrite the source `interaction.json` inside it.

Thus the candidate carries both:

```text
original source-form interaction.json inside application archive
canonical independently addressable interaction projection outside it
```

### 30.3 Toolchain bundle

Carry the exact Stage A interaction-aware authoring bundle recorded by verification.

Do not resolve from a changed project lock.

### 30.4 Outer determinism

Use accepted V0 canonical ZIP rules:

```text
ZIP_STORED
fixed timestamp
fixed member order
fixed regular-file mode 0644
fixed create-system metadata
no comments
no extra fields
no directories
no symlinks
no duplicate/absolute/parent paths
```

Build twice and require byte identity before preservation.

---

## 31. Portable verification receipt V1

Use:

```text
capy.development-verification-receipt/v1
```

It extends the path-free V0 receipt with:

```json
{
  "pipeline": "capy.development-verification-pipeline/v1",
  "interaction_contract": {
    "schema": "capy.application-interaction/dev-v0",
    "source_member": "interaction.json",
    "source_sha256": "<64 hex>",
    "canonical_sha256": "<64 hex>",
    "canonical_size_bytes": 1234,
    "operation_id": "csv.summarize"
  }
}
```

The stages array must contain all eleven V1 stages exactly once and all must be `PASSED`.

Only allowlisted portable facts enter the receipt.

Do not include:

```text
source path
canonical cache path
worktree path
home path
temporary path
raw stdout/stderr
request prose
credentials
environment variables
```

---

## 32. Release Candidate manifest V1

Use:

```text
capy.application-release-candidate/v1
```

Required high-level shape remains:

```text
schema
release_candidate_id
identity_sha256
project
source
application
toolchain
verification
handoff
verified_at
```

The application object gains exact interaction identity:

```json
{
  "application": {
    "id": "demo.csv_summary",
    "contract": "capy.script/dev-v0",
    "descriptor_sha256": "<64 hex>",
    "archive": {
      "member": "application/application.zip",
      "sha256": "<64 hex>",
      "size_bytes": 1234
    },
    "interaction": {
      "schema": "capy.application-interaction/dev-v0",
      "source_member": "interaction.json",
      "source_sha256": "<64 hex>",
      "member": "application/interaction.json",
      "sha256": "<64 hex>",
      "size_bytes": 1234,
      "operation_id": "csv.summarize"
    }
  }
}
```

### 32.1 Handoff claims

V1 must state exactly:

```text
verification = passed
independent_acceptance = required
interaction_contract = included_unaccepted
state_migration = not_assessed
rollback = not_assessed
runtime_version_digest = not_assigned
publication = not_performed
installation = not_performed
binding = not_performed
deployment = not_performed
publisher_signature = not_present
secret_scan = not_performed
runtime_import = not_performed
```

Do not claim that structural interaction validation equals semantic acceptance.

### 32.2 Candidate identity

The canonical candidate identity must include all V0 immutable facts plus:

```text
interaction schema
interaction source digest
interaction canonical digest
interaction operation ID
V1 verification receipt digest
V1 authoring-bundle identity
```

Derive:

```text
identity_sha256 = SHA-256(canonical identity JSON)
release_candidate_id = rc_ + first 32 hex characters
```

A collision with different full identity fails closed.

---

## 33. Release Candidate result V1

Return:

```text
capy.development-release-candidate-result/v1
```

Include:

```text
release-candidate ID
format schema
bundle digest and size
manifest digest
verification ID
project/application/source identities
interaction schema and digests
member digest/size list
bundle availability
handoff claims
```

Do not expose local bundle path except through the existing local `path_uri` field where the CLI/MCP contract already intentionally returns a local artifact URI. The portable manifest remains path-free.

Historical V0 inspection continues to return:

```text
capy.development-release-candidate-result/v0
```

---

## 34. Backward compatibility

This task must preserve exact accepted behavior for:

```text
legacy DEVKIT.lock
capy.toolchain-lock/v0
current Windows-compatible DevKit release
historical Minimal DevKit release
verification pipeline V0
verification result V0
release candidate manifest V0
portable receipt V0
V0 copied-byte validation and inspection
```

Rules:

```text
V0 toolchain → V0 verification → V0 release candidate
V1 interaction-aware toolchain → V1 verification → V1 release candidate
```

Do not silently synthesize an interaction contract for an old application.

Do not silently upgrade an old project lock.

Do not reinterpret a V0 candidate as V1.

### 34.1 Existing candidate migration fixture

Before modifying database or candidate code, preserve one exact accepted V0 candidate fixture and schema-3 database fixture from current main.

After migration, a fresh process must:

```text
inspect it successfully
validate copied bytes successfully
return V0 schema
preserve its exact bundle digest
```

---

## 35. MCP and JSON CLI

No new high-level tool is necessary.

Existing tools remain:

```text
capy_development_verify
capy_release_candidate_create
capy_release_candidate_inspect
```

Their descriptions should explain versioned behavior:

```text
interaction-aware locked projects require and verify interaction.json
historical projects preserve V0 behavior
release candidate V1 includes an unaccepted interaction contract
```

CLI commands remain:

```text
capy-dev development verify ... --json
capy-dev release-candidate create --verification-id ... --json
capy-dev release-candidate inspect --release-candidate-id ... --json
```

MCP and CLI must invoke the same core and return semantically identical values.

The process current working directory remains irrelevant to project selection and candidate identity.

---

## 36. Error and result semantics

### 36.1 Verification result failure

A candidate with an invalid interaction contract produces an ordinary verification result:

```text
status = FAILED
classification = INTERACTION_CONTRACT_FAILED
```

MCP:

```text
isError = false
```

because the verification operation completed truthfully.

CLI exit:

```text
1
```

as for other candidate verification failures.

### 36.2 Tool errors

Use tool errors for precondition/integrity failures such as:

```text
TOOLCHAIN_LOCK_UNBOUND
TOOLCHAIN_UNAVAILABLE
TOOLCHAIN_INTEGRITY_FAILED
SESSION_NOT_READY
CANDIDATE_COMMIT_INVALID
APPLICATION_NOT_AT_CANDIDATE
INTERACTION_EVIDENCE_MISSING
RELEASE_CANDIDATE_INTEGRITY_FAILED
```

MCP marks these as errors; CLI exits 2.

### 36.3 Release-candidate denial

Creation from any of these must create zero candidate rows and files:

```text
failed verification
interrupted verification
V1 verification missing interaction record
interaction canonical bytes missing or digest-invalid
application archive source interaction missing or changed
verification currently stale is not itself a denial if the exact durable
verification and bytes remain valid; candidate remains bound to the verified commit
```

The last rule preserves accepted Release Candidate V0 semantics: release construction uses exact durable verification, not mutable current head.

---

## 37. Security and data boundaries

### 37.1 Source confinement

The interaction validator reads only:

```text
application root/capability.toml
application root/interaction.json
```

Reject symlinks and path escapes.

### 37.2 No execution of interaction data

Never:

```text
eval strings
render HTML
load Python from contract
interpret templates
follow URLs
call providers
```

### 37.3 Plain text

All human text is inert data. Future UI must escape it.

### 37.4 No authority claims

The portable developer contract contains no:

```text
team role
membership ID
scope ID
connection grant
approval policy
publisher identity
production binding
```

Runtime owns those later.

### 37.5 No secret-free claim

This task performs no general application source secret scan.

Preserve:

```text
secret_scan = not_performed
```

in candidate handoff.

No provider secrets are supplied to qualification.

### 37.6 Bounded diagnostics

Preserve current stdout/stderr limits and truncation accounting.

Do not include full interaction source in error messages or portable receipts.

---

## 38. Test-owned acceptance applications

Use task-owned ordinary repositories only.

### 38.1 Journey A application

Application:

```text
demo.csv_summary
```

Shape:

```text
resource-only
one CSV resource slot
one optional boolean request field
read_only
no state
no connections
scalar result facts
no artifacts
```

Its interaction contract exercises:

```text
purpose/not_for
one operation
optional safe default
one resource field
fact presentation
boundary
```

### 38.2 Journey B application

Use a materially different but still bounded provider-free shape, for example:

```text
demo.text_report
```

Shape:

```text
one required text field
one optional field
artifact_generation
no state
no connections
one fixed artifact filename
scalar result fact plus artifact
```

Its interaction contract exercises:

```text
required and optional request fields
artifact_result presentation
fixed artifact label
result fact
boundary
```

Do not use accepted Proforma source as mutable qualification input.

### 38.3 Historical V0 fixture

Use one exact old-lock project with no interaction contract to prove:

```text
V0 verification and candidate remain valid
no interaction is synthesized
V0 result schemas remain exact
```

---

## 39. Real coding-harness Journey A — MCP

Use a fresh coding-harness context from outside every project directory.

The harness receives only:

```text
owner/developer request
Capy Developer MCP tools
normal shell/filesystem/Git abilities
```

It must:

```text
call capy_development_start with explicit new-project intent
receive the interaction-aware project template and exact lock
read CAPY.md and DevKit authoring guidance
implement demo.csv_summary
write application tests and conformance fixtures
write interaction.json
commit exact candidate
call capy_development_verify
repair any naturally encountered application or interaction failure
reach PASSED V1 verification
call capy_release_candidate_create
receive V1 .capyrc
restart Capy Developer
inspect the same V1 candidate
finish development terminally
```

Human ceremony target:

```text
manual repository path choice: 0
manual Git init: 0
manual branch/worktree choice: 0
manual DevKit install/version choice: 0
manual interaction schema explanation outside repository/tooling: 0
manual verification stage sequencing: 0
manual candidate packaging: 0
```

Do not add prompt phrases specific to the chosen coding harness beyond the generic task.

---

## 40. Real coding-harness Journey B — JSON CLI

Use a fresh different harness/context and the task-owned artifact-generation project.

Begin with one exact contract defect, such as:

```text
interaction marks a required field optional
or
interaction advertises an artifact absent from result schema
```

The harness must:

```text
prepare the exact existing project through JSON CLI
commit defective candidate
run verification
receive causal interaction-stage failure
create no release candidate
repair only the defect
commit a new candidate
run a new verification
reach PASSED V1 verification
create and inspect V1 candidate
finish session terminally
```

This journey proves that a human-contract failure is actionable and distinct from application execution failure.

---

## 41. Independent copied-byte oracle

Freeze a standard-library oracle before final qualification.

The oracle receives only:

```text
one copied .capyrc file
```

It receives no:

```text
Capy Developer package import
Capy Developer database
Git repository
worktree
verification cache
DevKit cache
Capy runtime source
previous harness conversation
```

For V1 it must verify:

```text
outer canonical ZIP bytes and exact five-member order
manifest and receipt canonical JSON
release-candidate ID and full identity digest
all member digests and sizes
application archive safety
one root capability.toml
one root interaction.json
application descriptor ID/schema
interaction source digest
canonicalization of source interaction JSON
exact equality with application/interaction.json
portable interaction schema exactness
cross-contract structural invariants
V1 verification receipt and eleven passed stages
exact toolchain bundle and contained wheel identity
handoff claims remain unaccepted/uninstalled/unpublished
```

The oracle may share frozen schema constants from evidence preparation, but it must not call production implementation code.

---

## 42. V1 tamper matrix

Reject at least:

```text
outer member removed
outer member added
outer duplicate member
outer member reordered
absolute member path
parent traversal member
backslash member
symlink member
noncanonical ZIP metadata
ZIP comment or extra field
manifest noncanonical JSON
receipt noncanonical JSON
interaction noncanonical outer JSON
manifest schema changed
candidate ID changed
identity digest changed
application archive bytes changed
descriptor bytes changed
interaction source bytes changed inside application archive
outer canonical interaction bytes changed
interaction source digest changed
interaction canonical digest changed
interaction schema changed
interaction application ID changed
operation ID changed
unknown request field inserted
required field weakened
resource count changed
unknown result fact inserted
artifact list changed
verification receipt interaction digest changed
interaction_check stage removed or failed
interaction_preserve stage removed or failed
toolchain bundle changed
contained wheel changed
handoff independent acceptance weakened
handoff interaction status changed to accepted
handoff installation/publication/deployment changed to performed
```

Require all tampered candidates to fail closed.

Do not mutate only database rows for this oracle. It must inspect copied bytes.

---

## 43. Historical regression matrix

Preserve and rerun:

```text
all accepted Capy Developer tests
Foundation existing/new project journeys
Verify V0 valid/invalid/repair behavior
Release Candidate V0 create/inspect/replay/restart behavior
V0 copied-byte oracle
V0 tamper controls
schema-1→4 migration
schema-2→4 migration
schema-3→4 migration
historical exact DevKit resolution
Windows resource-only verification
MCP/JSON CLI semantic parity
```

Protected repositories must have zero changes:

```text
gazeromo/capy-fedex-quote-cleanroom
gazeromo/capy-proforma-invoice
gazeromo/capy-outcome-runtime
accepted watcher application source
```

---

## 44. Cross-platform Stage B qualification

Run the complete Capy Developer suite on:

```text
Ubuntu
macOS
Windows
```

Every platform must prove:

```text
V1 new-project initialization
V1 interaction verification
V1 deterministic candidate construction
V1 candidate inspection
copied-byte V1 oracle
V0 compatibility and migration
MCP/CLI parity
```

Connection-bearing interaction contracts remain outside V0.

No platform exception is allowed for the resource-only and artifact-only acceptance apps.

Add one frozen cross-platform format vector with identical project/source/toolchain/verification/interaction facts and identical member bytes on every operating system. Its V1 manifest bytes, portable receipt bytes, interaction member bytes, outer candidate bytes, release-candidate ID, identity SHA-256, and bundle SHA-256 must be identical on Ubuntu, macOS, and Windows.

Real journey candidates may have different IDs because their durable session and verification identities/timestamps are different. Do not compare unrelated real journeys as though they had identical inputs.

---

## 45. Capy Developer package qualification

Target package:

```text
capy-developer 0.4.0
```

Require:

```text
two clean wheel builds from exact implementation commit
the wheels are byte-identical
fresh offline install with --no-index --no-deps
installed doctor passes
installed CLI V1 Journey B passes
installed MCP V1 Journey A passes
installed V0 candidate inspection passes
package contains exact accepted DevKit V1 authoring bundle
package retains exact historical trusted bundles needed by accepted behavior
no campaign/evidence files leak into installed package except deliberate immutable tool bytes
```

Record exact filename, size, SHA-256, source commit, and build tools.

---

## 46. Independent reviews

Use fresh independent contexts after implementation freeze.

Required review scopes:

### Review A — DevKit schema and validator

Check:

```text
exact source schema
cross-contract requiredness/default/resource/result validation
no domain-specific branches
no runtime dependency
plain-text and path safety
historical helper API unchanged
```

### Review B — DevKit release identity

Check:

```text
wheel/bundle reproducibility
bundle curation
release manifest exactness
historical release immutability
cross-platform evidence
```

### Review C — Capy Developer verification and persistence

Check:

```text
pipeline versioning
schema migration
V0/V1 coexistence
interaction evidence durability
replay/interruption/cleanup
no mutable-worktree trust after verification
```

### Review D — Release candidate V1 format and oracle

Check:

```text
identity completeness
outer canonical bytes
source/canonical interaction equivalence
portable receipt
handoff non-claims
V0 backward compatibility
tamper matrix
```

### Review E — final evidence and closure delta

Check:

```text
exact commits and trees
CI heads
receipt digests
zero-change conditions
merge readiness
no hidden acceptance/runtime claim
```

No unresolved P0-P2 finding may remain. Address actionable P3 findings before acceptance.

---

## 47. Evidence layout

Suggested DevKit evidence:

```text
campaigns/application_interaction_contract_v0/
├── PLAN.md
├── QUALIFICATION.json
├── RELEASE.json
├── ORACLE.json
├── REVIEWS.md
└── CLOSURE.json
```

Suggested Capy Developer evidence:

```text
campaigns/developer_interaction_contract_v0/
├── PLAN.md
├── QUALIFICATION.json
├── JOURNEY-A-MCP.json
├── JOURNEY-B-CLI.json
├── HISTORICAL-V0.json
├── ORACLE.json
├── ORACLE-TAMPER-MATRIX.json
├── PACKAGE-RELEASE.json
├── REVIEWS.md
└── CLOSURE.json
```

The exact filenames may differ, but all required machine facts must be preserved.

Do not place mutable secrets, raw private paths, or provider data in portable evidence.

---

## 48. Merge and closure policy

### 48.1 DevKit

```text
implement on exact branch from current accepted main
freeze implementation commit/tree
run local and three-platform qualification
build exact reproducible wheel and authoring bundle
run independent reviews
record release-binding closure
strict fast-forward to DevKit main
run exact post-merge CI
```

Only after this may Stage B consume the release.

### 48.2 Capy Developer

```text
implement on exact branch from current accepted main
freeze implementation commit/tree
run local and three-platform qualification
run real MCP and CLI journeys
run copied-byte oracle and tamper matrix
build exact reproducible 0.4.0 wheel
run independent reviews
record evidence commit and CI
create closure-only commit
run closure-delta review
strict fast-forward to main
run exact post-merge CI
```

### 48.3 Control repository

At authorization:

```text
record CAPY-DEVELOPER-INTERACTION-CONTRACT-V0 as current work
record both repository branches and explicit two-stage gate
```

At terminal closure:

```text
record exact DevKit and Developer commits, trees, package identities,
qualification, reviews, non-claims, and zero-change conditions
set work/NOW.md back to no authorized successor
```

No deployment is part of closure.

---

## 49. Hard zero-change conditions

Final evidence must prove:

```text
capy-outcome-runtime source changes: 0
production database changes: 0
production release changes: 0
application installation/binding/publication/deployment: 0
provider calls: 0
provider secrets accessed: 0
accepted FedEx repository changes: 0
accepted Proforma repository changes: 0
accepted Watcher repository changes: 0
historical DevKit bytes changed: 0
historical V0 .capyrc format changed: 0
coding-agent-specific core branches: 0
MCP/CLI semantic differences: 0
Luna/model calls in validation: 0
runtime-specific authority fields accepted from developer contract: 0
```

---

## 50. Explicit non-goals

Do not build:

```text
independent application acceptance
runtime import
runtime interaction-contract registry changes
Workbench UI rendering
Luna contract use
application preview
production publication or activation
Personal/Team binding
sharing/update/rollback policy
state migration
multiple application operations
stateful application interaction SDK
semantic connection setup UI
external-effect approval UI
arbitrary HTML/CSS/JavaScript
model-generated interface code
public SDK stability
remote MCP
harness installation
repository-provider provisioning
builder extraction
coding-agent supervision
public marketplace
```

Do not generalize the one-shot portable schema into the stateful application platform.

---

## 51. Stop conditions

Stop and record a truthful blocked outcome if:

```text
current repository truth differs materially from the recorded required bases
and cannot be reconciled without broadening authorization

Stage A cannot be independently accepted

interaction validation requires runtime source or application-specific code

one exact portable application cannot be represented without adding
multiple operations, state, connections, or external effects

new DevKit breaks the accepted capy.script/dev-v0 helper surface

historical trusted DevKit releases cannot remain exact and usable

schema migration loses or reinterprets V0 rows

V0 copied release candidate no longer validates identically

V1 candidate cannot be validated from copied bytes alone

resource/artifact-only interaction flow fails on any required OS

candidate identity omits an interaction/source/toolchain fact that changes
the claim

release candidate creation requires production/runtime authority

independent review finds a material unresolved overclaim, path escape,
identity gap, or backward-compatibility failure
```

Do not bypass a stop condition with a platform skip, hard-coded application exception, or weakened claim.

---

## 52. Acceptance checklist

A strong pass requires all of the following.

### DevKit authoring contract

```text
[ ] interaction.json source schema frozen
[ ] one portable operation only
[ ] request fields exactly cover executable scalar leaves
[ ] effective requiredness validated
[ ] safe defaults validated
[ ] resource fields exactly match descriptor slots/counts
[ ] result facts and artifacts validated
[ ] read-only/artifact-generation constraints validated
[ ] state/connections/external effects fail truthfully
[ ] canonical projection deterministic
[ ] application source never mutated by validator
```

### DevKit release

```text
[ ] new exact source commit/tree
[ ] new exact release-binding commit
[ ] new wheel reproducible
[ ] new authoring bundle reproducible
[ ] bundle schema V1
[ ] interaction schema bound in release manifest
[ ] fresh offline install
[ ] installed interaction-check
[ ] Ubuntu/macOS/Windows pass
[ ] historical release bytes unchanged
[ ] independent reviews accepted
```

### Capy Developer toolchain

```text
[ ] lock V1 supported
[ ] V0/legacy locks preserved
[ ] exact accepted DevKit V1 embedded/trusted
[ ] new projects use V1
[ ] old projects not silently upgraded
```

### Verification

```text
[ ] pipeline V1 identity explicit
[ ] eleven exact stages
[ ] interaction failure causal
[ ] canonical interaction bytes preserved content-addressed
[ ] source/canonical digests durable
[ ] result V1 path-free interaction projection
[ ] V0 result unchanged
[ ] restart/replay/interruption/cleanup pass
```

### Release Candidate

```text
[ ] manifest V1
[ ] portable receipt V1
[ ] exact five-member candidate
[ ] source interaction inside application archive
[ ] canonical interaction outer member
[ ] exact source/canonical equivalence
[ ] identity includes interaction facts
[ ] deterministic double build
[ ] copied-byte oracle passes
[ ] tamper matrix rejects all cases
[ ] V0 candidate remains supported
```

### Developer experience

```text
[ ] real MCP Journey A
[ ] real JSON CLI Journey B
[ ] unrelated-directory start
[ ] zero human repository/toolchain/verification/package ceremony
[ ] causal contract repair journey
[ ] session terminalization
```

### Package and closure

```text
[ ] full local suite
[ ] full Ubuntu suite
[ ] full macOS suite
[ ] full Windows suite
[ ] Capy Developer 0.4.0 reproducible wheel
[ ] fresh offline installation
[ ] installed CLI/MCP smoke
[ ] independent implementation/evidence/closure reviews
[ ] strict fast-forward merges
[ ] post-merge CI
[ ] control closure
[ ] zero deployment/production effect
```

---

## 53. Recommended implementation sequence

### Phase 0 — current-truth preflight

```text
inspect capy-project current state
inspect current DevKit main/release bytes
inspect current Capy Developer main and schemas
inspect current runtime interaction contract read-only
confirm protected application heads
record exact starting facts
```

### Phase 1 — authorize and freeze Stage A

```text
record task in control
create DevKit branch
copy this plan into campaign source
freeze interaction schema and truth-table tests
```

### Phase 2 — implement DevKit validator

```text
source parser
schema exactness
cross-contract validation
canonical JSON
stable diagnostics
interaction-check command
```

### Phase 3 — update template and authoring product

```text
interaction.json template
README/AGENTS/contract documentation
bundle V1 productization
```

### Phase 4 — qualify and accept DevKit

```text
full tests
hidden mutation oracle
three-platform CI
reproducible wheel/bundle
offline install
independent reviews
release binding
strict merge
post-merge CI
```

### Phase 5 — begin Stage B from exact accepted truth

```text
record exact Stage A release identities
create Capy Developer branch from required/current accepted main
freeze schema-3 migration fixture and V0 candidate fixture
```

### Phase 6 — toolchain and database migration

```text
lock V1
trusted release metadata
embedded bundle
schema 3→4
pipeline and candidate format identities
interaction evidence tables
```

### Phase 7 — verification V1

```text
interaction_check stage
canonical preservation
result/receipt V1
replay/recovery/cleanup
V0 compatibility
```

### Phase 8 — release candidate V1

```text
five-member format
manifest/identity V1
source/canonical interaction cross-check
inspect/validate dispatch by format version
V0 preservation
```

### Phase 9 — focused and migration tests

```text
truth tables
schema migrations
V0/V1 coexistence
candidate integrity
cross-platform cases
```

### Phase 10 — real harness journeys

```text
MCP CSV-summary journey
JSON CLI artifact-report failure/repair journey
historical V0 journey
```

### Phase 11 — frozen independent oracle

```text
valid copied V1 candidate
full tamper matrix
valid copied V0 regression candidate
```

### Phase 12 — package and review

```text
0.4.0 reproducible wheel
offline install
installed smoke
independent reviews
```

### Phase 13 — evidence and closure

```text
qualification receipts
evidence-head CI
closure-delta review
strict fast-forward merge
post-merge CI
control closure
```

---

## 54. Source basis and required archaeology

This plan is grounded in the following current accepted sources and should be copied into the active campaign before implementation:

```text
gazeromo/capy-project
  work/NOW.md at control main a87513aab945602cca15df4340234d459f2f401a
  work/done/CAPY-DEVELOPER-RELEASE-CANDIDATE-V0.md

gazeromo/capy-developer
  main 5a950b1a1b73ce6f99018261f0846bda2f3a5fea
  README.md
  docs/DIRECTION.md
  src/capy_developer/database.py
  src/capy_developer/toolchain.py
  src/capy_developer/verification.py
  src/capy_developer/release_candidate.py
  src/capy_developer/cli.py
  src/capy_developer/mcp.py
  campaigns/developer_verify_v0/CLOSURE.json
  campaigns/developer_release_candidate_v0/CLOSURE.json

gazeromo/capy-script-devkit
  main 8c4fec7f814a62ded441786b8eba28af14d1aa2d
  README.md
  SUPPORTED-V0.md
  CONTRACT.md
  AGENTS.md
  docs/PRODUCTIZATION.md
  src/capy_script/cli.py
  src/capy_script/descriptor.py
  src/capy_script/runner.py
  src/capy_script/template/python-basic/

gazeromo/capy-outcome-runtime — read only
  main 61a71a1067183343504305337128ca0af083542f
  src/capy_outcome_runtime/interaction_contracts.py
  src/capy_outcome_runtime/application_profiles.py
  src/capy_outcome_runtime/application_operations.py
  src/capy_outcome_runtime/application_interfaces.py
```

The runtime sources are evidence for categories and trust boundaries, not code to copy wholesale. Current machine/repository truth at implementation time outranks the exact commit references above; material divergence requires recording and evaluating a deviation before changes begin.

---

## 55. Completion report

The final Codex report must state exact:

```text
DevKit base
DevKit implementation commit/tree
DevKit release-binding/closure commit
DevKit wheel filename/digest/size
DevKit authoring-bundle digest/size
DevKit schemas
DevKit cross-platform test counts and CI IDs

Capy Developer base
implementation commit/tree
evidence commit/tree
closure/main commit
branch and remote-visible head
SQLite schema version
verification pipeline/result schemas
release candidate manifest/result/receipt schemas
0.4.0 wheel filename/digest/size
local and per-platform test counts
Journey A/B identities
V0 regression candidate identity
V1 candidate ID/identity/manifest/bundle digests and size
oracle and tamper counts
review verdicts
post-merge CI
control closure commit
```

It must also state exact zero counts for:

```text
runtime changes
production changes
protected application changes
provider calls
provider secrets
acceptance/publication/installation/binding/deployment
historical release mutation
Codex-specific core behavior
MCP/CLI semantic differences
```

If not accepted, report:

```text
latest exact candidate
which stage stopped
which claim is blocked
what remains unchanged
what owner decision is required
```

Do not call a structurally verified interaction contract independently accepted.

---

## 56. Final directive

Build the smallest complete developer-side human-contract boundary:

```text
ordinary application source
+ capability.toml executable truth
+ interaction.json human meaning
+ exact interaction-aware DevKit
+ deterministic cross-contract verification
+ exact canonical interaction evidence
+ deterministic release candidate V1
```

Preserve the trust ladder:

```text
DEVELOPED
  source and human contract exist

VERIFIED
  exact executable and structural interaction contracts passed

RELEASE CANDIDATE
  exact bytes and evidence are portable

ACCEPTED
  not part of this task

INSTALLED / ACTIVATED
  not part of this task
```

The task passes only when a fresh harness can create a provider-free portable app whose executable behavior and human-facing contract travel together as one exact, independently inspectable, still-unaccepted `.capyrc`—without changing runtime or production.
