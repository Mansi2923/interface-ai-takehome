# Design Write-Up

## 1. Architecture

Four stages, one shared execution layer:

`discovery.py` (LLM decides) → `Capability` artifact (`core/schemas.py`)
→ `replay.py` (no LLM, deterministic) → `escalation.py` (pause/handoff on
either path).

Discovery and replay share `core/locators.py` (locator resolution) and
`perception.py` (reading the page) rather than each having their own way
to find/read elements. This matters: the whole premise of the system is
that what gets *recorded* during discovery must be *exactly* what gets
*executed* during replay, not a re-implementation of similar-but-different
logic. If discovery clicked a button via role+name, replay must resolve
that same locator string the same way — one resolver, two callers.

Single-process, synchronous, local-file storage (JSON artifacts, JSONL
event logs). No queue, no service boundaries, no database. This is a
deliberate simplicity call: the assignment explicitly says not to reward
"scaling infrastructure," and a queue/service split would add real
complexity (serialization boundaries, retry semantics, deployment) without
demonstrating anything about the actual hard problems here (locator
robustness, error taxonomy, control transfer). The interesting seams
(capability schema, locator resolver, replay executor, guardrail checks)
are already separate modules with clear interfaces, so splitting into
services later is a deployment change, not a redesign.

Target surface: a self-built mock "legacy" bank admin console
(`app/server.py`) rather than a public site. Reasoning: public demo sites
have unpredictable DOMs I can't control and can't safely reproduce error
states on demand; a real bank system isn't available (and shouldn't be
sought). The mock app is server-rendered HTML with nested tables and no
test IDs (reproducing the "no clean DOM" reality described in the brief),
and it has reproducible, deterministic error states (member not found,
validation error, permission denial, a randomly-or-forcibly-triggered
session interstitial) — which is what let me actually prove the error
handling in `/evidence/`, not just describe it.

## 2. Artifact schema

A `Capability` is meant to be read by two audiences: a human reviewing it
before approving unattended replay, and an AI agent that needs to know
how to call it without reading the step list. The schema is built around
that:

- `input_params` / `outputs` are the *stable public contract* — an agent
  calling this capability only needs these two lists plus `description`.
- `steps` is the *implementation* — how the contract gets fulfilled. An
  agent invoking the capability never looks at this; a human reviewing it
  does.
- Every `Step` carries `locator: LocatorStrategy`, which is a **ranked
  list** (`primary` + `fallbacks`), not a single selector — see section 4
  for why. Each also carries its own `risk` level and `on_failure`
  policy, so guardrails and error handling operate per-action, not just
  per-capability.
- `checkpoint` is separate from the last step. A flow can execute every
  step "successfully" (no exception) and still not have actually reached
  the claimed end state — the checkpoint is an explicit assertion checked
  independently, so replay never just assumes the last click worked.
- `version`, `tenant_scope`, `base_capability_id` support reuse across
  tenants without re-recording (section 4).
- `created_by` distinguishes `llm_discovery` from `human_authored` —
  useful for review/audit and for a future confidence-scoring stretch
  goal.

Implementation choice: stdlib `dataclasses`, not pydantic. Both are
"typed, serializable" in the sense the brief asks for; dataclasses avoid
one dependency and are trivial to review line-by-line against this
document. The trade-off — no runtime validation on deserialize — is a
real one I'd revisit before using this for untrusted input (see section 7).

## 3. Determinism & error handling

Determinism comes from three things: (1) replay never calls the LLM —
every locator, value, and branch is fully determined by the saved
`Capability` plus the caller's params; (2) locator resolution
(`core/locators.py`) is a deterministic ranked search — try `primary`,
then each fallback in order, take the first that resolves to exactly one
visible element; (3) `{{param}}` template substitution is a plain string
replace, not model-interpreted.

Error taxonomy, enforced in `replay.py`:

- **Business outcome** — the app is telling us something real and
  expected that isn't the happy path. Detected via a `Result code: XXXX`
  marker the mock app's error pages render (standing in for whatever
  consistent signal a real app exposes — an error banner, a known status
  code). This returns `ReplayOutcome.BUSINESS_OUTCOME` with the code —
  never treated as a crash. This is the distinction the brief calls out
  as the most common design mistake, and it's the first thing I tested
  (see `/evidence/` and `tests/test_replay_smoke.py`).
