"""Dataclass contracts for capabilities and replay results."""

from __future__ import annotations
from typing import Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import json
from enum import Enum
from core.constants import DEFAULT_TIMEOUT_MS
from core.enums import ActionType, FailureHandling, ReplayOutcome, RiskLevel


def _enc(obj):
    """JSON encoder helper: Enum -> value, datetime -> isoformat."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Not serializable: {obj!r}")


@dataclass
class LocatorStrategy:
    primary: str                     # e.g. "role=button[name='Search']"
    fallbacks: list[str] = field(default_factory=list)
    reasoning: str = ""

    @staticmethod
    def from_dict(d: dict) -> "LocatorStrategy":
        return LocatorStrategy(primary=d["primary"], fallbacks=d.get("fallbacks", []), reasoning=d.get("reasoning", ""))


@dataclass
class Step:
    step_id: str
    action: ActionType
    risk: RiskLevel
    on_failure: FailureHandling
    description: str
    locator: Optional[LocatorStrategy] = None
    value: Optional[str] = None       # literal or {{param_name}} template
    extract_as: Optional[str] = None
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    @staticmethod
    def from_dict(d: dict) -> "Step":
        return Step(
            step_id=d["step_id"], action=ActionType(d["action"]), risk=RiskLevel(d["risk"]),
            on_failure=FailureHandling(d["on_failure"]), description=d.get("description", ""),
            locator=LocatorStrategy.from_dict(d["locator"]) if d.get("locator") else None,
            value=d.get("value"), extract_as=d.get("extract_as"),
            timeout_ms=d.get("timeout_ms", DEFAULT_TIMEOUT_MS),
        )


@dataclass
class InputParam:
    name: str
    type: str
    description: str
    required: bool = True
    example: Optional[str] = None

    @staticmethod
    def from_dict(d: dict) -> "InputParam":
        return InputParam(**d)


@dataclass
class OutputField:
    name: str
    type: str
    description: str
    source_step: str

    @staticmethod
    def from_dict(d: dict) -> "OutputField":
        return OutputField(**d)


@dataclass
class Checkpoint:
    description: str
    locator: LocatorStrategy
    expected_text_contains: str

    @staticmethod
    def from_dict(d: dict) -> "Checkpoint":
        return Checkpoint(description=d["description"], locator=LocatorStrategy.from_dict(d["locator"]),
                           expected_text_contains=d["expected_text_contains"])


@dataclass
class Capability:
    capability_id: str
    name: str
    description: str
    target_app: str
    input_params: list[InputParam]
    outputs: list[OutputField]
    steps: list[Step]
    checkpoint: Checkpoint
    allowed_domains: list[str]
    version: str = "1.0.0"
    tenant_scope: str = "base"
    base_capability_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "llm_discovery"
    notes: Optional[str] = None

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), default=_enc, indent=indent)

    @staticmethod
    def from_json(text: str) -> "Capability":
        d = json.loads(text)
        return Capability(
            capability_id=d["capability_id"], name=d["name"], description=d["description"],
            target_app=d["target_app"],
            input_params=[InputParam.from_dict(p) for p in d["input_params"]],
            outputs=[OutputField.from_dict(o) for o in d["outputs"]],
            steps=[Step.from_dict(s) for s in d["steps"]],
            checkpoint=Checkpoint.from_dict(d["checkpoint"]),
            allowed_domains=d["allowed_domains"],
            version=d.get("version", "1.0.0"), tenant_scope=d.get("tenant_scope", "base"),
            base_capability_id=d.get("base_capability_id"), created_by=d.get("created_by", "llm_discovery"),
            notes=d.get("notes"),
        )


# ---------------------------------------------------------------------------
# Replay result contract -- returned by replay.py to the calling AI agent.
# ---------------------------------------------------------------------------

@dataclass
class ReplayResult:
    outcome: ReplayOutcome
    message: str
    outputs: dict[str, Any] = field(default_factory=dict)
    business_outcome_code: Optional[str] = None
    failed_step: Optional[str] = None
    expected: Optional[str] = None
    observed: Optional[str] = None
    evidence_path: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), default=_enc, indent=indent)
