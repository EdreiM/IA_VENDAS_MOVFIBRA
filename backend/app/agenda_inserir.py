"""Grava agendamento confirmado na OS (IXC via n8n)."""

from __future__ import annotations

from typing import Any

from app.agenda_datetime import slot_para_data_hora
from app.config import get_settings
from app.integrations.agenda_inserir_webhook import inserir_agendamento_webhook


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def inserir_agendamento(estado: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    provider = (settings.agenda_provider or "mock").lower()

    ixc = _texto(estado.get("ixc_cliente_id"))
    data_hora = slot_para_data_hora(
        _texto(estado.get("data_agendamento")),
        _texto(estado.get("horario_escolhido")),
    )
    tecnico = _texto(estado.get("tecnico_id"))

    if not ixc:
        return {"resultado": "erro", "motivo": "ixc_cliente_id ausente", "erro": True}
    if not data_hora:
        return {"resultado": "erro", "motivo": "data/horário inválidos para agendamento", "erro": True}
    if not tecnico:
        return {"resultado": "erro", "motivo": "id_tecnico ausente", "erro": True}

    if provider == "webhook":
        return inserir_agendamento_webhook(estado)

    return {
        "resultado": "ok",
        "os_id": "mock",
        "motivo": "Agendamento mock local",
        "provider": "mock",
    }
