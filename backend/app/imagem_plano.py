"""Envio de imagem do plano (painel local → Chatwoot / webhook n8n)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.integrations.imagem_plano_webhook import enviar_imagem_plano_webhook
from app.media_store import caminho_local_imagem, url_absoluta_imagem

logger = logging.getLogger(__name__)


def _id_plano_estado(estado: dict[str, Any]) -> str:
    return str(
        estado.get("plano_confirmado_id")
        or estado.get("plano_em_negociacao_id")
        or estado.get("plano_apresentado_id")
        or estado.get("id_plano")
        or ""
    ).strip()


def _obter_plano_imagem(estado: dict[str, Any]) -> dict[str, Any] | None:
    from app.planos_admin import obter_plano

    raw = _id_plano_estado(estado)
    if not raw:
        return None
    try:
        return obter_plano(int(raw))
    except (TypeError, ValueError):
        return None


def _base_resultado(
    *,
    id_plano: str,
    imagem_url: str,
    abs_url: str,
) -> dict[str, Any]:
    """Campos comuns — painel sempre pode exibir se houver arquivo no plano."""
    return {
        "id_plano": id_plano,
        "imagem_url": imagem_url,
        "imagem_url_absoluta": abs_url,
        "imagem_painel": bool(imagem_url),
    }


def enviar_imagem_plano(estado: dict[str, Any]) -> dict[str, Any]:
    """
    - Painel de testes: sempre devolve imagem_url local (se existir no plano).
    - Com conversation_id: também dispara webhook n8n / Chatwoot (produção).
    """
    settings = get_settings()
    provider = (settings.imagem_plano_provider or "mock").lower()
    plano = _obter_plano_imagem(estado)
    id_plano = (
        str(plano["id"]) if plano and plano.get("id") is not None else _id_plano_estado(estado)
    )
    imagem_url = str((plano or {}).get("imagem_url") or "").strip()
    abs_url = url_absoluta_imagem(imagem_url) if imagem_url else ""
    local = caminho_local_imagem(imagem_url) if imagem_url else None
    cid = str(estado.get("conversation_id") or "").strip()
    base = _base_resultado(id_plano=id_plano, imagem_url=imagem_url, abs_url=abs_url)

    # Sem conversation_id — só preview no painel (não chama n8n)
    if imagem_url and not cid:
        return {
            **base,
            "resultado": "ok",
            "imagem_enviada": True,
            "motivo": "Imagem do painel (chat local)",
            "provider": "painel_local",
            "erro": False,
        }

    # Chatwoot direto (token + arquivo local)
    if local is not None and cid and settings.chatwoot_api_token:
        from app.integrations import chatwoot as chatwoot_api

        envio = chatwoot_api.enviar_anexo_imagem(cid, str(local))
        if envio.get("ok"):
            return {
                **base,
                "resultado": "ok",
                "imagem_enviada": True,
                "motivo": "Imagem enviada via Chatwoot (painel)",
                "provider": "chatwoot",
                "erro": False,
            }
        logger.warning("Chatwoot anexo falhou, tentando webhook: %s", envio.get("motivo"))

    # Webhook n8n (Chatwoot real) — painel continua mostrando imagem_url local
    if cid and provider == "webhook":
        estado_envio = dict(estado)
        if imagem_url:
            estado_envio["_imagem_url_painel"] = abs_url or imagem_url
            estado_envio["_plano_nome"] = (plano or {}).get("nome") or ""
        out = enviar_imagem_plano_webhook(estado_envio)
        merged = {**base, **out}
        merged["imagem_url"] = imagem_url or merged.get("imagem_url") or ""
        merged["imagem_painel"] = bool(imagem_url)
        merged.setdefault("id_plano", id_plano)
        return merged

    # Mock / fallback
    if imagem_url:
        return {
            **base,
            "resultado": "ok",
            "imagem_enviada": True,
            "motivo": "Imagem do painel (mock)",
            "provider": "painel_local",
            "erro": False,
        }

    return {
        **base,
        "resultado": "ok",
        "imagem_enviada": False,
        "motivo": "Plano sem imagem cadastrada no painel",
        "provider": "mock",
        "erro": False,
    }
