"""
Intenção do cliente na fase de planos — determinístico, baseado em estado explícito.

Padrão profissional: o que a Eva está esperando fica em `contexto_plano` + `aguardando`,
não inferido por palavras soltas na última resposta (frágil e causa bugs como
"Sim" após confirmar plano virar lista de desconto).
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class IntencaoPlano(str, Enum):
    """Próxima ação lógica na fase vendas/planos."""

    NENHUMA = "nenhuma"
    CONFIRMAR = "confirmar"
    LISTAR_DESCONTO = "listar_desconto"
    LISTAR_TODOS = "listar_todos"
    PEDIR_ESCOLHA = "pedir_escolha"
    RECUSAR = "recusar"
    ESCOLHER_REFERENCIA = "escolher_referencia"


# Valores persistidos em estado_cliente_ia.contexto_plano
CTX_APRESENTACAO_INICIAL = "apresentacao_inicial"
CTX_CONFIRMACAO_UNICO = "confirmacao_unico"
CTX_ESCOLHA_CATALOGO = "escolha_catalogo"
CTX_OFERTA_LISTA_DESCONTO = "oferta_lista_desconto"
CTX_ALTERNATIVAS = "alternativas"


def contexto_por_objetivo_resposta(objetivo: str | None) -> str:
    """Deriva contexto_plano a partir do objetivo de resposta (fallback seguro)."""
    o = (objetivo or "").strip()
    mapa = {
        "APRESENTAR_PLANO_INICIAL": CTX_APRESENTACAO_INICIAL,
        "APRESENTAR_PLANO_ESCOLHIDO_E_CONFIRMAR": CTX_CONFIRMACAO_UNICO,
        "APRESENTAR_TROCA_PLANO_E_CONFIRMAR": CTX_CONFIRMACAO_UNICO,
        "APRESENTAR_LISTA_COMPLETA_PLANOS": CTX_ESCOLHA_CATALOGO,
        "APRESENTAR_PLANOS_ALTERNATIVOS": CTX_ALTERNATIVAS,
        "INFORMAR_DETALHES_PLANO": CTX_CONFIRMACAO_UNICO,
    }
    return mapa.get(o, "")


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _eh_confirmacao(msg: str, flags: dict[str, Any]) -> bool:
    from app.parser import eh_confirmacao, eh_sim_antes_de_pergunta, normalizar_texto

    if flags.get("confirmacao"):
        return True
    # Com "?", só o sim dito antes da pergunta confirma: "pode ser sábado?" é pergunta
    if "?" in msg:
        return eh_sim_antes_de_pergunta(msg)
    return eh_confirmacao(normalizar_texto(msg))


def _tem_plano_em_foco(estado: dict[str, Any]) -> bool:
    return bool(
        _texto(estado.get("plano_em_negociacao"))
        and estado.get("plano_em_negociacao_id") is not None
    )


def resolver_intencao_plano_vendas(
    estado: dict[str, Any],
    resolucao: dict[str, Any],
    flags: dict[str, Any],
    *,
    aguardando: str,
) -> IntencaoPlano:
    """
    Resolve intenção na fase vendas com cobertura confirmada.
    Prioridade: contexto explícito > aguardando > mensagem literal.
    """
    from app.parser import (
        eh_pedido_lista_completa_planos,
        eh_pedido_plano_promocional,
        eh_pedido_planos_com_desconto,
        normalizar_texto,
    )

    msg = normalizar_texto(str(resolucao.get("mensagem") or ""))
    ctx = _texto(estado.get("contexto_plano"))
    conf =_eh_confirmacao(str(resolucao.get("mensagem") or ""), flags)
    neg = bool(flags.get("negacao"))
    plano_informado = bool((flags.get("plano") or {}).get("informado"))

    # Pedidos explícitos na mensagem (sempre vencem confirmação ambígua)
    if eh_pedido_lista_completa_planos(msg):
        return IntencaoPlano.LISTAR_TODOS
    if eh_pedido_planos_com_desconto(msg) or eh_pedido_plano_promocional(msg):
        return IntencaoPlano.LISTAR_DESCONTO
    if plano_informado and not conf:
        return IntencaoPlano.ESCOLHER_REFERENCIA
    if neg and aguardando == "confirmacao_plano" and not plano_informado:
        return IntencaoPlano.RECUSAR

    if not conf or neg:
        return IntencaoPlano.NENHUMA

    # --- Confirmação ("Sim", "Pode ser", etc.) ---

    if ctx == CTX_OFERTA_LISTA_DESCONTO:
        return IntencaoPlano.LISTAR_DESCONTO

    if ctx in {CTX_CONFIRMACAO_UNICO, CTX_APRESENTACAO_INICIAL}:
        if aguardando == "confirmacao_plano":
            return IntencaoPlano.CONFIRMAR

    if ctx == CTX_ESCOLHA_CATALOGO:
        if _tem_plano_em_foco(estado):
            return IntencaoPlano.CONFIRMAR
        return IntencaoPlano.PEDIR_ESCOLHA

    if ctx == CTX_ALTERNATIVAS and _tem_plano_em_foco(estado):
        return IntencaoPlano.CONFIRMAR

    # Legado: sem contexto_plano persistido ainda
    if aguardando == "confirmacao_plano":
        return IntencaoPlano.CONFIRMAR

    if aguardando in {"escolha_plano", "lista_planos"} and _tem_plano_em_foco(estado):
        return IntencaoPlano.CONFIRMAR

    return IntencaoPlano.NENHUMA
