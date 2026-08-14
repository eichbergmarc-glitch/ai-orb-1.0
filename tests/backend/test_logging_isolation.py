"""Tests and real sessions must never share log files."""

from __future__ import annotations

import os
from pathlib import Path

from backend.utils.paths import get_logs_dir


def test_pytest_uses_its_own_log_directory() -> None:
    configured = Path(os.environ["AI_ORB_LOG_DIR"]).resolve()

    assert get_logs_dir().resolve() == configured
    assert ".pytest_cache" in configured.parts
    assert configured.name == str(os.getpid())
    assert configured != (Path(__file__).resolve().parents[2] / "logs").resolve()
