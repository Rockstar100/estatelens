"""Unit tests for multi-provider LLM routing (no network)."""

from __future__ import annotations

from app.config import Settings
from app.services.openrouter import LLMClient


def _settings(**kwargs) -> Settings:
    """Build Settings without reading the project ``.env``."""
    defaults = dict(
        llm_provider="auto",
        openrouter_api_key="",
        openrouter_model="nvidia/nemotron-3-super-120b-a12b:free",
        openrouter_fallback_model="nex-agi/nex-n2.5-mini:free",
        openrouter_base_url="https://openrouter.ai/api/v1",
        groq_api_key="",
        groq_model="openai/gpt-oss-120b",
        groq_base_url="https://api.groq.com/openai/v1",
        gemini_api_key="",
        gemini_model="gemini-3.6-flash",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        app_base_url="http://localhost:8000",
        openrouter_timeout_seconds=45.0,
        openrouter_max_output_tokens=1200,
    )
    defaults.update(kwargs)
    return Settings.model_construct(**defaults)


def test_auto_prefers_groq_then_gemini_then_openrouter():
    s = _settings(
        groq_api_key="g",
        gemini_api_key="m",
        openrouter_api_key="o",
    )
    names = [p.name for p in LLMClient(s)._providers()]
    assert names == ["groq", "gemini", "openrouter"]


def test_auto_skips_missing_keys():
    s = _settings(gemini_api_key="m", openrouter_api_key="o")
    names = [p.name for p in LLMClient(s)._providers()]
    assert names == ["gemini", "openrouter"]


def test_force_gemini_only():
    s = _settings(
        llm_provider="gemini",
        groq_api_key="g",
        gemini_api_key="m",
        openrouter_api_key="o",
    )
    names = [p.name for p in LLMClient(s)._providers()]
    assert names == ["gemini"]


def test_primary_label_includes_provider():
    s = _settings(groq_api_key="g")
    assert LLMClient(s).primary_model_label.startswith("groq/")
