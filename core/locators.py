"""Ranked-fallback locator resolution."""

from __future__ import annotations
from playwright.sync_api import Page, Locator
from core.constants import (CSS_LOCATOR_RE, DEFAULT_TIMEOUT_MS, LABEL_LOCATOR_RE,
                            PLACEHOLDER_LOCATOR_RE, ROLE_LOCATOR_RE, TEXT_LOCATOR_RE)


def _build(page: Page, locator_str: str) -> Locator | None:
    if m := ROLE_LOCATOR_RE.match(locator_str):
        role, name = m.group(1), m.group(2)
        return page.get_by_role(role, name=name)
    if m := TEXT_LOCATOR_RE.match(locator_str):
        return page.get_by_text(m.group(1), exact=True)
    if m := LABEL_LOCATOR_RE.match(locator_str):
        return page.get_by_label(m.group(1))
    if m := PLACEHOLDER_LOCATOR_RE.match(locator_str):
        return page.get_by_placeholder(m.group(1))
    if m := CSS_LOCATOR_RE.match(locator_str):
        return page.locator(m.group(1))
    return None


class LocatorResolutionError(Exception):
    pass


def resolve(page: Page, primary: str, fallbacks: list[str], timeout_ms: int = DEFAULT_TIMEOUT_MS) -> tuple[Locator, str]:
    """Resolve the first visible primary or fallback locator."""
    tried = []
    for candidate in [primary, *fallbacks]:
        loc = _build(page, candidate)
        if loc is None:
            tried.append((candidate, "unparseable locator string"))
            continue
        try:
            loc.first.wait_for(state="visible", timeout=timeout_ms)
            count = loc.count()
            if count >= 1:
                return loc.first, candidate
            tried.append((candidate, "resolved to 0 elements"))
        except Exception as e:
            tried.append((candidate, f"not visible within {timeout_ms}ms: {e}"))
    raise LocatorResolutionError(
        f"No locator resolved. Tried: " + "; ".join(f"'{c}' -> {r}" for c, r in tried)
    )
