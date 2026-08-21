"""Shared configuration and compiled patterns."""

from __future__ import annotations

import os
import re

DISCOVERY_MODEL = "claude-sonnet-5"
DISCOVERY_MAX_STEPS = 20
DEFAULT_TIMEOUT_MS = 5000
HEADLESS = os.environ.get("HEADLESS", "0") == "1"

ROLE_LOCATOR_RE = re.compile(r"^role=(\w+)\[name='(.*)'\]$")
TEXT_LOCATOR_RE = re.compile(r"^text=(.*)$")
LABEL_LOCATOR_RE = re.compile(r"^label=(.*)$")
PLACEHOLDER_LOCATOR_RE = re.compile(r"^placeholder=(.*)$")
CSS_LOCATOR_RE = re.compile(r"^css=(.*)$")

REDACTED_VALUE = "[REDACTED]"
SENSITIVE_KEY_RE = re.compile(
    r"(password|token|ssn|credential|secret|api[_-]?key|cookie|auth)", re.IGNORECASE
)
