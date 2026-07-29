"""
Per-tag manually appended JITA task IDs.

When a user adds task IDs via "+", they are stored against the active regression
tag so later tag-based fetches still include those tasks (unique merge).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

TASK_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")


def normalize_task_id(task_id: Any) -> Optional[str]:
    if task_id is None:
        return None
    s = str(task_id).strip().lower()
    if not TASK_ID_RE.match(s):
        return None
    return s


def normalize_task_id_list(task_ids: Any) -> List[str]:
    if not task_ids:
        return []
    if isinstance(task_ids, str):
        parts = re.split(r"[\s,]+", task_ids.strip())
    elif isinstance(task_ids, (list, tuple)):
        parts = []
        for item in task_ids:
            if item is None:
                continue
            if isinstance(item, str) and ("," in item or " " in item.strip()):
                parts.extend(re.split(r"[\s,]+", item.strip()))
            else:
                parts.append(str(item).strip())
    else:
        parts = [str(task_ids).strip()]

    out: List[str] = []
    seen = set()
    for part in parts:
        nid = normalize_task_id(part)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out


def get_tag_extra_map(config: dict) -> Dict[str, List[str]]:
    raw = config.get("tag_extra_task_ids") or {}
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, List[str]] = {}
    for tag, ids in raw.items():
        key = str(tag).strip()
        if not key:
            continue
        cleaned[key] = normalize_task_id_list(ids)
    return cleaned


def get_extras_for_tag(config: dict, tag: str) -> List[str]:
    if not tag:
        return []
    return list(get_tag_extra_map(config).get(str(tag).strip(), []))


def merge_unique_ids(base: List[str], extra: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for part in list(base or []) + list(extra or []):
        nid = normalize_task_id(part)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
    return out


def append_extras_for_tag(config: dict, tag: str, task_ids: Any) -> Tuple[dict, List[str], List[str]]:
    """
    Append task IDs under config['tag_extra_task_ids'][tag].

    Returns (updated_config, merged_list_for_tag, newly_added).
    """
    tag_key = (tag or "").strip()
    if not tag_key:
        raise ValueError("tag is required")

    incoming = normalize_task_id_list(task_ids)
    if not incoming:
        raise ValueError("No valid 24-char JITA task IDs provided")

    mapping = get_tag_extra_map(config)
    existing = list(mapping.get(tag_key, []))
    seen = set(existing)
    newly_added: List[str] = []
    for tid in incoming:
        if tid in seen:
            continue
        seen.add(tid)
        existing.append(tid)
        newly_added.append(tid)

    mapping[tag_key] = existing
    updated = dict(config)
    updated["tag_extra_task_ids"] = mapping
    return updated, existing, newly_added


def remove_extras_for_tag(config: dict, tag: str, task_ids: Any) -> Tuple[dict, List[str], List[str]]:
    """
    Remove task IDs from config['tag_extra_task_ids'][tag].

    Returns (updated_config, remaining_list_for_tag, removed_ids).
    Empty remaining list deletes the tag key from the map.
    """
    tag_key = (tag or "").strip()
    if not tag_key:
        raise ValueError("tag is required")

    incoming = normalize_task_id_list(task_ids)
    if not incoming:
        raise ValueError("No valid 24-char JITA task IDs provided")

    mapping = get_tag_extra_map(config)
    existing = list(mapping.get(tag_key, []))
    remove_set = set(incoming)
    removed: List[str] = [tid for tid in existing if tid in remove_set]
    remaining = [tid for tid in existing if tid not in remove_set]

    if remaining:
        mapping[tag_key] = remaining
    elif tag_key in mapping:
        del mapping[tag_key]

    updated = dict(config)
    updated["tag_extra_task_ids"] = mapping
    return updated, remaining, removed


def task_has_tag(tester_tags: Any, expected_tag: str) -> bool:
    """Return True if expected_tag is present in tester_tags list."""
    if not expected_tag:
        return False
    if not isinstance(tester_tags, list):
        return False
    expected = str(expected_tag).strip()
    for t in tester_tags:
        if str(t).strip() == expected:
            return True
    return False


def classify_task_ids_against_tag(
    task_ids: List[str],
    expected_tag: str,
    task_meta_by_id: Dict[str, dict],
) -> Dict[str, List[str]]:
    """
    Split task IDs into matched / wrong_tag / not_found.

    task_meta_by_id: { lowercase_oid: { "tester_tags": [...] } }
    """
    matched: List[str] = []
    wrong_tag: List[str] = []
    not_found: List[str] = []
    for tid in normalize_task_id_list(task_ids):
        meta = task_meta_by_id.get(tid)
        if not meta:
            not_found.append(tid)
            continue
        if task_has_tag(meta.get("tester_tags"), expected_tag):
            matched.append(tid)
        else:
            wrong_tag.append(tid)
    return {
        "matched": matched,
        "wrong_tag": wrong_tag,
        "not_found": not_found,
    }


def plan_accept_after_tagging(
    classification: Dict[str, List[str]],
    successfully_tagged: List[str],
    failed_to_tag: List[str],
) -> Dict[str, List[str]]:
    """
    After attempting to add missing tester_tag on wrong_tag IDs, compute final sets.

    accepted = already matched + successfully tagged
    rejected_tag_failed = failed_to_tag
    rejected_not_found = not_found (cannot tag)
    """
    matched = list(classification.get("matched") or [])
    not_found = list(classification.get("not_found") or [])
    ok_tagged = normalize_task_id_list(successfully_tagged)
    fail_tagged = normalize_task_id_list(failed_to_tag)
    # Do not accept anything that failed tagging
    ok_set = set(ok_tagged) - set(fail_tagged)
    accepted = merge_unique_ids(matched, list(ok_set))
    return {
        "accepted": accepted,
        "tagged_now": [t for t in ok_tagged if t in ok_set],
        "rejected_tag_failed": fail_tagged,
        "rejected_not_found": not_found,
    }
