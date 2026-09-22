"""Configuração Chatwoot (painel) — entrada webhook, inbox, allowlist."""

from __future__ import annotations

from typing import Any

from app import admin_store
from app.config import get_settings


def _cfg(chave: str, default: str = "", *, unidade_id: int | None = None) -> str:
    return admin_store.get_config(chave, default, unidade_id=unidade_id).strip()


def _mask(valor: str) -> str:
    v = (valor or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "••••"
    return f"{v[:4]}...{v[-4:]}"


def resolver_public_base_url(*, unidade_id: int | None = None) -> str:
    db = _cfg("public_base_url", "", unidade_id=unidade_id)
    if db:
        return db.rstrip("/")
    return (get_settings().public_base_url or "http://127.0.0.1:8001").rstrip("/")


def resolver_webhook_url(*, unidade_id: int | None = None) -> str:
    return f"{resolver_public_base_url(unidade_id=unidade_id)}/webhooks/chatwoot"


def resolver_inbound_enabled(*, unidade_id: int | None = None) -> bool:
    db = _cfg("chatwoot_inbound_enabled", "", unidade_id=unidade_id).lower()
    if db in {"1", "true", "sim", "yes", "on"}:
        return True
    if db in {"0", "false", "nao", "não", "no", "off"}:
        return False
    # padrão: ligado se inbox configurado (fluxo direto Chatwoot)
    return bool(resolver_inbox_id(unidade_id=unidade_id))


def resolver_inbox_id(*, unidade_id: int | None = None) -> str:
    db = _cfg("chatwoot_inbox_id", "", unidade_id=unidade_id)
    if db:
        return db
    return (get_settings().chatwoot_inbox_id or "").strip()


def resolver_inbound_mode(*, unidade_id: int | None = None) -> str:
    db = _cfg("sofia_inbound_mode", "", unidade_id=unidade_id).lower()
    if db in {"closed", "allowlist", "open"}:
        return db
    return (get_settings().sofia_inbound_mode or "allowlist").strip().lower()


def resolver_allowlist_phones(*, unidade_id: int | None = None) -> str:
    db = _cfg("sofia_allowlist_phones", "", unidade_id=unidade_id)
    if db:
        return db
    return (get_settings().sofia_allowlist_phones or "").strip()


def resolver_buffer_enabled(*, unidade_id: int | None = None) -> bool:
    db = _cfg("chatwoot_buffer_enabled", "", unidade_id=unidade_id).lower()
    if db in {"1", "true", "sim", "yes", "on"}:
        return True
    if db in {"0", "false", "nao", "não", "no", "off"}:
        return False
    return bool(get_settings().chatwoot_buffer_enabled)


def resolver_webhook_token(*, unidade_id: int | None = None) -> str:
    db = _cfg("chatwoot_webhook_token", "", unidade_id=unidade_id)
    if db:
        return db
    return ""


def resolver_chatwoot_api_token(*, unidade_id: int | None = None) -> str:
    db = _cfg("chatwoot_api_token", "", unidade_id=unidade_id)
    if db:
        return db
    return (get_settings().chatwoot_api_token or "").strip()


def resolver_chatwoot_base_url(*, unidade_id: int | None = None) -> str:
    db = _cfg("chatwoot_base_url", "", unidade_id=unidade_id)
    if db:
        return db.rstrip("/")
    return (get_settings().chatwoot_base_url or "https://chatwoot.mov.pro.br").rstrip("/")


def envio_resposta_configurado(*, unidade_id: int | None = None) -> bool:
    """True se há ferramenta enviar_mensagem, webhook .env ou token API Chatwoot no painel."""
    try:
        from app.ferramentas_catalog import resolver_url_ferramenta

        if resolver_url_ferramenta("enviar_mensagem", unidade_id=unidade_id):
            return True
    except Exception:
        pass
    if resolver_chatwoot_api_token(unidade_id=unidade_id):
        return True
    settings = get_settings()
    return bool((settings.chatwoot_msg_webhook_url or "").strip()) or settings.chatwoot_reply_enabled


def verificar_webhook_token(
    token_header: str | None,
    *,
    unidade_id: int | None = None,
) -> bool:
    esperado = resolver_webhook_token(unidade_id=unidade_id)
    if not esperado:
        return True
    recebido = (token_header or "").strip()
    return recebido == esperado


def obter_config_chatwoot(*, unidade_id: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    token = resolver_webhook_token(unidade_id=unidade_id)
    api_token = resolver_chatwoot_api_token(unidade_id=unidade_id)
    return {
        "inbound_enabled": resolver_inbound_enabled(unidade_id=unidade_id),
        "inbox_id": resolver_inbox_id(unidade_id=unidade_id),
        "inbound_mode": resolver_inbound_mode(unidade_id=unidade_id),
        "allowlist_phones": resolver_allowlist_phones(unidade_id=unidade_id),
        "buffer_enabled": resolver_buffer_enabled(unidade_id=unidade_id),
        "public_base_url": resolver_public_base_url(unidade_id=unidade_id),
        "webhook_url": resolver_webhook_url(unidade_id=unidade_id),
        "webhook_token_configured": bool(token),
        "webhook_token_mask": _mask(token) if token else "",
        "envio_resposta_configurado": envio_resposta_configurado(unidade_id=unidade_id),
        "eventos_recomendados": ["message_created"],
        "chatwoot_base_url": resolver_chatwoot_base_url(unidade_id=unidade_id),
        "chatwoot_api_configured": bool(api_token),
        "chatwoot_api_token_mask": _mask(api_token) if api_token else "",
        "env_fallback": {
            "inbox_id": settings.chatwoot_inbox_id or "",
            "inbound_mode": settings.sofia_inbound_mode,
            "allowlist_phones": settings.sofia_allowlist_phones or "",
            "buffer_enabled": settings.chatwoot_buffer_enabled,
            "public_base_url": settings.public_base_url or "",
        },
    }


def salvar_config_chatwoot(dados: dict[str, Any], *, unidade_id: int | None = None) -> dict[str, Any]:
    plain = {
        "chatwoot_inbound_enabled": "1" if dados.get("inbound_enabled") else "0",
        "chatwoot_inbox_id": str(dados.get("inbox_id") or "").strip(),
        "sofia_inbound_mode": str(dados.get("inbound_mode") or "allowlist").strip().lower(),
        "sofia_allowlist_phones": str(dados.get("allowlist_phones") or "").strip(),
        "chatwoot_buffer_enabled": "1" if dados.get("buffer_enabled") else "0",
        "public_base_url": str(dados.get("public_base_url") or "").strip().rstrip("/"),
    }
    for k, v in plain.items():
        admin_store.set_config(k, v, unidade_id=unidade_id)

    tok = str(dados.get("webhook_token") or "").strip()
    if tok and not tok.startswith("••••"):
        admin_store.set_config("chatwoot_webhook_token", tok, unidade_id=unidade_id)

    base = str(dados.get("chatwoot_base_url") or "").strip().rstrip("/")
    if base:
        admin_store.set_config("chatwoot_base_url", base, unidade_id=unidade_id)

    api_tok = str(dados.get("chatwoot_api_token") or "").strip()
    if api_tok and not api_tok.startswith("••••"):
        admin_store.set_config("chatwoot_api_token", api_tok, unidade_id=unidade_id)

    return obter_config_chatwoot(unidade_id=unidade_id)


def payload_exemplo_message_created() -> dict[str, Any]:
    """Exemplo mínimo compatível com extrair_evento_chatwoot."""
    inbox = resolver_inbox_id() or "6"
    return {
        "event": "message_created",
        "message_type": "incoming",
        "private": False,
        "id": 99901,
        "content": "Oi, quero internet",
        "inbox": {"id": int(inbox) if inbox.isdigit() else inbox},
        "conversation": {
            "id": 2762,
            "inbox_id": int(inbox) if inbox.isdigit() else inbox,
            "meta": {"team": {}, "sender": {"phone_number": "+5593992219098"}},
            "contact_inbox": {"source_id": "93992219098"},
        },
        "sender": {
            "id": 1227,
            "name": "Cliente Teste",
            "phone_number": "+5593992219098",
            "identifier": "93992219098",
        },
    }
