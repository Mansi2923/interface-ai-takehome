"""
Perception: turn a live page into a compact, LLM-readable snapshot.

Why accessibility tree, not raw HTML (see REPORT.md section 1/4):
Legacy bank screens have no test IDs and often no semantic markup --
nested <table> layouts, generic <div>/<font> tags. But they still have to
be usable by a screen reader, so browsers compute an ACCESSIBILITY TREE
regardless of markup quality: every interactive element gets a role
(button, textbox, link...) and an accessible name (from its label, its
own text, aria-label, etc). That tree is far more stable across
re-skinned tenant variants of the same vendor app than CSS selectors or
DOM structure -- rebranding changes colors and class names, it rarely
changes what a button's accessible name is. This is also the SAME
representation available on native desktop apps (OS accessibility APIs),
which is why building perception on this abstraction, not on raw DOM, is
what lets the design extend to desktop surfaces later without a rewrite
(see REPORT.md section 4).

We give the LLM a numbered, flattened list of interactive+text elements
with role/name/text, not the full tree -- token budget and clarity.
"""

from __future__ import annotations
from playwright.sync_api import Page


def snapshot(page: Page, max_elements: int = 60) -> str:
    """Return a compact numbered list of interactive elements + visible
    text, formatted for the LLM. Also returns non-interactive text blocks
    so the model can read results/errors on the page."""
    ax_tree = page.accessibility.snapshot(interesting_only=True)
    lines = []
    counter = {"i": 0}

    def walk(node, depth=0):
        if node is None or counter["i"] >= max_elements:
            return
        role = node.get("role", "")
        name = node.get("name", "")
        if role in ("button", "link", "textbox", "combobox", "checkbox", "radio"):
            counter["i"] += 1
            lines.append(f"[{counter['i']}] role={role} name=\"{name}\"")
        elif role in ("text", "StaticText", "heading") and name.strip():
            lines.append(f"      text: \"{name.strip()}\"")
        for child in node.get("children", []) or []:
            walk(child, depth + 1)

    walk(ax_tree)
    return "\n".join(lines) if lines else "(empty page)"


def full_text(page: Page) -> str:
    """Raw visible text -- used for checkpoint/business-outcome matching,
    which needs to see everything, not just the truncated snapshot."""
    return page.inner_text("body")
