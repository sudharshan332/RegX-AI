"""Orchestration helpers that compose First-Level → schema → decision.

Callers inject existing Flask helpers (search, TG validation, AI chat) so this
module does not duplicate HTTP clients.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .decision_engine import decide_outcome, should_auto_write_triage
from .intermittent import match_approved_intermittent, attach_ai_log_validation
from .schema import build_analysis_from_first_level, SCHEMA_VERSION
from .thresholds import load_team_thresholds


def estimate_triage_confidence(first_level: Dict[str, Any]) -> float:
    """Independent triage_confidence heuristic (not averaged with intermittent)."""
    tg = first_level.get("tg_ticket_validation") or {}
    verdict = (tg.get("verdict") or "").strip()
    glean_ok = first_level.get("glean_ok")
    enriched = first_level.get("enriched_tickets") or first_level.get("existing_issues") or []
    best = (first_level.get("best_matching_ticket") or "").strip()

    score = 0.55
    if verdict == "Correct":
        score = 0.88
    elif verdict == "Partial":
        score = 0.65
    elif verdict == "Incorrect":
        score = 0.5
    elif verdict == "Missing":
        score = 0.45
    elif verdict == "Unknown":
        score = 0.4

    if best and enriched:
        score = min(1.0, score + 0.05)
    if glean_ok is False:
        score = min(score, 0.4)
    if first_level.get("analysis"):
        score = min(1.0, score + 0.02)
    return round(score, 3)


def build_intelligent_triage_payload(
    test_result: Dict[str, Any],
    first_level: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
    run_intermittent_ai_validation: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build full schema analysis + decision from an existing First-Level result."""
    thr = thresholds if thresholds is not None else load_team_thresholds()
    exception_summary = (
        test_result.get("exception_summary")
        or (first_level.get("exception_summary") if False else "")
        or ""
    )
    intermittent = match_approved_intermittent(exception_summary)

    # Optional AI log validation path (caller may supply); never required for gating.
    if intermittent.get("is_intermittent") and callable(run_intermittent_ai_validation):
        try:
            ai_val = run_intermittent_ai_validation(test_result, intermittent) or {}
            if ai_val.get("verdict"):
                intermittent = attach_ai_log_validation(
                    intermittent,
                    verdict=ai_val.get("verdict"),
                    reason=ai_val.get("reason") or "",
                    confidence=ai_val.get("confidence"),
                )
        except Exception:
            pass

    triage_confidence = estimate_triage_confidence(first_level)
    first_level = dict(first_level)
    first_level["triage_confidence"] = triage_confidence

    # Build a preliminary analysis without decision, then decide, then rebuild.
    preliminary = build_analysis_from_first_level(
        test_result,
        first_level,
        intermittent=intermittent,
        decision=None,
        triage_confidence=triage_confidence,
    )
    decision = decide_outcome(preliminary, thr)

    # Hybrid write policy annotation (actual write is caller's responsibility).
    if decision.get("outcome") == "AUTO_TRIAGE":
        if should_auto_write_triage(decision, preliminary, thr):
            decision["auto_triage_write"] = "eligible"
            decision["auto_triage_write_detail"] = (
                "Hybrid: TG Correct/VALID + open ticket — eligible for auto update-triage"
            )
        else:
            decision["auto_triage_write"] = "recommend_only"
            decision["auto_triage_write_detail"] = (
                "Hybrid: recommend only (TG not Correct/VALID or ticket not open)"
            )

    analysis = build_analysis_from_first_level(
        test_result,
        first_level,
        intermittent=intermittent,
        decision=decision,
        triage_confidence=triage_confidence,
    )
    analysis["schema_version"] = SCHEMA_VERSION
    return {
        "intelligent_triage": analysis,
        "decision": decision,
        "triage_confidence": triage_confidence,
        "intermittent_confidence": intermittent.get("intermittent_confidence"),
        "thresholds": {
            "version": thr.get("version"),
            "T_high": thr.get("T_high"),
            "T_auto": thr.get("T_auto"),
            "T_mid": thr.get("T_mid"),
            "T_intermittent": thr.get("T_intermittent"),
        },
    }


def persist_analysis_into_tag_payload(
    tag_payload: Dict[str, Any],
    testcase_id: str,
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """Embed intelligent_triage map keyed by testcase_id into saved-tag payload."""
    out = dict(tag_payload or {})
    mapping = dict(out.get("intelligent_triage") or {})
    if testcase_id:
        mapping[str(testcase_id)] = analysis
    out["intelligent_triage"] = mapping
    return out
