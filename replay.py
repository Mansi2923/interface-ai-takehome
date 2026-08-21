"""
Deterministic replay -- the path an AI agent triggers in production.

No LLM decisions here. Every step's locator, value, and control flow is
fully determined by the saved Capability + the caller's input params.

Error taxonomy (see REPORT.md section 3 for full reasoning):

  BUSINESS_OUTCOME  -- the app told us something legitimate and expected
                       that isn't the happy path ("no such member",
                       "validation error", "permission denied"). Detected
                       via a `Result code: XXXX` marker this app's error
                       pages render (a stand-in for whatever consistent
                       signal a real app's error states expose -- an error
                       banner's text, an HTTP status, a known dialog).
                       This is NOT a failure -- the caller needs this
                       result, not a stack trace.

  RECOVERABLE        -- a known, expected interstitial (session-timeout
                       nag) that isn't the goal but also isn't an error.
                       Detected and dismissed automatically, then the
                       original step is retried once.

  HARD_FAILURE       -- the locator couldn't be resolved, or the
                       checkpoint never matched. Before giving up, we
                       escalate to a human on the SAME live session; only
                       if that also fails (timeout / no response) do we
                       return HARD_FAILURE with enough detail (which step,
                       what was expected, what was observed, a screenshot)
                       to debug without re-running anything.
"""

from __future__ import annotations
import os
import re
import time
from pathlib import Path

# Non-headless by default -- this is what makes the human handoff real (see
# escalation.py). Override with HEADLESS=1 for CI / sandboxes with no
# display; escalation still works there via the intervention/control files,
# it just can't show a human a literal window to click in.
from core.constants import HEADLESS

from playwright.sync_api import sync_playwright

from core.schemas import Capability, ActionType, ReplayOutcome, ReplayResult
from core.guardrails import AllowlistPolicy, enforce_url, enforce_action_type, GuardrailViolation
from core.locators import resolve, LocatorResolutionError
from core.logging_utils import EvidenceLogger
from perception import full_text
from escalation import ControlHandoff

RESULT_CODE_RE = re.compile(r"Result code:\s*([A-Z_]+)")
INTERSTITIAL_BUTTON_NAME = "Extend Session"


def _substitute(value: str | None, params: dict) -> str | None:
    if value is None:
        return None
    for key, val in params.items():
        value = value.replace("{{" + key + "}}", str(val))
    return value


def _dismiss_interstitial_if_present(page) -> bool:
    btn = page.get_by_role("button", name=INTERSTITIAL_BUTTON_NAME)
    try:
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click()
            page.wait_for_load_state("networkidle")
            return True
    except Exception:
        pass
    return False


def run_replay(capability: Capability, params: dict, evidence_root: str = "evidence") -> ReplayResult:
    run_id = f"replay-{capability.name.replace(' ', '_')}-{int(time.time())}"
    run_dir = Path(evidence_root) / run_id
    logger = EvidenceLogger(run_id, "replay", evidence_root)
    policy = AllowlistPolicy(allowed_domains=capability.allowed_domains)
    logger.log("replay_started", capability_id=capability.capability_id,
               capability_name=capability.name, params={k: v for k, v in params.items()})

    missing = [p.name for p in capability.input_params if p.required and p.name not in params]
    if missing:
        return ReplayResult(outcome=ReplayOutcome.HARD_FAILURE,
                             message=f"Missing required input params: {missing}")

    extracted: dict[str, str] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        handoff = ControlHandoff(run_dir)

        try:
            enforce_url(policy, capability.target_app)
            page.goto(capability.target_app)

            for step in capability.steps:
                result = _execute_step(page, step, params, policy, extracted, logger, handoff, capability, run_id)
                if result is not None:  # a terminal outcome was reached mid-flow
                    browser.close()
                    return result

            # All steps ran -- verify the checkpoint before declaring success.
            cp = capability.checkpoint
            try:
                loc, matched = resolve(page, cp.locator.primary, cp.locator.fallbacks, timeout_ms=5000)
                text = loc.inner_text()
            except LocatorResolutionError:
                text = full_text(page)

            if cp.expected_text_contains in text:
                outputs = {of.name: extracted.get(of.source_step, None) for of in capability.outputs}
                logger.log("replay_success", outputs=outputs)
                browser.close()
                return ReplayResult(outcome=ReplayOutcome.SUCCESS, outputs=outputs,
                                     message="Checkpoint verified.", evidence_path=str(run_dir))

            snap_path = logger.save_screenshot("checkpoint_failed", page.screenshot())
            logger.log("checkpoint_failed", expected=cp.expected_text_contains, observed=text[:500])
            browser.close()
            return ReplayResult(
                outcome=ReplayOutcome.HARD_FAILURE,
                message="All steps executed but checkpoint was not verified.",
                expected=cp.expected_text_contains, observed=text[:500],
                evidence_path=snap_path,
            )

        except GuardrailViolation as e:
            logger.log("guardrail_blocked", reason=str(e))
            browser.close()
            return ReplayResult(outcome=ReplayOutcome.HARD_FAILURE, message=f"Guardrail violation: {e}")


