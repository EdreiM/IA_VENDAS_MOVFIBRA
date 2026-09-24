"""Parse do webhook Chatwoot (message_created) → campos da Eva.

Compatível com:
- payload nativo Chatwoot (como no pinData do webhook mov_woot)
- envelope n8n `{ body: {...} }`
- saída do node Normalizar Entrada (mensagem, telefone, conversationId…)
"""

from __future__ import annotations

from typing import Any

from app.chatwoot_config import resolver_inbox_id


def _dig(obj: Any, *keys: str, default: Any = None) -> Any:
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return default if cur is None else cur


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """n8n Webhook coloca o JSON do Chatwoot em body."""
    body = payload.get("body")
    if isinstance(body, dict) and (
        "event" in body or "conversation" in body or "message_type" in body or "content" in body
    ):
        return body
    return payload


def _attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    atts = payload.get("attachments")
    if isinstance(atts, list) and atts:
        return [a for a in atts if isinstance(a, dict)]
    msgs = _dig(payload, "conversation", "messages", default=[])
    if isinstance(msgs, list) and msgs:
        first = msgs[0] if isinstance(msgs[0], dict) else {}
        nested = first.get("attachments")
        if isinstance(nested, list):
            return [a for a in nested if isinstance(a, dict)]
    return []


