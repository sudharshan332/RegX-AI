"""
Services for the RegX-AI agent framework.

Keep this init lazy so ``jarvis_service`` can be imported without loading
the rest of the agent framework.
"""

__all__ = ["PatternCache", "CostTracker"]


def __getattr__(name):
    if name == "PatternCache":
        from .pattern_cache import PatternCache
        return PatternCache
    if name == "CostTracker":
        from .cost_tracker import CostTracker
        return CostTracker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")