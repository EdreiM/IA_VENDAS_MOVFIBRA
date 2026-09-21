"""Cliente HTTP para RAG externa (n8n ou outro serviço).

A URL/token vêm da Config IA do painel (prioridade) via ia_config.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _extrair_resposta(data: Any) -> dict[str, Any]:
    """Normaliza formatos comuns de retorno (n8n, array, body aninhado)."""
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return {"encontrado": False, "motivo": "Resposta inválida do webhook"}

    if isinstance(data.get("body"), dict):
        data = {**data, **data["body"]}

    chunks = data.get("chunks") or data.get("documentos") or data.get("sources") or []
    if isinstance(chunks, dict):
        chunks = [chunks]
    if not isinstance(chunks, list):
        chunks = []

    normalizados: list[dict[str, str]] = []
    for item in chunks:
        if isinstance(item, str):
            normalizados.append({"titulo": "", "conteudo": item})
        elif isinstance(item, dict):
            normalizados.append(
                {
                    "titulo": str(item.get("titulo") or item.get("title") or ""),
                    "conteudo": str(
                        item.get("conteudo")
                        or item.get("content")
                        or item.get("text")
                        or item.get("pageContent")
                        or ""
                    ),
                }
            )

    resposta = str(data.get("resposta") or data.get("answer") or data.get("text") or "").strip()
    encontrado = bool(data.get("encontrado", data.get("found", bool(resposta or normalizados))))

    return {
        "encontrado": encontrado,
        "resposta": resposta,
        "chunks": normalizados,
        "confianca": float(data.get("confianca") or data.get("confidence") or 0),
        "fontes": list(data.get("fontes") or data.get("sources_ids") or []),
        "motivo": str(data.get("motivo") or data.get("message") or ""),
    }


def consultar_rag_webhook(
    *,
    pergunta: str,
    mensagem: str,
    contexto: dict[str, Any],
) -> dict[str, Any]:
    from app import ia_config

    settings = get_settings()
    unidade_id = None
    raw_uid = (contexto or {}).get("unidade_id")
    if raw_uid is not None and str(raw_uid).strip() != "":
        try:
            unidade_id = int(raw_uid)
        except (TypeError, ValueError):
            unidade_id = None

    url = ia_config.resolver_rag_webhook_url(unidade_id=unidade_id)
    token = ia_config.resolver_rag_webhook_token(unidade_id=unidade_id)

    if not url:
        return {
            "encontrado": False,
            "motivo": "RAG webhook não cadastrado no painel (Config IA)",
            "provider": "webhook",
        }

    ctx = contexto or {}
    payload = {
        "pergunta": pergunta,
        "mensagem": mensagem,
        "contexto": ctx,
        "id_cliente": ctx.get("id_cliente") or "",
        "cidade": ctx.get("cidade") or "",
        "bairro": ctx.get("bairro") or "",
        "plano_confirmado": ctx.get("plano_confirmado") or "",
        "fase": ctx.get("fase") or "",
        "nome": ctx.get("nome") or "",
    }

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=settings.rag_timeout_seconds) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("RAG webhook timeout: %s", url)
        return {"encontrado": False, "motivo": "timeout", "erro": True, "provider": "webhook"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG webhook falhou (%s): %s", url, exc)
        return {"encontrado": False, "motivo": str(exc), "erro": True, "provider": "webhook"}

    resultado = _extrair_resposta(data)
    resultado["provider"] = "webhook"
    resultado["webhook_url"] = url
    return resultado