- **Recoverable** — a known interstitial (session-timeout nag). Detected
  and dismissed automatically before resolving the intended locator, then
  the original step proceeds. Not surfaced to the caller at all.
- **Hard failure** — locator resolution fails, or the final checkpoint
  never matches. Before giving up, the step is escalated to a human on
  the *same* live session (section 5); only if that also fails
  (timeout / no response) does replay return `HARD_FAILURE`, with the
  failed step id, what was expected, what was actually observed on the
  page, and a screenshot — enough to debug without re-running.

Secondary: UI drift is handled by the same fallback-locator mechanism —
if a tenant reskins a button's CSS but keeps its accessible name, the
`role=...[name=...]` primary locator still resolves. A drift that changes
the *label itself* is not something string fallbacks can survive; that's
a genuine capability-needs-updating case, which is what `version` and
periodic replay-success monitoring (a cut, section 7) are for.

**A concrete example from testing.** The first discovery run produced an
`extract` step whose locator searched for a table cell *by the exact
dollar value it was trying to read* (`role=cell[name='$4820.11']`) — a
locator that only worked because it happened to match the one member it
was recorded against. Replaying the same capability against a different
member (`67890`, balance `$150.00`) correctly failed at that step with a
clear `HARD_FAILURE` (failed step, expected vs. observed, a screenshot) —
exactly the debuggable failure the design is meant to produce. The fix
was replacing the value-based locator with a structural one
(`css=table tr:nth-child(3) td:nth-child(2)`, i.e. "3rd row of the detail
table," independent of the value inside it). Replaying against both
members afterward correctly returned their distinct balances
($4820.11 and $150.00), confirming the capability generalizes. This is
the kind of artifact defect the schema's `reasoning` field on each
locator is meant to force a reviewer to catch before approving a
capability for unattended use — in this case, discovery's own choice of
locator needed a second look.

## 4. Heterogeneity & multi-tenant

**Surface abstraction.** The seam between "how we perceive/act on a
surface" and "the recorded flow" is exactly `perception.py` +
`core/locators.py`. The `Capability`/`Step` schema never mentions
Playwright, DOM, or a browser at all — a `Step` says "click the element
with role=button, name='Search'," which is a statement about the
**accessibility tree**, not about HTML. That's the same abstraction
available on native desktop apps via OS accessibility APIs (the glossary
notes this explicitly). Extending to desktop would mean writing a new
`perception_desktop.py` / `locators_desktop.py` pair that resolves the
same `role=/name=` locator strings against an OS accessibility tree
instead of a browser page — the schema, replay engine, guardrails, and
escalation model would not change. A legacy web app with framesets is
actually the *easy* case here: it's still a browser accessibility tree,
just a messier one, which is exactly what the ranked-fallback locator
strategy exists for.

**Multi-tenant reuse.** `Capability.tenant_scope` ("base" or a tenant id)
plus `base_capability_id` model this directly: a capability recorded once
against a vendor product is `tenant_scope="base"`. A tenant whose
instance differs slightly (different branding, a relabeled button, an
extra confirmation step) gets a new `Capability` with
`tenant_scope=<tenant_id>` and `base_capability_id` pointing at the base
one — an override, not a from-scratch re-record. A replay caller resolves
"give me capability X for tenant Y" by looking for a tenant-scoped
override first, falling back to the base capability if none exists. This
project doesn't implement that resolution layer (explicitly out of scope
per section 3.7 — "design, not necessarily build"), but the schema
already has the fields it needs.

**Drift detection.** The realistic signal is aggregate replay outcomes,
not a diffing tool: if a tenant-scoped capability starts returning
`HARD_FAILURE` at a meaningfully higher rate than its base capability (or
than its own history), that's the trigger to flag it for human review —
this is exactly what the optional "confidence & approval" stretch goal
would formalize (draft → approved, scored by replay reliability). I did
not build this; `evidence/` per-run logs are the raw material it would
consume.

## 5. Escalation & handoff

The control-transfer model, in full, lives in `escalation.py`'s
docstring; summary here:

