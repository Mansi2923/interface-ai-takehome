"""LLM-driven capability discovery."""

from __future__ import annotations
import os
import time
import uuid
from pathlib import Path

import anthropic
from playwright.sync_api import sync_playwright

from core.schemas import (
    Capability, Step, ActionType, RiskLevel, FailureHandling,
    LocatorStrategy, InputParam, OutputField, Checkpoint,
)
from core.guardrails import AllowlistPolicy, enforce_url, enforce_action_type, GuardrailViolation
from core.constants import DISCOVERY_MAX_STEPS, DISCOVERY_MODEL, HEADLESS
from core.logging_utils import EvidenceLogger
from core.prompts import DISCOVERY_SYSTEM_PROMPT
from core.registry import DISCOVERY_TOOLS
from perception import snapshot as perceive, full_text
from escalation import ControlHandoff


def _param_or_literal(value: str, param_name: str | None) -> str:
    return "{{" + param_name + "}}" if param_name else value


def _build_capability(fin: dict, steps: list[Step], input_params: dict[str, InputParam],
                      target_url: str, allowed_domains: list[str]) -> Capability:
    outputs = [
        OutputField(name=output["name"], type=output["type"], description=output["description"],
                    source_step=next((step.step_id for step in steps
                                      if step.extract_as == output["source_extract_as"]), ""))
        for output in fin.get("outputs", [])
    ]
    checkpoint = Checkpoint(
        description=f"Verifies: {fin['capability_description']}",
        locator=LocatorStrategy(
            primary=f"role={fin.get('checkpoint_role', 'text')}[name='{fin.get('checkpoint_name', '')}']"
            if fin.get("checkpoint_role") else f"text={fin['checkpoint_expected_text']}",
            fallbacks=[f"text={fin['checkpoint_expected_text']}"],
            reasoning="Role+name from the confirming element, with a text-match fallback.",
        ),
        expected_text_contains=fin["checkpoint_expected_text"],
    )
    return Capability(
        capability_id=str(uuid.uuid4()), name=fin["capability_name"],
        description=fin["capability_description"], target_app=target_url,
        created_by="llm_discovery", input_params=list(input_params.values()), outputs=outputs,
        steps=steps, checkpoint=checkpoint, allowed_domains=allowed_domains,
    )


def _execute_and_record_action(page, act: dict, step_id: str, policy: AllowlistPolicy,
                               steps: list[Step], input_params: dict[str, InputParam]) -> Step:
    enforce_action_type(policy, act["action"])
    step = _execute_action(page, act, step_id, policy)
    steps.append(step)
    if step.action == ActionType.TYPE and act.get("param_name"):
        input_params[act["param_name"]] = InputParam(
            name=act["param_name"], type="string", required=True,
            description=f"Value typed into {act.get('role')} '{act.get('name')}'",
            example=act.get("value"),
        )
    return step


