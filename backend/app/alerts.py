"""Alertas operacionais (falha de ferramenta → Evolution e/ou Chatwoot)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.allowlist import normalizar_telefone
from app.config import get_settings
from app.integrations import chatwoot as chatwoot_api

logger = logging.getLogger(__name__)


def _numeros_alerta() -> list[str]:
    settings = get_settings()
    raw = settings.alert_phones or settings.evolution_alert_number or ""
    out: list[str] = []
    for part in raw.split(","):
        n = normalizar_telefone(part)
        if n and n not in out:
            out.append(n)
    return out


def _formatar(contexto: str, detalhe: str) -> str:
    settings = get_settings()
    tpl = settings.alert_message_template or "Eva alerta: {contexto} — {detalhe}"
    try:
        return tpl.format(contexto=contexto, detalhe=detalhe)
    except Exception:  # noqa: BLE001
        return f"Eva alerta: {contexto} — {detalhe}"


def _enviar_evolution(texto: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.evolution_api_url or not settings.evolution_api_key:
        return {"ok": False, "motivo": "evolution não configurada"}

    numeros = _numeros_alerta()
    if not numeros:
        return {"ok": False, "motivo": "nenhum número de alerta"}

    enviados = 0
    erros: list[str] = []
    url = settings.evolution_api_url.rstrip("/") + "/send/text"
    for number in numeros:
        try:
            with httpx.Client(timeout=15) as client:
                client.post(
                    url,
                    headers={"apikey": settings.evolution_api_key},
                    json={
                        "number": number,
                        "text": texto,
                    },
                )
            enviados += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha alerta Evolution (%s): %s", number, exc)
            erros.append(str(exc))
    return {"ok": enviados > 0, "enviados": enviados, "erros": erros}


def _enviar_chatwoot(texto: str) -> dict[str, Any]:
    settings = get_settings()
    cid = (settings.alert_chatwoot_conversation_id or "").strip()
    if not cid:
        return {"ok": False, "motivo": "alert_chatwoot_conversation_id vazio"}
    return chatwoot_api.enviar_mensagem(
        cid,
        texto,
        message_type="outgoing",
        private=bool(settings.alert_chatwoot_private),
    )


def enviar_alerta(contexto: str, detalhe: str = "") -> dict[str, Any]:
    """Dispara alerta conforme ALERT_PROVIDER."""
    settings = get_settings()
    provider = (settings.alert_provider or "none").strip().lower()
    if provider in {"", "none", "off"}:
        return {"ok": False, "motivo": "alertas desligados"}

    texto = _formatar(contexto, detalhe or "")
    if provider == "chatwoot":
        return {"provider": "chatwoot", **_enviar_chatwoot(texto)}
    if provider == "both":
        evo = _enviar_evolution(texto)
        cw = _enviar_chatwoot(texto)
        return {"provider": "both", "evolution": evo, "chatwoot": cw, "ok": evo.get("ok") or cw.get("ok")}
    # default evolution
    return {"provider": "evolution", **_enviar_evolution(texto)}
