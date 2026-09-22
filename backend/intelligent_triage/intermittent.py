"""Approved intermittent pattern gating + optional AI log validation.

Reuses backend/intermittent_patterns.json (approved patterns with confidence).
The filename intermittent_test_failure.json is treated as an alias if present.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATTERN_CANDIDATES = [
    os.path.join(_BACKEND_DIR, "intermittent_test_failure.json"),
    os.path.join(_BACKEND_DIR, "intermittent_patterns.json"),
]

_compiled_cache: Optional[List[Tuple[Any, Dict[str, Any]]]] = None


def _load_approved_patterns(force_reload: bool = False) -> List[Tuple[Any, Dict[str, Any]]]:
    global _compiled_cache
    if _compiled_cache is not None and not force_reload:
        return _compiled_cache

    patterns: List[Tuple[Any, Dict[str, Any]]] = []
    for path in _PATTERN_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("intermittent_patterns", data) if isinstance(data, dict) else data
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, str):
                    regex = item
                    meta = {
                        "id": None,
                        "confidence": 0.75,
                        "approved": True,
                        "description": regex[:80],
                        "action": "rerun",
                        "auto_triage": True,
                    }
                elif isinstance(item, dict):
                    regex = item.get("regex") or item.get("pattern") or ""
                    meta = {
                        "id": item.get("id"),
                        "confidence": float(item.get("confidence") or 0.75),
                        "approved": item.get("approved", True),
                        "description": item.get("description") or regex[:80],
                        "action": item.get("action") or "rerun",
                        "auto_triage": bool(item.get("auto_triage", True)),
                        "category": item.get("category"),
                        "root_cause": item.get("root_cause"),
                    }
                else:
                    continue
                if not regex:
                    continue
                try:
                    patterns.append((re.compile(regex, re.IGNORECASE), meta))
                except re.error as exc:
                    logger.warning("Invalid intermittent regex %r: %s", regex, exc)
            if patterns:
                logger.info("Loaded %d intermittent patterns from %s", len(patterns), path)
                break
        except Exception as exc:
            logger.warning("Could not load intermittent patterns from %s: %s", path, exc)

    _compiled_cache = patterns
    return patterns


def match_approved_intermittent(exception_summary: str) -> Dict[str, Any]:
    """Match exception_summary against approved intermittent patterns.

    Returns intermittent_analysis fields with independent intermittent_confidence.
    Does not consult triage_confidence.
    """
    text = (exception_summary or "").strip()
    empty = {
        "is_intermittent": False,
        "pattern_id": None,
        "pattern_description": None,
        "intermittent_confidence": None,
        "approved_pattern": False,
        "ai_log_validation": None,
        "action": None,
    }
    if not text:
        return empty

    best = None
    best_conf = -1.0
    for compiled, meta in _load_approved_patterns():
        if not meta.get("approved", True):
            continue
        if compiled.search(text):
            conf = float(meta.get("confidence") or 0.0)
            if conf > best_conf:
                best_conf = conf
                best = meta

    if not best:
        return empty

    return {
        "is_intermittent": True,
        "pattern_id": best.get("id"),
        "pattern_description": best.get("description"),
        "intermittent_confidence": best_conf,
        "approved_pattern": True,
        "ai_log_validation": None,
        "action": best.get("action") or "rerun",
        "root_cause": best.get("root_cause"),
        "auto_triage": best.get("auto_triage", True),
    }


def attach_ai_log_validation(
    intermittent: Dict[str, Any],
    verdict: str,
    reason: str = "",
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Attach optional AI log validation onto an intermittent_analysis dict.

    If AI rejects the intermittent claim, callers/decision engine will not RERUN.
    """
    out = dict(intermittent or {})
    out["ai_log_validation"] = {
        "verdict": verdict,
        "reason": reason,
        "confidence": confidence,
    }
    # If AI rejects, do not invent a lowered blended score — leave intermittent_confidence
    # as the pattern score; decision engine reads ai_log_validation.verdict independently.
    return out
