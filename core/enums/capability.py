"""Enums describing capability execution."""

from enum import Enum


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    WAIT_FOR = "wait_for"
    EXTRACT = "extract"
    ASSERT_TEXT = "assert_text"
    DISMISS_INTERSTITIAL = "dismiss_interstitial"


class RiskLevel(str, Enum):
    SAFE = "safe"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class FailureHandling(str, Enum):
    RETRY = "retry"
    RECOVERABLE_INTERSTITIAL = "recoverable_interstitial"
    HARD_FAIL = "hard_fail"


class ReplayOutcome(str, Enum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    ESCALATED = "escalated"
    HARD_FAILURE = "hard_failure"
