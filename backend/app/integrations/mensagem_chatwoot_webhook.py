"""Cliente HTTP — envio de mensagens de texto da Eva via n8n → Chatwoot."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    settings = get_settings()
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.chatwoot_msg_webhook_token:
        h["Authorization"] = f"Bearer {settings.chatwoot_msg_webhook_token}"
    return h


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def enviar_mensagens_chatwoot_webhook(
    conversation_id: str | int,
    mensagens: list[str],
    *,
    id_cliente: str = "",
    contact_id: str = "",
) -> dict[str, Any]:
    """Dispara n8n envia_mensagem_eva — uma ou várias bolhas WhatsApp."""
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    url = resolver_url_ferramenta(
        "enviar_mensagem",
        fallback_env=settings.chatwoot_msg_webhook_url,
    )
    if not url:
        return {"ok": False, "motivo": "enviar_mensagem sem webhook — cadastre no painel Ferramentas"}

    textos = [_texto(m) for m in mensagens if _texto(m)]
    if not textos:
        return {"ok": False, "motivo": "sem conteúdo para enviar"}

    cid = _texto(conversation_id)
    if not cid:
        return {"ok": False, "motivo": "conversation_id ausente"}

    payload: dict[str, Any] = {
        "conversation_id": cid,
        "id_cliente": _texto(id_cliente),
        "contact_id": _texto(contact_id),
        "outputs": textos,
    }
    if len(textos) == 1:
        payload["mensagem"] = textos[0]

    try:
        with httpx.Client(timeout=settings.chatwoot_msg_webhook_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
    except httpx.TimeoutException:
        logger.warning("Mensagem Chatwoot webhook timeout: %s", url)
        return {"ok": False, "motivo": "timeout", "timeout": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mensagem Chatwoot webhook falhou: %s", exc)
        return {"ok": False, "motivo": str(exc)}

    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        data = {}

    for _ in range(2):
        if isinstance(data.get("body"), dict):
            data = {**data, **data["body"]}

    ok = (
        str(data.get("resultado") or "").lower() == "ok"
        or data.get("ok") is True
        or data.get("sucesso") is True
        or str(data.get("sucesso") or "").lower() == "true"
    )
    if data.get("erro") is True or str(data.get("resultado") or "").lower() == "erro":
        ok = False

    return {
        "ok": ok,
        "enviadas": int(data.get("enviadas") or (len(textos) if ok else 0)),
        "total": int(data.get("total") or len(textos)),
        "motivo": _texto(data.get("motivo")) or ("Mensagens enviadas" if ok else "Falha no n8n"),
        "provider": "webhook",
        "raw": data,
    }
