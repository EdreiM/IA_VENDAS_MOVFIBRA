"""Cliente HTTP — cadastro completo no IXC via n8n (cliente + contrato + OS)."""

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
    if settings.cadastro_webhook_token:
        h["Authorization"] = f"Bearer {settings.cadastro_webhook_token}"
    return h


def _extrair_payload(data: Any) -> dict[str, Any]:
    from app.integrations.webhook_retorno import (
        eh_erro_ferramenta,
        motivo_erro_ferramenta,
        unwrap_body,
    )

    data = unwrap_body(data)
    if not data:
        return {
            "ok": False,
            "erro": True,
            "transferir": True,
            "motivo": "Resposta inválida do webhook",
        }

    # Erro nativo n8n (Execute Workflow → error output) ou JSON padronizado
    if eh_erro_ferramenta(data):
        resultado = str(data.get("resultado") or "").strip().lower()
        if resultado in {"ja_cadastrado", "cpf_ja_cadastrado", "cliente_existe"}:
            return {
                "ok": False,
                "erro": True,
                "ja_cadastrado": True,
                "transferir": True,
                "motivo": motivo_erro_ferramenta(data, padrao="CPF já cadastrado no IXC"),
                "id_cliente_ixc": str(
                    data.get("ixc_cliente_id")
                    or data.get("id_cliente_ixc")
                    or ""
                ).strip(),
            }
        return {
            "ok": False,
            "erro": True,
            "transferir": True,
            "motivo": motivo_erro_ferramenta(data, padrao="Erro no cadastro (n8n)"),
        }

    resultado = str(data.get("resultado") or "").strip().lower()
    motivo = str(data.get("motivo") or data.get("message") or "").strip()

    id_ixc = str(
        data.get("ixc_cliente_id")
        or data.get("id_cliente_ixc")
        or data.get("ixc_id_cliente")
        or ""
    ).strip()
    # Não confundir id_cliente da sessão WhatsApp com ID IXC
    if not id_ixc and str(data.get("id_cliente") or "").isdigit():
        id_ixc = str(data.get("id_cliente")).strip()

    os_id = str(data.get("os_id") or data.get("id_os") or "").strip()
    id_contrato = str(
        data.get("id_contrato_ixc")
        or data.get("id_contrato")
        or data.get("contrato_id")
        or ""
    ).strip()

    if resultado in {"ok", "sucesso", "success", "cadastrado"}:
        return {
            "ok": True,
            "erro": False,
            "motivo": motivo or "Cadastro concluído via n8n",
            "id_cliente_ixc": id_ixc,
            "os_id": os_id,
            "id_contrato_ixc": id_contrato,
            "provider": "webhook",
        }

    if resultado in {"ja_cadastrado", "cpf_ja_cadastrado", "cliente_existe"}:
        return {
            "ok": False,
            "erro": True,
            "ja_cadastrado": True,
            "transferir": True,
            "motivo": motivo or "CPF já cadastrado no IXC",
            "id_cliente_ixc": id_ixc,
        }

    if not resultado:
        return {
            "ok": False,
            "erro": True,
            "transferir": True,
            "motivo": "Webhook retornou vazio — verifique Respond to Webhook no n8n",
        }

    # Resultado textual desconhecido mas com ID → tratar como sucesso
    if id_ixc:
        return {
            "ok": True,
            "erro": False,
            "motivo": motivo or resultado,
            "id_cliente_ixc": id_ixc,
            "os_id": os_id,
            "id_contrato_ixc": id_contrato,
            "provider": "webhook",
        }

    return {
        "ok": False,
        "erro": True,
        "transferir": True,
        "motivo": motivo or f"Retorno inesperado: {resultado or '(vazio)'}",
    }


def cadastrar_cliente_webhook(estado: dict[str, Any]) -> dict[str, Any]:
    """
    Envia snapshot completo do atendimento.
    O subfluxo n8n deve: incluir cliente, contrato, OS (e o que mais a MOV exigir).
    """
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "cadastrar_cliente",
        unidade_id=uid,
        fallback_env=settings.cadastro_webhook_url,
    )
    if not url:
        return {
            "ok": False,
            "erro": True,
            "motivo": "cadastrar_cliente sem webhook — cadastre no painel Ferramentas",
        }

    payload = snapshot_cliente(estado, incluir_historico=False)
    # Aliases úteis no subfluxo (plano = id_vd_contrato no IXC) — sempre string p/ n8n
    pid = str(
        estado.get("plano_confirmado_id") or estado.get("plano_em_negociacao_id") or ""
    ).strip()
    if pid:
        payload["plano_id"] = pid
        payload["id_vd_contrato"] = pid
        payload["plano_confirmado_id"] = pid

    try:
        with httpx.Client(timeout=settings.cadastro_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Cadastro webhook timeout: %s", url)
        return {"ok": False, "erro": True, "motivo": "timeout no cadastro"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cadastro webhook falhou: %s", exc)
        return {"ok": False, "erro": True, "motivo": str(exc)}

    return _extrair_payload(data)
