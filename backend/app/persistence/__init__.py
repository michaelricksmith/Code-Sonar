"""Transactional persistence boundary for Code Sonar."""

from .runtime import configure_persistence_from_env, get_persistence

__all__ = ["configure_persistence_from_env", "get_persistence"]
