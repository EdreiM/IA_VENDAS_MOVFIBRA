"""Validação leve de campos cadastrais (mensagens humanas)."""

from __future__ import annotations

import re
from typing import Any


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _normalizar_nome(valor: str) -> str:
    t = _texto(valor).casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def rua_parece_eco_nome(rua: str, nome: str) -> bool:
    """Rua igual ao nome do cliente — quase sempre eco do LLM, não endereço real."""
    r = _normalizar_nome(rua)
    n = _normalizar_nome(nome)
    return bool(r and n and r == n)


def validar_campo(campo: str, valor: str, *, nome_cliente: str = "") -> str | None:
    """
    Retorna motivo amigável se inválido, ou None se ok.
    """
    v = _texto(valor)
    if not v:
        return None

    if campo == "nome":
        partes = [p for p in v.split() if p]
        if len(partes) < 2:
            return "preciso do nome completo (nome e sobrenome)"
        if any(ch.isdigit() for ch in v):
            return "o nome não deve ter números"
        return None

    if campo == "email":
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            return "esse e-mail não parece válido"
        return None

    if campo == "telefone":
        digitos = re.sub(r"\D", "", v)
        if len(digitos) < 10 or len(digitos) > 13:
            return "preciso de um telefone com DDD (10 ou 11 dígitos)"
        return None

    if campo == "cpf":
        digitos = re.sub(r"\D", "", v)
        if len(digitos) not in {11, 14}:
            return "CPF precisa ter 11 dígitos (ou CNPJ com 14)"
        return None

    if campo == "data_nascimento":
        if not re.match(r"^\d{2}/\d{2}/\d{4}$", v) and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return "preciso da data de nascimento no formato dd/mm/aaaa"
        return None

    if campo == "cep":
        digitos = re.sub(r"\D", "", v)
        if len(digitos) != 8:
            return "CEP precisa ter 8 dígitos"
        return None

    if campo == "rua":
        if len(v) < 3:
            return "preciso do nome da rua"
        if rua_parece_eco_nome(v, nome_cliente):
            return "preciso do nome da rua (logradouro), não o seu nome"
        return None

    if campo == "numero":
        if not v:
            return "preciso do número da casa ou apartamento"
        return None

    return None
