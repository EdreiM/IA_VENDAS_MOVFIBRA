"""Cliente LLM — OpenAI API ou Ollama local."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.config import get_settings
from app import ia_config

# Sem isto o cliente OpenAI espera até 10 minutos por resposta — e o cliente no WhatsApp também
TIMEOUT_SEGUNDOS = 30.0
TENTATIVAS_EXTRAS = 1


def modelo_ativo() -> str:
    """Identifica provider+modelo em uso (ex.: 'openai:gpt-4.1-mini')."""
    provider = ia_config.resolver_llm_provider()
    if provider == "ollama":
        return f"ollama:{get_settings().ollama_model}"
    return f"{provider}:{ia_config.resolver_openai_model()}"


def chat(
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    provider = ia_config.resolver_llm_provider()
    temp = (
        float(temperature)
        if temperature is not None
        else ia_config.resolver_temperatura(default=0.2)
    )

    if provider == "ollama":
        client = OpenAI(
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            api_key="ollama",
            timeout=TIMEOUT_SEGUNDOS,
            max_retries=TENTATIVAS_EXTRAS,
        )
        model = settings.ollama_model
    else:
        api_key = ia_config.resolver_openai_api_key()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY não configurada — salve no painel (Config IA) ou no .env"
            )
        client = OpenAI(api_key=api_key, timeout=TIMEOUT_SEGUNDOS, max_retries=TENTATIVAS_EXTRAS)
        model = ia_config.resolver_openai_model()

    extras: dict[str, Any] = {}
    if response_format is not None:
        extras["response_format"] = response_format

    response = client.chat.completions.create(
        model=model,
        temperature=temp,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **extras,
    )
    return (response.choices[0].message.content or "").strip()
