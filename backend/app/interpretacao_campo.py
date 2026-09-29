"""Interpretação antes de gravar — evita anotar conversa/pedido/pergunta como dado."""

from __future__ import annotations

import re
from typing import Any

from app.models import CAMPOS_DADOS, DadosExtraidos, Evento


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _norm(valor: str) -> str:
    t = _texto(valor).casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


_CHAVES_IMPERATIVO = (
    "me da ",
    "me dá ",
    "me passa",
    "me manda",
    "cadastra",
    "quero ver",
    "quero contratar",
    "da logo",
    "dá logo",
    "manda logo",
    "bora ",
    "vamo ",
)

_CHAVES_PEDIDO_URGENCIA = (
    "logo isso",
    "de uma vez",
    "rapido",
    "rápido",
    "aff",
    "puts",
    "caraca",
    "pooo",
    " po ",
    " mano",
)


def mensagem_tem_intencao_nao_dado(
    msg: str,
    msg_bruto: str,
    *,
    aguardando: str = "",
    fase: str = "",
) -> bool:
    """Cliente pede, pergunta ou conversa — não está informando o campo pendente."""
    from app.parser import (
        eh_confirmacao,
        eh_mensagem_sobre_planos,
        eh_pergunta_cancelamento,
        eh_pergunta_instalacao,
        normalizar_texto,
        tem_duvida_informativa,
    )
    from app.pos_venda_mensagens import eh_pedido_encerrar

    bruto = _texto(msg_bruto or msg)
    t = normalizar_texto(bruto)

    if eh_pedido_encerrar(bruto):
        return True
    if tem_duvida_informativa(msg, bruto, aguardando=aguardando or None):
        return True
    if eh_mensagem_sobre_planos(msg, bruto):
        return True
    if eh_pergunta_instalacao(msg, bruto):
        return True
    if eh_pergunta_cancelamento(msg, bruto):
        return True

    tn = _norm(bruto)
    if any(k in tn for k in _CHAVES_IMPERATIVO):
        return True
    if any(k in tn for k in _CHAVES_PEDIDO_URGENCIA):
        return True

    from app.state_machine import ORDEM_CADASTRO

    if aguardando in ORDEM_CADASTRO:
        if eh_confirmacao(msg) and aguardando == "nome":
            return True
        if eh_confirmacao(msg) and len(t.split()) <= 5:
            from app.parser import _texto_parece_apenas_dado_cadastro

            if not _texto_parece_apenas_dado_cadastro(bruto, aguardando):
                return True

    if aguardando == "localizacao" and fase in {"inicio", "viabilidade", "vendas"}:
        if not _mensagem_tem_sinal_localizacao(bruto):
            if any(
                k in tn
                for k in (
                    "quero",
                    "contratar",
                    "plano",
                    "planos",
                    "ver os",
                    "mostra",
                    "cadastr",
                )
            ):
                return True

    return False


def _mensagem_tem_sinal_localizacao(msg_bruto: str) -> bool:
    from app.localizacao_heuristica import (
        CIDADES_CONHECIDAS,
        BAIRROS_CONHECIDOS,
        extrair_clarificacao_localizacao,
    )

    bruto = _texto(msg_bruto)
    if not bruto:
        return False
    if extrair_clarificacao_localizacao(bruto):
        return True
    tn = _norm(bruto)
    if any(c in tn for c in CIDADES_CONHECIDAS):
        return True
    if any(b in tn for b in BAIRROS_CONHECIDOS):
        return True
    if re.search(r"\b(?:cidade|bairro|moro|fico|estou|to|aqui)\b", tn):
        return True
    if re.search(r"\b(?:em|no|na)\s+\w", tn):
        return True
    return False


