"""LLMConfig env-var loading tests.

The runtime depends on three required env vars (`LLM_BASE_URL`,
`LLM_API_KEY`, `LLM_MODEL`) and one optional override (`LLM_TIMEOUT_S`).
We test the optional path explicitly because the default was raised
from 30 s → 120 s in the same commit that added the override; it would
be easy to accidentally drop the override later and not notice in CI.
"""

from __future__ import annotations

import pytest

from app.spreadsheet.llm import LLMConfig, LLMConfigError

_REQUIRED = {
    "LLM_BASE_URL": "https://aigw.example.com/v1",
    "LLM_API_KEY": "sk-test",
    "LLM_MODEL": "model-x",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    for k, v in {**_REQUIRED, **extra}.items():
        monkeypatch.setenv(k, v)
    # Clear the optional override unless `extra` set it.
    if "LLM_TIMEOUT_S" not in extra:
        monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)


def test_from_env_uses_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    cfg = LLMConfig.from_env()
    assert cfg.timeout_s == 120.0


def test_from_env_honours_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, LLM_TIMEOUT_S="42.5")
    cfg = LLMConfig.from_env()
    assert cfg.timeout_s == 42.5


def test_from_env_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, LLM_BASE_URL="https://aigw.example.com/v1/")
    cfg = LLMConfig.from_env()
    assert cfg.base_url == "https://aigw.example.com/v1"


def test_from_env_missing_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", _REQUIRED["LLM_BASE_URL"])
    monkeypatch.setenv("LLM_API_KEY", _REQUIRED["LLM_API_KEY"])
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(LLMConfigError, match="LLM_MODEL"):
        LLMConfig.from_env()


def test_from_env_bad_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, LLM_TIMEOUT_S="not-a-number")
    with pytest.raises(LLMConfigError, match="LLM_TIMEOUT_S"):
        LLMConfig.from_env()


@pytest.mark.parametrize("bad", ["0", "-1", "-0.5", "nan", "inf", "-inf"])
def test_from_env_rejects_non_positive_or_non_finite_timeout(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """0, negatives, NaN, +/-inf must fail at config-load time, not at request time."""
    _set_env(monkeypatch, LLM_TIMEOUT_S=bad)
    with pytest.raises(LLMConfigError, match="LLM_TIMEOUT_S"):
        LLMConfig.from_env()
