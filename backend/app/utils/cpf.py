"""Utilitários de CPF/CNPJ."""

from __future__ import annotations

import re


def somente_numeros(valor: str) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def formatar_cpf_cnpj(valor: str) -> str:
    """Mesma lógica do n8n formata_cpf."""
    numeros = somente_numeros(valor)
    if len(numeros) == 11:
        return re.sub(r"(\d{3})(\d{3})(\d{3})(\d{2})", r"\1.\2.\3-\4", numeros)
    if len(numeros) == 14:
        return re.sub(r"(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})", r"\1.\2.\3/\4-\5", numeros)
    return ""


def cpf_valido_formato(valor: str) -> bool:
    return len(somente_numeros(valor)) in {11, 14}
