"""Conversão de data/horário do agendamento para o IXC/n8n."""

from __future__ import annotations

import re
from typing import Any


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def hora_inicio_slot(slot: str) -> int | None:
    m = re.search(r"(\d{1,2})\s*h", _texto(slot), re.IGNORECASE)
    return int(m.group(1)) if m else None


def slot_para_data_hora(data_br: str, slot: str) -> str:
    """
    Converte data dd/mm/yyyy + slot '8h às 9h' → yyyy-MM-dd HH:mm:ss
    (formato esperado pelo subfluxo n8n INSERE AGENDA).
    """
    data = _texto(data_br)
    horario = _texto(slot)
    m_date = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", data)
    hora = hora_inicio_slot(horario)
    if not m_date or hora is None:
        return ""
    dd, mm, yyyy = m_date.groups()
    return f"{yyyy}-{mm}-{dd} {hora:02d}:00:00"
