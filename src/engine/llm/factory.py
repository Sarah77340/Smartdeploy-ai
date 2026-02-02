from __future__ import annotations

import os
from typing import Optional

from .ollama_openai import OllamaConfig, OllamaProvider


def get_llm(
    model: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    temperature: float = 0.0,
    timeout_s: int = 600,
) -> OllamaProvider:
    """
    Returns an LLM client exposing chat_json(messages) -> dict.

    - Default provider: Ollama (local)
    - Model can be passed explicitly or via env SMARTDEPLOY_LLM_MODEL
    - Base URL can be passed explicitly or via env OLLAMA_BASE_URL
    """

    model_name = (
        model
        or os.environ.get("SMARTDEPLOY_LLM_MODEL")
        or "mistral"
    )

    ollama_url = (
        base_url
        or os.environ.get("OLLAMA_BASE_URL")
        or "http://127.0.0.1:11434"
    )

    cfg = OllamaConfig(
        base_url=ollama_url,
        model=model_name,
        temperature=temperature,
        timeout_s=timeout_s,
    )
    return OllamaProvider(cfg)
