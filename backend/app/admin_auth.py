"""Autenticação do painel — login email/senha."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import HTTPException

from app.config import get_settings


def token_sessao_admin() -> str:
    """Token derivado das credenciais admin (retornado após login)."""
    settings = get_settings()
    pwd = (settings.admin_password or "").strip()
    email = (settings.admin_email or "admin@movfibra.com").strip().lower()
    if not pwd:
        return ""
    msg = f"{email}:eva-admin-v1".encode()
    return hmac.new(pwd.encode(), msg, hashlib.sha256).hexdigest()


def credenciais_validas(email: str, password: str) -> bool:
    settings = get_settings()
    esperado_email = (settings.admin_email or "admin@movfibra.com").strip().lower()
    esperado_pwd = (settings.admin_password or "").strip()
    if not esperado_pwd:
        return False
    return email.strip().lower() == esperado_email and password == esperado_pwd


def exigir_admin(authorization: str | None, x_admin_token: str | None) -> None:
    settings = get_settings()
    pwd = (settings.admin_password or "").strip()
    api_tok = (settings.admin_api_token or "").strip()
    sessao = token_sessao_admin()

    # Sem senha nem token legado = modo aberto (só dev)
    if not pwd and not api_tok:
        return

    token = (x_admin_token or "").strip()
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if api_tok and token == api_tok:
        return
    if sessao and token == sessao:
        return

    raise HTTPException(status_code=401, detail="Faça login para continuar")


def login(email: str, password: str) -> dict[str, str | bool]:
    if not credenciais_validas(email, password):
        raise HTTPException(status_code=401, detail="Email ou senha inválidos")
    tok = token_sessao_admin()
    if not tok:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_PASSWORD não configurado no servidor",
        )
    return {
        "ok": True,
        "token": tok,
        "email": email.strip().lower(),
    }
