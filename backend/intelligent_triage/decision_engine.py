"""First-Level decision engine for Intelligent Triage (Phase 2).

Outcomes:
  RERUN_TESTCASE | AUTO_TRIAGE | NEEDS_DEEP_ANALYSIS | INSUFFICIENT_EVIDENCE | HUMAN_REVIEW

Hard rules:
  - Never average intermittent_confidence with triage_confidence
  - Deep AI recommended ≠ started; never auto-start Deep AI
  - Never AUTO_TRIAGE solely on Genie without AI validation
  - Never claim MCP success when ok is false
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .thresholds import DEFAULT_THRESHOLDS


class DecisionOutcome(str, Enum):
    RERUN_TESTCASE = "RERUN_TESTCASE"
    AUTO_TRIAGE = "AUTO_TRIAGE"
    NEEDS_DEEP_ANALYSIS = "NEEDS_DEEP_ANALYSIS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    HUMAN_REVIEW = "HUMAN_REVIEW"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _top_candidate(analysis_or_candidates) -> Optional[Dict[str, Any]]:
    if isinstance(analysis_or_candidates, list):
        candidates = analysis_or_candidates
    else:
        search = ((analysis_or_candidates or {}).get("glean_candidates") or {}).get("search") or {}
        candidates = search.get("candidates") or []
    if not candidates:
        return None
    return candidates[0]


def _tg_verdict(analysis: Dict[str, Any]) -> str:
    tg = (analysis or {}).get("triage_genie") or {}
    ai = tg.get("ai_validation") or {}
    return str(ai.get("verdict") or "").strip()


def _tg_ticket(analysis: Dict[str, Any]) -> str:
    tg = (analysis or {}).get("triage_genie") or {}
    original = tg.get("original") or {}
    ai = tg.get("ai_validation") or {}
    return str(ai.get("ticket") or original.get("ticket") or "").strip()


def decide_outcome(
    analysis: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute First-Level decision from a schema analysis object.

    Returns a decision dict suitable for analysis['decision'].
    Does not mutate Deep AI started flags (always False here).
    Does not perform auto-triage writes (caller decides hybrid write).
    """
    thr = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        thr.update(thresholds)

    reasons: List[str] = []
    intermittent = (analysis or {}).get("intermittent_analysis") or {}
    triage = (analysis or {}).get("triage_analysis") or {}
    mcp = (analysis or {}).get("mcp_health") or {}
    glean_mcp = ((analysis or {}).get("glean_candidates") or {}).get("search", {}).get("mcp_health") or mcp.get("glean") or {}
    jita = (analysis or {}).get("jita") or {}

    triage_conf = triage.get("triage_confidence")
    try:
        triage_conf_f = float(triage_conf) if triage_conf is not None else None
    except (TypeError, ValueError):
        triage_conf_f = None

    intermittent_conf = intermittent.get("intermittent_confidence")
    try:
        intermittent_conf_f = float(intermittent_conf) if intermittent_conf is not None else None
    except (TypeError, ValueError):
        intermittent_conf_f = None

    # --- Insufficient evidence ---
    log_url = (jita.get("test_log_url") or "").strip()
    exception_summary = (jita.get("exception_summary") or "").strip()
    glean_available = glean_mcp.get("available")
    glean_ok = glean_mcp.get("ok")

    if (glean_available is False or glean_ok is False) and not exception_summary and not log_url:
        reasons.append("Glean MCP unhealthy and no exception/log evidence")
        return _pack(
            DecisionOutcome.INSUFFICIENT_EVIDENCE,
            reasons,
            thr,
            deep_ai_recommended=False,
        )

    if not exception_summary and not log_url:
        reasons.append("Missing exception summary and test log URL")
        return _pack(
            DecisionOutcome.INSUFFICIENT_EVIDENCE,
            reasons,
            thr,
            deep_ai_recommended=False,
        )

    # --- Approved intermittent → RERUN ---
    if (
        intermittent.get("is_intermittent")
        and intermittent.get("approved_pattern")
        and intermittent_conf_f is not None
        and intermittent_conf_f >= float(thr.get("T_intermittent", 0.80))
    ):
        # Optional AI log validation may lower confidence; if present and rejected, fall through.
        ai_val = intermittent.get("ai_log_validation") or {}
        if ai_val.get("verdict") in ("Rejected", "Incorrect", "NotIntermittent"):
            reasons.append(
                "Approved intermittent pattern matched but AI log validation rejected it"
            )
        else:
            reasons.append(
                "Approved intermittent pattern matched (confidence=%.2f, independent of triage)"
                % intermittent_conf_f
            )
            return _pack(
                DecisionOutcome.RERUN_TESTCASE,
                reasons,
                thr,
                deep_ai_recommended=False,
            )

    tg_verdict = _tg_verdict(analysis)
    tg_ticket = _tg_ticket(analysis)
    top = _top_candidate(analysis)
    top_score = float((top or {}).get("match_score") or 0.0)
    top_open = (top or {}).get("is_open")
    best_ticket = (triage.get("best_matching_ticket") or "").strip()
    ai_val = ((analysis or {}).get("triage_genie") or {}).get("ai_validation") or {}
    ticket_open = ai_val.get("is_open")
    if ticket_open is None and top and (top.get("ticket") or "").upper() == tg_ticket.upper():
        ticket_open = top_open

    # Cap confidence messaging when MCP failed (do not fabricate evidence).
    if glean_ok is False:
        reasons.append("Glean MCP not ok — confidence capped; no fabricated tickets")

    # --- AUTO_TRIAGE ---
    # Never on Genie alone: require AI validation Correct/VALID + open ticket + scores.
    valid_verdicts = {"Correct", "VALID", "Valid"}
    if (
        tg_verdict in valid_verdicts
        and tg_ticket
        and (not best_ticket or best_ticket.upper() == tg_ticket.upper())
        and triage_conf_f is not None
        and triage_conf_f >= float(thr.get("T_auto", 0.85))
        and top_score >= float(thr.get("T_high", 0.75))
        and (ticket_open is True or ticket_open is None)
        and (not thr.get("require_open_ticket_for_auto") or ticket_open is True)
    ):
        if ticket_open is not True and thr.get("require_open_ticket_for_auto"):
            reasons.append("TG Correct but ticket open-state unknown/closed → HUMAN_REVIEW")
        else:
            reasons.append(
                "TG AI validation %s, open ticket, triage_confidence=%.2f, match_score=%.2f"
                % (tg_verdict, triage_conf_f, top_score)
            )
            return _pack(
                DecisionOutcome.AUTO_TRIAGE,
                reasons,
                thr,
                deep_ai_recommended=False,
            )

    # --- HUMAN_REVIEW for Genie/Glean conflict or mid confidence ---
    if tg_verdict in ("Incorrect", "Partial"):
        reasons.append("TG AI validation is %s — ambiguous / conflict" % tg_verdict)
        return _pack(
            DecisionOutcome.HUMAN_REVIEW,
            reasons,
            thr,
            deep_ai_recommended=False,
        )

    if triage_conf_f is not None and float(thr.get("T_mid", 0.55)) <= triage_conf_f < float(thr.get("T_auto", 0.85)):
        reasons.append(
            "triage_confidence=%.2f in mid band [T_mid, T_auto)" % triage_conf_f
        )
        return _pack(
            DecisionOutcome.HUMAN_REVIEW,
            reasons,
            thr,
            deep_ai_recommended=False,
        )

    # --- NEEDS_DEEP_ANALYSIS (recommended only; never started) ---
    issue_type = (triage.get("issue_type") or "").lower()
    has_usable_logs = bool(log_url) or bool(exception_summary)
    if has_usable_logs and (
        "product" in issue_type
        or "unknown" in issue_type
        or tg_verdict in ("Missing", "Unknown", "")
        or (triage_conf_f is not None and triage_conf_f < float(thr.get("T_mid", 0.55)))
    ):
        reasons.append("Needs skill-level RCA (Deep AI recommended, not auto-started)")
        return _pack(
            DecisionOutcome.NEEDS_DEEP_ANALYSIS,
            reasons,
            thr,
            deep_ai_recommended=True,
        )

    if glean_ok is False and not top:
        reasons.append("No Glean/Jira candidates and MCP unhealthy")
        return _pack(
            DecisionOutcome.INSUFFICIENT_EVIDENCE,
            reasons,
            thr,
            deep_ai_recommended=False,
        )

    reasons.append("Default: human review required")
    return _pack(
        DecisionOutcome.HUMAN_REVIEW,
        reasons,
        thr,
        deep_ai_recommended=False,
    )


