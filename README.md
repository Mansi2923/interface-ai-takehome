# Computer-Use Automation System

A small, real implementation of: goal → LLM-driven discovery run → saved
capability artifact → deterministic replay → human escalation, against a
mock legacy bank admin console. Built for the interface.ai take-home
assignment. See `REPORT.md` for the design write-up.

## What's here

```
app/server.py       mock "legacy" bank admin console (the target surface)
core/schemas.py     the Capability artifact schema + replay result contract
core/guardrails.py  allowlist enforcement + risk policy
core/locators.py    ranked-fallback locator resolution (role/name -> text -> css)
core/logging_utils.py   structured, redacting event logger
perception.py       accessibility-tree snapshot for the LLM
discovery.py         the LLM-driven observe/decide/act loop
replay.py            deterministic replay engine + error taxonomy
escalation.py        human-in-the-loop pause/handoff/resume
scripts/run_agent.py     CLI: run discovery, save an artifact
scripts/run_replay.py    CLI: replay a saved artifact
scripts/run_operator.py  CLI: minimal operator console for escalations
tests/test_replay_smoke.py  end-to-end replay test (success + error case)
artifacts/capabilities/  saved capability JSON files
evidence/                per-run logs, screenshots
```

## Setup

Requires Python 3.11+.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

export ANTHROPIC_API_KEY=sk-ant-...   # required for discovery only
```

Start the mock target app in one terminal:

```bash
python3 app/server.py
# serves http://127.0.0.1:5055
```

## Demo path

**1. Run discovery** (this is the real LLM-driven run; it opens a visible
Chromium window so you can watch it work, and so a human can take over
mid-run if needed):

```bash
python3 scripts/run_agent.py \
  --goal "Look up member 12345 and read their savings balance" \
  --target http://127.0.0.1:5055 \
  --domain 127.0.0.1
```

This saves `artifacts/capabilities/<name>.json` and writes logs +
screenshots to `evidence/discovery-<timestamp>/`.

**2. Replay the saved artifact**, no LLM involved:

```bash
python3 scripts/run_replay.py \
  --artifact "artifacts/capabilities/Lookup_Member_Balance.json" \
  --param member_id=12345
```

**3. Replay against a business-outcome case** (to see error handling,
not a crash):

```bash
python3 scripts/run_replay.py \
  --artifact "artifacts/capabilities/Lookup_Member_Balance.json" \
  --param member_id=00000
```
Expect `"outcome": "business_outcome", "business_outcome_code": "MEMBER_NOT_FOUND"`.

**4. Trigger escalation.** If a replay step fails in a way that isn't a
known business outcome, it pauses and writes
`evidence/<run>/intervention.json`. In a second terminal:

```bash
python3 scripts/run_operator.py --run-dir evidence/<run-id>
```
This shows the pending request; after you perform whatever's needed in
the still-open browser window and describe what you did, it hands
control back and the run resumes.

## Running without live services

Set `HEADLESS=1` to run Chromium headless (useful for CI or a sandbox
with no display). Escalation still works — the intervention/control-file
protocol doesn't depend on a visible window — but a human can't literally
click in the same session in that mode, since there's nothing rendered.

## Running the test

```bash
python3 app/server.py &
HEADLESS=1 python3 tests/test_replay_smoke.py
```
Exercises both the success path and the `MEMBER_NOT_FOUND` business-outcome
path against the live mock app.