def _valor_parece_resposta_campo(
    campo: str,
    valor: str,
    *,
    msg: str,
    msg_bruto: str,
    aguardando: str,
) -> bool:
    from app.parser import (
        _extrair_cpf,
        _extrair_cpf_embutido,
        _extrair_data_nascimento,
        _extrair_email,
        _extrair_nome_livre,
        _extrair_telefone_em_segmentos,
        _mensagem_e_apenas_cpf,
        _mensagem_tem_sinal_endereco,
        _parece_cpf_cnpj,
        _texto_parece_apenas_dado_cadastro,
        normalizar_texto,
    )
    from app.validation import nome_parece_frase_invalida, rua_parece_frase_invalida, validar_campo

    bruto = _texto(msg_bruto or msg)
    v = _texto(valor)
    if not v:
        return False

    if campo == "nome":
        if nome_parece_frase_invalida(v, bruto):
            return False
        if validar_campo("nome", v):
            return False
        if not _extrair_nome_livre(bruto) and not re.search(
            r"(?i)\b(?:meu|o)\s+nome\s*(?:é|e|eh)\s+", bruto
        ):
            if mensagem_tem_intencao_nao_dado(msg, bruto, aguardando=aguardando):
                return False
        return True

    if campo == "cpf":
        dig = re.sub(r"\D", "", v)
        if len(dig) not in {11, 14}:
            return False
        if _parece_cpf_cnpj(normalizar_texto(bruto), bruto):
            return True
        return bool(_extrair_cpf_embutido(bruto) or _extrair_cpf("", bruto))

    if campo == "email":
        return bool(_extrair_email(bruto)) and "@" in bruto

    if campo == "telefone":
        if aguardando == "cpf":
            return False
        if aguardando != "telefone" and _mensagem_e_apenas_cpf(bruto):
            return False
        return bool(_extrair_telefone_em_segmentos(bruto))

    if campo == "data_nascimento":
        return bool(_extrair_data_nascimento(bruto))

    if campo == "cep":
        dig = re.sub(r"\D", "", v)
        return len(dig) == 8 and bool(re.search(r"\d{5}", bruto))

    if campo == "rua":
        if rua_parece_frase_invalida(v):
            return False
        if validar_campo("rua", v):
            return False
        return _mensagem_tem_sinal_endereco(bruto, aguardando=aguardando) or bool(
            re.search(r"(?i)\bru[aá]\b", bruto)
        )

    if campo == "numero":
        return bool(re.search(r"\b\d+[A-Za-z]?\b", bruto))

    if campo in {"cidade", "bairro"}:
        return _mensagem_tem_sinal_localizacao(bruto)

    if campo == "turno_escolhido":
        from app.agenda_slots import match_horario

        return bool(match_horario(bruto, {}).slot)

    return _texto_parece_apenas_dado_cadastro(bruto, campo) if campo in {
        "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero"
    } else True


def _campos_com_valor(dados: DadosExtraidos) -> list[str]:
    out: list[str] = []
    for campo in CAMPOS_DADOS:
        if _texto(getattr(dados, campo, "")):
            out.append(campo)
    return out


