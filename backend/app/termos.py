"""Envio de áudio fidelidade + PDF termos (n8n → Chatwoot)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.integrations.termos_webhook import enviar_termos_webhook


def _url_termos(unidade_id: int | None = None) -> str:
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    return resolver_url_ferramenta(
        "enviar_termos",
        unidade_id=unidade_id,
        fallback_env=settings.termos_webhook_url,
    ).strip()


def enviar_termos(estado: dict[str, Any]) -> dict[str, Any]:
    """
    Prioridade:
    1) URL no painel Ferramentas ou TERMOS_PROVIDER=webhook → webhook n8n (sempre)
    2) Mock local só se provider=mock e sem URL configurada
    """
    settings = get_settings()
    provider = (settings.termos_provider or "mock").lower()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None

    url = _url_termos(uid)
    usar_webhook = bool(url) or provider == "webhook"

    if usar_webhook:
        if not url:
            return {
                "resultado": "erro",
                "motivo": "enviar_termos sem webhook — cadastre no painel Ferramentas",
                "audio_enviado": False,
                "termo_enviado": False,
                "erro": True,
            }
        return enviar_termos_webhook(estado)

    return {
        "resultado": "ok",
        "audio_enviado": True,
        "termo_enviado": True,
        "motivo": "Termos mock local",
        "provider": "mock",
        "erro": False,
    }
