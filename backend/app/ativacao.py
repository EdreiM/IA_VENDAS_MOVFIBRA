"""Ativação de contrato no IXC (n8n)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.integrations.ativacao_webhook import ativar_cliente_webhook


def ativar_cliente(estado: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    provider = (settings.ativacao_provider or "mock").lower()

    if provider == "webhook":
        return ativar_cliente_webhook(estado)

    return {
        "resultado": "ok",
        "ativado": True,
        "id_contrato_ixc": str(estado.get("id_contrato_ixc") or ""),
        "motivo": "Ativação mock local",
        "provider": "mock",
        "erro": False,
    }
