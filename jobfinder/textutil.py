"""Small text helpers."""
from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup


def html_to_text(raw: str) -> str:
    """Turn HTML (possibly HTML-escaped) into plain text."""
    if not raw:
        return ""
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    text = BeautifulSoup(raw, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()
