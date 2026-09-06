# Bounded capability-probe review

Reviewer: native gpt-6-astra / medium, fresh context, task scope probe_review.
This is preparation review, not either final product completion gate.

Initial independent controls: initialize, single-tool discovery, accepted-core
fixed search, receipt plus seven negative controls (start, alternate query, extra
limit, null params, resources/read, array message, non-string method). Pass;
only disposable-root catalog/directories/receipt written. No production access.

Minor finding: rejected requests lost JSON-RPC request IDs. Parent preserved only
string/integer IDs and added assertions. Fresh follow-up: focused test passes;
six independent controls confirm valid-ID correlation and no ID carry-over for
malformed, absent or boolean IDs. Original finding retained here.

Final qualification: synthetic probe preparation verified, no remaining material
findings. Actual desktop launch/MCP attachment unproven; no product acceptance.
Both reviewer passes use temporary roots and leave desktop-state untouched.

No product-worker delegation occurred before the desktop proof. Usage telemetry
was not exposed; no aggregate token estimate is claimed.

## Owner attempt 1 and bounded repair

Owner reports correct workspace and actual MCP call reaching the probe, but
-32602 rejection. Original envelope was not retained; do not claim its exact
shape. Whole-envelope equality rejects permitted `_meta`; advertised optional
limit also exceeded probe policy. Revision 2 strips only object-valued `_meta`
before core dispatch and advertises the exact allowed query. Two focused tests
pass, including metadata canaries and unchanged negative controls. This repair
is parent-verified; prior independent review applies to revision 1 only.
MCP metadata reference: https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/progress
Actual desktop successful core invocation remains pending a fresh conversation.
