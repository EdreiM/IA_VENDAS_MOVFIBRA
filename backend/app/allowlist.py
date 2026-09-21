"""Controle de quem pode falar com a Eva (teste vs produção)."""

from __future__ import annotations

import re

from app.config import get_settings


def _resolver_modo() -> str:
    try:
        from app.chatwoot_config import resolver_inbound_mode

        return resolver_inbound_mode()
    except Exception:
        return (get_settings().sofia_inbound_mode or "allowlist").strip().lower()


def _resolver_allowlist_raw() -> str:
    try:
        from app.chatwoot_config import resolver_allowlist_phones

        return resolver_allowlist_phones()
    except Exception:
        return (get_settings().sofia_allowlist_phones or "").strip()


def normalizar_telefone(valor: str | None) -> str:
    """Só dígitos; remove 55 do país se sobrar 12–13 dígitos típicos BR."""
    digits = re.sub(r"\D", "", valor or "")
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]
    return digits


def lista_permitidos() -> set[str]:
    raw = _resolver_allowlist_raw()
    return {normalizar_telefone(p) for p in raw.split(",") if normalizar_telefone(p)}


def modo_entrada() -> str:
    return _resolver_modo()


def entrada_permitida(id_cliente: str | None, *, telefone: str | None = None) -> bool:
    """
    closed    → ninguém via canal (só testes locais se enforce no /chat estiver off)
    allowlist → só números listados
    open      → todos (produção Meta)
    """
    mode = modo_entrada()
    if mode == "open":
        return True
    if mode == "closed":
        return False

    candidatos = [
        normalizar_telefone(id_cliente),
        normalizar_telefone(telefone),
    ]
    # JID WhatsApp: 5593...@s.whatsapp.net
    if id_cliente and "@" in id_cliente:
        candidatos.append(normalizar_telefone(id_cliente.split("@", 1)[0]))

    permitidos = lista_permitidos()
    return any(c and c in permitidos for c in candidatos)


def motivo_bloqueio() -> str:
    mode = modo_entrada()
    if mode == "closed":
        return "Entrada fechada (sofia_inbound_mode=closed). Use /chat local ou abra allowlist."
    if mode == "allowlist":
        return "Número fora da allowlist de teste. Inclua em SOFIA_ALLOWLIST_PHONES."
    return "Entrada bloqueada."
