"""Team-specific Intelligent Triage thresholds with architecture-doc defaults."""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_ROOT = os.path.join(_PROJECT_ROOT, "data")
_DEFAULT_TEAM = os.environ.get("REGX_DEFAULT_TEAM", "CDP_FT")

# Defaults from architecture doc section E.3 (tunable per team).
DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "version": "v1",
    "T_high": 0.75,          # min Glean/candidate match_score for AUTO_TRIAGE
    "T_auto": 0.85,          # min triage_confidence for AUTO_TRIAGE
    "T_mid": 0.55,           # mid band → HUMAN_REVIEW when below T_auto
    "T_intermittent": 0.80,  # min intermittent_confidence for RERUN_TESTCASE
    "T_insufficient_cap": 0.40,  # confidence cap when evidence/MCP weak
    "require_open_ticket_for_auto": True,
    "require_tg_correct_for_auto_write": True,
}


def _current_team(explicit_team: Optional[str] = None) -> str:
    if explicit_team and str(explicit_team).strip():
        return str(explicit_team).strip()
    try:
        from flask import g, has_request_context

        if has_request_context():
            team = getattr(g, "team", None)
            if team and str(team).strip():
                return str(team).strip()
    except Exception:
        pass
    return _DEFAULT_TEAM


def thresholds_path(team: Optional[str] = None, for_write: bool = False) -> str:
    """Path to data/<team>/failed_analysis/thresholds.json."""
    team = _current_team(team)
    directory = os.path.join(_DATA_ROOT, team, "failed_analysis")
    path = os.path.join(directory, "thresholds.json")
    if for_write:
        os.makedirs(directory, exist_ok=True)
    return path


def load_team_thresholds(team: Optional[str] = None) -> Dict[str, Any]:
    """Load team thresholds, merging over DEFAULT_THRESHOLDS."""
    merged = deepcopy(DEFAULT_THRESHOLDS)
    path = thresholds_path(team, for_write=False)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key, value in data.items():
                    if key in DEFAULT_THRESHOLDS or key in ("version", "notes"):
                        merged[key] = value
    except Exception as exc:
        logger.warning("Could not load triage thresholds from %s: %s", path, exc)
    return merged


def save_team_thresholds(data: Dict[str, Any], team: Optional[str] = None) -> Dict[str, Any]:
    """Persist team thresholds (merged with defaults) and return the saved object."""
    merged = deepcopy(DEFAULT_THRESHOLDS)
    if isinstance(data, dict):
        for key, value in data.items():
            merged[key] = value
    path = thresholds_path(team, for_write=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    return merged
