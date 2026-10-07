"""Encerramento de atendimento (n8n: PDF IXC + resolve Chatwoot)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.integrations.encerrar_webhook import encerrar_atendimento_webhook


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def encerrar_atendimento(estado: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    provider = (settings.encerrar_provider or "mock").lower()
    id_cliente = _texto(estado.get("id_cliente"))

    if not id_cliente:
        return {
            "resultado": "erro",
            "motivo": "id_cliente ausente",
            "erro": True,
        }

    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None

    from app.ferramentas_catalog import resolver_url_ferramenta

    url = resolver_url_ferramenta(
        "encerrar_atendimento",
        unidade_id=uid,
        fallback_env=settings.encerrar_webhook_url,
    )
    usar_webhook = bool(url) or provider == "webhook"

    if usar_webhook:
        if not url:
            resultado = {
                "resultado": "erro",
                "motivo": "encerrar_atendimento sem webhook — cadastre no painel Ferramentas",
                "erro": True,
            }
        else:
            resultado = encerrar_atendimento_webhook(estado)
    else:
        resultado = {
            "resultado": "ok",
            "motivo": "Encerramento mock local",
            "provider": "mock",
            "erro": False,
        }

    # O histórico do cliente é mantido depois do encerramento: é o registro do
    # atendimento no painel e o contexto se o cliente voltar a falar.
    return resultado
