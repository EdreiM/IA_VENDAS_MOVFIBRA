"""Consulta RAG externa — objeções, FAQ, benefícios (sem redeploy do backend)."""

from __future__ import annotations

import logging
from typing import Any

from app.integrations.rag_webhook import consultar_rag_webhook

logger = logging.getLogger(__name__)

# Mock local — só para testes sem n8n
MOCK_RAG: dict[str, str] = {
    "fidelidade": (
        "Os planos MOV FIBRA têm fidelidade de 12 meses. "
        "Em caso de cancelamento antes desse prazo, pode haver multa proporcional ao tempo restante."
    ),
    "cancelamento": (
        "O cancelamento encerra o serviço. É necessário devolver os equipamentos. "
        "Se estiver no período de fidelidade (12 meses), há multa proporcional conforme o contrato. "
        "O valor exato da multa depende dos meses restantes — a equipe confirma no contrato."
    ),
    "multa": (
        "A multa de fidelidade é proporcional ao tempo que falta para completar 12 meses. "
        "Não é o valor cheio do plano; a equipe calcula com base no contrato."
    ),
    "taxa": (
        "Sobre taxas: a mensalidade do plano é o valor mensal informado. "
        "No cancelamento antecipado pode haver multa proporcional de fidelidade, "
        "e é preciso devolver roteador/equipamentos."
    ),
    "roteador": (
        "Os planos MOV FIBRA incluem roteador Wi-Fi em comodato (equipamento da MOV TELECOM). "
        "O roteador deve ser devolvido em caso de cancelamento. "
        "O plano MOV ESSENCIAL inclui 1 roteador. Planos com Mesh/repetidor oferecem um segundo ponto de acesso."
    ),
    "comodato": (
        "O roteador é fornecido em comodato pela MOV TELECOM — o equipamento é da operadora "
        "e deve ser devolvido se o cliente cancelar o serviço."
    ),
    "mudanca": (
        "Após contratar, é possível solicitar mudança de endereço (transferência de ponto). "
        "A equipe verifica cobertura no novo endereço, agenda a visita técnica se necessário "
        "e pode haver taxa de mudança conforme contrato. Entre em contato com a central para agendar."
    ),
    "endereco": (
        "Para mudança de endereço após a contratação: solicite pela central/atendimento, "
        "informe o novo endereço completo, aguarde verificação de cobertura e agendamento da instalação no novo ponto."
    ),
    "instalacao": (
        "A instalação é gratuita (visita do técnico e configuração inclusas no plano). "
        "Após o cadastro o cliente escolhe horário na agenda — não confirme visita para o mesmo dia "
        "sem consultar a agenda. Não invente taxa de instalação nem fidelidade nesta resposta."
    ),
    "agendamento": (
        "O agendamento é feito após o cadastro. O cliente escolhe um horário disponível "
        "e confirma. Não prometa visita para hoje sem horário na agenda. "
        "Se precisar remarcar, entre em contato com a central."
    ),
    "mesh": "A rede Mesh amplia a cobertura Wi-Fi em casa com pontos extras (repetidor).",
}


def _norm(s: str) -> str:
    t = (s or "").casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    return t


def _consultar_mock(pergunta: str, mensagem: str) -> dict[str, Any]:
    texto = _norm(f"{pergunta} {mensagem}")
    for chave, resposta in MOCK_RAG.items():
        if chave in texto:
            return {
                "encontrado": True,
                "resposta": resposta,
                "chunks": [{"titulo": chave, "conteudo": resposta}],
                "confianca": 0.9,
                "fontes": [f"mock:{chave}"],
                "provider": "mock",
            }
    return {
        "encontrado": False,
        "resposta": "",
        "chunks": [],
        "motivo": "Nenhum trecho mock encontrado",
        "provider": "mock",
    }


def consultar_rag(
    *,
    pergunta: str,
    mensagem: str = "",
    estado: dict[str, Any] | None = None,
    plano: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Entrada: pergunta isolada + mensagem original + contexto do atendimento.
    Saída: encontrado, resposta (opcional), chunks (contexto para o LLM).
    """
    from app import ia_config

    unidade_id = None
    if estado and estado.get("unidade_id") is not None:
        try:
            unidade_id = int(estado["unidade_id"])
        except (TypeError, ValueError):
            unidade_id = None

    provider = ia_config.resolver_rag_provider(unidade_id=unidade_id)
    if provider in {"", "none", "off"}:
        return {"encontrado": False, "motivo": "RAG desligada no painel", "provider": "none"}

    query = (pergunta or mensagem or "").strip()
    if not query:
        return {"encontrado": False, "motivo": "Pergunta vazia", "provider": provider}

    from app.webhook_payload import snapshot_cliente

    st = estado or {}
    ctx = snapshot_cliente(st, incluir_historico=False)
    if unidade_id is not None:
        ctx["unidade_id"] = unidade_id
    if plano:
        ctx["plano"] = {
            "nome": plano.get("nome") or "",
            "valor": plano.get("valor"),
            "beneficios": plano.get("beneficios") or plano.get("descricao") or "",
        }

    if provider == "mock":
        return _consultar_mock(query, mensagem)

    if provider == "webhook":
        return consultar_rag_webhook(pergunta=query, mensagem=mensagem, contexto=ctx)

    logger.warning("RAG provider desconhecido: %s", provider)
    return {"encontrado": False, "motivo": f"Provider inválido: {provider}", "provider": provider}


def formatar_contexto_rag(rag: dict[str, Any]) -> str:
    """Texto para injetar no prompt da Eva."""
    if not rag or not rag.get("encontrado"):
        return ""

    partes: list[str] = []
    if rag.get("resposta"):
        partes.append(f"Resposta sugerida: {rag['resposta']}")

    for chunk in rag.get("chunks") or []:
        titulo = chunk.get("titulo") or "FAQ"
        conteudo = chunk.get("conteudo") or ""
        if conteudo:
            partes.append(f"[{titulo}] {conteudo}")

    fontes = rag.get("fontes") or []
    if fontes:
        partes.append(f"Fontes: {', '.join(str(f) for f in fontes)}")

    return "\n".join(partes).strip()
