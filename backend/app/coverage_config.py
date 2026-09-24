"""Configuração de cobertura/viabilidade (painel) — Google Maps + IXC."""

from __future__ import annotations

from typing import Any

from app import admin_store
from app.config import get_settings


def _mask(valor: str) -> str:
    v = (valor or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "••••"
    return f"{v[:4]}...{v[-4:]}"


def _cfg(chave: str, default: str = "", *, unidade_id: int | None = None) -> str:
    return admin_store.get_config(chave, default, unidade_id=unidade_id).strip()


def resolver_coverage_provider(*, unidade_id: int | None = None) -> str:
    """Produção usa sempre IXC; mock legado no painel é ignorado."""
    db = _cfg("coverage_provider", "", unidade_id=unidade_id).lower()
    if db in {"ixc", "mock"}:
        return "ixc"
    env = (get_settings().coverage_provider or "ixc").strip().lower()
    return "ixc" if env == "mock" else env


def resolver_google_maps_api_key(*, unidade_id: int | None = None) -> str:
    db = _cfg("google_maps_api_key", "", unidade_id=unidade_id)
    if db:
        return db
    return (get_settings().google_maps_api_key or "").strip()


def resolver_ixc_base_url(*, unidade_id: int | None = None) -> str:
    db = _cfg("ixc_base_url", "", unidade_id=unidade_id)
    if db:
        return db.rstrip("/")
    return (get_settings().ixc_base_url or "https://ixc.mov.pro.br/webservice/v1").rstrip("/")


def resolver_ixc_user(*, unidade_id: int | None = None) -> str:
    db = _cfg("ixc_user", "", unidade_id=unidade_id)
    if db:
        return db
    return (get_settings().ixc_user or "").strip()


def resolver_ixc_password(*, unidade_id: int | None = None) -> str:
    db = _cfg("ixc_password", "", unidade_id=unidade_id)
    if db:
        return db
    return (get_settings().ixc_password or "").strip()


def cobertura_configurada(*, unidade_id: int | None = None) -> bool:
    """True se credenciais IXC mínimas presentes."""
    return bool(
        resolver_ixc_user(unidade_id=unidade_id)
        and resolver_ixc_password(unidade_id=unidade_id)
    )


def google_configurado(*, unidade_id: int | None = None) -> bool:
    return bool(resolver_google_maps_api_key(unidade_id=unidade_id))


def obter_config_cobertura(*, unidade_id: int | None = None) -> dict[str, Any]:
    gkey = resolver_google_maps_api_key(unidade_id=unidade_id)
    ixc_user = resolver_ixc_user(unidade_id=unidade_id)
    ixc_pass = resolver_ixc_password(unidade_id=unidade_id)
    faltando: list[str] = []
    if not ixc_user or not ixc_pass:
        faltando.append("IXC (usuário e senha)")
    if not gkey:
        faltando.append("Google Maps (endereço em texto)")

    return {
        "coverage_provider": "ixc",
        "ixc_base_url": resolver_ixc_base_url(unidade_id=unidade_id),
        "google_maps_configured": bool(gkey),
        "google_maps_api_key_mask": _mask(gkey) if gkey else "",
        "ixc_configured": bool(ixc_user and ixc_pass),
        "ixc_user_mask": _mask(ixc_user) if ixc_user else "",
        "ixc_password_configured": bool(ixc_pass),
        "ixc_password_mask": _mask(ixc_pass) if ixc_pass else "",
        "cobertura_pronta": not faltando,
        "faltando": faltando,
    }


def salvar_config_cobertura(dados: dict[str, Any], *, unidade_id: int | None = None) -> dict[str, Any]:
    admin_store.set_config("coverage_provider", "ixc", unidade_id=unidade_id)

    base = str(dados.get("ixc_base_url") or "").strip().rstrip("/")
    if base:
        admin_store.set_config("ixc_base_url", base, unidade_id=unidade_id)

    gkey = str(dados.get("google_maps_api_key") or "").strip()
    if gkey and not gkey.startswith("••••"):
        admin_store.set_config("google_maps_api_key", gkey, unidade_id=unidade_id)

    user = str(dados.get("ixc_user") or "").strip()
    if user and not user.startswith("••••"):
        admin_store.set_config("ixc_user", user, unidade_id=unidade_id)

    pwd = str(dados.get("ixc_password") or "").strip()
    if pwd and not pwd.startswith("••••"):
        admin_store.set_config("ixc_password", pwd, unidade_id=unidade_id)

    return obter_config_cobertura(unidade_id=unidade_id)
