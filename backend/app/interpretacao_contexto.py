"""Reconcilia interpretação do LLM com o contexto real da conversa."""

from __future__ import annotations

import re
from typing import Any

from app.models import DadosExtraidos, Evento


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def referencia_parece_pergunta_nao_plano(referencia: str, msg_bruto: str = "") -> bool:
    """
    Texto anotado em dados.plano que não é nome/referência de plano.
    Perguntas legítimas sobre plano (preço, detalhe, catálogo) retornam False.
    """
    from app.parser import (
        INTENCAO_PLANO_KEYWORDS,
        eh_mensagem_sobre_planos,
        eh_pedido_lista_completa_planos,
        eh_pedido_plano_promocional,
        eh_pergunta_cancelamento,
        eh_pergunta_informativa_sobre_plano,
        eh_pergunta_instalacao,
        eh_pergunta_mudanca_endereco,
        extrair_referencia_plano_na_mensagem,
        normalizar_texto,
        tem_duvida_informativa,
    )
    from app.plans import normalizar_referencia_plano
    from app.pos_venda_mensagens import eh_pedido_encerrar
    from app.validation import nome_parece_frase_invalida, rua_parece_frase_invalida

    bruto = _texto(msg_bruto or referencia)
    ref = _texto(referencia)
    check = bruto or ref
    if not check:
        return False

    t = normalizar_texto(check)

    if eh_pergunta_instalacao(t, check):
        return True
    if eh_pergunta_cancelamento(t, check):
        return True
    if eh_pergunta_mudanca_endereco(check):
        return True
    if eh_pedido_encerrar(check):
        return True

    ref_norm = normalizar_referencia_plano(ref)
    ref_intencao = bool(ref_norm) and ref_norm.casefold() != ref.casefold()

    if (
        eh_mensagem_sobre_planos(t, check)
        or any(k in t for k in INTENCAO_PLANO_KEYWORDS)
        or extrair_referencia_plano_na_mensagem(t, check)
        or ref_intencao
        or eh_pedido_lista_completa_planos(check)
        or eh_pedido_plano_promocional(check)
        or eh_pergunta_informativa_sobre_plano(t, check)
    ):
        return False

    if "?" in check or tem_duvida_informativa(t, check):
        if len(t.split()) >= 3:
            return True

    if ref and nome_parece_frase_invalida(ref, bruto):
        return True
    if ref and rua_parece_frase_invalida(ref):
        return True

    if len(t.split()) >= 5 and not re.search(
        r"\b(mov|combo|plano|infinity|essencial|flex|super|up\+|one\+)\b", t
    ):
        return True
    return False


def referencia_parece_plano(referencia: str, msg_bruto: str = "") -> bool:
    """Há sinal claro de intenção de plano — não só evento do LLM."""
    ref = _texto(referencia)
    bruto = _texto(msg_bruto or referencia)
    if not ref and not bruto:
        return False
    if referencia_parece_pergunta_nao_plano(ref or bruto, bruto):
        return False

    from app.parser import (
        INTENCAO_PLANO_KEYWORDS,
        eh_mensagem_sobre_planos,
        extrair_referencia_plano_na_mensagem,
        normalizar_texto,
    )
    from app.plans import normalizar_referencia_plano

    t = normalizar_texto(bruto or ref)
    if extrair_referencia_plano_na_mensagem(t, bruto):
        return True
    if normalizar_referencia_plano(ref):
        return True
    if eh_mensagem_sobre_planos(t, bruto):
        return True
    if any(k in t for k in INTENCAO_PLANO_KEYWORDS):
        return True
    # Nome curto de plano: "mov up", "super+"
    if len(t.split()) <= 4 and re.search(
        r"\b(mov|combo|infinity|essencial|flex|super|up\+?|one\+?)\b", t
    ):
        return True
    return False


