"""Contexto de conversa — follow-ups ('quanto paga?', 'pra cancelar') herdam o tópico."""

from __future__ import annotations

import re
from typing import Any


def _norm(texto: str) -> str:
    t = (texto or "").casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    t = re.sub(r"[!?.,;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# tópico → palavras que abrem o assunto
TOPICOS: list[tuple[str, tuple[str, ...]]] = [
    (
        "cancelamento",
        (
            "cancelar",
            "cancelamento",
            "desistir",
            "rescindir",
            "multa",
            "fidelidade",
            "taxa de cancelamento",
            "devolver equipamento",
        ),
    ),
    (
        "preco_plano",
        (
            "quanto custa o plano",
            "valor do plano",
            "mensalidade",
            "preco do plano",
            "quanto fica o plano",
        ),
    ),
    (
        "beneficio_plano",
        (
            "disney",
            "mesh",
            "roteador",
            "roteadores",
            "repetidor",
            "beneficio",
            "o que tem no plano",
            "o que inclui",
            "tem mais o que",
            "inclui",
            "direito a",
            "tenho direito",
            "comodato",
        ),
    ),
    (
        "mudanca_endereco",
        (
            "mudar de endereco",
            "mudanca de endereco",
            "trocar de endereco",
            "outro endereco",
            "novo endereco",
            "mudar endereco",
            "transferir endereco",
            "levar a internet",
        ),
    ),
    (
        "instalacao",
        (
            "instalacao",
            "instalar",
            "agendar",
            "agendamento",
            "horario",
            "tecnico",
            "visita",
            "vir instalar",
            "quando vem",
            "quando instala",
        ),
    ),
]

# follow-ups curtos que sozinhos não dizem o assunto
FOLLOWUPS = {
    "quanto que paga",
    "quanto paga",
    "quanto e",
    "quanto custa",
    "quanto fica",
    "e a taxa",
    "tem taxa",
    "a taxa",
    "e quanto",
    "e a multa",
    "qual a multa",
    "pra cancelar",
    "para cancelar",
    "e se cancelar",
    "e cancelar",
    "e depois",
    "e ai",
    "como assim",
    "explica melhor",
    "me explica",
    "isso",
    "e esse",
    "e esse plano",
    "nele",
    "nesse",
    "nesse plano",
    "tem isso",
    "inclui isso",
    "hoje",
    "hj",
    "mas hoje",
    "e hoje",
    "pra hoje",
    "ainda hoje",
    "hoje mesmo",
    "amanha",
    "e amanha",
    "pra amanha",
    "opcoes de que",
    "opções de que",
    "de que",
}


def detectar_topico(texto: str) -> str | None:
    t = _norm(texto)
    if not t:
        return None
    for topico, chaves in TOPICOS:
        if any(c in t for c in chaves):
            return topico
    return None


def eh_followup_curto(texto: str) -> bool:
    t = _norm(texto)
    if not t:
        return False
    t = re.sub(r"^(?:mas|e|ai|ah|entao|ok|blz)\s+", "", t).strip()
    if t in FOLLOWUPS:
        return True
    if t in {"hoje", "hj", "amanha", "hoje mesmo", "ainda hoje", "pra hoje"}:
        return True
    if len(t.split()) <= 6 and any(
        t == p or t.startswith(p + " ") or t.startswith(p)
        for p in (
            "quanto",
            "e a",
            "e o",
            "pra ",
            "para ",
            "tem taxa",
            "a multa",
            "a taxa",
        )
    ):
        return True
    return False


def topico_do_historico(historico: list[dict[str, str]] | None, limite: int = 6) -> str | None:
    if not historico:
        return None
    # do mais recente ao mais antigo
    for h in reversed(historico[-limite:]):
        top = detectar_topico(str(h.get("mensagem") or ""))
        if top:
            return top
    return None


def enriquecer_pergunta(
    mensagem: str,
    *,
    pergunta: str = "",
    ultimo_topico: str | None = None,
    historico: list[dict[str, str]] | None = None,
    plano_nome: str = "",
) -> dict[str, Any]:
    """
    Devolve pergunta enriquecida + tópico efetivo para RAG/LLM.
    Ex.: 'quanto que paga?' + topico cancelamento → pergunta sobre multa.
    """
    bruto = (pergunta or mensagem or "").strip()
    try:
        from app.parser import eh_mensagem_correcao_cadastro

        if eh_mensagem_correcao_cadastro(bruto, bruto):
            return {
                "pergunta": bruto,
                "topico": None,
                "mensagem_original": bruto,
                "era_followup": False,
            }
    except Exception:
        pass
    topico = detectar_topico(bruto) or ultimo_topico or topico_do_historico(historico)

    pergunta_final = bruto
    if eh_followup_curto(bruto) and topico:
        if topico == "cancelamento":
            if any(x in _norm(bruto) for x in ("opcoes de que", "opções de que", "de que")):
                pergunta_final = (
                    "O que acontece se eu cancelar o plano antes do fim da fidelidade de 12 meses? "
                    "Há multa proporcional e devolução de equipamentos?"
                )
            elif any(x in _norm(bruto) for x in ("quanto", "paga", "custa", "taxa", "multa", "valor")):
                pergunta_final = (
                    "Qual a multa ou taxa de cancelamento do plano "
                    f"{plano_nome or 'contratado'} antes do fim da fidelidade? "
                    "Como funciona o cancelamento?"
                )
            else:
                pergunta_final = (
                    f"Como funciona o cancelamento do plano {plano_nome or 'MOV FIBRA'}? "
                    "Há multa de fidelidade e precisa devolver equipamentos?"
                )
        elif topico == "beneficio_plano":
            pergunta_final = (
                f"Quais benefícios, roteadores e inclusos tem o plano {plano_nome or 'em negociação'}? "
                f"Detalhe sobre: {bruto}"
            )
        elif topico == "preco_plano":
            pergunta_final = f"Qual o valor mensal do plano {plano_nome or 'em negociação'}?"
        elif topico == "instalacao":
            if any(x in _norm(bruto) for x in ("hoje", "hj", "amanha", "agora", "ja")):
                pergunta_final = (
                    "Consigo instalação ainda hoje ou amanhã? "
                    "Como funciona o agendamento da visita do técnico na MOV FIBRA?"
                )
            else:
                pergunta_final = f"Sobre instalação/agendamento: {bruto}"
        elif topico == "mudanca_endereco":
            pergunta_final = (
                "Como funciona a mudança de endereço após contratar a internet MOV FIBRA? "
                "É possível transferir o serviço para outro endereço? Quais são os passos e custos?"
            )

    return {
        "pergunta": pergunta_final,
        "topico": topico,
        "mensagem_original": bruto,
        "era_followup": eh_followup_curto(bruto) and bool(topico),
    }


def rotulo_topico(topico: str | None) -> str:
    return {
        "cancelamento": "cancelamento / multa / fidelidade",
        "preco_plano": "preço / mensalidade do plano",
        "beneficio_plano": "benefícios / equipamentos do plano",
        "instalacao": "instalação / agendamento",
        "mudanca_endereco": "mudança de endereço pós-contratação",
    }.get(topico or "", topico or "(nenhum)")
