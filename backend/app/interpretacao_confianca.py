"""Usa confiança do LLM para clarificar antes de gravar ou avançar o funil."""

from __future__ import annotations

from typing import Any

from app.models import Evento

# Limiares — conservadores para cadastro; mais tolerante em vendas/perguntas.
CONFIANCA_ALTA = 0.88
CONFIANCA_MINIMA_OUTRO = 0.55
CONFIANCA_MINIMA_CADASTRO = 0.72
CONFIANCA_MINIMA_DADO_FORA_PENDENTE = 0.78

_CHAVES_MENSAGEM_CONVERSACIONAL = (
    "confuso",
    "confusa",
    "nossa",
    "aff",
    "nao entendi",
    "não entendi",
    "nao sei",
    "não sei",
    "sla",
    "slk",
    "tipo assim",
    "que isso",
    "que confus",
)


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _campo_parece_confiavel(
    campo: str,
    valor: str,
    *,
    msg: str,
    aguardando: str,
) -> bool:
    from app.interpretacao_campo import _valor_parece_resposta_campo

    return _valor_parece_resposta_campo(
        campo,
        valor,
        msg=msg,
        msg_bruto=msg,
        aguardando=aguardando or campo,
    )


def avaliar_necessidade_clarificacao(
    estado: dict[str, Any],
    resolucao: dict[str, Any],
    *,
    confianca: float,
    msg: str,
) -> dict[str, Any] | None:
    """
    Retorna contexto de clarificação ou None se pode seguir o fluxo normal.
    """
    from app.parser import eh_confirmacao, normalizar_texto
    from app.pos_venda_mensagens import eh_pedido_encerrar
    from app.state_machine import ORDEM_CADASTRO

    # confianca=0 → LLM não informou (testes/regressão) — não bloquear fluxo.
    if confianca <= 0 or confianca >= CONFIANCA_ALTA:
        return None

    bruto = _texto(msg)
    if not bruto or eh_pedido_encerrar(bruto):
        return None

    eventos = list(resolucao.get("eventos") or [])
    flags = resolucao.get("flags") or {}
    fase = _texto(estado.get("fase"))
    aguardando = _texto(estado.get("aguardando"))
    para_salvar = dict((resolucao.get("dados") or {}).get("para_salvar") or {})
    campos_info = list((resolucao.get("dados") or {}).get("campos_informados") or [])

    if flags.get("pediu_humano"):
        return None

    # Confirmação curta no pendente esperado — não interromper.
    if flags.get("confirmacao") and eh_confirmacao(normalizar_texto(bruto)):
        if aguardando in {"confirmacao_plano", "confirmacao_dados", "confirmacao_horario", "aceite_termos"}:
            return None
        if len(normalizar_texto(bruto).split()) <= 4:
            return None

    pendente = aguardando or None

    # OUTRO com baixa confiança — pedir reformulação.
    if Evento.OUTRO.value in eventos and confianca < CONFIANCA_MINIMA_OUTRO:
        return {
            "motivo": "outro",
            "pendente": pendente,
            "fase": fase,
            "confianca": confianca,
            "mensagem_cliente": bruto,
        }

    # Cadastro: dado suspeito ou fora do pendente com confiança baixa.
    if fase == "cadastro" and aguardando in ORDEM_CADASTRO:
        t_msg = normalizar_texto(bruto)
        if aguardando in campos_info and any(k in t_msg for k in _CHAVES_MENSAGEM_CONVERSACIONAL):
            return {
                "motivo": "cadastro_incerto",
                "pendente": aguardando,
                "fase": fase,
                "confianca": confianca,
                "campos_suspeitos": [aguardando],
                "mensagem_cliente": bruto,
            }

        suspeitos: list[str] = []
        for campo in campos_info:
            if campo not in ORDEM_CADASTRO and campo not in {"cidade", "bairro"}:
                continue
            valor = _texto(para_salvar.get(campo))
            if not valor:
                continue
            confiavel = _campo_parece_confiavel(
                campo, valor, msg=bruto, aguardando=aguardando
            )
            from app.validation import validar_campo

            if validar_campo(campo, valor) is not None:
                suspeitos.append(campo)
                continue
            if confiavel:
                continue
            if campo != aguardando and confianca < CONFIANCA_MINIMA_DADO_FORA_PENDENTE:
                suspeitos.append(campo)
            elif confianca < CONFIANCA_MINIMA_CADASTRO:
                suspeitos.append(campo)

        if suspeitos:
            return {
                "motivo": "cadastro_incerto",
                "pendente": aguardando,
                "fase": fase,
                "confianca": confianca,
                "campos_suspeitos": suspeitos,
                "mensagem_cliente": bruto,
            }

    # Vendas: plano informado com confiança baixa e sem sinal claro de plano.
    if (
        fase == "vendas"
        and flags.get("plano_informado")
        and confianca < CONFIANCA_MINIMA_CADASTRO
    ):
        from app.interpretacao_contexto import referencia_parece_plano

        ref = _texto((resolucao.get("plano") or {}).get("valor") or bruto)
        if ref and not referencia_parece_plano(ref, bruto):
            return {
                "motivo": "plano_incerto",
                "pendente": pendente or "confirmacao_plano",
                "fase": fase,
                "confianca": confianca,
                "mensagem_cliente": bruto,
            }

    # PERGUNTA + DADO na mesma msg com confiança muito baixa — confirmar intenção.
    if (
        flags.get("tem_pergunta")
        and Evento.DADO_INFORMADO.value in eventos
        and confianca < 0.62
        and fase in {"cadastro", "vendas"}
    ):
        tem_cadastro = any(c in ORDEM_CADASTRO for c in campos_info)
        if tem_cadastro:
            return {
                "motivo": "ambiguo",
                "pendente": pendente,
                "fase": fase,
                "confianca": confianca,
                "mensagem_cliente": bruto,
            }

    return None


def dados_sem_campos_suspeitos(
    dados_base: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Remove campos que motivaram clarificação — não persistir lixo."""
    from app.state_machine import ORDEM_CADASTRO

    d = dict(dados_base)
    motivo = str(ctx.get("motivo") or "")
    if motivo == "cadastro_incerto":
        for campo in ctx.get("campos_suspeitos") or []:
            d.pop(campo, None)
    elif motivo in {"outro", "ambiguo", "plano_incerto"}:
        for campo in ORDEM_CADASTRO:
            d.pop(campo, None)
        d.pop("plano", None)
    return d