def _execute_step(page, step, params, policy, extracted, logger, handoff, capability, run_id) -> ReplayResult | None:
    """Executes one step. Returns a ReplayResult if this step produced a
    terminal outcome (business outcome, or hard failure after failed
    escalation); returns None if execution should continue to the next step."""
    enforce_action_type(policy, step.action.value)
    value = _substitute(step.value, params)

    try:
        if step.action == ActionType.NAVIGATE:
            enforce_url(policy, value)
            page.goto(value)
        elif step.locator is not None:
            if _dismiss_interstitial_if_present(page):
                logger.log("recovered_interstitial", step_id=step.step_id)
            loc, matched = resolve(page, step.locator.primary, step.locator.fallbacks, timeout_ms=step.timeout_ms)
            logger.log("locator_resolved", step_id=step.step_id, matched=matched)
            if step.action == ActionType.CLICK:
                loc.click()
            elif step.action == ActionType.TYPE:
                loc.fill(value or "")
            elif step.action == ActionType.SELECT:
                loc.select_option(label=value)
            elif step.action == ActionType.EXTRACT:
                extracted[step.step_id] = loc.inner_text()
            elif step.action == ActionType.ASSERT_TEXT:
                if value not in full_text(page):
                    raise AssertionError(f"Expected text '{value}' not found")
        logger.log("step_executed", step_id=step.step_id, action=step.action.value)

    except (LocatorResolutionError, AssertionError, Exception) as e:
        # Before treating this as a failure, check whether the page is
        # showing a known, expected BUSINESS OUTCOME rather than an error.
        page_text = full_text(page)
        m = RESULT_CODE_RE.search(page_text)
        if m:
            code = m.group(1)
            logger.log("business_outcome", code=code, step_id=step.step_id)
            return ReplayResult(
                outcome=ReplayOutcome.BUSINESS_OUTCOME, business_outcome_code=code,
                message=f"App returned business outcome: {code}",
                outputs={}, failed_step=step.step_id,
            )

        # Not a known business outcome -- escalate to a human on this same
        # live session before giving up.
        logger.log("step_failed_escalating", step_id=step.step_id, error=str(e))
        try:
            handoff.request_intervention(
                logger, page, reason=f"Step {step.step_id} ({step.action.value}) failed: {e}",
                capability_or_goal=capability.name, step_id=step.step_id, timeout_seconds=120,
            )
            # Human resolved it -- retry this step once.
            return _execute_step(page, step, params, policy, extracted, logger, handoff, capability, run_id)
        except TimeoutError:
            snap_path = logger.save_screenshot(f"failure_{step.step_id}", page.screenshot())
            return ReplayResult(
                outcome=ReplayOutcome.HARD_FAILURE,
                message=f"Step {step.step_id} failed and escalation timed out.",
                failed_step=step.step_id, expected=step.description, observed=str(e)[:500],
                evidence_path=snap_path,
            )
    return None
