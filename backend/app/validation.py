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


_CHAVES_RUA_INVALIDA = (
    "plano",
    "planos",
    "combo",
    " mov ",
    "mov ",
    "infinity",
    "essencial",
    "flex",
    "super",
    "mais barato",
    "mais barata",
    "mais caro",
    "mais forte",
    "outro plano",
    "outros planos",
    "quero um",
    "trocar de plano",
    "mudar de plano",
    "opcoes",
    "opcao",
    "mensalidade",
    "preco",
    "quanto custa",
    "instalar",
    "instalacao",
    "taxa",
)


def rua_parece_frase_invalida(rua: str) -> bool:
    """Frase conversacional/planos gravada como logradouro."""
    t = _normalizar_nome(rua)
    if not t or len(t.split()) < 3:
        return False
    return any(k in t for k in _CHAVES_RUA_INVALIDA)


_CHAVES_NOME_INVALIDO = (
    "me da ",
    "me dá ",
    "me passa",
    "me manda",
    "cadastra",
    "quero ver",
    "quero contratar",
    "da logo",
    "dá logo",
    "atende sim",
    "quanto",
    "preco",
    "plano",
    "planos",
    "contratar",
    "instalar",
    "cancelar",
    "multa",
    "encerrar",
    "finalizar",
    "atendimento",
    "desistir",
    "continuar",
    " mano",
    " po ",
    "pooo",
)

_PALAVRAS_NAO_NOME = frozenset({
    "me", "da", "de", "dá", "logo", "quero", "ver", "contratar", "mano", "po",
    "sim", "nao", "não", "ta", "tá", "atende", "isso", "ai", "aí", "pra", "por",
    "favor", "cadastra", "manda", "passa", "coloca", "corre", "bora", "vamo",
    "pooo", "aff", "puts", "caraca", "bro", "vei", "cara",
    "pode", "encerrar", "finalizar", "atendimento", "desistir", "continuar", "parar",
})


def nome_parece_frase_invalida(nome: str, msg_bruto: str = "") -> bool:
    """Frase conversacional/imperativo — não é nome de pessoa."""
    t = _normalizar_nome(nome)
    bruto = _normalizar_nome(msg_bruto or nome)
    if not t:
        return True
    if any(k in bruto for k in _CHAVES_NOME_INVALIDO):
        return True
    if re.search(r"\b(me|nos|te)\s+(da|dá|passa|manda|coloca|envia)\b", bruto):
        return True
    partes = [p for p in t.split() if p]
    if not partes:
        return True
    if all(p in _PALAVRAS_NAO_NOME for p in partes):
        return True
    return False


def validar_campo(campo: str, valor: str, *, nome_cliente: str = "") -> str | None:
    """
    Retorna motivo amigável se inválido, ou None se ok.
    """
    v = _texto(valor)
    if not v:
        return None

    if campo == "nome":
        if nome_parece_frase_invalida(v):
            return "isso não parece um nome — me passa seu nome completo"
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
        if len(digitos) == 11:
            from app.utils.cpf import cpf_digitos_conferem

            if not cpf_digitos_conferem(digitos):
                return "esse CPF não confere — pode conferir os números e mandar de novo?"
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
        if rua_parece_frase_invalida(v):
            return "preciso do nome da rua (logradouro), não uma pergunta ou pedido de plano"
        return None

    if campo == "numero":
        if not v:
            return "preciso do número da casa ou apartamento"
        return None

    if campo in {"cidade", "bairro"}:
        if len(v) < 2:
            return f"preciso do nome {'da cidade' if campo == 'cidade' else 'do bairro'}"
        if "?" in v or len(v.split()) > 6:
            return "me passa só o nome da cidade ou bairro, por favor"
        return None

    return None
