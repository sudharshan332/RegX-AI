"""
Agent Framework for RegX-AI

Cost-effective agent system for automated failure analysis with smart pattern matching.
"""

from .base import BaseAgent, SkillWrapperAgent
from .registry import AgentRegistry

__version__ = "1.0.0"
__all__ = ["BaseAgent", "SkillWrapperAgent", "AgentRegistry"]