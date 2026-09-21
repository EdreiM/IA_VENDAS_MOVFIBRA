"""Consulta de horários disponíveis para instalação."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from app.config import get_settings
from app.integrations.agenda_webhook import buscar_horarios_webhook

logger = logging.getLogger(__name__)


def _proximo_dia_util() -> date:
    alvo = date.today() + timedelta(days=1)
    while alvo.weekday() >= 5:
        alvo += timedelta(days=1)
    return alvo


def _data_br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def consultar_horarios(estado: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    provider = (settings.agenda_provider or "mock").lower()

    if provider == "webhook":
        return buscar_horarios_webhook(estado)

    data = _data_br(_proximo_dia_util())
    return {
        "resultado": "ok",
        "tecnico_id": "159",
        "data": data,
        "manha": ["8h às 9h", "9h às 10h", "10h às 11h", "11h às 12h"],
        "tarde": ["14h às 15h", "15h às 16h", "16h às 17h", "17h às 18h"],
        "motivo": "Horários mock locais",
        "provider": "mock",
    }
