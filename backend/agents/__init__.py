"""
Agent Framework for RegX-AI

Cost-effective agent system for automated failure analysis with smart pattern matching.

Keep this package init lightweight. Importing leaf modules such as
``agents.services.jarvis_service`` must not require optional deps like PyYAML
(pulled in by ``agents.base``).
"""

__version__ = "1.0.0"
__all__ = ["BaseAgent", "SkillWrapperAgent", "AgentRegistry"]


def __getattr__(name):
    if name in ("BaseAgent", "SkillWrapperAgent"):
        from .base import BaseAgent, SkillWrapperAgent
        return BaseAgent if name == "BaseAgent" else SkillWrapperAgent
    if name == "AgentRegistry":
        from .registry import AgentRegistry
        return AgentRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")