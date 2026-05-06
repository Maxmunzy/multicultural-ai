"""Map model/card outputs back to OCR/PDF layout boxes.

This module is intentionally pure and side-effect free. It can be wired into
`/notice/analyze/{id}` once backend storage for OCR/PDF layout JSON is decided.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any


_KEEP = re.compile(r"[^0-9A-Za-z가-힣]+")


def normalize_highlight_text(text: str) -> str:
    """Normalize text for OCR/model fuzzy matching."""
    return _KEEP.sub("", text or "").lower()


def _as_dict(item: Any) -> dict:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    return {}


def _match_score(query: str, candidate: str) -> float:
    q = normalize_highlight_text(query)
    c = normalize_highlight_text(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return min(len(q), len(c)) / max(len(q), len(c))
    return SequenceMatcher(None, q, c).ratio()


def _load_layout_lines(layout_json: str | list | dict | None) -> list[dict]:
    """Accept Android flat layout JSON or pdf_bbox_probe page JSON."""
    if not layout_json:
        return []
    if isinstance(layout_json, str):
        try:
            payload = json.loads(layout_json)
        except json.JSONDecodeError:
            return []
    else:
        payload = layout_json

    if isinstance(payload, list):
        return [line for line in payload if isinstance(line, dict)]

    if not isinstance(payload, dict):
        return []

    lines: list[dict] = []
    for page in payload.get("pages", []):
        if not isinstance(page, dict):
            continue
        page_size = {"width": page.get("width"), "height": page.get("height")}
        for line in page.get("lines", []):
            if not isinstance(line, dict):
                continue
            merged = dict(line)
            merged.setdefault("page", page.get("page", 1))
            merged.setdefault("page_size", page_size)
            lines.append(merged)
    return lines


def _bbox(line: dict) -> dict | None:
    bbox = line.get("bbox")
    if isinstance(bbox, dict):
        return {
            "x": bbox.get("x", 0),
            "y": bbox.get("y", 0),
            "width": bbox.get("width", 0),
            "height": bbox.get("height", 0),
        }
    if all(key in line for key in ("x", "y", "width", "height")):
        return {
            "x": line.get("x", 0),
            "y": line.get("y", 0),
            "width": line.get("width", 0),
            "height": line.get("height", 0),
        }
    return None


def _page_size(line: dict) -> dict:
    page_size = line.get("page_size")
    if isinstance(page_size, dict):
        return {
            "width": page_size.get("width", 0),
            "height": page_size.get("height", 0),
        }
    return {
        "width": line.get("page_width", 0),
        "height": line.get("page_height", 0),
    }


def build_highlights_from_cards(
    cards: list[Any],
    layout_json: str | list | dict | None,
    *,
    min_score: float = 0.62,
    limit: int = 12,
) -> list[dict]:
    """Build highlight response candidates from card values and layout lines.

    Matching strategy:
    1. exact normalized match
    2. normalized substring match
    3. SequenceMatcher fuzzy score
    """
    lines = _load_layout_lines(layout_json)
    if not cards or not lines:
        return []

    used_line_ids: set[int] = set()
    highlights: list[dict] = []

    for card_index, raw_card in enumerate(cards):
        card = _as_dict(raw_card)
        query = card.get("value_ko") or card.get("title_ko") or ""
        if not query:
            continue

        best_idx = -1
        best_score = 0.0
        for line_index, line in enumerate(lines):
            if line_index in used_line_ids:
                continue
            score = _match_score(query, line.get("text", ""))
            if score > best_score:
                best_idx = line_index
                best_score = score

        if best_idx < 0 or best_score < min_score:
            continue

        line = lines[best_idx]
        bbox = _bbox(line)
        if not bbox:
            continue

        used_line_ids.add(best_idx)
        highlights.append({
            "highlight_id": f"h_{len(highlights) + 1:03d}",
            "page": int(line.get("page") or 1),
            "source": line.get("source") or "layout_line",
            "bbox": bbox,
            "page_size": _page_size(line),
            "text": line.get("text", query),
            "category": card.get("chip"),
            "importance": card.get("importance", round(best_score, 3)),
            "translated": card.get("value_translated", ""),
            "easy_ko": card.get("value_easy_ko", ""),
        })

        if len(highlights) >= limit:
            break

    return highlights