def _mensagem_de_conteudo(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if content is not None and str(content).strip():
        return str(content).strip()

    processed = payload.get("processed_message_content")
    if processed is not None and str(processed).strip():
        return str(processed).strip()

    # Localização Meta/Chatwoot: content null + attachment file_type=location
    for att in _attachments(payload):
        ftype = str(att.get("file_type") or "").lower()
        if ftype == "location":
            lat = att.get("coordinates_lat")
            lng = att.get("coordinates_long")
            if lat is not None and lng is not None:
                from app.geo_coords import normalizar_lat_lng_br

                try:
                    la, ln = normalizar_lat_lng_br(float(lat), float(lng))
                    return f"{la},{ln}"
                except (TypeError, ValueError):
                    return f"{lat},{lng}"
        # Imagem/áudio sem caption — placeholder curto (Eva trata texto; mídia fica no n8n)
        if ftype in {"image", "audio", "file", "video"}:
            caption = str(att.get("fallback_title") or "").strip()
            return caption or f"[{ftype}]"

    return ""


def _inbox_id(payload: dict[str, Any]) -> str | None:
    for candidate in (
        payload.get("inboxId"),
        payload.get("inbox_id"),
        _dig(payload, "inbox", "id"),
        _dig(payload, "conversation", "inbox_id"),
    ):
        if candidate is not None and str(candidate).strip() != "":
            return str(candidate).strip()
    return None


def _team_name(payload: dict[str, Any]) -> str:
    team = _dig(payload, "conversation", "meta", "team", default=None)
    if isinstance(team, dict):
        return str(team.get("name") or "").strip()
    if team is None:
        return str(payload.get("teamName") or "").strip()
    return str(team).strip()


def _sender_name(payload: dict[str, Any]) -> str:
    sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    name = sender.get("name") or _dig(payload, "conversation", "meta", "sender", "name")
    return str(payload.get("senderName") or name or "").strip()


def _normalizar_pre_parseado(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Payload já tratado pelo n8n (Normalizar Entrada / Edit Fields)."""
    if not (
        payload.get("mensagem")
        and (
            payload.get("id_cliente")
            or payload.get("telefone")
            or payload.get("conversation_id")
            or payload.get("conversationId")
            or payload.get("contatoJID")
        )
    ):
        return None

    conv = payload.get("conversation_id") or payload.get("conversationId")
    tel = str(payload.get("telefone") or payload.get("contatoJID") or "").strip()
    inbox = str(payload.get("inboxId") or payload.get("inbox_id") or "") or None
    esperado = resolver_inbox_id()
    if esperado and inbox and inbox != esperado:
        return None

    return {
        "mensagem": str(payload.get("mensagem") or "").strip(),
        "id_cliente": str(payload.get("id_cliente") or tel).strip(),
        "conversation_id": str(conv).strip() if conv is not None else None,
        "contact_id": str(payload.get("contact_id") or payload.get("contactId") or "").strip() or None,
        "telefone": tel or None,
        "inbox_id": inbox,
        "event": str(payload.get("event") or "normalized"),
        "message_id": str(
            payload.get("message_id") or payload.get("messageId") or payload.get("id") or ""
        ).strip()
        or None,
    }


def extrair_evento_chatwoot(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Retorna dict normalizado ou None se deve ignorar.
    Filtros leves (inbox / direction) quando configurados — o n8n pode filtrar antes.
    """
    return analisar_evento_chatwoot(payload).get("evento")


def analisar_evento_chatwoot(payload: dict[str, Any]) -> dict[str, Any]:
    """Diagnóstico completo — usado no painel para testar payload do Chatwoot."""
    esperado = resolver_inbox_id()
    base: dict[str, Any] = {
        "processavel": False,
        "motivo": None,
        "evento": None,
        "inbox_esperado": esperado or None,
        "inbox_recebido": None,
    }

    if not isinstance(payload, dict):
        base["motivo"] = "Body não é objeto JSON"
        return base

    pre = _normalizar_pre_parseado(payload)
    if pre:
        base.update(processavel=True, evento=pre, motivo=None, inbox_recebido=pre.get("inbox_id"))
        return base

    raw = _unwrap(payload)
    inbox = _inbox_id(raw)
    base["inbox_recebido"] = inbox

    message_type = raw.get("message_type")
    if message_type in (1, "1", "outgoing", "outgoing_message"):
        base["motivo"] = "Mensagem outgoing (resposta da empresa/IA) — ignorada"
        return base
    if raw.get("private") is True:
        base["motivo"] = "Nota privada — ignorada"
        return base

    if esperado and inbox and inbox != esperado:
        base["motivo"] = f"Inbox {inbox} diferente da caixa da IA ({esperado})"
        return base

    if _sender_name(raw).casefold() == "evolutionapi":
        base["motivo"] = "Remetente técnico EvolutionAPI — ignorado"
        return base

    team = _team_name(raw)
    if team:
        base["motivo"] = f"Conversa com time atribuído ({team}) — humano atende"
        return base

    event = str(raw.get("event") or "").strip()
    if event and event not in {"message_created", "message_updated", ""}:
        if "conversation" not in raw and "sender" not in raw:
            base["motivo"] = f"Evento {event!r} não é mensagem de cliente"
            return base

    content = _mensagem_de_conteudo(raw)
    if not content:
        base["motivo"] = "Sem conteúdo de texto (content vazio e sem localização/mídia reconhecível)"
        return base

    conversation = raw.get("conversation") if isinstance(raw.get("conversation"), dict) else {}
    sender = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
    meta_sender = _dig(conversation, "meta", "sender", default={}) or {}
    if not isinstance(meta_sender, dict):
        meta_sender = {}

    contact_inbox = conversation.get("contact_inbox") if isinstance(conversation.get("contact_inbox"), dict) else {}
    source_id = contact_inbox.get("source_id") or _dig(conversation, "messages", default=[])

    conversation_id = raw.get("conversation_id") or conversation.get("id") or _dig(raw, "conversation", "id")
    contact_id = sender.get("id") or meta_sender.get("id") or raw.get("contact_id")
    telefone = (
        sender.get("phone_number")
        or meta_sender.get("phone_number")
        or contact_inbox.get("source_id")
        or sender.get("identifier")
        or meta_sender.get("identifier")
        or ""
    )
    if isinstance(source_id, str) and source_id and not telefone:
        telefone = source_id

    identifier = str(
        sender.get("identifier") or meta_sender.get("identifier") or telefone or contact_id or ""
    ).strip()

    id_cliente = identifier or str(telefone or "").strip()
    if not id_cliente and conversation_id:
        id_cliente = f"cw-{conversation_id}"

    evento = {
        "mensagem": content,
        "id_cliente": id_cliente,
        "conversation_id": str(conversation_id) if conversation_id is not None else None,
        "contact_id": str(contact_id) if contact_id is not None else None,
        "telefone": str(telefone or "") or None,
        "inbox_id": inbox,
        "event": event or "message_created",
        "message_id": str(raw.get("id") or raw.get("message_id") or "").strip() or None,
    }
    base.update(processavel=True, evento=evento, motivo=None)
    return base
