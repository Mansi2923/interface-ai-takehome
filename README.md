# CoreServ Capability Recorder

A working answer to a specific problem: **an AI agent can't call an API on
software that doesn't have one.** A lot of bank back-office software falls
into that bucket — old, server-rendered, click-only. This project watches
an LLM operate one of those screens *once*, saves exactly what it did as a
reusable "capability," and from then on replays that capability
deterministically — no model involved, no re-reasoning about the UI. If
something goes wrong that the recording didn't anticipate, it hands
control to a human on the *same* browser session rather than failing silently.

Built for the interface.ai take-home assignment. `REPORT.md` has the full
design write-up and reasoning; this file is just setup and demo steps.

## What's here
app/server.py mock "legacy" bank admin console (the target surface)
core/schemas.py the Capability artifact schema + replay result contract
core/guardrails.py allowlist enforcement + risk policy
core/locators.py ranked-fallback locator resolution (role/name -> text -> css)
core/logging_utils.py structured, redacting event logger
perception.py accessibility-tree snapshot for the LLM
discovery.py the LLM-driven observe/decide/act loop
replay.py deterministic replay engine + error taxonomy
escalation.py human-in-the-loop pause/handoff/resume
scripts/run_agent.py CLI: run discovery, save an artifact
scripts/run_replay.py CLI: replay a saved artifact
scripts/run_operator.py CLI: minimal operator console for escalations
tests/test_replay_smoke.py end-to-end replay test (success + error case)
artifacts/capabilities/ saved capability JSON files
evidence/ per-run logs, screenshots

## Setup

Requires Python 3.9+ (tested on 3.9; nothing here needs anything newer).

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

You'll need your own Anthropic API key for the discovery step (get one at
console.anthropic.com):
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**You need two terminals running at once** for everything below — one for
the mock app, one for running commands. Both need the venv activated
separately (`source venv/bin/activate` in each).

**Terminal 1** — start the mock target app and leave it running:
```bash
python3 app/server.py
# serves http://127.0.0.1:5055
```

## Demo path (Terminal 2)

**1. Run discovery.** This is the real LLM-driven run — it opens a
visible Chromium window so you can watch it work, and so a human can take
over mid-run if needed:
```bash
python3 scripts/run_agent.py \
  --goal "Search for a member using the member ID field, then extract and report their savings balance from the detail page. Treat the member ID as a parameter, not a fixed value." \
  --target http://127.0.0.1:5055 \
  --domain 127.0.0.1
```
This saves `artifacts/capabilities/<name>.json` and writes logs +
screenshots to `evidence/discovery-<timestamp>/`. Check the terminal's
final summary line for the exact filename it chose — the model names the
capability itself, so it won't always be the same name run to run.

**2. Replay the saved artifact** with a real member ID, no LLM involved:
```bash
python3 scripts/run_replay.py \
  --artifact "artifacts/capabilities/<name-from-step-1>.json" \
  --param member_id=12345
```
Expect `"outcome": "success"` with a `savings_balance` value in `outputs`.

**3. Replay against a *different* member** to confirm it's genuinely
parameterized, not a recording of one specific lookup:
```bash
python3 scripts/run_replay.py \
  --artifact "artifacts/capabilities/<name-from-step-1>.json" \
  --param member_id=67890
```
You should get a **different** `savings_balance` back. If both runs
return the same value, the capability isn't actually reading the caller's
`member_id` — worth checking the artifact's `extract` step locator.

**4. Replay a business-outcome case** (to see error handling, not a crash):
```bash
python3 scripts/run_replay.py \
  --artifact "artifacts/capabilities/<name-from-step-1>.json" \
  --param member_id=00000
```
Expect `"outcome": "business_outcome", "business_outcome_code": "MEMBER_NOT_FOUND"`.

**5. Trigger escalation.** If a replay step fails in a way that isn't a
known business outcome, it pauses and writes `evidence/<run>/intervention.json`,
and waits up to 2 minutes for a human. In a third terminal:
```bash
python3 scripts/run_operator.py --run-dir evidence/<run-id>
```
This shows the pending request; after you perform whatever's needed in
the still-open browser window and describe what you did, it hands
control back and the run resumes. If no one responds in time, replay
returns a `HARD_FAILURE` with the failure detail and a screenshot instead
— that's expected behavior, not a bug, if you don't run the operator
console in time.

## Running without a visible browser

Set `HEADLESS=1` to run Chromium headless (useful for CI or a machine
with no display):
```bash
HEADLESS=1 python3 scripts/run_replay.py --artifact "..." --param member_id=12345
```
Escalation still works in this mode — the intervention/control-file
protocol doesn't depend on a visible window — but a human can't literally
click in the same session, since nothing is rendered.

## Running the automated test

```bash
python3 app/server.py &
HEADLESS=1 python3 tests/test_replay_smoke.py
```
Exercises both the success path and the `MEMBER_NOT_FOUND` business-outcome
path against the live mock app, using a hand-built capability (no LLM
call needed for this one — good for a quick sanity check that the core
plumbing works before running the real thing).

## Common setup issues

- **`ModuleNotFoundError`** — almost always means the venv isn't active
  in that terminal. Check your prompt starts with `(venv)`; if not, run
  `source venv/bin/activate` again (it's per-terminal, not global).
- **`Executable doesn't exist at .../Chromium.app`** — you installed the
  `playwright` Python package but not the browser binary itself. Run
  `playwright install chromium`.
- **`ERR_CONNECTION_REFUSED`** on replay/discovery — Terminal 1's Flask
  app isn't running. Check it didn't get closed, and that
  `curl http://127.0.0.1:5055/` returns HTML.
- **`anthropic.BadRequestError` about model not found** — check
  `core/constants.py`'s `DISCOVERY_MODEL` matches a currently valid
  Claude API model string (e.g. `claude-sonnet-5`).
