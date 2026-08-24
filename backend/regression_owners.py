"""
Load regression owners from team-scoped regression_owners.csv and resolve
testcase names to owner display names.

CSV format (header required):
  name,Regression_Owner

Unmapped tests resolve to UNKNOWN_OWNER ("Unknown user").
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

UNKNOWN_OWNER = "Unknown user"
BLANK_OWNER_VALUES = {
    "",
    "nan",
    "none",
    "null",
    "unknown",
    "unknown user",
    "unmapped",
    "n/a",
    "-",
}
_PARAM_RE = re.compile(r"~~~[^.]+")
_HEADER_KEYS = {"name", "test area", "testcase", "test_name", "testcase_name"}

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_ROOT = os.path.join(_PROJECT_ROOT, "data")
_DEFAULT_TEAM = os.environ.get("REGX_DEFAULT_TEAM", "CDP_FT")

owner_mapping: Dict[str, str] = {}
_prefixes_longest_first: List[str] = []
_canonical_mapping: Dict[str, str] = {}
_canonical_prefixes_longest_first: List[str] = []
_loaded_path: Optional[str] = None


def canonical_test_name(name: str) -> str:
    """Strip pytest-style ~~~parametrization segments from a test name."""
    return _PARAM_RE.sub("", name or "")


def _current_team(explicit_team: Optional[str] = None) -> Optional[str]:
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


def owner_csv_candidates(team: Optional[str] = None) -> List[str]:
    """Return CSV paths to try, preferred first."""
    team = _current_team(team)
    paths: List[str] = []

    def _add(path: str) -> None:
        if path and path not in paths:
            paths.append(path)

    if team:
        _add(os.path.join(_DATA_ROOT, team, "regression_owners.csv"))
    _add(os.path.join(_DATA_ROOT, "CDP_FT", "regression_owners.csv"))
    _add(os.path.join(_DATA_ROOT, "CDP_ST", "regression_owners.csv"))
    if os.path.isdir(_DATA_ROOT):
        try:
            for name in sorted(os.listdir(_DATA_ROOT)):
                child = os.path.join(_DATA_ROOT, name)
                if os.path.isdir(child):
                    _add(os.path.join(child, "regression_owners.csv"))
        except OSError:
            pass
    _add(os.path.join(_PROJECT_ROOT, "regression_owners.csv"))
    return paths


def pick_owner_csv(team: Optional[str] = None) -> Optional[str]:
    """Pick the first existing CSV that has at least one data row."""
    existing: List[str] = []
    for path in owner_csv_candidates(team):
        if os.path.isfile(path):
            existing.append(path)
            if os.path.getsize(path) > 40:
                try:
                    df = pd.read_csv(path, header=0, nrows=2)
                    if len(df.index) > 0:
                        return path
                except Exception:
                    continue
    return existing[0] if existing else None


def _normalize_owner(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return UNKNOWN_OWNER
    text = str(value).strip()
    if not text or text.lower() in BLANK_OWNER_VALUES:
        return UNKNOWN_OWNER
    return text


def _row_name_and_owner(row, columns) -> Tuple[Optional[str], str]:
    name = None
    owner = UNKNOWN_OWNER
    col_map = {str(c).strip().lower(): c for c in columns}
    name_col = next((col_map[k] for k in ("name", "test area", "testcase", "test_name", "testcase_name") if k in col_map), None)
    owner_col = next(
        (col_map[k] for k in ("regression_owner", "regression owner", "owner") if k in col_map),
        None,
    )
    if name_col is not None:
        raw_name = row.get(name_col)
    else:
        raw_name = row.iloc[0] if len(row) else None
    if owner_col is not None:
        raw_owner = row.get(owner_col)
    else:
        raw_owner = row.iloc[1] if len(row) > 1 else None

    if raw_name is None or (isinstance(raw_name, float) and pd.isna(raw_name)):
        return None, UNKNOWN_OWNER
    name = str(raw_name).strip()
    if not name or name.lower() in _HEADER_KEYS:
        return None, UNKNOWN_OWNER
    owner = _normalize_owner(raw_owner)
    return name, owner


def _rebuild_indexes(mapping: Dict[str, str]) -> None:
    global owner_mapping, _prefixes_longest_first
    global _canonical_mapping, _canonical_prefixes_longest_first
    owner_mapping = mapping
    _prefixes_longest_first = sorted(mapping.keys(), key=len, reverse=True)
    canon: Dict[str, str] = {}
    for name, owner in mapping.items():
        key = canonical_test_name(name)
        if key and key not in canon:
            canon[key] = owner
    _canonical_mapping = canon
    _canonical_prefixes_longest_first = sorted(canon.keys(), key=len, reverse=True)


def load_owner_mapping(team: Optional[str] = None, csv_path: Optional[str] = None) -> Dict[str, str]:
    """Load test-name → owner mapping from regression_owners.csv."""
    global _loaded_path
    path = csv_path or pick_owner_csv(team)
    mapping: Dict[str, str] = {}
    if not path:
        logger.warning("regression_owners.csv not found under data/<team>/ or project root")
        _rebuild_indexes(mapping)
        _loaded_path = None
        return mapping

    try:
        df = pd.read_csv(path, header=0)
        for _, row in df.iterrows():
            name, owner = _row_name_and_owner(row, df.columns)
            if not name:
                continue
            mapping[name] = owner
        _rebuild_indexes(mapping)
        _loaded_path = path
        logger.info("Loaded %s owner mappings from %s", len(mapping), path)
    except Exception as exc:
        logger.error("Error loading owner mapping from %s: %s", path, exc)
        _rebuild_indexes({})
        _loaded_path = path
    return owner_mapping


def resolve_owner(test_name: Optional[str]) -> str:
    """Resolve a JITA test name to a regression owner from the CSV mapping."""
    if not test_name:
        return UNKNOWN_OWNER
    name = str(test_name).strip()
    if not name:
        return UNKNOWN_OWNER

    owner = owner_mapping.get(name)
    if owner:
        return owner

    for prefix in _prefixes_longest_first:
        if name.startswith(prefix):
            return owner_mapping[prefix]

    canon = canonical_test_name(name)
    owner = _canonical_mapping.get(canon)
    if owner:
        return owner
    for prefix in _canonical_prefixes_longest_first:
        if canon.startswith(prefix):
            return _canonical_mapping[prefix]

    return UNKNOWN_OWNER
