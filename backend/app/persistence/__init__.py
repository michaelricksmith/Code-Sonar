"""Transactional persistence boundary for Code Sonar.

The runtime is imported lazily (PEP 562) so that modules which only need
``app.persistence.schema`` — e.g. ``app.models.user``, which registers the
``users`` table on the shared metadata — do not drag the full persistence
runtime (and its own model imports) into a circular import.
"""

__all__ = ["configure_persistence_from_env", "get_persistence"]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in __all__:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
