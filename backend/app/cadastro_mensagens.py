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


def campos_para_pedir(
    estado: dict[str, Any] | None, pendente: str | None = None
) -> list[str]:
    """Campos do próximo par a pedir (1 ou 2).

    Com `pendente` (o campo que a máquina de estados aguarda), o pedido sempre
    começa por ele — mesmo que já exista um valor salvo, como um CPF ainda não
    validado. Sem isso o texto pede um campo e o estado espera outro.
    """
    estado = estado or {}
    par_pendente = next((p for p in PARES_CADASTRO if pendente in p), None)
    if par_pendente:
        pos = par_pendente.index(pendente)
        return [pendente] + [
            c for c in par_pendente[pos + 1 :] if not str(estado.get(c) or "").strip()
        ]
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


ORDEM_CADASTRO_ACK = ("nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero")


def anotar_e_pedir_proximo(
    *,
    campos_anotados: list[str],
    campos_corrigidos: list[str],
    pendente: str,
    estado: dict[str, Any],
    retomada_cadastro: bool = False,
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

    def _frase_anotacao(campos: list[str], corrigiu: bool) -> str:
        rotulos = {
            "nome": "seu nome",
            "cpf": "CPF",
            "email": "e-mail",
            "telefone": "telefone",
            "data_nascimento": "data de nascimento",
            "cep": "CEP",
            "rua": "rua",
            "numero": "número",
        }
        itens = [rotulos.get(c, c) for c in campos if c in rotulos]
        if not itens:
            return "Atualizei!" if corrigiu else "Anotei!"
        if len(itens) == 1:
            lista = itens[0]
        elif len(itens) == 2:
            lista = f"{itens[0]} e {itens[1]}"
        else:
            lista = f"{', '.join(itens[:-1])} e {itens[-1]}"
        if corrigiu:
            return f"Atualizei {lista}."
        # Uma atendente não repete "Anotei X." oito vezes: a frase muda a cada passo do cadastro
        feitos = sum(1 for c in ORDEM_CADASTRO_ACK if str(estado.get(c) or "").strip())
        primeiro_nome = str(estado.get("nome") or "").strip().split(" ")[0] if "nome" not in campos else ""
        chamar = f", {primeiro_nome}" if primeiro_nome else ""
        variacoes = (
            f"Anotei {lista}.",
            f"Perfeito{chamar}! Anotei {lista}.",
            f"Peguei {lista}, obrigada!",
            f"Ótimo{chamar}, já tenho {lista}.",
        )
        return variacoes[feitos % len(variacoes)]

    anotados_ok = [
        c
        for c in campos_anotados
        if c in ROTULO_CAMPO and c not in campos_corrigidos and str(estado.get(c) or "").strip()
    ]
    corrigidos_ok = [
        c for c in campos_corrigidos if c in ROTULO_CAMPO and str(estado.get(c) or "").strip()
    ]

    if corrigidos_ok:
        corpo = _frase_anotacao(corrigidos_ok, corrigiu=True)
    elif anotados_ok:
        corpo = _frase_anotacao(anotados_ok, corrigiu=False)
    else:
        faltam = campos_para_pedir(estado, pendente) or ([pendente] if pendente else [])
        return pedir_campos(faltam)

    prefixo_retomada = ""
    if retomada_cadastro:
        from app.vendas_mensagens import frase_voltar_ao_cadastro

        prefixo_retomada = frase_voltar_ao_cadastro(pendente)
        if corpo:
            return f"{corpo} {prefixo_retomada}"
    if pendente and pendente != "confirmacao_dados":
        faltam = campos_para_pedir(estado, pendente) or [pendente]
        prox = pedir_campos(faltam)
        if prefixo_retomada and not corpo:
            return f"{prefixo_retomada} {prox}".strip()
        return f"{corpo} {prox}".strip()
    return corpo or prefixo_retomada


def confirmar_plano_e_avancar(
    plano_nome: str,
    valor: str = "",
    estado: dict[str, Any] | None = None,
) -> str:
    preco = f" — *{valor}*" if valor else ""
    estado = estado or {}
    faltam = campos_para_pedir(estado) or (["cpf"] if str(estado.get("nome") or "").strip() else ["nome", "cpf"])
    return (
        f"Perfeito! Vamos seguir com o *{plano_nome}*{preco}. "
        + pedir_campos(faltam)
    )
