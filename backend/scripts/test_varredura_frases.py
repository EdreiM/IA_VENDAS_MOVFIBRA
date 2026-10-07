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
from app import pipeline

# A consulta de CPF no IXC é rede (bloqueada acima): simula "CPF novo, pode cadastrar"
pipeline.validar_cpf = lambda **k: {
    "ja_cadastrado": False,
    "erro": False,
    "motivo": "CPF novo",
    "cpf_formatado": k.get("cpf_cnpj"),
    "cpf_numeros": "".join(ch for ch in str(k.get("cpf_cnpj") or "") if ch.isdigit()),
}

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


ROTULO_NO_TEXTO = {
    "nome": "nome",
    "cpf": "cpf",
    "email": "e-mail",
    "telefone": "telefone",
    "data_nascimento": "data de nascimento",
    "cep": "cep",
    "rua": "rua",
    "numero": "número",
}


def _texto_da_eva(dec, estado: dict, msg: str) -> str:
    from app import response

    response.chat = lambda *a, **k: ""  # respostas de cadastro são por template
    return response.gerar_resposta(dec, estado, historico=[], mensagem_cliente=msg)


def conversa_cadastro(cpf_inicial: dict) -> list[str]:
    """Nome → e-mail → celular. A Eva deve pedir o campo que o estado aguarda e
    nunca gravar o celular (11 dígitos) por cima do CPF."""
    violacoes: list[str] = []
    estado = dict(BASE, **CONFIRMADO, fase="cadastro", aguardando="nome", **cpf_inicial)
    cpf_antes = estado.get("cpf")
    passos = [
        ("Edrei Tester", {"nome": "Edrei Tester"}),
        ("edreitester@gmail.com", {"email": "edreitester@gmail.com"}),
        ("93992219098", {"telefone": "93992219098"}),
    ]
    for msg, dados in passos:
        llm = {"eventos": ["DADO_INFORMADO"], "dados": dados, "confianca": 0.95}
        estado, dec = regressao._turno(estado, msg, llm)
        texto = _texto_da_eva(dec, estado, msg).casefold()
        rotulo = ROTULO_NO_TEXTO.get(str(dec.aguardando))
        if rotulo and rotulo not in texto:
            violacoes.append(
                f"[{cpf_inicial or 'sem cpf'}] {msg!r}: estado aguarda {dec.aguardando}, "
                f"mas a Eva disse {texto[:90]!r}"
            )
    if estado.get("cpf") != cpf_antes:
        violacoes.append(f"[{cpf_inicial or 'sem cpf'}] CPF virou {estado.get('cpf')!r} (era {cpf_antes!r})")
    if estado.get("telefone") != "93992219098":
        violacoes.append(f"[{cpf_inicial or 'sem cpf'}] telefone não foi gravado: {estado.get('telefone')!r}")
    return violacoes


VALORES = {
    "nome": ("Edrei Tester Maciel", "Edrei Tester Maciel"),
    "cpf": ("604.210.790-96", "60421079096"),
    "email": ("edreitester@gmail.com", "edreitester@gmail.com"),
    "telefone": ("93 99221-9098", "93992219098"),
    "data_nascimento": ("15/03/1990", "15/03/1990"),
    "cep": ("68020-000", "68020000"),
    "rua": ("Rua das Flores", "Rua das Flores"),
    "numero": ("123", "123"),
}
DUVIDAS = [
    "Mas tem multa de cancelamento?",
    "Mas quanto tempo demora a instalação?",
    "E se eu mudar de endereço depois?",
    "Vocês atendem aos sábados?",
]


