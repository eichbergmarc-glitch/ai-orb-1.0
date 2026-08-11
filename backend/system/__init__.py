"""Systemschicht von AI-Orb.

Enthält querschnittliche Systemfunktionen, die von allen anderen
Backend-Modulen genutzt werden dürfen, allen voran das zentrale Logging
(:mod:`backend.system.logging_setup`).
"""

from backend.system.logging_setup import get_logger, setup_logging

__all__ = ["get_logger", "setup_logging"]