def run_discovery(goal: str, target_url: str, allowed_domains: list[str],
                   evidence_root: str = "evidence") -> Capability:
    run_id = f"discovery-{int(time.time())}"
    run_dir = Path(evidence_root) / run_id
    logger = EvidenceLogger(run_id, "discovery", evidence_root)
    policy = AllowlistPolicy(allowed_domains=allowed_domains)
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    logger.log("discovery_started", goal=goal, target_url=target_url)
    enforce_url(policy, target_url)

    steps: list[Step] = []
    input_params: dict[str, InputParam] = {}
    messages = [{"role": "user", "content": f"Goal: {goal}\nStarting URL: {target_url}"}]

    with sync_playwright() as pw:
        # Non-headless: this is also the browser window a human takes over
        # during escalation (see escalation.py docstring).
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        page.goto(target_url)
        handoff = ControlHandoff(run_dir)

        for step_num in range(1, DISCOVERY_MAX_STEPS + 1):
            snap = perceive(page)
            messages.append({"role": "user", "content": f"[Step {step_num}] Current page ({page.url}):\n{snap}"})
            logger.log("observation", step_num=step_num, url=page.url, snapshot=snap)

            response = client.messages.create(
    model=DISCOVERY_MODEL, max_tokens=1024, system=DISCOVERY_SYSTEM_PROMPT,
    tools=DISCOVERY_TOOLS,
    tool_choice={"type": "auto", "disable_parallel_tool_use": True},
    messages=messages,
)
            messages.append({"role": "assistant", "content": response.content})
            logger.log("model_response", step_num=step_num,
                       text=[b.text for b in response.content if b.type == "text"])

            tool_use = next((b for b in response.content if b.type == "tool_use"), None)
            if tool_use is None:
                messages.append({"role": "user", "content": "Please take an action using one of the provided tools."})
                continue

            step_id = f"s{step_num}"

            if tool_use.name == "escalate":
                reason = tool_use.input["reason"]
                resolution = handoff.request_intervention(logger, page, reason, goal, step_id)
                messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_use.id,
                                 "content": f"A human intervened and reported: {resolution.get('note', '(no note)')}. Continue."}],
                })
                continue

            if tool_use.name == "finish":
                capability = _build_capability(
                    tool_use.input, steps, input_params, target_url, allowed_domains,
                )
                logger.log("discovery_finished", capability_id=capability.capability_id, steps=len(steps))
                browser.close()
                return capability

            # tool_use.name == "act"
            act = tool_use.input
            try:
                _execute_and_record_action(page, act, step_id, policy, steps, input_params)
                logger.log("action_executed", step_id=step_id, action=act["action"],
                           role=act.get("role"), name=act.get("name"))
                result_text = f"Action succeeded: {act['action']}."
            except GuardrailViolation as e:
                logger.log("guardrail_blocked", step_id=step_id, reason=str(e))
                result_text = f"BLOCKED by guardrails: {e}. Choose a different action or escalate."
            except Exception as e:
                logger.log("action_failed", step_id=step_id, error=str(e))
                result_text = f"Action failed: {e}. Re-observe and try a different approach, or escalate if stuck."

            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use.id, "content": result_text}],
            })

        browser.close()
    raise RuntimeError(
        f"Discovery did not finish within {DISCOVERY_MAX_STEPS} steps -- see {logger.events_path}"
    )


def _execute_action(page, act: dict, step_id: str, policy: AllowlistPolicy) -> Step:
    action = ActionType(act["action"])
    risk = RiskLevel(act.get("risk", "safe"))
    on_failure = FailureHandling.HARD_FAIL
    locator = None

    if action == ActionType.NAVIGATE:
        enforce_url(policy, act["value"])
        page.goto(act["value"])
    else:
        locator_str = f"role={act['role']}[name='{act['name']}']"
        locator = LocatorStrategy(primary=locator_str, fallbacks=[f"text={act['name']}"],
                                   reasoning="Accessibility role+name is the most stable identifier on this non-semantic UI.")
        target = page.get_by_role(act["role"], name=act["name"]).first
        if action == ActionType.CLICK:
            target.click()
        elif action == ActionType.TYPE:
            target.fill(act["value"])
        elif action == ActionType.SELECT:
            target.select_option(label=act["value"])
        elif action == ActionType.EXTRACT:
            pass  # text read below regardless of action
        elif action == ActionType.ASSERT_TEXT:
            assert act["value"] in full_text(page), f"Expected text '{act['value']}' not found on page"

    extract_as = act.get("extract_as")
    value_for_step = _param_or_literal(act.get("value", ""), act.get("param_name"))

    if action == ActionType.EXTRACT and locator is not None:
        target = page.get_by_role(act["role"], name=act["name"]).first
        extracted = target.inner_text()
        value_for_step = extracted  # record what was read, for reference

    return Step(
        step_id=step_id, action=action, locator=locator, value=value_for_step,
        extract_as=extract_as, risk=risk, on_failure=on_failure,
        description=act.get("description", ""),
    )
