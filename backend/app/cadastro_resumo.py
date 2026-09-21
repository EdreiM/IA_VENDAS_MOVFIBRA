"""Resumo cadastral formatado antes da confirmação e cadastro no IXC."""

from __future__ import annotations

from typing import Any

from app.utils.cpf import formatar_cpf_cnpj
from app.utils.formatters import (
    formatar_cep,
    formatar_data_nascimento,
    formatar_telefone,
    titulo_palavras,
)


def _valor(estado: dict[str, Any], campo: str) -> str:
    v = estado.get(campo)
    return "" if v is None else str(v).strip()


def montar_resumo_cadastro(estado: dict[str, Any]) -> str:
    nome = _valor(estado, "nome")
    cpf = formatar_cpf_cnpj(_valor(estado, "cpf")) or _valor(estado, "cpf")
    email = _valor(estado, "email")
    telefone = formatar_telefone(_valor(estado, "telefone"))
    nascimento = formatar_data_nascimento(_valor(estado, "data_nascimento"))
    cep = formatar_cep(_valor(estado, "cep"))
    rua = titulo_palavras(_valor(estado, "rua"))
    numero = _valor(estado, "numero")
    bairro = titulo_palavras(_valor(estado, "bairro"))
    cidade = titulo_palavras(_valor(estado, "cidade"))
    plano = _valor(estado, "plano_confirmado") or _valor(estado, "plano_em_negociacao")

    linhas = [
        "📋 Confira seus dados cadastrais",
        "",
        f"👤 Nome: {nome}",
        f"🪪 CPF: {cpf}",
        f"📧 E-mail: {email}",
        f"📱 Telefone: {telefone}",
        f"🎂 Data de nascimento: {nascimento}",
        "",
        "📍 Endereço",
        f"• CEP: {cep}",
        f"• Rua: {rua}",
        f"• Número: {numero}",
        f"• Bairro: {bairro}",
        f"• Cidade: {cidade}",
        "",
        f"🌐 Plano escolhido: {plano}",
        "",
        "✅ Está tudo correto?",
        "",
        "Se quiser corrigir algum dado, é só me avisar!",
    ]
    return "\n".join(linhas)