The browser runs **non-headless** by default. That one choice is what
makes the handoff real instead of simulated — the "live session" a human
takes over is the literal visible window the automation was just driving:
same cookies, same in-progress form, same page. There's no second session
to keep in sync.

Control transfer is a tiny per-run state file (`control.json`) plus a
blocking wait: automation hits a stuck condition → writes an
`InterventionRequest` (reason, step, page URL, screenshot) →
`control.json` flips to `{"owner": "human"}` → automation blocks, polling.
A human (via `scripts/run_operator.py`, deliberately minimal per the
assignment's scope note — a full co-browsing console is out of scope)
reads the request, does whatever's needed *in that open window*, then
resolves it: their note is captured as evidence and `control.json` flips
back to `{"owner": "automation"}`. The blocked call wakes up and retries
the step that triggered escalation.

This fires from two places: `discovery.py` when the model explicitly
calls an `escalate` tool (it's uncertain or about to do something risky),
and `replay.py` when a step fails and isn't a recognized business
outcome — replay tries a human handoff before giving up and returning
`HARD_FAILURE`.

Limits: a single blocking `time.sleep` poll loop, one intervention at a
time, no notification system (a human has to know to check) — all
reasonable for the scope, all called out in section 7.

## 6. Safety

Two independent, always-on checks in `core/guardrails.py`, enforced at
the point of action (not just declared and trusted):

- **Allowlist**: every URL navigation and every action type is checked
  against an explicit allowlist before it executes, in both discovery and
  replay. A capability also carries its own `allowed_domains`, so a saved
  artifact can't later be replayed against a different domain than the
  one it was recorded and reviewed against.
- **Risk classification**: every `Step` declares `SAFE` / `REVERSIBLE` /
  `IRREVERSIBLE`. `IRREVERSIBLE` steps aren't blocked at replay time — a
  saved capability has, by definition, already been through a discovery
  run and is meant to be reused — but they're the load-bearing thing a
  human reviewer should scrutinize before approving a capability for
  unattended production replay. That approval gate (draft → approved) is
  a stretch goal I didn't build; today, review is manual, via reading the
  artifact JSON.

**Data handling.** `core/logging_utils.py` redacts any field whose key
matches a sensitive-name pattern (password, token, ssn, credential,
secret, api_key, cookie, auth) before it's ever written to disk, in every
event, in both discovery and replay logs. This is a narrow, explicit
list rather than a value-shape heuristic — see section 7 for the
trade-off. No credentials are stored anywhere in this project; the mock
app has no login.

## 7. Cuts

Left out deliberately, in priority order of what I'd build next:

1. **Redaction by value shape, not just key name.** Today a
   sensitive-looking value under an innocuously-named key (e.g. a full
   account number in a field called `notes`) would not be caught. Adding
   pattern-based scanning (SSN/card-number shapes) on top of the
   key-based check is the natural next step.
2. **Approval workflow gating unattended replay** (stretch goal, not
   built): score a capability by observed replay success rate, require a
   human to flip `draft → approved` before it can run without a human
   watching.
3. **Multi-tenant resolution layer.** The schema supports it
   (`tenant_scope`/`base_capability_id`); the lookup logic that picks a
   tenant override vs. the base capability at replay time isn't built.
4. **Runtime validation on artifact deserialize.** Dropping pydantic
   removed a dependency but also removed free schema validation on
   `Capability.from_json` — a malformed artifact currently fails with a
   raw `KeyError` rather than a clear validation error. Worth adding back
   narrowly (a `validate()` method) without pulling in the full
   dependency.
5. **Notification for pending escalations.** Right now a human has to
   know to run `run_operator.py` and check; a real system would push
   (Slack, email, a queue) rather than rely on polling awareness.
6. **Multi-run stability signal** (stretch goal, not built): replay N
   times, report a flakiness rate per capability.

What I did *not* cut: the artifact schema, the locator-resolution/replay
determinism, and the escalation mechanism are all real and tested end to
end — see `/evidence/` and `tests/test_replay_smoke.py`, which exercises
both a full success path and the `MEMBER_NOT_FOUND` business-outcome path
against the live mock app.