def dado_com_duvida() -> tuple[int, list[str]]:
    """O cliente manda o dado pedido e, na mesma mensagem, uma dúvida.

    O dado tem que ser gravado e a Eva não pode pedir o mesmo campo de novo.
    """
    violacoes: list[str] = []
    turnos = 0
    for i, campo in enumerate(ORDEM):
        texto_valor, salvo_esperado = VALORES[campo]
        for duvida in DUVIDAS:
            for separador in ("\n", ", "):
                estado0 = dict(
                    BASE,
                    **CONFIRMADO,
                    fase="cadastro",
                    aguardando=campo,
                    documento_cpf_validado=(i > 1),
                    **{c: CAD[c] for c in ORDEM[:i]},
                )
                msg = f"{texto_valor}{separador}{duvida}"
                llm = {
                    "eventos": ["DADO_INFORMADO", "PERGUNTA"],
                    "dados": {campo: texto_valor},
                    "pergunta": duvida,
                    "confianca": 0.93,
                }
                estado, dec = regressao._turno(dict(estado0), msg, llm)
                turnos += 1
                onde = f"[cadastro/{campo}] {msg!r} → {dec.objetivo_resposta}"
                obtido = str(estado.get(campo) or "")
                if campo in {"cpf", "telefone", "cep"}:
                    obtido = "".join(ch for ch in obtido if ch.isdigit())
                if salvo_esperado.casefold() not in obtido.casefold():
                    violacoes.append(f"{onde}: não gravou {campo} (ficou {estado.get(campo)!r})")
                elif dec.aguardando == campo:
                    violacoes.append(f"{onde}: gravou {campo} mas pediu {campo} de novo")
                if dec.fase != "cadastro":
                    violacoes.append(f"{onde}: saiu do cadastro para {dec.fase}")
    return turnos, violacoes


def conversa_real_7_outubro() -> list[str]:
    """Trechos de um atendimento real em que a interpretação do LLM estava certa
    e o parser apagou o valor (cidade, plano e data de nascimento)."""
    v: list[str] = []

    # "Quero ver os planos / Aqui em santarém" → a cidade tem que ficar guardada
    est, _ = regressao._turno(
        {"fase": "viabilidade", "aguardando": "localizacao", "cumprimento_feito": True},
        "Quero ver os planos ai\nAqui em santarém",
        {"eventos": ["PEDIDO_CONTRATACAO", "LOCALIZACAO_INFORMADA"], "dados": {"cidade": "Santarém"}, "confianca": 0.95},
    )
    if str(est.get("cidade") or "").casefold() != "santarém":
        v.append(f"cidade não foi guardada junto com o pedido de planos: {est.get('cidade')!r}")

    # "Pode ser o infinity" com o SUPER+ em negociação → não pode fechar o SUPER+
    base_plano = dict(
        BASE, fase="vendas", aguardando="confirmacao_plano",
        plano_em_negociacao="MOV SUPER+", plano_em_negociacao_id=2, plano_apresentado_id=2,
    )
    for llm in (
        {"eventos": ["PLANO_INFORMADO"], "dados": {"plano": "infinity"}},
        {"eventos": ["CONFIRMACAO"], "dados": {}},
    ):
        est, dec = regressao._turno(dict(base_plano), "Pode ser o infinity", {**llm, "confianca": 0.9})
        if est.get("plano_confirmado"):
            v.append(f"'Pode ser o infinity' confirmou {est.get('plano_confirmado')!r} (llm={llm['eventos']})")
        if "INFINITY" not in str(est.get("plano_em_negociacao") or "").upper():
            v.append(f"'Pode ser o infinity' deixou em negociação {est.get('plano_em_negociacao')!r}")

    # "16 de agosto de 2000 / 68020000" → data por extenso e CEP na mesma mensagem
    for valor_llm in ("16/08/2000", "16 de agosto de 2000"):
        est, dec = regressao._turno(
            dict(
                BASE, **CONFIRMADO, fase="cadastro", aguardando="data_nascimento",
                documento_cpf_validado=True, **{c: CAD[c] for c in ORDEM[:4]},
            ),
            "16 de agosto de 2000\n68020000",
            {"eventos": ["DADO_INFORMADO"], "dados": {"data_nascimento": valor_llm, "cep": "68020000"}, "confianca": 0.95},
        )
        if est.get("data_nascimento") != "16/08/2000" or dec.aguardando == "data_nascimento":
            v.append(f"data por extenso não foi aceita: {est.get('data_nascimento')!r}, aguardando={dec.aguardando}")
    return v


