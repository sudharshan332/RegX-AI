"""
Intelligent Triage Phase 2 — schema, decision engine, thresholds, persistence.

Reuses Failed Analysis helpers in test_flask.py; this package holds pure
orchestration logic that can be unit-tested without the full Flask app.
"""

from .schema import (
    SCHEMA_VERSION,
    build_empty_analysis,
    build_analysis_from_first_level,
    merge_glean_ai_validation,
    set_deep_ai_started,
)
from .decision_engine import decide_outcome, DecisionOutcome
from .thresholds import (
    DEFAULT_THRESHOLDS,
    load_team_thresholds,
    save_team_thresholds,
)
from .persistence import (
    failed_analysis_dir,
    load_failed_analysis_tags,
    save_failed_analysis_tags,
    load_failed_analysis_results,
    save_failed_analysis_results,
    delete_failed_analysis_results,
)

__all__ = [
    "SCHEMA_VERSION",
    "build_empty_analysis",
    "build_analysis_from_first_level",
    "merge_glean_ai_validation",
    "set_deep_ai_started",
    "decide_outcome",
    "DecisionOutcome",
    "DEFAULT_THRESHOLDS",
    "load_team_thresholds",
    "save_team_thresholds",
    "failed_analysis_dir",
    "load_failed_analysis_tags",
    "save_failed_analysis_tags",
    "load_failed_analysis_results",
    "save_failed_analysis_results",
    "delete_failed_analysis_results",
]
