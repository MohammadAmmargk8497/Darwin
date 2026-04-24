"""Unit tests for src.common.settings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.settings import DarwinSettings, clear_settings_cache, load_settings


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_defaults_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_CONFIG", str(tmp_path / "does-not-exist.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    # Force env_file to a path that doesn't exist so the real .env doesn't leak in
    monkeypatch.chdir(tmp_path)

    s = DarwinSettings()
    assert s.provider == "ollama"
    assert s.model_name == "llama3.1"
    assert s.temperature == 0.7


def test_json_provides_defaults(tmp_path, monkeypatch):
    cfg = tmp_path / "agent.json"
    cfg.write_text(json.dumps({"model_name": "llama3.2:3b", "temperature": 0.5}))
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.chdir(tmp_path)

    s = load_settings(str(cfg))
    assert s.model_name == "llama3.2:3b"
    assert s.temperature == 0.5


def test_env_overrides_json(tmp_path, monkeypatch):
    cfg = tmp_path / "agent.json"
    cfg.write_text(json.dumps({"model_name": "llama3.1", "temperature": 0.7}))
    monkeypatch.setenv("MODEL_NAME", "from-env")
    monkeypatch.setenv("TEMPERATURE", "0.1")
    monkeypatch.chdir(tmp_path)

    s = load_settings(str(cfg))
    assert s.model_name == "from-env"
    assert s.temperature == 0.1


def test_openai_api_key_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    monkeypatch.chdir(tmp_path)

    s = DarwinSettings()
    assert s.openai_api_key == "sk-test-123"


def test_obsidian_api_key_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_API_KEY", "obs-secret")
    monkeypatch.chdir(tmp_path)

    s = DarwinSettings()
    assert s.obsidian_api_key == "obs-secret"


def test_obsidian_vault_path_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    s = DarwinSettings()
    assert s.obsidian_vault_path == Path(str(tmp_path))


def test_malformed_json_falls_back_to_defaults(tmp_path, monkeypatch):
    cfg = tmp_path / "bad.json"
    cfg.write_text("{ not valid json")
    monkeypatch.chdir(tmp_path)

    s = load_settings(str(cfg))
    assert s.provider == "ollama"
    assert s.model_name == "llama3.1"