def _pack(
    outcome: DecisionOutcome,
    reasons: List[str],
    thr: Dict[str, Any],
    deep_ai_recommended: bool,
) -> Dict[str, Any]:
    return {
        "outcome": outcome.value if isinstance(outcome, DecisionOutcome) else str(outcome),
        "reasons": reasons,
        "decided_at": _utc_now(),
        "thresholds_version": thr.get("version", "v1"),
        "deep_ai_recommended": bool(deep_ai_recommended),
        "deep_ai_started": False,
        "auto_triage_write": None,
        "auto_triage_write_detail": None,
    }


def should_auto_write_triage(
    decision: Dict[str, Any],
    analysis: Dict[str, Any],
    thresholds: Optional[Dict[str, Any]] = None,
) -> bool:
    """Hybrid policy: auto update-triage only when TG Correct/VALID AND ticket open.

    Otherwise recommend only (even if outcome is AUTO_TRIAGE).
    """
    thr = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        thr.update(thresholds)

    if (decision or {}).get("outcome") != DecisionOutcome.AUTO_TRIAGE.value:
        return False

    if not thr.get("require_tg_correct_for_auto_write", True):
        return True

    tg_verdict = _tg_verdict(analysis)
    if tg_verdict not in {"Correct", "VALID", "Valid"}:
        return False

    ai_val = ((analysis or {}).get("triage_genie") or {}).get("ai_validation") or {}
    if ai_val.get("is_open") is not True:
        return False
    return True
