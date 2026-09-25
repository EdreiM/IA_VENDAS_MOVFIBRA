"""Handoff Chatwoot — usado na transferência automática e no dashboard."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.integrations import chatwoot as chatwoot_api

logger = logging.getLogger(__name__)


def _int_or_none(v: Any) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def labels_do_env() -> list[str]:
    settings = get_settings()
    return [p.strip() for p in (settings.chatwoot_transfer_labels or "").split(",") if p.strip()]


def montar_payload_transferencia(estado: dict[str, Any], motivo: str) -> dict[str, Any]:
    """
    Pacote enviado ao webhook n8n `transferir_atendimento_eva`.
    Inclui snapshot completo + campo `contexto` resumido para o subfluxo.
    """
    from app.webhook_payload import snapshot_cliente

    motivo_txt = (motivo or estado.get("motivo_transferencia") or "TRANSFERIR_HUMANO").strip()
    snap = snapshot_cliente(estado, incluir_historico=True)
    ctx = {
        "fase": snap.get("fase"),
        "aguardando": snap.get("aguardando"),
        "objetivo": motivo_txt,
        "plano_confirmado": snap.get("plano_confirmado"),
        "plano_em_negociacao": snap.get("plano_em_negociacao"),
        "tem_cobertura": snap.get("tem_cobertura"),
        "cadastro_completo": snap.get("cadastro_completo"),
        "ixc_cliente_id": snap.get("ixc_cliente_id"),
        "id_contrato_ixc": snap.get("id_contrato_ixc"),
        "os_id": snap.get("os_id"),
        "ativado_ixc": bool(estado.get("ativado_ixc")),
        "agendamento_confirmado": snap.get("agendamento_confirmado"),
        "termos_enviados": bool(estado.get("termos_enviados")),
    }
    return {
        **snap,
        "motivo": motivo_txt,
        "contexto": ctx,
        "ativado_ixc": bool(estado.get("ativado_ixc")),
        "termos_enviados": bool(estado.get("termos_enviados")),
        "transferido_humano": True,
    }


def handoff_por_config(
    conversation_id: str | int | None,
    *,
    motivo: str = "",
    assignee_id: int | None = None,
    team_id: int | None = None,
    labels: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """
    Executa handoff com overrides opcionais; senão usa .env.
    Não falha o funil se conversation_id faltar — retorna ok=False.
    """
    settings = get_settings()
    if not conversation_id:
        return {"ok": False, "motivo": "conversation_id ausente"}

    aid = assignee_id if assignee_id is not None else _int_or_none(settings.chatwoot_transfer_assignee_id)
    tid = team_id if team_id is not None else _int_or_none(settings.chatwoot_transfer_team_id)
    labs = labels if labels is not None else labels_do_env()
    st = (status if status is not None else settings.chatwoot_transfer_status) or None

    nota = None
    if motivo:
        nota = f"[Eva] Transferência automática — {motivo}"

    result = chatwoot_api.handoff_conversa(
        conversation_id,
        assignee_id=aid,
        team_id=tid,
        labels=labs or None,
        status=st,
        nota_privada=nota,
    )
    if not result.get("ok"):
        logger.warning("Handoff Chatwoot incompleto: %s", result)
    return result


def _executar_ferramenta_transferir(estado: dict[str, Any], motivo: str) -> dict[str, Any] | None:
    """Usa ferramenta cadastrada transferir_atendimento se existir."""
    try:
        from app.ferramentas import obter_ferramenta_por_key, registrar_chamada
        from app.ferramentas_catalog import resolver_url_ferramenta
    except Exception:
        return None

    unidade_id = estado.get("unidade_id")
    try:
        unidade_id = int(unidade_id) if unidade_id is not None else None
    except (TypeError, ValueError):
        unidade_id = None

    tool = obter_ferramenta_por_key("transferir_atendimento", unidade_id=unidade_id)
    if not tool:
        return None

    settings = get_settings()
    cid = estado.get("conversation_id")
    url = resolver_url_ferramenta(
        "transferir_atendimento",
        unidade_id=unidade_id,
        fallback_env=settings.transfer_webhook_url,
    )
    payload = montar_payload_transferencia(estado, motivo)

    if url:
        timeout = float(settings.transfer_webhook_timeout_seconds or 45.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)
            ok = 200 <= resp.status_code < 300
            registrar_chamada(
                int(tool["id"]),
                ok=ok,
                conversation_id=str(cid) if cid else None,
                motivo=motivo,
            )
            return {
                "ok": ok,
                "via": "ferramenta_webhook",
                "ferramenta_id": tool.get("id"),
                "status_code": resp.status_code,
                "body": (resp.text or "")[:2000],
            }
        except Exception as exc:
            registrar_chamada(
                int(tool["id"]),
                ok=False,
                conversation_id=str(cid) if cid else None,
                motivo=str(exc)[:300],
            )
            logger.warning("Webhook transferir falhou: %s", exc)
            return {
                "ok": False,
                "via": "ferramenta_webhook",
                "ferramenta_id": tool.get("id"),
                "motivo": str(exc)[:500],
            }

    result = handoff_por_config(cid, motivo=motivo or "TRANSFERIR_HUMANO")
    try:
        registrar_chamada(
            int(tool["id"]),
            ok=bool(result.get("ok")),
            conversation_id=str(cid) if cid else None,
            motivo=motivo,
        )
    except Exception:
        pass
    result = dict(result)
    result["via"] = "ferramenta_fallback_chatwoot"
    result["ferramenta_id"] = tool.get("id")
    return result


def talvez_handoff_ao_transferir(estado: dict[str, Any], motivo: str = "") -> dict[str, Any] | None:
    """
    Preferência: ferramenta cadastrada `transferir_atendimento`.
    Senão: CHATWOOT_TRANSFER_ENABLED + handoff .env.
    """
    try:
        tool_result = _executar_ferramenta_transferir(estado, motivo)
        if tool_result is not None:
            return tool_result
    except Exception as exc:
        logger.warning("Ferramenta transferir falhou, fallback Chatwoot: %s", exc)

    settings = get_settings()
    if not settings.chatwoot_transfer_enabled:
        return None
    cid = estado.get("conversation_id")
    return handoff_por_config(cid, motivo=motivo or "TRANSFERIR_HUMANO")
