"""Matching de horários escolhidos pelo cliente."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _norm(s: str) -> str:
    t = s.casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def horarios_disponiveis(estado: dict[str, Any]) -> tuple[list[str], list[str]]:
    manha = estado.get("horarios_manha") or []
    tarde = estado.get("horarios_tarde") or []
    if isinstance(manha, str):
        import json
        try:
            manha = json.loads(manha)
        except json.JSONDecodeError:
            manha = []
    if isinstance(tarde, str):
        import json
        try:
            tarde = json.loads(tarde)
        except json.JSONDecodeError:
            tarde = []
    return (
        [str(h).strip() for h in manha if str(h).strip()],
        [str(h).strip() for h in tarde if str(h).strip()],
    )


PEDIDO_OUTRO_HORARIO = (
    "outro horario",
    "outra hora",
    "nao posso nesse",
    "não posso nesse",
    "nao consigo nesse",
    "não consigo nesse",
    "nenhum serve",
    "nenhum horario",
    "nenhum horário",
    "tem outro",
    "tem outra",
    "outro dia",
    "outra data",
    "semana que vem",
    "mais cedo",
    "mais tarde",
    "de noite",
    "a noite",
    "à noite",
    "depois das 18",
    "antes das 8",
    "só a tarde",
    "so a tarde",
    "só de manha",
    "so de manha",
    "prefiro",
    "nao da",
    "não dá",
    "impossivel",
    "impossível",
)


def pediu_outro_horario(mensagem: str) -> bool:
    msg = _norm(mensagem)
    if any(p in msg for p in PEDIDO_OUTRO_HORARIO):
        return True
    return bool(re.search(r"\b(?:tem|quero|preciso)\s+(?:outr[oa]|amanha|depois)\b", msg))


def _hora_inicio(slot: str) -> int | None:
    m = re.search(r"(\d{1,2})\s*h", slot)
    return int(m.group(1)) if m else None


def _slot_contem_hora(slot: str, hora: int) -> bool:
    ini = _hora_inicio(slot)
    if ini is None:
        return False
    return ini == hora or f"{hora}h" in slot.casefold()


@dataclass
class ResultadoMatch:
    slot: str = ""
    invalido: bool = False
    ambiguo: bool = False
    turno: str = ""


def match_horario(mensagem: str, estado: dict[str, Any]) -> ResultadoMatch:
    msg = _norm(mensagem)
    manha, tarde = horarios_disponiveis(estado)
    todos = manha + tarde

    if not msg or not todos:
        return ResultadoMatch(invalido=True)

    # Match exato ou substring
    for slot in todos:
        if _norm(slot) == msg or _norm(slot) in msg or msg in _norm(slot):
            return ResultadoMatch(slot=slot)

    # Hora explícita: "9h", "14h", "às 9"
    horas = [int(h) for h in re.findall(r"\b(\d{1,2})\s*h", msg)]
    if horas:
        matches = [s for s in todos if any(_slot_contem_hora(s, h) for h in horas)]
        if len(matches) == 1:
            return ResultadoMatch(slot=matches[0])
        if len(matches) > 1:
            return ResultadoMatch(ambiguo=True, turno="")
        return ResultadoMatch(invalido=True)

    # Turno genérico
    quer_manha = any(w in msg for w in ("manha", "manhã", "cedo"))
    quer_tarde = "tarde" in msg
    if quer_manha and not quer_tarde:
        if len(manha) == 1:
            return ResultadoMatch(slot=manha[0])
        if len(manha) > 1:
            if "primeir" in msg or "1 " in msg:
                return ResultadoMatch(slot=manha[0])
            return ResultadoMatch(ambiguo=True, turno="manha")
        return ResultadoMatch(invalido=True)
    if quer_tarde and not quer_manha:
        if len(tarde) == 1:
            return ResultadoMatch(slot=tarde[0])
        if len(tarde) > 1:
            if "primeir" in msg or "1 " in msg:
                return ResultadoMatch(slot=tarde[0])
            return ResultadoMatch(ambiguo=True, turno="tarde")
        return ResultadoMatch(invalido=True)

    # Numeração: "o 1", "opcao 2"
    m = re.search(r"\b(?:opcao|opção|numero|nº|#)?\s*(\d+)\b", msg)
    if m:
        idx = int(m.group(1)) - 1
        lista = manha + tarde
        if 0 <= idx < len(lista):
            return ResultadoMatch(slot=lista[idx])

    return ResultadoMatch(invalido=True)


def slot_valido(slot: str, estado: dict[str, Any]) -> bool:
    manha, tarde = horarios_disponiveis(estado)
    return slot in manha + tarde
