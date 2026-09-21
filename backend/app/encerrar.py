"""Encerramento de atendimento (n8n: PDF IXC + resolve Chatwoot)."""

from __future__ import annotations

from typing import Any

from app import db
from app.config import get_settings
from app.integrations.encerrar_webhook import encerrar_atendimento_webhook


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def encerrar_atendimento(estado: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    provider = (settings.encerrar_provider or "mock").lower()
    id_cliente = _texto(estado.get("id_cliente"))

    if not id_cliente:
        return {
            "resultado": "erro",
            "motivo": "id_cliente ausente",
            "erro": True,
        }

    if provider == "webhook":
        resultado = encerrar_atendimento_webhook(estado)
    else:
        resultado = {
            "resultado": "ok",
            "motivo": "Encerramento mock local",
            "provider": "mock",
            "erro": False,
        }

    # Só limpa histórico se encerrou com sucesso (não limpa em erro/timeout)
    ok = (
        not resultado.get("erro")
        and not resultado.get("timeout")
        and str(resultado.get("resultado") or "").lower() in {"ok", "sucesso", "success"}
    )
    if ok:
        try:
            db.limpar_historico(id_cliente)
        except Exception:  # noqa: BLE001
            pass

    return resultado
