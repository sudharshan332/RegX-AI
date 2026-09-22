"""Team-scoped failed-analysis persistence with legacy flat-path fallback."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_ROOT = os.path.join(_PROJECT_ROOT, "data")
_DEFAULT_TEAM = os.environ.get("REGX_DEFAULT_TEAM", "CDP_FT")


def _sanitize_tag_for_filename(tag: str) -> str:
    sanitized = re.sub(r"[^\w.\-]+", "_", (tag or "").strip())
    return sanitized[:180] or "untagged"


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


def failed_analysis_dir(team: Optional[str] = None, for_write: bool = False) -> str:
    """Return data/<team>/failed_analysis/ (create when for_write)."""
    team = _current_team(team)
    path = os.path.join(_DATA_ROOT, team, "failed_analysis")
    if for_write:
        os.makedirs(path, exist_ok=True)
    return path


def _team_tags_path(team: Optional[str] = None, for_write: bool = False) -> str:
    return os.path.join(failed_analysis_dir(team, for_write=for_write), "saved_tags.json")


def _team_results_path(tag: str, team: Optional[str] = None, for_write: bool = False) -> str:
    sanitized = _sanitize_tag_for_filename(tag)
    return os.path.join(
        failed_analysis_dir(team, for_write=for_write),
        f"results_{sanitized}.json",
    )


def _legacy_tags_path() -> str:
    return os.path.join(_DATA_ROOT, "failed_analysis_saved_tags.json")


def _legacy_results_path(tag: str) -> str:
    sanitized = _sanitize_tag_for_filename(tag)
    return os.path.join(_DATA_ROOT, f"failed_analysis_{sanitized}.json")


def load_failed_analysis_tags(team: Optional[str] = None) -> Dict[str, Any]:
    """Load saved tags: team path first, then legacy flat file."""
    candidates = [
        _team_tags_path(team, for_write=False),
        _legacy_tags_path(),
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "tags" in data:
                    return data
        except Exception as exc:
            logger.error("Error loading failed analysis tags from %s: %s", path, exc)
    return {"tags": []}


def save_failed_analysis_tags(data: Dict[str, Any], team: Optional[str] = None) -> None:
    """Always write to the team-scoped path going forward."""
    path = _team_tags_path(team, for_write=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_failed_analysis_results(tag: str, team: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load per-tag results: team path, then legacy data/failed_analysis_<tag>.json."""
    candidates = [
        _team_results_path(tag, team, for_write=False),
        _legacy_results_path(tag),
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as exc:
            logger.error("Error loading failed analysis results for '%s' from %s: %s", tag, path, exc)
    return None


def save_failed_analysis_results(tag: str, data: Dict[str, Any], team: Optional[str] = None) -> None:
    """Write results under data/<team>/failed_analysis/results_<tag>.json."""
    path = _team_results_path(tag, team, for_write=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def delete_failed_analysis_results(tag: str, team: Optional[str] = None) -> None:
    """Delete team-scoped and legacy cache files for a tag (intelligent-triage coupling)."""
    paths = [
        _team_results_path(tag, team, for_write=False),
        _legacy_results_path(tag),
    ]
    # Also try other known team folders so Home/config tag delete cleans caches broadly.
    try:
        if os.path.isdir(_DATA_ROOT):
            for entry in os.listdir(_DATA_ROOT):
                team_dir = os.path.join(_DATA_ROOT, entry, "failed_analysis")
                if os.path.isdir(team_dir):
                    paths.append(
                        os.path.join(team_dir, f"results_{_sanitize_tag_for_filename(tag)}.json")
                    )
    except Exception:
        pass

    seen = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info("Deleted failed analysis cache: %s", path)
        except Exception as exc:
            logger.warning("Could not delete failed analysis cache %s: %s", path, exc)
