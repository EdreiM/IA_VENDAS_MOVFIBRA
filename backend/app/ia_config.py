"""Configuração operacional da IA (painel) — lida com mascaramento de secrets."""

from __future__ import annotations

from typing import Any

from app import admin_store
from app.config import get_settings


SECRET_KEYS = frozenset({"openai_api_key", "transcription_api_key", "rag_webhook_token"})


def _mask(valor: str) -> str:
    v = (valor or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "••••"
    return f"{v[:4]}...{v[-4:]}"


def _cfg(chave: str, default: str = "", *, unidade_id: int | None = None) -> str:
    return admin_store.get_config(chave, default, unidade_id=unidade_id)


def resolver_openai_api_key(*, unidade_id: int | None = None) -> str:
    db = _cfg("openai_api_key", "", unidade_id=unidade_id).strip()
    if db:
        return db
    return (get_settings().openai_api_key or "").strip()


def resolver_llm_provider(*, unidade_id: int | None = None) -> str:
    db = _cfg("llm_provider", "", unidade_id=unidade_id).strip()
    if db:
        return db.lower()
    return (get_settings().llm_provider or "openai").lower().strip()


def resolver_openai_model(*, unidade_id: int | None = None) -> str:
    db = _cfg("openai_model", "", unidade_id=unidade_id).strip()
    # Default oficial: gpt-4.1-mini (substitui o legado gpt-4o-mini do painel antigo)
    if db == "gpt-4o-mini":
        try:
            from app import admin_store

            admin_store.set_config("openai_model", "gpt-4.1-mini", unidade_id=unidade_id)
        except Exception:
            pass
        db = "gpt-4.1-mini"
    if db:
        return db
    return (get_settings().openai_model or "gpt-4.1-mini").strip()


def resolver_temperatura(*, unidade_id: int | None = None, default: float = 0.3) -> float:
    raw = _cfg("llm_temperature", "", unidade_id=unidade_id).strip()
    if not raw:
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return default


def resolver_nome_ia(*, unidade_id: int | None = None) -> str:
    return _cfg("nome_ia", "Eva", unidade_id=unidade_id).strip() or "Eva"


def resolver_rag_webhook_url(*, unidade_id: int | None = None) -> str:
    """Prioridade: ferramenta consultar_rag → sofia_config painel → .env."""
    try:
        from app.ferramentas_catalog import resolver_url_ferramenta

        tool_url = resolver_url_ferramenta("consultar_rag", unidade_id=unidade_id)
        if tool_url:
            return tool_url
    except Exception:
        pass
    db = _cfg("rag_webhook_url", "", unidade_id=unidade_id).strip()
    if db:
        return db
    return (get_settings().rag_webhook_url or "").strip()


def resolver_rag_webhook_token(*, unidade_id: int | None = None) -> str:
    db = _cfg("rag_webhook_token", "", unidade_id=unidade_id).strip()
    if db:
        return db
    return (get_settings().rag_webhook_token or "").strip()


def resolver_rag_provider(*, unidade_id: int | None = None) -> str:
    """
    Fonte da verdade: painel.
    Se houver URL cadastrada no painel, usa webhook mesmo que o .env diga mock.
    """
    db_prov = _cfg("rag_provider", "", unidade_id=unidade_id).strip().lower()
    url = resolver_rag_webhook_url(unidade_id=unidade_id)
    if db_prov in {"webhook", "mock", "none", "off"}:
        if db_prov == "webhook" and not url:
            return "none"
        return db_prov
    # Sem provider no painel: se tem URL (painel ou env), webhook; senão env/mock
    if url:
        return "webhook"
    return (get_settings().rag_provider or "mock").lower().strip() or "mock"


def obter_config_ia(*, unidade_id: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    openai_key = resolver_openai_api_key(unidade_id=unidade_id)
    trans_key = _cfg("transcription_api_key", "", unidade_id=unidade_id).strip()
    rag_token = resolver_rag_webhook_token(unidade_id=unidade_id)
    rag_url = resolver_rag_webhook_url(unidade_id=unidade_id)

    return {
        "nome_ia": resolver_nome_ia(unidade_id=unidade_id),
        "tom_voz": _cfg("tom_voz", "Calorosa, simpática, objetiva", unidade_id=unidade_id),
        "pode_emoji": _cfg("pode_emoji", "1", unidade_id=unidade_id) in ("1", "true", "True", "sim"),
        "llm_provider": resolver_llm_provider(unidade_id=unidade_id),
        "openai_model": resolver_openai_model(unidade_id=unidade_id),
        "llm_temperature": resolver_temperatura(unidade_id=unidade_id),
        "openai_api_key_mask": _mask(openai_key),
        "openai_api_key_configured": bool(openai_key),
        "transcription_api_key_mask": _mask(trans_key),
        "transcription_api_key_configured": bool(trans_key),
        "rag_provider": resolver_rag_provider(unidade_id=unidade_id),
        "rag_webhook_url": rag_url,
        "rag_webhook_token_mask": _mask(rag_token) if rag_token else "",
        "rag_webhook_token_configured": bool(rag_token),
        "env_fallback": {
            "llm_provider": settings.llm_provider,
            "openai_model": settings.openai_model,
            "openai_configured": bool((settings.openai_api_key or "").strip()),
            "rag_webhook_url": settings.rag_webhook_url or "",
        },
    }


def salvar_config_ia(dados: dict[str, Any], *, unidade_id: int | None = None) -> dict[str, Any]:
    """Salva campos do painel. Secrets vazios não sobrescrevem a key atual."""
    rag_url = str(dados.get("rag_webhook_url") or "").strip()
    rag_provider = str(dados.get("rag_provider") or "").strip().lower()
    if not rag_provider:
        rag_provider = "webhook" if rag_url else "none"

    plain = {
        "nome_ia": str(dados.get("nome_ia") or "Eva").strip() or "Eva",
        "tom_voz": str(dados.get("tom_voz") or "").strip(),
        "pode_emoji": "1" if dados.get("pode_emoji") else "0",
        "llm_provider": str(dados.get("llm_provider") or "openai").strip().lower(),
        "openai_model": str(dados.get("openai_model") or "gpt-4.1-mini").strip(),
        "llm_temperature": str(dados.get("llm_temperature") if dados.get("llm_temperature") is not None else "0.3"),
        "rag_provider": rag_provider,
        "rag_webhook_url": rag_url,
    }
    for k, v in plain.items():
        admin_store.set_config(k, v, unidade_id=unidade_id)

    openai_new = str(dados.get("openai_api_key") or "").strip()
    if openai_new and not openai_new.startswith("••••"):
        admin_store.set_config("openai_api_key", openai_new, unidade_id=unidade_id)

    trans_new = str(dados.get("transcription_api_key") or "").strip()
    if trans_new and not trans_new.startswith("••••"):
        admin_store.set_config("transcription_api_key", trans_new, unidade_id=unidade_id)

    rag_tok = str(dados.get("rag_webhook_token") or "").strip()
    if rag_tok and not rag_tok.startswith("••••"):
        admin_store.set_config("rag_webhook_token", rag_tok, unidade_id=unidade_id)

    return obter_config_ia(unidade_id=unidade_id)
