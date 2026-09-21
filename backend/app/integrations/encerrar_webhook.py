"""Cliente HTTP — encerrar atendimento via n8n (Chatwoot + PDF IXC)."""

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
    if settings.encerrar_webhook_token:
        h["Authorization"] = f"Bearer {settings.encerrar_webhook_token}"
    return h


def _extrair_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return {
            "resultado": "erro",
            "motivo": "Resposta inválida do webhook",
            "erro": True,
        }

    for _ in range(3):
        if isinstance(data.get("body"), dict):
            data = {**data, **data["body"]}
        elif isinstance(data.get("json"), dict):
            data = {**data, **data["json"]}

    retorno = str(
        data.get("resultado")
        or data.get("Retorno")
        or data.get("retorno")
        or ""
    ).strip()
    retorno_l = retorno.casefold()

    if retorno_l in {"encerrado", "ok", "atendimento inserido"}:
        return {
            "resultado": "ok",
            "motivo": retorno or "Encerrado",
            "erro": False,
        }
    if not retorno:
        return {
            "resultado": "erro",
            "motivo": "Webhook retornou vazio — verifique Respond to Webhook no n8n",
            "erro": True,
        }
    if "erro" in retorno_l or "sem_cadastro" in retorno_l:
        return {"resultado": "erro", "motivo": retorno, "erro": True}

    return {"resultado": "ok", "motivo": retorno, "erro": False}


def encerrar_atendimento_webhook(estado: dict[str, Any]) -> dict[str, Any]:
    """
    Envia snapshot completo + histórico.
    n8n NÃO precisa mais consultar Postgres.
    """
    settings = get_settings()
    from app.ferramentas_catalog import resolver_url_ferramenta

    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "encerrar_atendimento",
        unidade_id=uid,
        fallback_env=settings.encerrar_webhook_url,
    )
    if not url:
        return {
            "resultado": "erro",
            "motivo": "encerrar_atendimento sem webhook — cadastre no painel Ferramentas",
            "erro": True,
        }

    payload = snapshot_cliente(estado, incluir_historico=True)
    if not payload.get("id_cliente"):
        return {
            "resultado": "erro",
            "motivo": "id_cliente ausente",
            "erro": True,
        }

    try:
        with httpx.Client(timeout=settings.encerrar_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Encerrar webhook timeout: %s", url)
        return {
            "resultado": "ok",
            "motivo": "timeout — encerramento disparado",
            "erro": False,
            "timeout": True,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Encerrar webhook falhou: %s", exc)
        return {"resultado": "erro", "motivo": str(exc), "erro": True}

    out = _extrair_payload(data)
    out["provider"] = "webhook"
    return out
