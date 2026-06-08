from __future__ import annotations

from typing import Mapping


BUILTIN_MODEL_ALIASES: dict[str, str] = {
    "gpt5.5": "openai/gpt-5.5",
    "gpt-5.5": "openai/gpt-5.5",
    "gpt_5_5": "openai/gpt-5.5",
    "seed2.0": "ep-20260214145701-frz7j",
    "seed-2.0": "ep-20260214145701-frz7j",
    "seed_2_0": "ep-20260214145701-frz7j",
    "qwen3.7": "qwen/qwen3.7",
    "qwen-3.7": "qwen/qwen3.7",
    "qwen_3_7": "qwen/qwen3.7",
    "gemini3.1": "google/gemini-3.1",
    "gemini-3.1": "google/gemini-3.1",
    "gemini_3_1": "google/gemini-3.1",
    "k2.6": "moonshotai/kimi-k2.6",
    "k-2.6": "moonshotai/kimi-k2.6",
    "k_2_6": "moonshotai/kimi-k2.6",
    "glm5.1": "z-ai/glm-5.1",
    "glm-5.1": "z-ai/glm-5.1",
    "glm_5_1": "z-ai/glm-5.1",
    "claude4.7": "anthropic/claude-opus-4.7",
    "claude-4.7": "anthropic/claude-opus-4.7",
    "claude_4_7": "anthropic/claude-opus-4.7",
    "opus4.7": "anthropic/claude-opus-4.7",
    "opus-4.7": "anthropic/claude-opus-4.7",
}


BUILTIN_CODEX_MODEL_ALIASES: dict[str, str] = {
    "gpt5.5": "gpt-5.5",
    "gpt-5.5": "gpt-5.5",
    "gpt_5_5": "gpt-5.5",
}


def _alias_key(value: str) -> str:
    return value.strip().lower().replace(" ", "")


def _relaxed_alias_key(value: str) -> str:
    return _alias_key(value).replace("_", "-")


def merged_model_aliases(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    aliases = dict(BUILTIN_MODEL_ALIASES)
    for key, value in (overrides or {}).items():
        aliases[_alias_key(str(key))] = str(value)
        aliases[_relaxed_alias_key(str(key))] = str(value)
    return aliases


def resolve_model_alias(model_name: str | None, overrides: Mapping[str, str] | None = None) -> str | None:
    if model_name is None:
        return None
    raw = str(model_name).strip()
    if not raw:
        return raw
    if raw.startswith("exact:"):
        return raw.removeprefix("exact:").strip()
    aliases = merged_model_aliases(overrides)
    return aliases.get(_alias_key(raw)) or aliases.get(_relaxed_alias_key(raw)) or raw


def resolve_codex_model_alias(model_name: str | None, overrides: Mapping[str, str] | None = None) -> str | None:
    if model_name is None:
        return None
    raw = str(model_name).strip()
    if not raw:
        return raw
    if raw.startswith("exact:"):
        return raw.removeprefix("exact:").strip()
    aliases = dict(BUILTIN_CODEX_MODEL_ALIASES)
    for key, value in (overrides or {}).items():
        aliases[_alias_key(str(key))] = str(value)
        aliases[_relaxed_alias_key(str(key))] = str(value)
    return aliases.get(_alias_key(raw)) or aliases.get(_relaxed_alias_key(raw)) or raw
