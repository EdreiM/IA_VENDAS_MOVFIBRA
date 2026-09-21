"""Catálogo de planos — PostgreSQL local ou webhook n8n (com cache)."""

from __future__ import annotations

import logging
import time
from typing import Any

from app import db
from app.config import get_settings
from app.integrations.plans_webhook import buscar_planos_webhook

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {
    "key": "",
    "expires": 0.0,
    "planos": [],
    "plano_destaque_id": None,
}


def _contexto_de_estado(estado: dict[str, Any] | None) -> dict[str, Any]:
    from app.webhook_payload import snapshot_cliente

    return snapshot_cliente(estado or {}, incluir_historico=False)


def _cache_key(ctx: dict[str, Any]) -> str:
    return f"{ctx.get('cidade')}|{ctx.get('bairro')}|{ctx.get('tem_cobertura')}"


def invalidar_cache_planos() -> None:
    _cache["key"] = ""
    _cache["expires"] = 0.0
    _cache["planos"] = []
    _cache["plano_destaque_id"] = None


def _carregar_local() -> list[dict[str, Any]]:
    return db.listar_planos_ativos()


def _carregar_webhook(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    settings = get_settings()
    key = _cache_key(ctx)
    now = time.monotonic()
    ttl = max(30.0, float(settings.plans_cache_ttl_seconds))

    if _cache["key"] == key and _cache["expires"] > now and _cache["planos"]:
        return list(_cache["planos"])

    resultado = buscar_planos_webhook(ctx)
    planos = resultado.get("planos") or []

    if planos:
        _cache["key"] = key
        _cache["expires"] = now + ttl
        _cache["planos"] = planos
        _cache["plano_destaque_id"] = resultado.get("plano_destaque_id")
        return list(planos)

    if _cache["planos"] and _cache["key"] == key:
        logger.warning("Plans webhook falhou — usando cache anterior")
        return list(_cache["planos"])

    logger.warning("Plans webhook falhou — fallback PostgreSQL local")
    return _carregar_local()


def listar_planos(estado: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    settings = get_settings()
    provider = settings.plans_provider.lower()

    if provider in {"", "postgres", "postgresql", "local", "sqlite"}:
        return _carregar_local()

    if provider == "webhook":
        return _carregar_webhook(_contexto_de_estado(estado))

    logger.warning("Plans provider desconhecido: %s — usando PostgreSQL", provider)
    return _carregar_local()


def _norm_nome(nome: str) -> str:
    return " ".join(str(nome or "").casefold().split())


def _plano_por_nome(planos: list[dict[str, Any]], referencia: str) -> dict[str, Any] | None:
    ref = _norm_nome(referencia)
    if not ref:
        return None

    for p in planos:
        if _norm_nome(p.get("nome")) == ref:
            return p

    for p in planos:
        nome = _norm_nome(p.get("nome"))
        if ref in nome or nome in ref:
            if "super" in ref and "super+" in nome and ref != nome:
                continue
            if "one" in ref and "one+" in nome and ref != nome:
                continue
            if "up" in ref and "up+" in nome and ref != nome:
                continue
            return p

    return None


def plano_destaque(estado: dict[str, Any] | None = None) -> dict[str, Any] | None:
    planos = listar_planos(estado)
    if not planos:
        return None

    # 1) Flag "plano inicial" no painel (destaque)
    for p in planos:
        if p.get("destaque"):
            return p

    # 2) Fallback legado: PLANS_PLANO_INICIAL no .env
    settings = get_settings()
    preferido = (settings.plans_plano_inicial or "").strip()
    if preferido:
        escolhido = _plano_por_nome(planos, preferido)
        if escolhido:
            return escolhido

    # 3) Webhook: plano_destaque_id do n8n (só se ainda estiver em webhook)
    if settings.plans_provider.lower() == "webhook":
        destaque_id = _cache.get("plano_destaque_id")
        if destaque_id is not None:
            for p in planos:
                if int(p["id"]) == int(destaque_id):
                    return p

    return planos[0]
