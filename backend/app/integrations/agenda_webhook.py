"""Cliente HTTP — horários de técnicos via n8n."""

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
    if settings.agenda_webhook_token:
        h["Authorization"] = f"Bearer {settings.agenda_webhook_token}"
    return h


def _lista_horarios(valor: Any) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if str(v).strip()]


def _extrair_payload(data: Any) -> dict[str, Any]:
    from app.integrations.webhook_retorno import (
        eh_erro_ferramenta,
        motivo_erro_ferramenta,
        unwrap_body,
    )

    data = unwrap_body(data)
    if not data:
        return {"resultado": "erro", "motivo": "Resposta inválida do webhook", "erro": True}
    if eh_erro_ferramenta(data) and str(data.get("resultado") or "").lower() not in {
        "ok",
        "sucesso",
        "horarios",
        "sem_horarios",
    }:
        # Só trata como erro duro se veio flag/erro nativo (não um resultado de negócio)
        if data.get("errorMessage") or data.get("errorDescription") or data.get("transferir"):
            return {
                "resultado": "erro",
                "motivo": motivo_erro_ferramenta(data, padrao="Falha ao buscar horários"),
                "erro": True,
                "transferir": True,
            }

    resultado = str(data.get("resultado") or "").strip().lower()
    if not resultado:
        return {
            "resultado": "erro",
            "motivo": "Webhook retornou vazio — verifique Respond to Webhook no n8n",
            "erro": True,
        }
    return {
        "resultado": resultado,
        "tecnico_id": str(data.get("tecnico_id") or data.get("id_tecnico") or "").strip(),
        "data": str(data.get("data") or data.get("data_alvo_br") or "").strip(),
        "manha": _lista_horarios(data.get("manha")),
        "tarde": _lista_horarios(data.get("tarde")),
        "motivo": str(data.get("motivo") or data.get("message") or "").strip(),
        "erro": resultado == "erro" or bool(data.get("erro")),
        "transferir": bool(data.get("transferir")) or resultado == "erro",
    }


def buscar_horarios_webhook(estado: dict[str, Any]) -> dict[str, Any]:
    """
    Envia snapshot do cliente. Subfluxo TECNICOS HORARIOS usa:
    id_cliente (IXC), cidade, bairro.
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
        "buscar_horarios_agenda",
        unidade_id=uid,
        fallback_env=settings.agenda_webhook_url,
    )
    if not url:
        return {
            "resultado": "erro",
            "motivo": "buscar_horarios_agenda sem webhook — cadastre no painel Ferramentas",
            "erro": True,
        }

    payload = snapshot_cliente(estado, incluir_historico=False)
    # O subfluxo antigo espera id_cliente = ID IXC
    ixc = str(payload.get("ixc_id_cliente") or "").strip()
    if ixc:
        payload["id_cliente"] = ixc
        payload["id_cliente_sessao"] = str(estado.get("id_cliente") or "")
    else:
        # fallback: ainda manda o que tiver (cidade/bairro)
        payload["id_cliente"] = str(estado.get("id_cliente") or "")

    try:
        with httpx.Client(timeout=settings.agenda_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Agenda webhook timeout: %s", url)
        return {"resultado": "erro", "motivo": "timeout", "erro": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agenda webhook falhou: %s", exc)
        return {"resultado": "erro", "motivo": str(exc), "erro": True}

    out = _extrair_payload(data)
    out["provider"] = "webhook"
    return out
