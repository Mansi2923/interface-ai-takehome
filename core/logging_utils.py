"""Structured JSONL evidence logger with field-name redaction."""

from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from core.constants import REDACTED_VALUE, SENSITIVE_KEY_RE

def redact(obj):
    if isinstance(obj, dict):
        return {
            k: (REDACTED_VALUE if SENSITIVE_KEY_RE.search(k) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class EvidenceLogger:
    def __init__(self, run_id: str, run_type: str, evidence_root: str = "evidence"):
        self.run_dir = Path(evidence_root) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_dir / "events.jsonl"
        self.run_type = run_type

    def log(self, event_type: str, **fields):
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_type": self.run_type,
            "event": event_type,
            **redact(fields),
        }
        with open(self.events_path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
        return event

    def save_screenshot(self, name: str, png_bytes: bytes) -> str:
        path = self.run_dir / f"{name}.png"
        with open(path, "wb") as f:
            f.write(png_bytes)
        return str(path)

    def save_text(self, name: str, text: str) -> str:
        path = self.run_dir / name
        with open(path, "w") as f:
            f.write(text)
        return str(path)
