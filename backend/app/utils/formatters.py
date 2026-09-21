"""Formatação de dados para exibição ao cliente."""

from __future__ import annotations

import re
from typing import Any

from app.utils.cpf import formatar_cpf_cnpj, somente_numeros


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def titulo_palavras(valor: str) -> str:
    t = _texto(valor)
    if not t:
        return ""
    return " ".join(p[:1].upper() + p[1:].lower() if p else "" for p in t.split())


def formatar_telefone(valor: str) -> str:
    n = somente_numeros(valor)
    if len(n) == 11:
        return f"({n[:2]}) {n[2:7]}-{n[7:]}"
    if len(n) == 10:
        return f"({n[:2]}) {n[2:6]}-{n[6:]}"
    return _texto(valor)


def formatar_cep(valor: str) -> str:
    n = somente_numeros(valor)
    if len(n) == 8:
        return f"{n[:5]}-{n[5:]}"
    return _texto(valor)


def formatar_data_nascimento(valor: str) -> str:
    t = _texto(valor)
    if not t:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", t)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return t
