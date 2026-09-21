"""Cliente HTTP — envio de imagem do plano via n8n (Chatwoot)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.imagem_plano_payload import montar_payload_imagem_plano

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    settings = get_settings()
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.imagem_plano_webhook_token:
        h["Authorization"] = f"Bearer {settings.imagem_plano_webhook_token}"
    return h


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _extrair_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return {
            "resultado": "erro",
            "imagem_enviada": False,
            "motivo": "Resposta inválida do webhook",
            "erro": True,
        }

    for _ in range(3):
        if isinstance(data.get("body"), dict):
            data = {**data, **data["body"]}
        elif isinstance(data.get("json"), dict):
            data = {**data, **data["json"]}

    resultado = _texto(data.get("resultado")).lower()
    enviada = bool(data.get("imagem_enviada"))
    motivo = _texto(data.get("motivo") or data.get("retorno") or data.get("message"))

    if not resultado:
        if enviada or "enviada" in motivo.casefold():
            resultado = "ok"
        elif motivo:
            resultado = "erro"
        else:
            return {
                "resultado": "erro",
                "imagem_enviada": False,
                "motivo": "Webhook retornou vazio",
                "erro": True,
            }

    ok = resultado == "ok" or enviada
    return {
        "resultado": "ok" if ok else "erro",
        "imagem_enviada": ok,
        "id_plano": _texto(data.get("id_plano")),
        "motivo": motivo or ("Imagem enviada" if ok else "Imagem não enviada"),
        "erro": not ok,
    }


def enviar_imagem_plano_webhook(estado: dict[str, Any]) -> dict[str, Any]:
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "enviar_imagem_plano",
        unidade_id=uid,
        fallback_env=settings.imagem_plano_webhook_url,
    )
    if not url:
        return {
            "resultado": "erro",
            "imagem_enviada": False,
            "motivo": "enviar_imagem_plano sem webhook — cadastre no painel Ferramentas",
            "erro": True,
        }

    payload = montar_payload_imagem_plano(estado)

    faltando: list[str] = []
    if not payload.get("conversation_id"):
        faltando.append("conversation_id")
    if not payload.get("imagem_url"):
        faltando.append("imagem_url")
    if not payload.get("id_plano"):
        faltando.append("id_plano")
    if faltando:
        return {
            "resultado": "erro",
            "imagem_enviada": False,
            "motivo": f"Campos ausentes: {', '.join(faltando)}",
            "erro": True,
        }

    try:
        with httpx.Client(timeout=settings.imagem_plano_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Imagem plano webhook timeout: %s", url)
        return {
            "resultado": "erro",
            "imagem_enviada": False,
            "motivo": "timeout",
            "erro": True,
            "timeout": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Imagem plano webhook falhou: %s", exc)
        return {
            "resultado": "erro",
            "imagem_enviada": False,
            "motivo": str(exc),
            "erro": True,
        }

    out = _extrair_payload(data)
    out["provider"] = "webhook"
    if payload.get("imagem_url_relativa"):
        out["imagem_url"] = payload["imagem_url_relativa"]
    return out
