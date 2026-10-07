"""Fatos confirmados que a Eva pode usar ao responder dúvidas.

A resposta é escrita pelo LLM a cada pergunta (ver `response._resposta_inteligente`),
mas só com o que está aqui, na base de conhecimento (RAG) e nos dados do plano.
Para mudar o que a Eva afirma sobre um assunto, edite o texto deste arquivo.
"""

from __future__ import annotations

FATOS_POR_TOPICO: dict[str, str] = {
    "cancelamento": (
        "- O plano tem fidelidade de 12 meses.\n"
        "- Cancelando antes do fim da fidelidade, pode haver multa proporcional ao tempo que "
        "ainda faltava; não é o valor cheio do plano.\n"
        "- O valor exato da multa consta no contrato. A Eva não calcula esse valor no chat; "
        "a equipe detalha no contrato ou quando o cliente solicitar.\n"
        "- No cancelamento é preciso devolver os equipamentos (roteador/repetidor) em bom estado."
    ),
    "instalacao": (
        "- A instalação é gratuita: a visita do técnico e a configuração já estão inclusas "
        "no plano, sem taxa extra.\n"
        "- A visita do técnico é agendada depois do cadastro: o cliente escolhe um horário "
        "disponível na agenda da região.\n"
        "- Não dá para confirmar instalação para hoje ou para uma data específica antes do "
        "agendamento; a disponibilidade só aparece na hora de agendar."
    ),
}


def fatos_do_topico(topico: str | None) -> str:
    return FATOS_POR_TOPICO.get(str(topico or "").strip(), "")
