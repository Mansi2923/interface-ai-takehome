"""
Human-in-the-loop escalation and handoff.

The control-transfer model (see REPORT.md section 5 for full reasoning):

The automation runs the browser NON-HEADLESS. That single choice is what
makes the handoff real rather than simulated: the "live session" a human
takes over is the literal visible browser window the automation was just
driving -- same cookies, same page, same in-progress form state. There is
no second session to keep in sync and no re-login.

The control-transfer protocol is a tiny state file per run
(evidence/<run_id>/control.json) plus a blocking wait:

  1. Automation hits a stuck/risky condition -> writes an
     InterventionRequest (reason, step, screenshot, page URL) to
     intervention.json, sets control.json to {"owner": "human"}, and
     BLOCKS, polling control.json.
  2. A human operator (in this project: scripts/run_operator.py, a
     deliberately minimal/mocked console per the assignment's scope note)
     sees the pending request, reads the context, and performs whatever
     manual steps are needed directly in the open browser window.
  3. The operator then runs the CLI's "resume" action, which records what
     they did (a free-text note, captured as evidence) and flips
     control.json to {"owner": "automation"}.
  4. The blocked automation wakes up, logs the handback, and continues
     from the current page state (or a specified resume step).

This is intentionally minimal (a full real-time co-browsing console is
explicitly out of scope) but the mechanism itself -- pause, cede control
of the SAME session, signal resume, capture what the human did -- is
real, not stubbed.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime, timezone


@dataclass
class InterventionRequest:
    request_id: str
    run_id: str
    capability_or_goal: str
    step_id: str | None
    reason: str
    page_url: str
    screenshot_path: str | None
    created_at: str


class ControlHandoff:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.control_path = run_dir / "control.json"
        self.intervention_path = run_dir / "intervention.json"
        self._set_owner("automation")

    def _set_owner(self, owner: str):
        self.control_path.write_text(json.dumps({"owner": owner, "ts": datetime.now(timezone.utc).isoformat()}))

    def _owner(self) -> str:
        if not self.control_path.exists():
            return "automation"
        return json.loads(self.control_path.read_text())["owner"]

    def request_intervention(self, logger, page, reason: str, capability_or_goal: str,
                              step_id: str | None, poll_seconds: float = 2.0, timeout_seconds: float = 600) -> dict:
        """Pauses the automation and blocks until a human hands control back.
        Returns the operator's resolution note. Raises TimeoutError if no
        human responds within timeout_seconds (a hard failure the caller
        must surface, not silently continue past)."""
        screenshot_path = None
        try:
            png = page.screenshot()
            screenshot_path = str(self.run_dir / "escalation_screenshot.png")
            Path(screenshot_path).write_bytes(png)
        except Exception:
            pass  # best-effort; a missing screenshot shouldn't block the escalation itself

        request = InterventionRequest(
            request_id=f"esc-{int(time.time())}",
            run_id=self.run_dir.name,
            capability_or_goal=capability_or_goal,
            step_id=step_id,
            reason=reason,
            page_url=page.url,
            screenshot_path=screenshot_path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.intervention_path.write_text(json.dumps(asdict(request), indent=2))
        self._set_owner("human")
        logger.log("escalation_requested", reason=reason, step_id=step_id, page_url=page.url)

        waited = 0.0
        while self._owner() == "human":
            time.sleep(poll_seconds)
            waited += poll_seconds
            if waited >= timeout_seconds:
                logger.log("escalation_timeout", waited_seconds=waited)
                raise TimeoutError(f"No human resumed control within {timeout_seconds}s")

        resolution_path = self.run_dir / "resolution.json"
        resolution = json.loads(resolution_path.read_text()) if resolution_path.exists() else {"note": ""}
        logger.log("escalation_resolved", operator_note=resolution.get("note", ""))
        return resolution


def operator_resume(run_dir: Path, note: str):
    """Called by the operator console to hand control back. Records what
    the human did, then flips ownership so the blocked automation resumes."""
    (run_dir / "resolution.json").write_text(json.dumps({
        "note": note, "resumed_at": datetime.now(timezone.utc).isoformat()
    }))
    (run_dir / "control.json").write_text(json.dumps({
        "owner": "automation", "ts": datetime.now(timezone.utc).isoformat()
    }))
