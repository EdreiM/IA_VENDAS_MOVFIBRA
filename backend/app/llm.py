"""Cliente LLM — OpenAI API ou Ollama local."""

from __future__ import annotations

from openai import OpenAI

from app.config import get_settings
from app import ia_config


def chat(system: str, user: str, *, temperature: float | None = None) -> str:
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
        )
        model = settings.ollama_model
    else:
        api_key = ia_config.resolver_openai_api_key()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY não configurada — salve no painel (Config IA) ou no .env"
            )
        client = OpenAI(api_key=api_key)
        model = ia_config.resolver_openai_model()

    response = client.chat.completions.create(
        model=model,
        temperature=temp,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (response.choices[0].message.content or "").strip()
