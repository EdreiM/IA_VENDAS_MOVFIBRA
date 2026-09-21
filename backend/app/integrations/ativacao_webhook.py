"""Cliente HTTP — ativação de contrato IXC via n8n."""

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
    if settings.ativacao_webhook_token:
        h["Authorization"] = f"Bearer {settings.ativacao_webhook_token}"
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
            "ativado": False,
            "erro": True,
            "transferir": True,
        }
    if data.get("errorMessage") or data.get("errorDescription") or data.get("transferir"):
        return {
            "resultado": "erro",
            "motivo": motivo_erro_ferramenta(data, padrao="Falha na ativação"),
            "ativado": False,
            "erro": True,
            "transferir": True,
        }

    resultado = _texto(data.get("resultado")).lower()
    motivo = _texto(data.get("motivo") or data.get("message") or data.get("retorno"))
    ativado = bool(data.get("ativado"))

    if not resultado:
        if ativado or "sucesso" in motivo.casefold() or "ativado" in motivo.casefold():
            resultado = "ok"
        elif motivo:
            resultado = "erro"
        else:
            return {
                "resultado": "erro",
                "motivo": "Webhook retornou vazio — verifique Respond to Webhook no n8n",
                "ativado": False,
                "erro": True,
                "transferir": True,
            }

    ok = resultado == "ok" and not data.get("erro")
    return {
        "resultado": "ok" if ok else "erro",
        "ativado": ok or ativado,
        "id_contrato_ixc": _texto(data.get("id_contrato_ixc")),
        "motivo": motivo or ("Contrato ativado" if ok else "Falha na ativação"),
        "erro": not ok,
        "transferir": (not ok) or bool(data.get("transferir")),
    }


def ativar_cliente_webhook(estado: dict[str, Any]) -> dict[str, Any]:
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "ativar_cliente",
        unidade_id=uid,
        fallback_env=settings.ativacao_webhook_url,
    )
    if not url:
        return {
            "resultado": "erro",
            "motivo": "ativar_cliente sem webhook — cadastre no painel Ferramentas",
            "ativado": False,
            "erro": True,
        }

    payload = snapshot_cliente(estado, incluir_historico=False)
    if not payload.get("id_contrato_ixc"):
        return {
            "resultado": "erro",
            "motivo": "id_contrato_ixc ausente",
            "ativado": False,
            "erro": True,
        }

    try:
        with httpx.Client(timeout=settings.ativacao_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Ativação webhook timeout: %s", url)
        return {
            "resultado": "erro",
            "motivo": "timeout",
            "ativado": False,
            "erro": True,
            "timeout": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ativação webhook falhou: %s", exc)
        return {
            "resultado": "erro",
            "motivo": str(exc),
            "ativado": False,
            "erro": True,
        }

    out = _extrair_payload(data)
    out["provider"] = "webhook"
    return out
