"""Team-scoped failed-analysis persistence with legacy flat-path fallback.

Canonical paths (per architecture + product request):
  - Tags:    data/<team>/failed_analysis_saved_tags.json
  - Results: data/<team>/failed_analysis/results_<tag>.json

Also reads (and merges) older layouts so existing tags/results keep working:
  - data/<team>/failed_analysis/saved_tags.json
  - data/failed_analysis_saved_tags.json
  - data/<team>/failed_analysis_<tag>.json
  - data/failed_analysis_<tag>.json
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

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


def _using_flat_team_override() -> bool:
    """True when REGX_TEAM_DATA_DIR points at a single team sandbox (tests/prod override)."""
    return bool((os.environ.get("REGX_TEAM_DATA_DIR") or "").strip())


def _data_root_or_override() -> str:
    if _using_flat_team_override():
        return (os.environ.get("REGX_TEAM_DATA_DIR") or "").strip()
    return _DATA_ROOT


def failed_analysis_dir(team: Optional[str] = None, for_write: bool = False) -> str:
    """Return data/<team>/failed_analysis/ (or <override>/failed_analysis/)."""
    if _using_flat_team_override():
        path = os.path.join(_data_root_or_override(), "failed_analysis")
    else:
        team = _current_team(team)
        path = os.path.join(_DATA_ROOT, team, "failed_analysis")
    if for_write:
        os.makedirs(path, exist_ok=True)
    return path


def _team_root(team: Optional[str] = None, for_write: bool = False) -> str:
    if _using_flat_team_override():
        path = _data_root_or_override()
    else:
        path = os.path.join(_DATA_ROOT, _current_team(team))
    if for_write:
        os.makedirs(path, exist_ok=True)
    return path


def _team_tags_path(team: Optional[str] = None, for_write: bool = False) -> str:
    """Canonical: data/<team>/failed_analysis_saved_tags.json"""
    return os.path.join(_team_root(team, for_write=for_write), "failed_analysis_saved_tags.json")


def _phase2_tags_path(team: Optional[str] = None, for_write: bool = False) -> str:
    """Older Phase-2 layout: data/<team>/failed_analysis/saved_tags.json"""
    return os.path.join(failed_analysis_dir(team, for_write=for_write), "saved_tags.json")


def _team_results_path(tag: str, team: Optional[str] = None, for_write: bool = False) -> str:
    sanitized = _sanitize_tag_for_filename(tag)
    return os.path.join(
        failed_analysis_dir(team, for_write=for_write),
        f"results_{sanitized}.json",
    )


def _team_flat_results_path(tag: str, team: Optional[str] = None) -> str:
    sanitized = _sanitize_tag_for_filename(tag)
    return os.path.join(_team_root(team, for_write=False), f"failed_analysis_{sanitized}.json")


def _legacy_tags_path() -> str:
    return os.path.join(_DATA_ROOT, "failed_analysis_saved_tags.json")


def _legacy_results_path(tag: str) -> str:
    sanitized = _sanitize_tag_for_filename(tag)
    return os.path.join(_DATA_ROOT, f"failed_analysis_{sanitized}.json")


def _read_json(path: str) -> Optional[Any]:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.error("Error reading JSON %s: %s", path, exc)
    return None


def _tag_name(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("name") or "").strip()
    return str(entry or "").strip()


def _tag_candidates(team: Optional[str] = None) -> List[str]:
    paths = [
        _team_tags_path(team, for_write=False),
        _phase2_tags_path(team, for_write=False),
    ]
    if not _using_flat_team_override():
        paths.append(_legacy_tags_path())
    return paths


def _results_candidates(tag: str, team: Optional[str] = None) -> List[str]:
    paths = [
        _team_results_path(tag, team, for_write=False),
        _team_flat_results_path(tag, team),
    ]
    if not _using_flat_team_override():
        paths.append(_legacy_results_path(tag))
    return paths


def load_failed_analysis_tags(team: Optional[str] = None) -> Dict[str, Any]:
    """Load saved tags by merging team + legacy sources (never hide legacy behind empty team file)."""
    seen: Dict[str, Any] = {}
    order: List[str] = []
    for path in _tag_candidates(team):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        tags = data.get("tags")
        if not isinstance(tags, list):
            continue
        for entry in tags:
            name = _tag_name(entry)
            if not name or name in seen:
                continue
            seen[name] = entry if isinstance(entry, dict) else {"name": name}
            order.append(name)
    return {"tags": [seen[n] for n in order]}


def save_failed_analysis_tags(data: Dict[str, Any], team: Optional[str] = None) -> None:
    """Write canonical team tags file: data/<team>/failed_analysis_saved_tags.json."""
    path = _team_tags_path(team, for_write=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _merge_cursor_ai(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base or {})
    extra = extra or {}
    for key in ("results", "sessions", "follow_up_history_by_testcase"):
        merged = dict(out.get(key) or {})
        merged.update(extra.get(key) or {})
        if merged:
            out[key] = merged
    return out


def _score_results_payload(data: Dict[str, Any]) -> Tuple[int, int, int]:
    """Prefer payloads with more failure rows, then more IT analyses, then cursor AI."""
    results_n = len(data.get("results") or [])
    it_n = len(data.get("intelligent_triage") or {})
    cursor = data.get("cursor_ai") or {}
    cursor_n = len(cursor.get("results") or {})
    return (results_n, it_n, cursor_n)


def load_failed_analysis_results(tag: str, team: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load per-tag results, merging team + legacy so empty team writes don't hide legacy data."""
    loaded: List[Dict[str, Any]] = []
    for path in _results_candidates(tag, team):
        data = _read_json(path)
        if isinstance(data, dict):
            loaded.append(data)
    if not loaded:
        return None

    best = max(loaded, key=_score_results_payload)
    merged = dict(best)
    it_map: Dict[str, Any] = {}
    cursor: Dict[str, Any] = {}
    for data in loaded:
        for tid, analysis in (data.get("intelligent_triage") or {}).items():
            if not tid or not analysis:
                continue
            tid_s = str(tid)
            prev = it_map.get(tid_s)
            if not prev:
                it_map[tid_s] = analysis
                continue
            prev_deep = (prev.get("deep_ai") or {}).get("status") not in (None, "", "not_run")
            new_deep = (analysis.get("deep_ai") or {}).get("status") not in (None, "", "not_run")
            if new_deep and not prev_deep:
                it_map[tid_s] = analysis
            elif analysis.get("decision") and not prev.get("decision"):
                it_map[tid_s] = analysis
        cursor = _merge_cursor_ai(cursor, data.get("cursor_ai") or {})

    if it_map:
        merged["intelligent_triage"] = it_map
    if cursor:
        merged["cursor_ai"] = cursor
    if not merged.get("tag"):
        merged["tag"] = tag
    return merged


