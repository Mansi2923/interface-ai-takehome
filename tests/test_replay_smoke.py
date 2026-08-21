import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import (
    Capability, Step, ActionType, RiskLevel, FailureHandling,
    LocatorStrategy, InputParam, OutputField, Checkpoint,
)
from replay import run_replay

steps = [
    Step(step_id="s1", action=ActionType.TYPE, risk=RiskLevel.SAFE, on_failure=FailureHandling.HARD_FAIL,
         description="type member id", value="{{member_id}}",
         locator=LocatorStrategy(primary="role=textbox[name='']", fallbacks=["css=input[name=member_id]"],
                                  reasoning="only textbox on page")),
    Step(step_id="s2", action=ActionType.CLICK, risk=RiskLevel.SAFE, on_failure=FailureHandling.HARD_FAIL,
         description="click search",
         locator=LocatorStrategy(primary="role=button[name='Search']", fallbacks=["text=Search"],
                                  reasoning="stable role/name")),
    Step(step_id="s3", action=ActionType.EXTRACT, risk=RiskLevel.SAFE, on_failure=FailureHandling.HARD_FAIL,
         description="read savings balance", extract_as="balance",
         locator=LocatorStrategy(primary="css=table tr:nth-child(3) td:nth-child(2)", fallbacks=[],
                                  reasoning="3rd row of detail table")),
]
checkpoint = Checkpoint(description="member detail shown", locator=steps[2].locator, expected_text_contains="$")
cap = Capability(
    capability_id="c1", name="Lookup Member Balance",
    description="Look up a member and read savings balance",
    target_app="http://127.0.0.1:5055",
    input_params=[InputParam(name="member_id", type="string", description="member id")],
    outputs=[OutputField(name="savings_balance", type="string", description="savings balance", source_step="s3")],
    steps=steps, checkpoint=checkpoint, allowed_domains=["127.0.0.1"],
)

print("=== SUCCESS CASE (member 12345) ===")
result = run_replay(cap, {"member_id": "12345"})
print(result.to_json())

print()
print("=== BUSINESS OUTCOME CASE (member 00000, not found) ===")
result2 = run_replay(cap, {"member_id": "00000"})
print(result2.to_json())
