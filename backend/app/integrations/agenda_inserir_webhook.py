"""Cliente HTTP — grava agendamento na OS via n8n."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agenda_datetime import slot_para_data_hora
from app.config import get_settings
from app.webhook_payload import snapshot_cliente

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    settings = get_settings()
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.agenda_webhook_token:
        h["Authorization"] = f"Bearer {settings.agenda_webhook_token}"
    return h


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _extrair_payload(data: Any) -> dict[str, Any]:
    from app.integrations.webhook_retorno import (
        eh_erro_ferramenta,
        motivo_erro_ferramenta,
        unwrap_body,
    )

    data = unwrap_body(data)
    if not data:
        return {
            "resultado": "erro",
            "motivo": "Resposta inválida do webhook",
            "erro": True,
            "transferir": True,
        }
    if data.get("errorMessage") or data.get("errorDescription") or data.get("transferir"):
        return {
            "resultado": "erro",
            "motivo": motivo_erro_ferramenta(data, padrao="Falha ao inserir agendamento"),
            "erro": True,
            "transferir": True,
        }
    if eh_erro_ferramenta(data) and str(data.get("resultado") or "").lower() == "erro":
        return {
            "resultado": "erro",
            "motivo": motivo_erro_ferramenta(data, padrao="Falha ao inserir agendamento"),
            "erro": True,
            "transferir": True,
        }

    resultado = str(data.get("resultado") or "").strip().lower()
    if not resultado:
        return {
            "resultado": "erro",
            "motivo": "Webhook retornou vazio — verifique Respond to Webhook no n8n",
            "erro": True,
            "transferir": True,
        }

    return {
        "resultado": resultado,
        "os_id": str(data.get("os_id") or "").strip(),
        "motivo": str(data.get("motivo") or data.get("message") or "").strip(),
        "erro": resultado == "erro",
        "transferir": bool(data.get("transferir")) or resultado == "erro",
    }


def inserir_agendamento_webhook(estado: dict[str, Any]) -> dict[str, Any]:
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "inserir_agendamento",
        unidade_id=uid,
        fallback_env=settings.agenda_inserir_webhook_url,
    )
    if not url:
        return {
            "resultado": "erro",
            "motivo": "inserir_agendamento sem webhook — cadastre no painel Ferramentas",
            "erro": True,
        }

    data_br = _texto(estado.get("data_agendamento"))
    slot = _texto(estado.get("horario_escolhido"))
    data_hora = slot_para_data_hora(data_br, slot)

    payload = snapshot_cliente(estado, incluir_historico=False)
    payload["data_hora_agendamento"] = data_hora
    # aliases explícitos do subfluxo INSERE AGENDA
    payload["ixc_id_cliente"] = payload.get("ixc_id_cliente") or ""
    payload["id_tecnico"] = payload.get("tecnico_id") or ""

    if not payload["ixc_id_cliente"]:
        return {"resultado": "erro", "motivo": "ixc_cliente_id ausente", "erro": True}
    if not data_hora:
        return {"resultado": "erro", "motivo": "data/horário inválidos", "erro": True}
    if not payload["id_tecnico"]:
        return {"resultado": "erro", "motivo": "id_tecnico ausente", "erro": True}

    try:
        with httpx.Client(timeout=settings.agenda_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Agenda inserir webhook timeout: %s", url)
        return {"resultado": "erro", "motivo": "timeout", "erro": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agenda inserir webhook falhou: %s", exc)
        return {"resultado": "erro", "motivo": str(exc), "erro": True}

    out = _extrair_payload(data)
    out["provider"] = "webhook"
    return out
