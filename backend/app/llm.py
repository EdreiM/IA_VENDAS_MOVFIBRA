"""Cliente LLM — OpenAI, Anthropic (Claude) ou Ollama local, escolhido no painel."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from app.config import get_settings
from app import ia_config

# Sem isto o cliente OpenAI espera até 10 minutos por resposta — e o cliente no WhatsApp também
TIMEOUT_SEGUNDOS = 30.0
TENTATIVAS_EXTRAS = 1

# Resposta da Eva e JSON do interpretador são curtos; o raciocínio do Claude conta neste limite
MAX_TOKENS_CLAUDE = 4096
# Claude Sonnet 5.5: se o filtro de segurança recusar, a própria API refaz no modelo indicado
_FALLBACK_SONNET = "server-side-fallback-2026-07-01"


class RecusaDoModelo(RuntimeError):
    """O modelo recusou responder (stop_reason "refusal"): quem chamou trata como falha."""


def erros_de_requisicao() -> tuple[type[BaseException], ...]:
    """Erros 400 dos provedores (schema recusado, parâmetro inválido)."""
    from openai import BadRequestError as OpenAIBadRequest

    erros: list[type[BaseException]] = [OpenAIBadRequest]
    try:
        from anthropic import BadRequestError as AnthropicBadRequest

        erros.append(AnthropicBadRequest)
    except ImportError:
        pass
    return tuple(erros)


def modelo_ativo() -> str:
    """Identifica provider+modelo em uso (ex.: 'openai:gpt-4.1-mini', 'anthropic:claude-haiku-5-5')."""
    provider = ia_config.resolver_llm_provider()
    if provider == "ollama":
        return f"ollama:{get_settings().ollama_model}"
    return f"{provider}:{ia_config.resolver_modelo_em_uso()}"


def chat(
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> str:
    settings = get_settings()
    provider = ia_config.resolver_llm_provider()
    espera = float(timeout or TIMEOUT_SEGUNDOS)
    if provider == "anthropic":
        return _chat_claude(system, user, response_format=response_format, espera=espera)
    temp = (
        float(temperature)
        if temperature is not None
        else ia_config.resolver_temperatura(default=0.2)
    )

    if provider == "ollama":
        client = OpenAI(
            base_url=f"{settings.ollama_base_url.rstrip('/')}/v1",
            api_key="ollama",
            timeout=espera,
            max_retries=TENTATIVAS_EXTRAS,
        )
        model = settings.ollama_model
    else:
        api_key = ia_config.resolver_openai_api_key()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY não configurada — salve no painel (Config IA) ou no .env"
            )
        client = OpenAI(api_key=api_key, timeout=espera, max_retries=TENTATIVAS_EXTRAS)
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
    _registrar_custo(provider, model, getattr(response, "usage", None))
    return (response.choices[0].message.content or "").strip()


def _chat_claude(
    system: str, user: str, *, response_format: dict[str, Any] | None, espera: float
) -> str:
    """Mesma chamada pela API da Anthropic.

    - `temperature` não vai: os modelos Claude 5.5 recusam valores fora do padrão (400).
      O tom vem do prompt.
    - O esforço de raciocínio (`output_config.effort`) vem do painel; "low" é o mais barato
      e rápido, e basta para ler a mensagem e escrever a resposta curta da Eva.
    - O prompt de sistema vai com cache: ele se repete em toda mensagem e a leitura em cache
      custa um décimo da entrada.
    - O schema JSON do interpretador (formato da OpenAI) vira `output_config.format`.
    """
    import anthropic

    api_key = ia_config.resolver_anthropic_api_key()
    if not api_key:
        raise RuntimeError(
            "Chave da Anthropic não configurada — salve no painel (Config IA) ou no .env"
        )
    model = ia_config.resolver_anthropic_model()
    client = anthropic.Anthropic(api_key=api_key, timeout=espera, max_retries=TENTATIVAS_EXTRAS)

    output_config: dict[str, Any] = {"effort": ia_config.resolver_esforco_claude()}
    schema = ((response_format or {}).get("json_schema") or {}).get("schema")
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    pedido: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS_CLAUDE,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": output_config,
    }
    if model.startswith("claude-sonnet-5-5"):
        response = client.beta.messages.create(betas=[_FALLBACK_SONNET], fallbacks="default", **pedido)
    else:
        response = client.messages.create(**pedido)
    _registrar_custo("anthropic", getattr(response, "model", None) or model, getattr(response, "usage", None))
    if response.stop_reason == "refusal":
        categoria = getattr(getattr(response, "stop_details", None), "category", None)
        raise RecusaDoModelo(f"Claude recusou responder (categoria: {categoria})")
    # A resposta pode começar com blocos de raciocínio: só o texto interessa
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()


def _registrar_custo(provider: str, model: str, usage: Any) -> None:
    try:
        from app import custos

        custos.registrar_chat(provider, model, usage)
    except Exception:  # noqa: BLE001 — registrar custo nunca derruba a chamada
        pass
