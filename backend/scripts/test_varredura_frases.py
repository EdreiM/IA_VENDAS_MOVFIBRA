# -*- coding: utf-8 -*-
"""
Varredura — frases comuns do cliente em cada estado do funil.

Para cada estado (aguardando X) passa frases que NÃO são o dado pedido ("tá bom",
"pera aí", "não entendi", "tá caro"...), com o LLM classificando corretamente, e
confere duas regras:
  1. conversa nunca é gravada como nome, rua, cidade, e-mail etc.;
  2. frase neutra não avança o funil, não finaliza e não transfere.

Sem LLM e sem rede: todo HTTP é bloqueado (o .env local aponta para o n8n real).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx


def _bloquear(self, request, *args, **kwargs):
    raise httpx.ConnectError("rede bloqueada na varredura", request=request)


async def _bloquear_async(self, request, *args, **kwargs):
    raise httpx.ConnectError("rede bloqueada na varredura", request=request)


httpx.Client.send = _bloquear
httpx.AsyncClient.send = _bloquear_async

import logging

logging.disable(logging.CRITICAL)

import test_regressao_contexto as regressao

ORDEM = ["nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero"]
CAD = {
    "nome": "João Silva",
    "cpf": "12345678909",
    "email": "j@g.com",
    "telefone": "93991234567",
    "data_nascimento": "15/03/1990",
    "cep": "68020000",
    "rua": "Rua A",
    "numero": "10",
}
BASE = {"tem_cobertura": True, "cidade": "Santarém", "bairro": "Diamantino", "cumprimento_feito": True}
NEGOCIACAO = {"plano_em_negociacao": "MOV ESSENCIAL", "plano_em_negociacao_id": 7, "plano_apresentado_id": 7}
CONFIRMADO = {"plano_confirmado": "MOV ESSENCIAL", "plano_confirmado_id": 7}


def estados():
    yield "inicio", {"fase": "inicio"}
    yield "viabilidade/localizacao", {"fase": "viabilidade", "aguardando": "localizacao"}
    yield "vendas/confirmacao_plano", dict(BASE, **NEGOCIACAO, fase="vendas", aguardando="confirmacao_plano")
    yield "vendas/escolha_plano", dict(BASE, fase="vendas", aguardando="escolha_plano")
    for i, campo in enumerate(ORDEM):
        yield f"cadastro/{campo}", dict(
            BASE,
            **CONFIRMADO,
            fase="cadastro",
            aguardando=campo,
            documento_cpf_validado=(i > 1),
            **{c: CAD[c] for c in ORDEM[:i]},
        )
    completo = dict(BASE, **CONFIRMADO, **CAD, documento_cpf_validado=True)
    yield "cadastro/confirmacao_dados", dict(completo, fase="cadastro", aguardando="confirmacao_dados")
    yield "termos/aceite_termos", dict(
        completo, fase="termos", aguardando="aceite_termos", termos_enviados=True,
        ixc_cliente_id="1", id_contrato_ixc="2",
    )
    agenda = dict(
        completo, cadastro_completo=True, ixc_cliente_id="1",
        horarios_manha='["9h às 10h"]', horarios_tarde='["14h às 15h"]', data_agendamento="22/09/2026",
    )
    yield "agendamento/escolha_horario", dict(agenda, fase="agendamento", aguardando="escolha_horario")
    yield "agendamento/confirmacao_horario", dict(
        agenda, fase="agendamento", aguardando="confirmacao_horario", horario_escolhido="14h às 15h"
    )


# (mensagem, eventos que o LLM devolve, tipo)
FRASES = [
    ("ok", ["CONFIRMACAO"], "confirma"),
    ("tá bom", ["CONFIRMACAO"], "confirma"),
    ("beleza", ["CONFIRMACAO"], "confirma"),
    ("pode ser", ["CONFIRMACAO"], "confirma"),
    ("isso mesmo", ["CONFIRMACAO"], "confirma"),
    ("fechado", ["CONFIRMACAO"], "confirma"),
    ("não", ["NEGACAO"], "nega"),
    ("não entendi", ["OUTRO"], "neutra"),
    ("como assim?", ["PERGUNTA"], "neutra"),
    ("pera aí", ["CONVERSA_SOCIAL"], "neutra"),
    ("um momento", ["CONVERSA_SOCIAL"], "neutra"),
    ("kkkk", ["CONVERSA_SOCIAL"], "neutra"),
    ("obrigado", ["CONVERSA_SOCIAL"], "neutra"),
    ("vou ver aqui e te falo", ["CONVERSA_SOCIAL"], "neutra"),
    ("vou pensar", ["OUTRO"], "neutra"),
    ("tá caro", ["OUTRO"], "neutra"),
    ("tá errado", ["OUTRO"], "neutra"),
    ("depois eu vejo", ["OUTRO"], "neutra"),
    ("já mandei", ["OUTRO"], "neutra"),
    ("oi", ["SAUDACAO"], "neutra"),
    ("bom dia", ["SAUDACAO"], "neutra"),
    ("tem fidelidade?", ["PERGUNTA"], "neutra"),
    ("quanto custa a instalação?", ["PERGUNTA"], "neutra"),
    ("vocês são de onde?", ["PERGUNTA"], "neutra"),
    ("pode repetir?", ["PERGUNTA"], "neutra"),
    ("quero falar com atendente", ["PEDIU_HUMANO"], "humano"),
]

CAMPOS_DO_CLIENTE = ["nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero", "cidade", "bairro"]
ORDEM_FASES = ["inicio", "viabilidade", "vendas", "cadastro", "termos", "agendamento", "pos_venda", "finalizado"]


def varrer() -> tuple[int, list[str]]:
    violacoes: list[str] = []
    turnos = 0
    for nome_estado, estado0 in estados():
        for msg, eventos, tipo in FRASES:
            llm = {
                "eventos": eventos,
                "dados": {},
                "pergunta": msg if "PERGUNTA" in eventos else "",
                "confianca": 0.93,
            }
            estado, dec = regressao._turno(dict(estado0), msg, llm)
            turnos += 1
            onde = f"[{nome_estado}] {msg!r} → {dec.objetivo_resposta}"

            for campo in CAMPOS_DO_CLIENTE:
                antes, depois = estado0.get(campo), estado.get(campo)
                if depois not in (None, "") and depois != antes:
                    violacoes.append(f"{onde}: gravou {campo}={depois!r}")

            if tipo != "neutra":
                continue
            f0, f1 = str(estado0.get("fase")), str(dec.fase)
            if f1 == "finalizado":
                violacoes.append(f"{onde}: finalizou o atendimento")
            elif f1 == "transferido":
                violacoes.append(f"{onde}: transferiu para humano")
            elif (
                f0 in ORDEM_FASES
                and f1 in ORDEM_FASES
                and ORDEM_FASES.index(f1) > ORDEM_FASES.index(f0)
                and not (f0 == "inicio" and f1 == "viabilidade")
            ):
                violacoes.append(f"{onde}: avançou {f0} → {f1}")
    return turnos, violacoes


def main() -> None:
    turnos, violacoes = varrer()
    for v in violacoes:
        print(f"  FALHOU {v}")
    if violacoes:
        print(f"\n❌ {len(violacoes)} violação(ões) em {turnos} turnos")
        sys.exit(1)
    print(f"  OK {turnos} turnos sem dado inventado nem avanço indevido")
    print("\n✅ Varredura de frases OK")


if __name__ == "__main__":
    main()
