"""Consultor de planos — qual plano indicar para este cliente, e por quê.

A máquina de estados apresenta o plano em destaque e as listas. O que faltava era o
que uma vendedora faz: ouvir o que o cliente contou ("somos 8 em casa", "queria com
Disney", "só preciso de internet", "esse não, tem outro?") e indicar o plano certo,
ligando a indicação ao que ele disse — ou perguntar o que falta para indicar.

O modelo escolhe entre os planos do catálogo do painel e escreve a abertura. O código
confere: o plano precisa existir no catálogo, e a abertura só pode citar valor,
percentual ou quantidade que esteja nos fatos (app/verificacao.py). A ficha do plano
(preço, benefícios) continua saindo do cadastro do painel, sem passar pelo modelo.
Nada é oferecido além do que está no catálogo.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM = """Você é a consultora de planos da MOV FIBRA no WhatsApp.

Sua tarefa: indicar UM plano do catálogo para este cliente, com base no que ele contou, e escrever a frase de abertura da mensagem.

Regras:
- Só existem os planos do CATÁLOGO. Não ofereça desconto, brinde, condição ou plano que não esteja lá.
- Dimensione pelo que o catálogo e a base de conhecimento dizem (por exemplo, quantos dispositivos cada plano comporta): indique o menor plano que comporta o que o cliente disse. Não empurre um plano maior sem motivo.
- Se o cliente pediu um benefício (streaming, chip de celular, repetidor Mesh, jogos), indique um plano que tenha esse benefício.
- Se pediu o mais em conta, indique o de menor valor que ainda atende ao que ele disse precisar.
- Se o plano que já está em conversa atende, mantenha-o.
- Se ainda não dá para indicar (o cliente só disse que quer outro, sem dizer o que procura), devolva plano "" e, na abertura, pergunte o que falta — em geral, quantos aparelhos usam a internet e se ele procura algum benefício.

A abertura:
- 1 ou 2 frases, como uma vendedora de verdade no WhatsApp: natural, direta, em primeira pessoa.
- Ligue a indicação ao que o cliente disse ("como são 8 aparelhos aí...").
- Cite só fatos do catálogo. Não repita a lista de benefícios nem o preço cheio: a ficha do plano é enviada logo depois da sua frase.
- Sem pressão e sem urgência inventada.

Responda SOMENTE com JSON: {"plano": "<nome exato do catálogo ou vazio>", "abertura": "<texto>"}"""


def _fmt(valor: Any) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""


def catalogo_em_texto(planos: list[dict[str, Any]]) -> str:
    """Os planos do painel como fatos para o modelo (e para a conferência da abertura)."""
    linhas: list[str] = []
    for p in planos:
        nome = str(p.get("nome") or "").strip()
        if not nome:
            continue
        partes = [f"{nome} — {_fmt(p.get('valor'))}/mês"]
        if p.get("valor_pontualidade"):
            partes.append(f"pagando até o vencimento: {_fmt(p.get('valor_pontualidade'))}")
        if p.get("dispositivos_max"):
            partes.append(f"até {int(p['dispositivos_max'])} dispositivos")
        beneficios = str(p.get("beneficios") or "").strip() or str(p.get("descricao") or "").strip()
        # O painel guarda um benefício por linha: no prompt vira uma lista em linha só
        beneficios = "; ".join(ln.strip() for ln in beneficios.splitlines() if ln.strip())
        if beneficios:
            partes.append(f"inclui: {beneficios[:420]}")
        tags = [str(t) for t in (p.get("tags") or []) if t]
        if tags:
            partes.append(f"perfil: {', '.join(tags)}")
        linhas.append("- " + " | ".join(partes))
    return "\n".join(linhas)


def _schema(nomes: list[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "recomendacao",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["plano", "abertura"],
                "properties": {
                    "plano": {"type": "string", "enum": ["", *nomes]},
                    "abertura": {"type": "string"},
                },
            },
        },
    }


def recomendar(
    estado: dict[str, Any],
    mensagem: str,
    planos: list[dict[str, Any]],
    *,
    historico: list[dict[str, str]] | None = None,
    base: str = "",
) -> dict[str, Any] | None:
    """{"plano": dict | None, "abertura": str} — ou None quando o modelo não respondeu algo utilizável.

    `plano` None com abertura preenchida = a Eva precisa perguntar antes de indicar.
    """
    from app.llm import chat
    from app.verificacao import afirmacoes_sem_base

    nomes = [str(p.get("nome") or "").strip() for p in planos if str(p.get("nome") or "").strip()]
    if not nomes:
        return None
    atual = str(estado.get("plano_em_negociacao") or estado.get("plano_apresentado") or "").strip()
    catalogo = catalogo_em_texto(planos)
    notas = "\n".join(
        f"- {ln.strip()}" for ln in str(estado.get("notas_conversa") or "").split("\n") if ln.strip()
    )
    hist = ""
    for h in (historico or [])[-8:]:
        quem = "Cliente" if h.get("remetente") == "cliente" else "Eva"
        hist += f"{quem}: {str(h.get('mensagem') or '')[:600]}\n"

    user = f"""CATÁLOGO (os únicos planos que existem):
{catalogo}

PLANO JÁ EM CONVERSA: {atual or '(nenhum ainda)'}

O QUE O CLIENTE JÁ CONTOU:
{notas or '(nada anotado)'}

BASE DE CONHECIMENTO DA EMPRESA:
{base or '(nenhum trecho)'}

CONVERSA ATÉ AQUI:
{hist or '(sem histórico)'}

MENSAGEM DO CLIENTE AGORA: {mensagem or '(sem texto)'}
"""
    try:
        from app import custos

        custos.marcar("consultor")
        bruto = chat(SYSTEM, user, temperature=0.3, response_format=_schema(nomes))
        data = json.loads(bruto)
    except Exception:  # noqa: BLE001 — sem modelo, quem chamou segue o fluxo de sempre
        logger.warning("Consultor de planos indisponível", exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    nome = str(data.get("plano") or "").strip()
    abertura = " ".join(str(data.get("abertura") or "").split())[:420]
    plano = next((p for p in planos if str(p.get("nome") or "").strip().casefold() == nome.casefold()), None)
    if nome and plano is None:
        return None  # indicou plano que não existe
    # A abertura só pode citar número que esteja no catálogo, na base ou no que o cliente disse
    fatos = f"{catalogo}\n{base}\n{notas}\n{hist}\n{mensagem}"
    if abertura and afirmacoes_sem_base(abertura, fatos):
        abertura = ""
    if plano is None and not abertura:
        return None
    return {"plano": plano, "abertura": abertura}
