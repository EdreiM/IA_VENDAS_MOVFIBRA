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


def cpf_digitos_conferem(valor: str) -> bool:
    """Dígitos verificadores de um CPF (11 dígitos). Não consulta nenhum sistema."""
    n = somente_numeros(valor)
    if len(n) != 11 or n == n[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(n[i]) * (tamanho + 1 - i) for i in range(tamanho))
        if (soma * 10) % 11 % 10 != int(n[tamanho]):
            return False
    return True


def celular_e_nao_cpf(valor: str) -> bool:
    """11 dígitos com cara de celular (DDD + 9...) que não fecham como CPF."""
    n = somente_numeros(valor)
    return len(n) == 11 and n[0] != "0" and n[1] != "0" and n[2] == "9" and not cpf_digitos_conferem(n)


def cpf_valido_formato(valor: str) -> bool:
    return len(somente_numeros(valor)) in {11, 14}