def aplicar_guards_interpretacao(
    *,
    dados: DadosExtraidos,
    eventos: list[str],
    pergunta: str,
    estado: dict[str, Any],
    msg: str,
    msg_bruto: str,
    aguardando: str,
    fase: str,
    campos_corrigidos: list[str],
) -> str:
    """
    Remove dados extraídos quando a mensagem não responde ao pendente.
    Ajusta eventos (PERGUNTA vs DADO_INFORMADO).
    """
    from app.parser import extrair_parte_pergunta, tem_duvida_informativa
    from app.pos_venda_mensagens import eh_pedido_encerrar
    from app.state_machine import ORDEM_CADASTRO

    bruto_guard = _texto(msg_bruto or msg)
    if eh_pedido_encerrar(bruto_guard):
        for campo in CAMPOS_DADOS:
            setattr(dados, campo, "")
        eventos[:] = [
            e
            for e in eventos
            if e
            not in {
                Evento.DADO_INFORMADO.value,
                Evento.PLANO_INFORMADO.value,
                Evento.LOCALIZACAO_INFORMADA.value,
                Evento.CONFIRMACAO.value,
                Evento.PERGUNTA.value,
                Evento.OUTRO.value,
                Evento.CONVERSA_SOCIAL.value,
            }
        ]
        if Evento.NEGACAO.value not in eventos:
            eventos.append(Evento.NEGACAO.value)
        return ""

    corrigidos = {c.lower() for c in campos_corrigidos}
    aguardando = _texto(aguardando)
    fase = _texto(fase)
    bruto = _texto(msg_bruto or msg)

    intencao_nao_dado = mensagem_tem_intencao_nao_dado(
        msg, bruto, aguardando=aguardando, fase=fase
    )
    tem_duvida = tem_duvida_informativa(
        msg, bruto, aguardando=aguardando if fase == "cadastro" else None
    )

    from app.interpretacao_contexto import sanitizar_plano_informado_llm

    pergunta = sanitizar_plano_informado_llm(
        dados=dados,
        eventos=eventos,
        pergunta=pergunta,
        msg=msg,
        msg_bruto=bruto,
        intencao_nao_dado=intencao_nao_dado,
        tem_duvida=tem_duvida,
    )

    for campo in list(CAMPOS_DADOS):
        if campo in corrigidos:
            continue
        valor = _texto(getattr(dados, campo, ""))
        if not valor:
            continue

        rejeitar = False

        if campo == "nome":
            from app.validation import nome_parece_frase_invalida

            if nome_parece_frase_invalida(valor, bruto):
                rejeitar = True

        if not rejeitar and aguardando and campo == aguardando:
            if not _valor_parece_resposta_campo(
                campo, valor, msg=msg, msg_bruto=bruto, aguardando=aguardando
            ):
                rejeitar = True

        if not rejeitar and aguardando in ORDEM_CADASTRO and campo in ORDEM_CADASTRO:
            idx_a = ORDEM_CADASTRO.index(aguardando)
            idx_c = ORDEM_CADASTRO.index(campo)
            if idx_c > idx_a and not _valor_parece_resposta_campo(
                campo, valor, msg=msg, msg_bruto=bruto, aguardando=aguardando
            ):
                rejeitar = True

        if not rejeitar and campo in {"cidade", "bairro"}:
            if aguardando == "localizacao" and not _mensagem_tem_sinal_localizacao(bruto):
                rejeitar = True
            elif intencao_nao_dado and not _mensagem_tem_sinal_localizacao(bruto):
                rejeitar = True

        if rejeitar:
            setattr(dados, campo, "")

    campos_restantes = _campos_com_valor(dados)
    tinha_dado = Evento.DADO_INFORMADO.value in eventos

    if tinha_dado and not campos_restantes:
        eventos[:] = [e for e in eventos if e != Evento.DADO_INFORMADO.value]

    if (intencao_nao_dado or tem_duvida) and not campos_restantes:
        if Evento.CORRECAO_DADO.value not in eventos:
            if Evento.PERGUNTA.value not in eventos:
                eventos.append(Evento.PERGUNTA.value)
            if not pergunta:
                pergunta = extrair_parte_pergunta(bruto, msg) or bruto

    if aguardando == "localizacao" and intencao_nao_dado:
        eventos[:] = [
            e
            for e in eventos
            if e
            not in {
                Evento.LOCALIZACAO_INFORMADA.value,
                Evento.DADO_INFORMADO.value,
            }
        ]
        dados.cidade = ""
        dados.bairro = ""

    return pergunta


def filtrar_campos_informados(
    campos_info: list[str],
    dados: dict[str, Any],
    *,
    msg: str,
    msg_bruto: str,
    aguardando: str | None,
    estado: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    """Última barreira na state machine antes de persistir."""
    from app.state_machine import ORDEM_CADASTRO

    aguardando = _texto(aguardando)
    bruto = _texto(msg_bruto or msg)
    if not aguardando or not campos_info:
        return campos_info, dados

    aceitos: list[str] = []
    dados_out = dict(dados)
    for campo in campos_info:
        valor = _texto(dados_out.get(campo))
        if not valor:
            continue
        if campo in ORDEM_CADASTRO or campo in {"cidade", "bairro", "turno_escolhido"}:
            if not _valor_parece_resposta_campo(
                campo, valor, msg=msg, msg_bruto=bruto, aguardando=aguardando
            ):
                dados_out.pop(campo, None)
                continue
        aceitos.append(campo)

    return aceitos, dados_out