def depois_do_encerramento() -> list[str]:
    """'Obrigado' após o encerramento: resposta curta, uma vez, sem recomeçar o funil."""
    v: list[str] = []
    from app.pos_venda_mensagens import cortesia_pos_encerramento

    final = dict(BASE, **CONFIRMADO, **CAD, fase="finalizado", cadastro_completo=True, agendamento_confirmado=True)
    est, dec = regressao._turno(dict(final), "Obrigado", {"eventos": ["CONVERSA_SOCIAL"], "dados": {}, "confianca": 0.9})
    if dec.fase != "finalizado" or dec.objetivo_resposta != "CORTESIA_POS_ENCERRAMENTO":
        v.append(f"'Obrigado' após encerrar → {dec.acao}/{dec.objetivo_resposta} fase={dec.fase}")
    if not (dec.contexto_resposta or {}).get("resolver_conversa"):
        v.append("'Obrigado' após encerrar não pede para resolver a conversa reaberta")
    if est.get("nome") != CAD["nome"]:
        v.append("dados do cliente foram perdidos depois do agradecimento")
    # Segundo agradecimento: silêncio (não fica respondendo em laço)
    ja = dict(final, ultima_mensagem_sofia=cortesia_pos_encerramento(CAD["nome"]))
    _, dec2 = regressao._turno(ja, "👍", {"eventos": ["CONVERSA_SOCIAL"], "dados": {}, "confianca": 0.9})
    if dec2.acao != "AGUARDAR":
        v.append(f"segundo agradecimento deveria ficar em silêncio, veio {dec2.acao}")
    return v


def agenda_de_cliente_real() -> list[str]:
    """Com conversa do Chatwoot, horário e agendamento nunca podem ser simulados."""
    v: list[str] = []
    from app.agenda import consultar_horarios
    from app.agenda_inserir import inserir_agendamento

    real = {
        "id_cliente": "5593999999999", "conversation_id": "999", "ixc_cliente_id": "1",
        "tecnico_id": "159", "data_agendamento": "08/10/2026", "horario_escolhido": "8h às 9h",
        "cidade": "Santarém", "bairro": "Diamantino",
    }
    for nome, fn in (("horários", consultar_horarios), ("agendamento", inserir_agendamento)):
        r = fn(dict(real))
        if r.get("provider") == "mock" or (str(r.get("resultado")).lower() == "ok" and not r.get("erro")):
            v.append(f"{nome} de cliente real voltou simulado/ok sem chamar o webhook: {r}")
    return v


def main() -> None:
    falhas = 0

    for rotulo, checagem in (
        ("atendimento real de 07/10: cidade, plano e data preservados", conversa_real_7_outubro),
        ("'Obrigado' após encerrar: cortesia única, sem recomeçar", depois_do_encerramento),
        ("agenda de cliente real nunca é simulada", agenda_de_cliente_real),
    ):
        violacoes = checagem()
        for v in violacoes:
            print(f"  FALHOU {v}")
        falhas += len(violacoes)
        if not violacoes:
            print(f"  OK {rotulo}")

    turnos, violacoes = dado_com_duvida()
    for v in violacoes:
        print(f"  FALHOU {v}")
    falhas += len(violacoes)
    if not violacoes:
        print(f"  OK {turnos} mensagens de dado + dúvida: dado gravado e não pedido de novo")

    turnos, violacoes = varrer()
    for v in violacoes:
        print(f"  FALHOU {v}")
    falhas += len(violacoes)
    if not violacoes:
        print(f"  OK {turnos} turnos sem dado inventado nem avanço indevido")

    # Conversa real em que o celular foi gravado como CPF e a Eva pediu o telefone de novo
    violacoes = []
    for cpf_inicial in (
        {"cpf": "60421079096"},  # CPF salvo mas ainda não validado
        {"cpf": "60421079096", "documento_cpf_validado": True},
        {},
    ):
        violacoes += conversa_cadastro(cpf_inicial)
    for v in violacoes:
        print(f"  FALHOU {v}")
    falhas += len(violacoes)
    if not violacoes:
        print("  OK nome → e-mail → celular: texto pede o campo aguardado e o celular não vira CPF")

    if falhas:
        print(f"\n❌ {falhas} violação(ões)")
        sys.exit(1)
    print("\n✅ Varredura de frases OK")


if __name__ == "__main__":
    main()
