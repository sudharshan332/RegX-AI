"""Resolve RegX-AI workspace paths relative to this package (no hard-coded /Users paths)."""

from __future__ import annotations

import os

# backend/agents/paths.py → backend/agents → backend → repo root
_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_AGENTS_DIR)
_WORKSPACE_ROOT = os.path.dirname(_BACKEND_DIR)


def workspace_root() -> str:
    return _WORKSPACE_ROOT


def backend_dir() -> str:
    return _BACKEND_DIR


def agents_data_dir() -> str:
    path = os.path.join(_AGENTS_DIR, "data")
    os.makedirs(path, exist_ok=True)
    return path


def agents_config_dir() -> str:
    return os.path.join(_AGENTS_DIR, "config")


def data_dir() -> str:
    return os.path.join(_WORKSPACE_ROOT, "data")


def intermittent_patterns_file() -> str:
    return os.path.join(_BACKEND_DIR, "intermittent_patterns.json")


def rdm_patterns_file() -> str:
    return os.path.join(_WORKSPACE_ROOT, "data", "rdm_failure_patterns.json")
