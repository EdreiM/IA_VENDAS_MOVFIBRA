"""Mensagens fixas do cadastro — menos deriva da LLM."""

from __future__ import annotations

from typing import Any

ROTULO_CAMPO = {
    "nome": "nome completo",
    "cpf": "CPF",
    "email": "e-mail",
    "telefone": "telefone com DDD",
    "data_nascimento": "data de nascimento (dd/mm/aaaa)",
    "cep": "CEP",
    "rua": "nome da rua",
    "numero": "número da casa ou apartamento",
    "confirmacao_dados": "confirmação dos dados",
}

# Cadastro em pares — menos idas e vindas. O cliente pode mandar os dois juntos
# ou só um; o que faltar é pedido em seguida.
PARES_CADASTRO: tuple[tuple[str, str], ...] = (
    ("nome", "cpf"),
    ("email", "telefone"),
    ("data_nascimento", "cep"),
    ("rua", "numero"),
)

_PROMPTS_PAR = {
    ("nome", "cpf"): (
        "Me passa seu *nome completo* e o *CPF*. Pode ser na mesma mensagem."
    ),
    ("email", "telefone"): (
        "Agora o *e-mail* e o *telefone com DDD*. Pode mandar os dois juntos."
    ),
    ("data_nascimento", "cep"): (
        "Qual sua *data de nascimento* (dd/mm/aaaa) e o *CEP* da instalação?"
    ),
    ("rua", "numero"): (
        "Qual o *nome da rua* e o *número* da casa ou apartamento?"
    ),
}


def par_de(campo: str | None) -> tuple[str, ...]:
    if not campo:
        return ()
    for par in PARES_CADASTRO:
        if campo in par:
            return par
    return (campo,)


def campos_para_pedir(estado: dict[str, Any] | None) -> list[str]:
    """Campos ainda vazios do próximo par (1 ou 2)."""
    estado = estado or {}
    for par in PARES_CADASTRO:
        faltam = [c for c in par if not str(estado.get(c) or "").strip()]
        if faltam:
            return faltam
    return []


def pedir_campos(campos: list[str] | tuple[str, ...]) -> str:
    itens = [c for c in campos if c in ROTULO_CAMPO and c != "confirmacao_dados"]
    if len(itens) >= 2:
        chave = (itens[0], itens[1])
        if chave in _PROMPTS_PAR:
            return _PROMPTS_PAR[chave]
    if len(itens) == 1:
        return pedir_campo(itens[0])
    if itens:
        return pedir_campo(itens[0])
    return "Me passa o próximo dado, por favor."


def pedir_campo(campo: str) -> str:
    rotulo = ROTULO_CAMPO.get(campo, campo)
    if campo == "nome":
        return "Agora me passa seu *nome completo*, por favor."
    if campo == "cpf":
        return "Me informa seu *CPF*, por favor."
    if campo == "email":
        return "Qual o seu *e-mail*?"
    if campo == "telefone":
        return "Me passa seu *telefone com DDD*, por favor."
    if campo == "data_nascimento":
        return "Qual sua *data de nascimento*? (dd/mm/aaaa)"
    if campo == "cep":
        return "Qual o *CEP* do endereço de instalação?"
    if campo == "rua":
        return "Qual o *nome da rua*?"
    if campo == "numero":
        return "Qual o *número* da casa ou apartamento?"
    return f"Me informe seu {rotulo}, por favor."


def anotar_e_pedir_proximo(
    *,
    campos_anotados: list[str],
    campos_corrigidos: list[str],
    pendente: str,
    estado: dict[str, Any],
) -> str:
    vistos: set[str] = set()
    teve_correcao = False
    teve_anotacao = False
    for campo in campos_corrigidos + campos_anotados:
        if campo in vistos or campo not in ROTULO_CAMPO:
            continue
        vistos.add(campo)
        if not str(estado.get(campo) or "").strip():
            continue
        if campo in campos_corrigidos:
            teve_correcao = True
        else:
            teve_anotacao = True

    if teve_correcao:
        corpo = "Atualizei!"
    elif teve_anotacao:
        corpo = "Anotei!"
    else:
        faltam = campos_para_pedir(estado) or ([pendente] if pendente else [])
        return pedir_campos(faltam)

    if pendente and pendente != "confirmacao_dados":
        faltam = campos_para_pedir(estado) or [pendente]
        return f"{corpo} {pedir_campos(faltam)}"
    return corpo


def confirmar_plano_e_avancar(plano_nome: str, valor: str = "") -> str:
    preco = f" — *{valor}*" if valor else ""
    return (
        f"Perfeito! Vamos seguir com o *{plano_nome}*{preco}. "
        + pedir_campos(["nome", "cpf"])
    )