def classificar_pergunta_informativa(
    msg: str,
    msg_bruto: str = "",
    *,
    topico: str | None = None,
) -> str | None:
    """
    Retorna tópico da pergunta informativa ou None.
    instalacao | cancelamento | mudanca_endereco | beneficio | generica
    """
    from app.parser import (
        eh_pergunta_cancelamento,
        eh_pergunta_instalacao,
        eh_pergunta_mudanca_endereco,
        normalizar_texto,
        tem_duvida_informativa,
    )
    from app.state_machine import _detectar_beneficio_pergunta

    bruto = _texto(msg_bruto or msg)
    t = normalizar_texto(msg or bruto)
    top = _texto(topico).casefold()

    if top == "instalacao" or eh_pergunta_instalacao(t, bruto, topico=top):
        return "instalacao"
    if top == "cancelamento" or eh_pergunta_cancelamento(t, bruto, topico=top):
        return "cancelamento"
    if top == "mudanca_endereco" or eh_pergunta_mudanca_endereco(bruto):
        return "mudanca_endereco"
    if top == "beneficio_plano" or _detectar_beneficio_pergunta(t):
        return "beneficio"
    if tem_duvida_informativa(t, bruto) or "?" in bruto:
        return "generica"
    return None


def sanitizar_plano_informado_llm(
    *,
    dados: DadosExtraidos,
    eventos: list[str],
    pergunta: str,
    msg: str,
    msg_bruto: str,
    intencao_nao_dado: bool,
    tem_duvida: bool,
) -> str:
    """
    PLANO_INFORMADO / PEDIU_TROCAR_PLANO só permanecem se a mensagem
    realmente cita ou pede um plano — senão vira PERGUNTA.
    """
    from app.parser import extrair_parte_pergunta

    if Evento.PLANO_INFORMADO.value not in eventos and Evento.PEDIU_TROCAR_PLANO.value not in eventos:
        return pergunta

    ref = _texto(dados.plano) or _texto(msg_bruto)
    if referencia_parece_plano(ref, msg_bruto):
        return pergunta

    eventos[:] = [
        e
        for e in eventos
        if e
        not in {
            Evento.PLANO_INFORMADO.value,
            Evento.PEDIU_TROCAR_PLANO.value,
            Evento.CONFIRMACAO.value,
        }
    ]
    dados.plano = ""
    if intencao_nao_dado or tem_duvida or "?" in _texto(msg_bruto):
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        if not pergunta:
            pergunta = extrair_parte_pergunta(msg_bruto, msg) or _texto(msg_bruto)
    return pergunta


def deve_resolver_referencia_plano(
    estado: dict[str, Any],
    resolucao: dict[str, Any],
    referencia: str,
) -> bool:
    """Última barreira antes de RESOLVER_PLANO — evita buscar plano em frases."""
    from app.parser import (
        INTENCAO_PLANO_KEYWORDS,
        PERGUNTAS_PRECO,
        eh_pergunta_detalhe_plano,
        eh_pergunta_plano_por_preco,
        eh_pergunta_preco_plano_nomeado,
        normalizar_texto,
    )

    ref = _texto(referencia)
    msg_bruta = _texto(
        resolucao.get("mensagem") or resolucao.get("pergunta_original") or ref
    )
    if not ref:
        return False
    if referencia_parece_pergunta_nao_plano(ref, msg_bruta):
        return False

    t_msg = normalizar_texto(msg_bruta)
    tem_intencao_troca = any(k in t_msg for k in INTENCAO_PLANO_KEYWORDS)
    if (
        any(p in t_msg for p in PERGUNTAS_PRECO)
        or eh_pergunta_preco_plano_nomeado(t_msg, msg_bruta)
        or eh_pergunta_plano_por_preco(t_msg, msg_bruta)
        or (
            eh_pergunta_detalhe_plano(t_msg, msg_bruta)
            and not tem_intencao_troca
        )
    ):
        return False

    if not referencia_parece_plano(ref, msg_bruta):
        return False

    from app.plans import resolver_plano
    from app.plans_catalog import listar_planos

    plano_atual_id = None
    for chave in ("plano_em_negociacao_id", "plano_apresentado_id", "plano_confirmado_id"):
        try:
            if estado.get(chave) is not None:
                plano_atual_id = int(estado[chave])
                break
        except (TypeError, ValueError):
            continue

    resolvido = resolver_plano(ref, listar_planos(estado), plano_atual_id=plano_atual_id)
    return resolvido.get("evento") in {"PLANO_RESOLVIDO", "PLANO_AMBIGUO"}
