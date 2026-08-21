"""
Safety guardrails.

Two independent checks, both enforced at the point of action -- not just
declared in config and trusted:

1. Allowlist: a domain/route the agent (discovery OR replay) is about to
   touch must match an explicit allowlist entry. Anything else is blocked
   before the action executes, not caught after the fact.

2. Risk policy: every step declares a RiskLevel. IRREVERSIBLE actions
   (anything that submits a real change -- confirming a transaction,
   submitting a form that creates a record) are never auto-approved during
   discovery on the first pass through this project's scope; they require
   the step to be explicitly whitelisted as an expected terminal action of
   the capability being recorded. During replay, IRREVERSIBLE steps are
   allowed to execute (that's the point of a saved capability -- it's been
   reviewed once), but they are always logged with full context and are
   the first thing a human reviewer should scrutinize before approving an
   artifact for unattended use.

This is intentionally conservative and simple -- see REPORT.md section 6
for what a production version would add (per-tenant policy overrides,
approval workflow gating unattended replay, etc.)
"""

from __future__ import annotations
from urllib.parse import urlparse
from dataclasses import dataclass, field
from core.schemas import RiskLevel


@dataclass
class AllowlistPolicy:
    allowed_domains: list[str] = field(default_factory=list)
    allowed_action_types: list[str] = field(default_factory=lambda: [
        "navigate", "click", "type", "select", "wait_for", "extract",
        "assert_text", "dismiss_interstitial",
    ])

    def check_url(self, url: str) -> tuple[bool, str]:
        host = urlparse(url).hostname or ""
        for domain in self.allowed_domains:
            if host == domain or host.endswith("." + domain):
                return True, ""
        return False, f"Domain '{host}' is not in the allowlist {self.allowed_domains}"

    def check_action_type(self, action_type: str) -> tuple[bool, str]:
        if action_type in self.allowed_action_types:
            return True, ""
        return False, f"Action type '{action_type}' is not permitted"


class GuardrailViolation(Exception):
    pass


def enforce_url(policy: AllowlistPolicy, url: str):
    ok, reason = policy.check_url(url)
    if not ok:
        raise GuardrailViolation(reason)


def enforce_action_type(policy: AllowlistPolicy, action_type: str):
    ok, reason = policy.check_action_type(action_type)
    if not ok:
        raise GuardrailViolation(reason)


def is_irreversible(risk: RiskLevel) -> bool:
    return risk == RiskLevel.IRREVERSIBLE
