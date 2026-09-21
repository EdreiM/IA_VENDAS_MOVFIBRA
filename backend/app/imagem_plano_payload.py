"""Monta payload pronto para n8n → Chatwoot (imagem do plano)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.vendas_mensagens import legenda_imagem_plano
from app.webhook_payload import snapshot_cliente


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _mime_type(file_name: str) -> str:
    ext = Path(file_name).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")


def _id_plano_estado(estado: dict[str, Any]) -> str:
    return _texto(
        estado.get("plano_confirmado_id")
        or estado.get("plano_em_negociacao_id")
        or estado.get("plano_apresentado_id")
        or estado.get("id_plano")
    )


def montar_payload_imagem_plano(estado: dict[str, Any]) -> dict[str, Any]:
    """
    Pacote único para o webhook enviar_imagem_plano_sofia.

    O n8n só precisa:
    1) GET em imagem_url → binary attachments[]
    2) POST Chatwoot multipart (content + attachments[])
    """
    from app.media_store import url_absoluta_imagem
    from app.planos_admin import obter_plano

    payload = snapshot_cliente(estado, incluir_historico=False)
    id_plano = _id_plano_estado(estado)
    payload["id_plano"] = id_plano

    plano_db: dict[str, Any] | None = None
    if id_plano:
        try:
            plano_db = obter_plano(int(id_plano))
        except (TypeError, ValueError):
            plano_db = None

    imagem_rel = ""
    if plano_db and plano_db.get("imagem_url"):
        imagem_rel = _texto(plano_db.get("imagem_url"))
    painel_abs = _texto(estado.get("_imagem_url_painel"))
    imagem_abs = painel_abs or (url_absoluta_imagem(imagem_rel) if imagem_rel else "")

    payload["imagem_url_relativa"] = imagem_rel
    payload["imagem_url"] = imagem_abs

    if plano_db:
        payload["plano_nome"] = _texto(plano_db.get("nome"))
        if not payload.get("plano_confirmado"):
            payload["plano_confirmado"] = payload["plano_nome"]

    file_name = Path(imagem_rel).name if imagem_rel else ""
    if not file_name and id_plano:
        file_name = f"plano_{id_plano}.jpg"
    if not file_name:
        file_name = "plano.jpg"

    payload["imagem_file_name"] = file_name
    payload["imagem_mime_type"] = _mime_type(file_name)
    payload["chatwoot_attachment_field"] = "attachments[]"

    content = legenda_imagem_plano(plano_db)
    payload["content"] = content
    payload["descricao"] = content

    return payload
