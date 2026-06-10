from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_hermes_profile(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Keep tests from reading the operator's real Hermes profile.

    Individual tests may still override HERMES_HOME or HERMES_CONFIG with
    monkeypatch when they need a specific fixture config.
    """

    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HERMES_CONFIG", str(hermes_home / "config.yaml"))
