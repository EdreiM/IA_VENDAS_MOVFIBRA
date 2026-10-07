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
    "outro horário",
    "outra hora",
    "tem outro horario",
    "tem outro horário",
    "tem outra hora",
    "nao posso nesse",
    "não posso nesse",
    "nao consigo nesse",
    "não consigo nesse",
    "nenhum serve",
    "nenhum horario",
    "nenhum horário",
    "outro dia",
    "outra data",
    "semana que vem",
    "de noite",
    "a noite",
    "à noite",
    "depois das 18",
    "antes das 8",
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


_ORDINAIS = {"primeir": 0, "segund": 1, "terceir": 2, "quart": 3, "quint": 4}


def _horas_citadas(msg: str) -> list[int]:
    """Horas na mensagem: '9h', 'às 9', '14:00', '9 horas' ou só '9'."""
    com_marca = [int(h) for h in re.findall(r"\b(\d{1,2})\s*(?:h\b|hs\b|hrs?\b|horas?\b|:\d{2})", msg)]
    if com_marca:
        return com_marca
    return [int(h) for h in re.findall(r"\b(\d{1,2})\b", msg)]


def match_horario(mensagem: str, estado: dict[str, Any]) -> ResultadoMatch:
    msg = _norm(mensagem)
    manha, tarde = horarios_disponiveis(estado)
    todos = manha + tarde

    if not msg or not todos:
        return ResultadoMatch(invalido=True)

    # O horário escrito por inteiro ("14h às 15h")
    for slot in todos:
        if _norm(slot) == msg or _norm(slot) in msg:
            return ResultadoMatch(slot=slot)

    quer_manha = any(w in msg for w in ("manha", "cedo"))
    quer_tarde = "tarde" in msg
    lista = manha if (quer_manha and not quer_tarde) else tarde if (quer_tarde and not quer_manha) else todos

    # "o primeiro", "o último (da tarde)"
    if "ultim" in msg and lista:
        return ResultadoMatch(slot=lista[-1])
    for raiz, idx in _ORDINAIS.items():
        if raiz in msg:
            return ResultadoMatch(slot=lista[idx]) if idx < len(lista) else ResultadoMatch(invalido=True)

    horas = _horas_citadas(msg)
    if horas:
        # A hora dita é a de INÍCIO: "às 9" é 9h–10h, não 8h–9h
        for h in horas:
            inicio = [s for s in todos if _hora_inicio(s) == h]
            if len(inicio) == 1:
                return ResultadoMatch(slot=inicio[0])
            if len(inicio) > 1:
                return ResultadoMatch(ambiguo=True, turno="")
        # "opção 2" / "o 2" — posição na lista, quando o número não é uma hora de início
        if len(horas) == 1 and 1 <= horas[0] <= len(todos) and not re.search(r"\d\s*(?:h\b|:)", msg):
            return ResultadoMatch(slot=todos[horas[0] - 1])
        return ResultadoMatch(invalido=True)

    # Só o turno
    if quer_manha != quer_tarde:
        if len(lista) == 1:
            return ResultadoMatch(slot=lista[0])
        if len(lista) > 1:
            return ResultadoMatch(ambiguo=True, turno="manha" if quer_manha else "tarde")
        return ResultadoMatch(invalido=True)

    return ResultadoMatch(invalido=True)


def slot_valido(slot: str, estado: dict[str, Any]) -> bool:
    manha, tarde = horarios_disponiveis(estado)
    return slot in manha + tarde