def save_failed_analysis_results(tag: str, data: Dict[str, Any], team: Optional[str] = None) -> None:
    """Write results under data/<team>/failed_analysis/results_<tag>.json.

    Merges with any previously saved intelligent_triage / cursor_ai so a results-only
    write cannot wipe prior First Level / Deep AI analyses.
    """
    path = _team_results_path(tag, team, for_write=True)
    existing = _read_json(path) if os.path.exists(path) else None
    if not isinstance(existing, dict):
        existing = {}

    # Pull IT/cursor from sibling/legacy candidates without re-entering save.
    prior_it: Dict[str, Any] = {}
    prior_cursor: Dict[str, Any] = {}
    prior_results: List[Any] = []
    for cand in _results_candidates(tag, team):
        if cand == path:
            continue
        other = _read_json(cand)
        if not isinstance(other, dict):
            continue
        for tid, analysis in (other.get("intelligent_triage") or {}).items():
            if tid and analysis and str(tid) not in prior_it:
                prior_it[str(tid)] = analysis
        prior_cursor = _merge_cursor_ai(prior_cursor, other.get("cursor_ai") or {})
        if not prior_results and other.get("results"):
            prior_results = list(other.get("results") or [])

    out = dict(data or {})
    it_out = dict(prior_it)
    it_out.update(existing.get("intelligent_triage") or {})
    it_out.update(out.get("intelligent_triage") or {})
    if it_out:
        out["intelligent_triage"] = it_out

    cursor_out = _merge_cursor_ai(prior_cursor, existing.get("cursor_ai") or {})
    cursor_out = _merge_cursor_ai(cursor_out, out.get("cursor_ai") or {})
    if cursor_out:
        out["cursor_ai"] = cursor_out

    incoming_results = out.get("results")
    if incoming_results is None or (
        isinstance(incoming_results, list)
        and len(incoming_results) == 0
        and (existing.get("results") or prior_results)
    ):
        preserved = existing.get("results") or prior_results or []
        if preserved:
            out["results"] = preserved

    out.setdefault("tag", tag)
    if isinstance(out.get("results"), list):
        out["count"] = len(out["results"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


def delete_failed_analysis_results(tag: str, team: Optional[str] = None) -> None:
    """Delete team-scoped and legacy cache files for a tag."""
    paths = list(_results_candidates(tag, team))
    try:
        if os.path.isdir(_DATA_ROOT):
            for entry in os.listdir(_DATA_ROOT):
                team_dir = os.path.join(_DATA_ROOT, entry, "failed_analysis")
                if os.path.isdir(team_dir):
                    paths.append(
                        os.path.join(team_dir, f"results_{_sanitize_tag_for_filename(tag)}.json")
                    )
                flat = os.path.join(
                    _DATA_ROOT, entry, f"failed_analysis_{_sanitize_tag_for_filename(tag)}.json"
                )
                paths.append(flat)
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


def get_cached_intelligent_analysis(
    tag: str, testcase_id: str, team: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Return saved intelligent_triage entry for a testcase_id, if any."""
    tid = str(testcase_id or "").strip()
    if not tag or not tid:
        return None
    cached = load_failed_analysis_results(tag, team=team) or {}
    analysis = (cached.get("intelligent_triage") or {}).get(tid)
    return analysis if isinstance(analysis, dict) and analysis else None
