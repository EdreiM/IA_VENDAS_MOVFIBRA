"""Cliente HTTP — envio de áudio + PDF termos via n8n (Chatwoot)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.webhook_payload import snapshot_cliente

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    settings = get_settings()
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.termos_webhook_token:
        h["Authorization"] = f"Bearer {settings.termos_webhook_token}"
    return h


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _extrair_payload(data: Any) -> dict[str, Any]:
    from app.integrations.webhook_retorno import (
        motivo_erro_ferramenta,
        unwrap_body,
    )

    data = unwrap_body(data)
    if not data:
        return {
            "resultado": "erro",
            "motivo": "Resposta inválida do webhook",
            "audio_enviado": False,
            "termo_enviado": False,
            "erro": True,
            "transferir": True,
        }
    if data.get("errorMessage") or data.get("errorDescription") or data.get("transferir"):
        return {
            "resultado": "erro",
            "motivo": motivo_erro_ferramenta(data, padrao="Falha ao enviar termos"),
            "audio_enviado": False,
            "termo_enviado": False,
            "erro": True,
            "transferir": True,
        }

    resultado = _texto(data.get("resultado")).lower()
    audio = bool(data.get("audio_enviado"))
    termo = bool(data.get("termo_enviado"))
    motivo = _texto(data.get("motivo") or data.get("message"))

    if not resultado and not motivo and not audio and not termo:
        return {
            "resultado": "erro",
            "motivo": "Webhook retornou vazio — verifique Respond to Webhook no n8n",
            "audio_enviado": False,
            "termo_enviado": False,
            "erro": True,
            "transferir": True,
        }

    if not resultado:
        resultado = "ok" if audio and termo else "erro"

    # n8n às vezes marca audio_enviado=false mesmo com áudio no Chatwoot (Resposta Sofia antigo)
    if resultado == "erro" and termo and not audio:
        pass
    elif resultado == "erro" and audio and termo:
        resultado = "ok"

    ok_final = resultado == "ok" or (audio and termo) or (termo and not bool(data.get("transferir")))

    return {
        "resultado": "ok" if ok_final else "erro",
        "audio_enviado": audio or (ok_final and termo),
        "termo_enviado": termo,
        "motivo": motivo or ("Áudio e termo enviados" if ok_final else "Falha parcial"),
        "erro": not ok_final,
        "transferir": bool(data.get("transferir")) or (not termo and resultado == "erro"),
    }


def enviar_termos_webhook(estado: dict[str, Any]) -> dict[str, Any]:
    """Dispara subfluxo n8n — áudio fidelidade + PDF termo no Chatwoot."""
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "enviar_termos",
        unidade_id=uid,
        fallback_env=settings.termos_webhook_url,
    )
    if not url:
        return {
            "resultado": "erro",
            "motivo": "enviar_termos sem webhook — cadastre no painel Ferramentas",
            "audio_enviado": False,
            "termo_enviado": False,
            "erro": True,
        }

    payload = snapshot_cliente(estado, incluir_historico=False)
    faltando: list[str] = []
    if not payload.get("conversation_id"):
        faltando.append("conversation_id")
    if not payload.get("id_contrato_ixc"):
        faltando.append("id_contrato_ixc")
    if not payload.get("ixc_id_cliente"):
        faltando.append("ixc_id_cliente")
    if faltando:
        payload["campos_ausentes"] = faltando
        logger.warning(
            "Termos webhook com campos ausentes (%s) — enviando mesmo assim para %s",
            ", ".join(faltando),
            url,
        )

    try:
        with httpx.Client(timeout=settings.termos_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Termos webhook timeout: %s", url)
        return {
            "resultado": "erro",
            "motivo": "timeout",
            "audio_enviado": False,
            "termo_enviado": False,
            "erro": True,
            "timeout": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Termos webhook falhou: %s", exc)
        return {
            "resultado": "erro",
            "motivo": str(exc),
            "audio_enviado": False,
            "termo_enviado": False,
            "erro": True,
        }

    out = _extrair_payload(data)
    out["provider"] = "webhook"
    return out
