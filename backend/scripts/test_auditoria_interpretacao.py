# -*- coding: utf-8 -*-
"""
Auditoria de interpretação — o que as regras fazem com uma leitura CORRETA do LLM.

Cada caso é (estado do funil, mensagem do cliente, interpretação correta). O turno
roda inteiro em memória (parser → resolver → máquina de estados → ações simuladas)
e as checagens apontam onde o código estraga a interpretação:

  - dado informado que não foi gravado, ou foi pedido de novo;
  - frase de conversa gravada como dado;
  - objeção/dúvida que avançou o funil, confirmou plano ou encerrou;
  - plano escolhido diferente do que o cliente falou;
  - texto da Eva pedindo um campo diferente do que o estado aguarda.

Sem LLM e sem rede (todo HTTP é bloqueado; integrações são simuladas).

  py scripts/test_auditoria_interpretacao.py            # roda e falha se houver violação
  py scripts/test_auditoria_interpretacao.py --resumo   # só a contagem por categoria
  py scripts/test_auditoria_interpretacao.py --exportar # gera eval/casos_auditoria.jsonl
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter
from typing import Any, Callable, Iterator

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx


def _bloquear(self, request, *args, **kwargs):
    raise httpx.ConnectError("rede bloqueada na auditoria", request=request)


async def _bloquear_async(self, request, *args, **kwargs):
    raise httpx.ConnectError("rede bloqueada na auditoria", request=request)


httpx.Client.send = _bloquear
httpx.AsyncClient.send = _bloquear_async
logging.disable(logging.CRITICAL)

from app import pipeline, response
from app.contexto_conversa import enriquecer_pergunta
from app.db import aplicar_transicao
from app.parser import (
    eh_apenas_dado_cadastro,
    eh_mensagem_correcao_cadastro,
    parse_interpretacao,
)
from app.plano_intencao import contexto_por_objetivo_resposta
from app.plans_catalog import listar_planos
from app.resolver import normalizar_campo, resolver
from app.state_machine import decidir

# ── Integrações simuladas ────────────────────────────────────────────────────


def _so_digitos(v: Any) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _cobertura(**k):
    cidade, bairro = str(k.get("cidade") or ""), str(k.get("bairro") or "")
    ok = normalizar_campo("cidade", cidade) in {"santarem", "belterra", "mojui dos campos"}
    return {
        "resultado": "cobertura_confirmada" if ok else "sem_cobertura",
        "tem_cobertura": ok,
        "cidade_normalizada": cidade,
        "bairro_normalizado": bairro,
        "motivo": "simulado",
    }


pipeline.checar_cobertura = _cobertura
pipeline.validar_cpf = lambda **k: {
    "ja_cadastrado": False, "erro": False, "motivo": "CPF novo",
    "cpf_formatado": k.get("cpf_cnpj"), "cpf_numeros": _so_digitos(k.get("cpf_cnpj")),
}
pipeline.cadastrar_cliente = lambda estado: {
    "ok": True, "erro": False, "id_cliente_ixc": "9001", "os_id": "7001", "id_contrato_ixc": "8001",
    "motivo": "simulado",
}
pipeline.enviar_termos = lambda estado: {
    "resultado": "ok", "audio_enviado": True, "termo_enviado": True, "provider": "webhook",
}
pipeline.ativar_cliente = lambda estado: {"resultado": "ok", "ativado": True}
pipeline.consultar_horarios = lambda estado: {
    "resultado": "ok", "tecnico_id": "159", "data": "08/10/2026",
    "manha": ["8h às 9h", "9h às 10h", "10h às 11h"], "tarde": ["14h às 15h", "15h às 16h"],
}
pipeline.inserir_agendamento = lambda estado: {"resultado": "ok", "os_id": "7001"}
pipeline.encerrar_atendimento = lambda estado: {"resultado": "ok", "motivo": "simulado"}
pipeline.enviar_imagem_plano = lambda estado: {"resultado": "ok", "imagem_enviada": False, "motivo": "sem imagem"}
response.chat = lambda *a, **k: ""

TERMINAIS = {"RESPONDER", "TRANSFERIR_HUMANO", "AGUARDAR"}


def turno(estado: dict, msg: str, llm: dict) -> tuple[dict, Any, Any]:
    """Um turno como em pipeline.process_message, com o estado em memória."""
    estado = dict(estado)
    interp = parse_interpretacao(json.dumps(llm, ensure_ascii=False), msg, estado)
    ctx = enriquecer_pergunta(
        msg,
        pergunta=interp.pergunta or msg,
        historico=[],
        plano_nome=str(estado.get("plano_em_negociacao") or estado.get("plano_confirmado") or ""),
        ultimo_topico=str(estado.get("ultimo_topico") or "") or None,
    )
    if pipeline.tem_pergunta(interp) and ctx.get("pergunta"):
        interp.pergunta = str(ctx["pergunta"])
    meta: dict[str, Any] = {}
    if ctx.get("topico"):
        meta["ultimo_topico"] = ctx["topico"]
    elif eh_apenas_dado_cadastro(msg, msg) or eh_mensagem_correcao_cadastro(msg, msg):
        meta["limpar_topico"] = True
    if meta:
        estado = aplicar_transicao(estado, str(estado.get("fase") or "inicio"), estado.get("aguardando"), meta)

    res = resolver(estado, interp)
    res["mensagem"] = msg
    res["pergunta"] = interp.pergunta
    res["topico_contexto"] = ctx.get("topico")
    res["pergunta_original"] = ctx.get("mensagem_original") or msg
    res["confianca"] = float(interp.confianca or 0)
    dec = decidir(estado, res)
    if dec.acao == "RESOLVER_PLANO":
        c = dict(dec.contexto_resposta or {})
        if not str(c.get("referencia_plano") or "").strip():
            c["referencia_plano"] = (res.get("plano") or {}).get("valor") or ""
        dec.contexto_resposta = c
    for _ in range(5):
        if dec.acao in TERMINAIS:
            break
        estado = aplicar_transicao(estado, dec.fase, dec.aguardando, dec.atualizar_dados)
        dec = pipeline._executar_acao(estado, dec)
    finais = dict(dec.atualizar_dados or {})
    ctx_plano = contexto_por_objetivo_resposta(dec.objetivo_resposta)
    if ctx_plano and "contexto_plano" not in finais:
        finais["contexto_plano"] = ctx_plano
    estado = aplicar_transicao(estado, dec.fase, dec.aguardando, finais)
    return estado, dec, interp


def texto_da_eva(dec, estado: dict, msg: str) -> str:
    return response.gerar_resposta(dec, estado, historico=[], mensagem_cliente=msg)


# ── Estados ──────────────────────────────────────────────────────────────────

PLANOS = {str(p["nome"]): int(p["id"]) for p in listar_planos({})}
ORDEM = ["nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero"]
CAD = {
    "nome": "João Silva", "cpf": "12345678909", "email": "j@g.com", "telefone": "93991234567",
    "data_nascimento": "15/03/1990", "cep": "68020000", "rua": "Rua A", "numero": "10",
}
BASE = {
    "id_cliente": "auditoria", "tem_cobertura": True, "cidade": "Santarém", "bairro": "Diamantino",
    "cumprimento_feito": True,
}


def _plano(nome: str, papel: str) -> dict:
    d = {f"plano_{papel}": nome, f"plano_{papel}_id": PLANOS[nome]}
    if papel == "em_negociacao":
        d.update(plano_apresentado=nome, plano_apresentado_id=PLANOS[nome])
    return d


def E(nome: str) -> dict:
    """Estado do funil pelo nome (ex.: 'cad/telefone', 'vendas/confirmacao_plano')."""
    if nome == "inicio":
        return {"id_cliente": "auditoria", "fase": "inicio"}
    if nome == "viab":
        return {"id_cliente": "auditoria", "fase": "viabilidade", "aguardando": "localizacao", "cumprimento_feito": True}
    if nome == "viab/tem_cidade":
        return dict(E("viab"), cidade="Santarém")
    if nome == "vendas/confirmacao_plano":
        return dict(BASE, **_plano("MOV SUPER+", "em_negociacao"), fase="vendas", aguardando="confirmacao_plano")
    if nome == "vendas/escolha_plano":
        return dict(BASE, plano_apresentado="MOV SUPER+", plano_apresentado_id=PLANOS["MOV SUPER+"],
                    fase="vendas", aguardando="escolha_plano")
    conf = _plano("MOV SUPER+", "confirmado")
    if nome.startswith("cad/") and nome[4:] in ORDEM:
        campo = nome[4:]
        i = ORDEM.index(campo)
        return dict(BASE, **conf, fase="cadastro", aguardando=campo, documento_cpf_validado=(i > 1),
                    **{c: CAD[c] for c in ORDEM[:i]})
    completo = dict(BASE, **conf, **CAD, documento_cpf_validado=True)
    if nome == "cad/confirmacao_dados":
        return dict(completo, fase="cadastro", aguardando="confirmacao_dados")
    if nome == "termos":
        return dict(completo, fase="termos", aguardando="aceite_termos", termos_enviados=True,
                    cadastro_completo=True, ixc_cliente_id="9001", id_contrato_ixc="8001", os_id="7001")
    agenda = dict(completo, cadastro_completo=True, ixc_cliente_id="9001", tecnico_id="159",
                  horarios_manha='["8h às 9h", "9h às 10h", "10h às 11h"]',
                  horarios_tarde='["14h às 15h", "15h às 16h"]', data_agendamento="08/10/2026")
    if nome == "agenda/escolha_horario":
        return dict(agenda, fase="agendamento", aguardando="escolha_horario")
    if nome == "agenda/confirmacao_horario":
        return dict(agenda, fase="agendamento", aguardando="confirmacao_horario", horario_escolhido="14h às 15h")
    if nome == "pos":
        return dict(agenda, fase="pos_venda", aguardando="duvidas", agendamento_confirmado=True,
                    horario_escolhido="14h às 15h")
    raise KeyError(nome)


ESTADOS_CADASTRO = [f"cad/{c}" for c in ORDEM]
ESTADOS_CONFIRMACAO = ["vendas/confirmacao_plano", "cad/confirmacao_dados", "termos", "agenda/confirmacao_horario"]
TODOS = ["inicio", "viab", "vendas/confirmacao_plano", "vendas/escolha_plano", *ESTADOS_CADASTRO,
         "cad/confirmacao_dados", "termos", "agenda/escolha_horario", "agenda/confirmacao_horario", "pos"]
ORDEM_FASES = ["inicio", "viabilidade", "vendas", "cadastro", "termos", "agendamento", "pos_venda", "finalizado"]
CAMPOS_CLIENTE = [*ORDEM, "cidade", "bairro", "complemento"]


def L(eventos: list[str], dados: dict | None = None, pergunta: str = "", corrigidos: list[str] | None = None) -> dict:
    return {"eventos": eventos, "dados": dados or {}, "campos_corrigidos": corrigidos or [],
            "pergunta": pergunta, "confianca": 0.93}


# ── Checagens ────────────────────────────────────────────────────────────────
# Cada checagem recebe (estado_antes, estado_depois, decisao, interpretacao, msg) e devolve erro ou None.

Check = Callable[[dict, dict, Any, Any, str], "str | None"]


def _igual(campo: str, esperado: str, obtido: Any) -> bool:
    if campo in {"cpf", "telefone", "cep"}:
        return _so_digitos(esperado) == _so_digitos(obtido)
    e, o = normalizar_campo(campo, esperado), normalizar_campo(campo, str(obtido or ""))
    return bool(e) and (e == o or (campo in {"nome", "rua", "cidade", "bairro"} and e in o))


def gravou(**campos: str) -> Check:
    def f(a, d, dec, i, msg):
        for campo, esperado in campos.items():
            if not _igual(campo, esperado, d.get(campo)):
                return f"não gravou {campo}={esperado!r} (ficou {d.get(campo)!r})"
        return None
    return f


def nao_mexeu_em(*campos: str) -> Check:
    def f(a, d, dec, i, msg):
        for campo in campos or CAMPOS_CLIENTE:
            if (d.get(campo) or None) != (a.get(campo) or None):
                return f"mexeu em {campo}: {a.get(campo)!r} → {d.get(campo)!r}"
        return None
    return f


def so_mexeu_em(*permitidos: str) -> Check:
    return nao_mexeu_em(*[c for c in CAMPOS_CLIENTE if c not in permitidos])


def nao_pede_de_novo(campo: str) -> Check:
    return lambda a, d, dec, i, msg: (
        f"pediu {campo} de novo" if dec.aguardando == campo else None
    )


def continua_aguardando() -> Check:
    return lambda a, d, dec, i, msg: (
        None if dec.aguardando == a.get("aguardando") and dec.fase == a.get("fase")
        else f"saiu de {a.get('fase')}/{a.get('aguardando')} para {dec.fase}/{dec.aguardando}"
    )


def fica_na_fase() -> Check:
    return lambda a, d, dec, i, msg: (
        None if dec.fase == a.get("fase") else f"mudou de fase: {a.get('fase')} → {dec.fase}"
    )


def nao_avanca() -> Check:
    def f(a, d, dec, i, msg):
        f0, f1 = str(a.get("fase")), str(dec.fase)
        if f1 == "transferido":
            return f"transferiu para humano ({dec.objetivo_resposta})"
        if f1 == "finalizado":
            return "finalizou o atendimento"
        if f0 in ORDEM_FASES and f1 in ORDEM_FASES and ORDEM_FASES.index(f1) > ORDEM_FASES.index(f0):
            if not (f0 == "inicio" and f1 == "viabilidade"):
                return f"avançou {f0} → {f1}"
        for flag in ("plano_confirmado", "cadastro_completo", "agendamento_confirmado", "ixc_cliente_id"):
            if d.get(flag) and not a.get(flag):
                return f"marcou {flag}={d.get(flag)!r}"
        return None
    return f


def avanca_para(fase: str, aguardando: str | None = None) -> Check:
    def f(a, d, dec, i, msg):
        if dec.fase != fase or (aguardando is not None and dec.aguardando != aguardando):
            return f"esperado {fase}/{aguardando or '*'}, veio {dec.fase}/{dec.aguardando} ({dec.objetivo_resposta})"
        return None
    return f


def plano_e(nome: str) -> Check:
    def f(a, d, dec, i, msg):
        atual = d.get("plano_confirmado") if d.get("plano_confirmado") != a.get("plano_confirmado") else None
        atual = atual or d.get("plano_em_negociacao")
        if str(atual or "").upper() != nome.upper():
            return f"plano esperado {nome}, ficou negociação={d.get('plano_em_negociacao')!r} confirmado={d.get('plano_confirmado')!r} ({dec.objetivo_resposta})"
        return None
    return f


def nao_confirma_outro_plano(nome: str) -> Check:
    def f(a, d, dec, i, msg):
        conf = d.get("plano_confirmado")
        if conf and not a.get("plano_confirmado") and str(conf).upper() != nome.upper():
            return f"confirmou {conf!r} quando o cliente falou {nome}"
        return None
    return f


def fase_e(fase: str) -> Check:
    return lambda a, d, dec, i, msg: None if dec.fase == fase else f"esperado fase {fase}, veio {dec.fase} ({dec.objetivo_resposta})"


def responde() -> Check:
    return lambda a, d, dec, i, msg: None if dec.acao == "RESPONDER" else f"ação {dec.acao} ({dec.objetivo_resposta})"


ROTULO = {"nome": "nome", "cpf": "cpf", "email": "e-mail", "telefone": "telefone",
          "data_nascimento": "data de nascimento", "cep": "cep", "rua": "rua", "numero": "número"}
OBJETIVOS_COM_TEMPLATE = ("ANOTAR_E_PEDIR_PROXIMO", "PEDIR_", "INFORMAR_CANCELAMENTO_E_RETOMAR", "INFORMAR_INSTALACAO_E_RETOMAR")


def texto_pede_o_aguardado() -> Check:
    def f(a, d, dec, i, msg):
        rot = ROTULO.get(str(dec.aguardando))
        obj = str(dec.objetivo_resposta or "")
        if not rot or dec.fase != "cadastro" or not obj.startswith(OBJETIVOS_COM_TEMPLATE):
            return None
        txt = texto_da_eva(dec, d, msg).casefold()
        return None if rot in txt else f"estado aguarda {dec.aguardando} mas a Eva disse: {txt[-90:]!r}"
    return f


# ── Bancos de mensagens ──────────────────────────────────────────────────────

Caso = tuple[str, str, str, dict, list]

VALORES: dict[str, list[tuple[str, str]]] = {
    # campo: [(texto do cliente, valor que deve ficar gravado)]
    "nome": [
        ("Edrei Maciel", "Edrei Maciel"),
        ("edrei tester maciel", "edrei tester maciel"),
        ("MARIA DA SILVA SOUZA", "Maria da Silva Souza"),
        ("meu nome é João Pedro Alves", "João Pedro Alves"),
        ("Me chamo Carlos Eduardo Lima", "Carlos Eduardo Lima"),
        ("é Ana Clara dos Santos", "Ana Clara dos Santos"),
        ("Francisco de Assis Pereira Neto", "Francisco de Assis Pereira Neto"),
        ("sou a Beatriz Nogueira", "Beatriz Nogueira"),
    ],
    "cpf": [
        ("604.210.790-96", "60421079096"),
        ("60421079096", "60421079096"),
        ("meu cpf é 604.210.790-96", "60421079096"),
        ("CPF: 604.210.790-96", "60421079096"),
        ("604 210 790 96", "60421079096"),
        ("é 529.982.247-25", "52998224725"),
    ],
    "email": [
        ("edrei@gmail.com", "edrei@gmail.com"),
        ("meu email é edrei.tester@hotmail.com", "edrei.tester@hotmail.com"),
        ("EDREI@GMAIL.COM", "edrei@gmail.com"),
        ("e-mail: joao_silva@yahoo.com.br", "joao_silva@yahoo.com.br"),
        ("pode anotar maria.souza@outlook.com", "maria.souza@outlook.com"),
    ],
    "telefone": [
        ("93992219098", "93992219098"),
        ("(93) 99221-9098", "93992219098"),
        ("93 99221-9098", "93992219098"),
        ("meu número é 93 992219098", "93992219098"),
        ("93 9 9221 9098", "93992219098"),
        ("é o 93991112222", "93991112222"),
    ],
    "data_nascimento": [
        ("16/08/2000", "16/08/2000"),
        ("16-08-2000", "16/08/2000"),
        ("16.08.2000", "16/08/2000"),
        ("16 de agosto de 2000", "16/08/2000"),
        ("nasci em 16/08/2000", "16/08/2000"),
        ("16 ago 2000", "16/08/2000"),
        ("1 de março de 1985", "01/03/1985"),
        ("dia 5/7/1992", "05/07/1992"),
    ],
    "cep": [
        ("68020000", "68020000"),
        ("68020-000", "68020000"),
        ("cep 68020-000", "68020000"),
        ("o cep é 68.020-000", "68020000"),
        ("68005 120", "68005120"),
    ],
    "rua": [
        ("Rua das Flores", "Rua das Flores"),
        ("Sergio Henn", "Sergio Henn"),
        ("Av. Mendonça Furtado", "Mendonça Furtado"),
        ("travessa 15 de agosto", "15 de agosto"),
        ("moro na rua das acácias", "acácias"),
        ("é na Rui Barbosa", "Rui Barbosa"),
        ("Avenida Presidente Vargas", "Presidente Vargas"),
        ("rua 24 de outubro", "24 de outubro"),
    ],
    "numero": [
        ("891", "891"),
        ("número 77", "77"),
        ("nº 45", "45"),
        ("casa 12", "12"),
        ("é o 1200", "1200"),
    ],
}

PARES_JUNTOS = [
    ("cad/nome", "Edrei Maciel, 604.210.790-96", {"nome": "Edrei Maciel", "cpf": "60421079096"}),
    ("cad/nome", "Edrei Maciel cpf 60421079096", {"nome": "Edrei Maciel", "cpf": "60421079096"}),
    ("cad/nome", "Maria Souza\n529.982.247-25", {"nome": "Maria Souza", "cpf": "52998224725"}),
    ("cad/email", "edrei@gmail.com 93992219098", {"email": "edrei@gmail.com", "telefone": "93992219098"}),
    ("cad/email", "edrei@gmail.com\n(93) 99221-9098", {"email": "edrei@gmail.com", "telefone": "93992219098"}),
    ("cad/email", "email edrei@gmail.com e telefone 93 99221-9098", {"email": "edrei@gmail.com", "telefone": "93992219098"}),
    ("cad/data_nascimento", "16/08/2000 68020000", {"data_nascimento": "16/08/2000", "cep": "68020000"}),
    ("cad/data_nascimento", "16 de agosto de 2000\n68020000", {"data_nascimento": "16/08/2000", "cep": "68020000"}),
    ("cad/data_nascimento", "nasci 16/08/2000, cep 68020-000", {"data_nascimento": "16/08/2000", "cep": "68020000"}),
    ("cad/rua", "Rua das Flores, 123", {"rua": "Rua das Flores", "numero": "123"}),
    ("cad/rua", "Sergio Henn 891", {"rua": "Sergio Henn", "numero": "891"}),
    ("cad/rua", "Av Mendonça Furtado nº 2040", {"rua": "Mendonça Furtado", "numero": "2040"}),
    ("cad/rua", "Ségio henn, 891\né um condomínio", {"rua": "Ségio henn", "numero": "891"}),
]

DUVIDAS = [
    "tem multa de cancelamento?", "tem fidelidade?", "e se eu cancelar antes?", "quanto tempo demora a instalação?",
    "a instalação é paga?", "tem taxa de instalação?", "qual o vencimento da fatura?", "posso pagar no cartão?",
    "aceita pix?", "vocês atendem aos sábados?", "o roteador é de vocês?", "preciso devolver o equipamento?",
    "e se eu mudar de endereço depois?", "vocês são de onde?", "tem suporte 24h?", "a internet é fibra mesmo?",
    "como funciona o contrato?", "qual a velocidade?", "funciona pra jogar?", "quantos aparelhos aguenta?",
    "tem telefone fixo?", "o técnico vem que horas?", "demora quanto pra ativar?", "é seguro passar meus dados?",
    "pra que precisa do cpf?", "posso colocar no nome de outra pessoa?",
]

CONFIRMACOES = [
    "sim", "pode ser", "isso", "isso mesmo", "ok", "tá bom", "beleza", "fechado", "com certeza", "claro",
    "pode sim", "quero sim", "sim, pode seguir", "pode continuar", "bora", "vamos", "positivo", "correto",
    "tá certo", "tudo certo", "perfeito", "confirmo", "pode mandar", "sim por favor", "s", "ss", "uhum",
    "aham", "exato", "certinho", "pode fechar", "tá ok", "ok pode ser", "sim sim", "isso aí", "show", "fechou",
]

NAO_CONFIRMA = [
    # (mensagem, eventos do LLM)
    ("não", ["NEGACAO"]), ("não quero", ["NEGACAO"]), ("agora não", ["NEGACAO"]), ("não, obrigado", ["NEGACAO"]),
    ("tá caro", ["OUTRO"]), ("muito caro", ["OUTRO"]), ("achei caro", ["OUTRO"]), ("vou pensar", ["OUTRO"]),
    ("deixa eu ver aqui", ["CONVERSA_SOCIAL"]), ("depois eu vejo", ["OUTRO"]), ("não sei", ["OUTRO"]),
    ("não entendi", ["OUTRO"]), ("espera", ["CONVERSA_SOCIAL"]), ("pera aí", ["CONVERSA_SOCIAL"]),
    ("calma", ["CONVERSA_SOCIAL"]), ("tá errado", ["OUTRO"]), ("não é isso", ["NEGACAO"]), ("hmm", ["CONVERSA_SOCIAL"]),
    ("sei lá", ["OUTRO"]), ("vou falar com minha esposa", ["OUTRO"]), ("ainda não", ["NEGACAO"]),
    ("to pensando", ["OUTRO"]), ("ok vou pensar", ["OUTRO"]), ("sim mas tá caro", ["OUTRO"]),
    ("tá, mas deixa eu ver com meu marido", ["OUTRO"]), ("me dá um minuto", ["CONVERSA_SOCIAL"]),
    ("já te falo", ["CONVERSA_SOCIAL"]), ("kkkk", ["CONVERSA_SOCIAL"]), ("nossa", ["CONVERSA_SOCIAL"]),
]

CONVERSA = [
    ("ok", ["CONFIRMACAO"]), ("tá bom", ["CONFIRMACAO"]), ("beleza", ["CONFIRMACAO"]), ("pode ser", ["CONFIRMACAO"]),
    ("certo", ["CONFIRMACAO"]), ("entendi", ["CONVERSA_SOCIAL"]), ("pera aí", ["CONVERSA_SOCIAL"]),
    ("um momento", ["CONVERSA_SOCIAL"]), ("já mando", ["CONVERSA_SOCIAL"]), ("vou pegar aqui", ["CONVERSA_SOCIAL"]),
    ("deixa eu procurar", ["CONVERSA_SOCIAL"]), ("kkkk", ["CONVERSA_SOCIAL"]), ("obrigado", ["CONVERSA_SOCIAL"]),
    ("não entendi", ["OUTRO"]), ("como assim?", ["PERGUNTA"]), ("pode repetir?", ["PERGUNTA"]),
    ("o que você precisa mesmo?", ["PERGUNTA"]), ("não tenho agora", ["OUTRO"]), ("não lembro", ["OUTRO"]),
    ("não sei de cabeça", ["OUTRO"]), ("vou ver e te falo", ["CONVERSA_SOCIAL"]), ("oi", ["SAUDACAO"]),
    ("bom dia", ["SAUDACAO"]), ("opa", ["SAUDACAO"]), ("tá caro", ["OUTRO"]), ("vou pensar", ["OUTRO"]),
    ("precisa mesmo disso?", ["PERGUNTA"]), ("pra quê?", ["PERGUNTA"]), ("já mandei", ["OUTRO"]),
    ("é o mesmo de antes", ["OUTRO"]), ("tá demorando", ["OUTRO"]), ("to no trabalho agora", ["CONVERSA_SOCIAL"]),
]

ESCOLHAS_PLANO = [
    # (mensagem, plano que o LLM extrai, plano esperado)
    ("quero o infinity", "infinity", "MOV INFINITY"),
    ("pode ser o infinity", "infinity", "MOV INFINITY"),
    ("o infinity", "infinity", "MOV INFINITY"),
    ("infinity", "infinity", "MOV INFINITY"),
    ("vou de infinity", "infinity", "MOV INFINITY"),
    ("sim, o infinity", "infinity", "MOV INFINITY"),
    ("fecha no infinity", "infinity", "MOV INFINITY"),
    ("então me vê o infinity", "infinity", "MOV INFINITY"),
    ("prefiro o one+", "one+", "MOV ONE+"),
    ("o mov one", "mov one", "MOV ONE+"),
    ("pode ser o one plus", "one plus", "MOV ONE+"),
    ("quero o up+", "up+", "MOV UP+"),
    ("me vê o mov up", "mov up", "MOV UP+"),
    ("quero o flex", "flex", "MOV FLEX"),
    ("pode ser o mov flex", "mov flex", "MOV FLEX"),
    ("o plano essencial", "essencial", "MOV ESSENCIAL"),
    ("quero o mov essencial", "mov essencial", "MOV ESSENCIAL"),
    ("o de 189", "o de 189", "MOV INFINITY"),
    ("quero o de 149", "o de 149", "MOV UP+"),
    ("pode ser o de 189", "o de 189", "MOV INFINITY"),
    ("quero o mais barato", "mais barato", "MOV FLEX"),
    ("Quero esse up", "up", "MOV UP+"),
    ("quero o up", "UP+", "MOV UP+"),
    ("pode ser o one", "one", "MOV ONE+"),
    ("fico com o flex", "MOV FLEX", "MOV FLEX"),
    ("o mais em conta", "mais em conta", "MOV FLEX"),
]

MESMO_PLANO = [
    "quero o super+ mesmo", "pode ser o super+", "fico com o super+", "sim, o super+", "o mov super+ tá ótimo",
]

CORRECOES = [
    # (mensagem, campo, valor do LLM, valor esperado)
    ("o nome está errado, é João Carlos Silva", "nome", "João Carlos Silva", "João Carlos Silva"),
    ("corrige meu nome pra Maria Aparecida Souza", "nome", "Maria Aparecida Souza", "Maria Aparecida Souza"),
    ("meu email é outro: novo.email@gmail.com", "email", "novo.email@gmail.com", "novo.email@gmail.com"),
    ("o email tá errado, é joao2@gmail.com", "email", "joao2@gmail.com", "joao2@gmail.com"),
    ("telefone errado, o certo é 93991112222", "telefone", "93991112222", "93991112222"),
    ("o número da casa é 892", "numero", "892", "892"),
    ("a rua é Rui Barbosa", "rua", "Rui Barbosa", "Rui Barbosa"),
    ("o cep é 68005-120", "cep", "68005120", "68005120"),
    ("nasci em 17/08/2000 na verdade", "data_nascimento", "17/08/2000", "17/08/2000"),
    ("a data de nascimento é 17 de agosto de 2000", "data_nascimento", "17/08/2000", "17/08/2000"),
]

LOCALIZACOES = [
    # (estado, mensagem, dados do LLM, esperado)
    ("viab", "Santarém, Diamantino", {"cidade": "Santarém", "bairro": "Diamantino"}, {"cidade": "Santarém", "bairro": "Diamantino"}),
    ("viab", "moro no diamantino em santarém", {"cidade": "Santarém", "bairro": "Diamantino"}, {"cidade": "Santarém", "bairro": "Diamantino"}),
    ("viab", "Aqui no diamantino, Santarém", {"cidade": "Santarém", "bairro": "Diamantino"}, {"cidade": "Santarém", "bairro": "Diamantino"}),
    ("viab", "bairro aparecida, santarém", {"cidade": "Santarém", "bairro": "Aparecida"}, {"cidade": "Santarém", "bairro": "Aparecida"}),
    ("viab", "sou de santarém, bairro aeroporto velho", {"cidade": "Santarém", "bairro": "Aeroporto Velho"}, {"cidade": "Santarém", "bairro": "Aeroporto Velho"}),
    ("viab", "santarém no bairro santa clara", {"cidade": "Santarém", "bairro": "Santa Clara"}, {"cidade": "Santarém", "bairro": "Santa Clara"}),
    ("viab", "Santarém - Centro", {"cidade": "Santarém", "bairro": "Centro"}, {"cidade": "Santarém", "bairro": "Centro"}),
    ("viab", "santarém", {"cidade": "Santarém"}, {"cidade": "Santarém"}),
    ("viab", "Aqui em santarém", {"cidade": "Santarém"}, {"cidade": "Santarém"}),
    ("viab", "Quero ver os planos ai\nAqui em santarém", {"cidade": "Santarém"}, {"cidade": "Santarém"}),
    ("viab", "quero internet, moro em santarém no diamantino", {"cidade": "Santarém", "bairro": "Diamantino"}, {"cidade": "Santarém", "bairro": "Diamantino"}),
    ("viab", "oi, sou de santarém", {"cidade": "Santarém"}, {"cidade": "Santarém"}),
    ("viab", "Belterra, centro", {"cidade": "Belterra", "bairro": "Centro"}, {"cidade": "Belterra", "bairro": "Centro"}),
    ("viab/tem_cidade", "Diamantino", {"bairro": "Diamantino"}, {"cidade": "Santarém", "bairro": "Diamantino"}),
    ("viab/tem_cidade", "no aparecida", {"bairro": "Aparecida"}, {"cidade": "Santarém", "bairro": "Aparecida"}),
    ("viab/tem_cidade", "bairro santa clara", {"bairro": "Santa Clara"}, {"cidade": "Santarém", "bairro": "Santa Clara"}),
    ("viab/tem_cidade", "é no maracanã", {"bairro": "Maracanã"}, {"cidade": "Santarém", "bairro": "Maracanã"}),
    ("inicio", "Santarém, Diamantino", {"cidade": "Santarém", "bairro": "Diamantino"}, {"cidade": "Santarém", "bairro": "Diamantino"}),
    ("inicio", "oi, quero internet em santarém no diamantino", {"cidade": "Santarém", "bairro": "Diamantino"}, {"cidade": "Santarém", "bairro": "Diamantino"}),
]

HUMANO = ["quero falar com atendente", "me passa pra um humano", "quero falar com uma pessoa",
          "atendente por favor", "prefiro falar com alguém da equipe"]
ENCERRAR = ["quero encerrar", "pode encerrar o atendimento", "encerrar"]
HORARIOS = [("pode ser 14h", "14h às 15h"), ("8", "8h às 9h"), ("as 9", "9h às 10h"), ("14h às 15h", "14h às 15h"),
            ("o das 15", "15h às 16h"), ("de manhã às 10", "10h às 11h"), ("quero o primeiro horário", "8h às 9h")]


def casos() -> Iterator[Caso]:
    # 1. Dado pedido, em vários formatos
    for campo, valores in VALORES.items():
        for txt, esperado in valores:
            checks = [gravou(**{campo: esperado}), nao_pede_de_novo(campo), fase_e("cadastro"),
                      so_mexeu_em(campo, "numero" if campo == "rua" else campo, "complemento"),
                      texto_pede_o_aguardado()]
            yield ("dado", f"cad/{campo}", txt, L(["DADO_INFORMADO"], {campo: esperado}), checks)

    # 2. Dois dados na mesma mensagem (a Eva pede em pares)
    for est, txt, dados in PARES_JUNTOS:
        primeiro = est[4:]
        yield ("par", est, txt, L(["DADO_INFORMADO"], dados),
               [gravou(**dados), *[nao_pede_de_novo(c) for c in dados], fase_e("cadastro"),
                so_mexeu_em(*dados, "complemento"), texto_pede_o_aguardado()])

    # 3. Dado fora de ordem: informa outro campo, o pendente continua pendente
    for i, pendente in enumerate(ORDEM[:-1]):
        for outro in ORDEM[i + 1:i + 3]:
            txt, esperado = VALORES[outro][0]
            checks = [gravou(**{outro: esperado}), fase_e("cadastro"), texto_pede_o_aguardado(),
                      so_mexeu_em(outro, "numero" if outro == "rua" else outro)]
            if not (pendente == "nome" and outro == "cpf"):
                checks.append(lambda a, d, dec, i_, m, p=pendente: None if dec.aguardando == p else f"pendente era {p}, passou a aguardar {dec.aguardando}")
            yield ("fora_de_ordem", f"cad/{pendente}", txt, L(["DADO_INFORMADO"], {outro: esperado}), checks)

    # 4. Dúvida pura em qualquer etapa: responde e continua onde estava
    for est in TODOS:
        for d in DUVIDAS:
            checks = [nao_mexeu_em(), nao_avanca()]
            if est.startswith(("cad/", "termos", "agenda/")):
                checks.append(continua_aguardando())
            yield ("duvida", est, d, L(["PERGUNTA"], pergunta=d), checks)

    # 5. Confirmações nas etapas de confirmação
    destino = {"vendas/confirmacao_plano": ("cadastro", "nome"), "cad/confirmacao_dados": ("termos", "aceite_termos"),
               "termos": ("agendamento", "escolha_horario"), "agenda/confirmacao_horario": ("pos_venda", "duvidas")}
    for est in ESTADOS_CONFIRMACAO:
        for c in CONFIRMACOES:
            yield ("confirmacao", est, c, L(["CONFIRMACAO"]), [avanca_para(*destino[est]), nao_mexeu_em()])

    # 6. Objeção, adiamento ou conversa nas etapas de confirmação: nunca avança
    for est in ESTADOS_CONFIRMACAO:
        for m, ev in NAO_CONFIRMA:
            if est == "termos" and ev == ["NEGACAO"]:
                # Recusar os termos encaminha para um humano (FLUXO_SOFIA.md)
                yield ("nao_confirma", est, m, L(ev), [fase_e("transferido"), nao_mexeu_em()])
                continue
            yield ("nao_confirma", est, m, L(ev), [nao_avanca(), nao_mexeu_em()])

    # 7. Conversa quando a Eva pediu um dado: nada é gravado, não avança
    for est in ESTADOS_CADASTRO:
        for m, ev in CONVERSA:
            yield ("conversa", est, m, L(ev, pergunta=m if "PERGUNTA" in ev else ""),
                   [nao_mexeu_em(), nao_avanca(), fica_na_fase()])

    # 8. Escolha de plano: fica o plano que o cliente falou
    for est in ("vendas/confirmacao_plano", "vendas/escolha_plano"):
        for m, ref, esperado in ESCOLHAS_PLANO:
            yield ("plano", est, m, L(["PLANO_INFORMADO"], {"plano": ref}),
                   [plano_e(esperado), nao_confirma_outro_plano(esperado), nao_mexeu_em()])
    for m in MESMO_PLANO:
        yield ("plano", "vendas/confirmacao_plano", m, L(["PLANO_INFORMADO"], {"plano": "super+"}),
               [plano_e("MOV SUPER+"), nao_mexeu_em()])
    # troca de plano no meio do cadastro
    for m, ref, esperado in ESCOLHAS_PLANO[:6]:
        yield ("plano", "cad/email", m, L(["PLANO_INFORMADO"], {"plano": ref}),
               [plano_e(esperado), nao_mexeu_em()])

    # 9. Correções
    for m, campo, valor, esperado in CORRECOES:
        yield ("correcao", "cad/confirmacao_dados", m, L(["CORRECAO_DADO"], {campo: valor}, corrigidos=[campo]),
               [gravou(**{campo: esperado}), fase_e("cadastro"), nao_avanca(), so_mexeu_em(campo)])
        if campo in {"nome", "email"}:
            yield ("correcao", "cad/data_nascimento", m, L(["CORRECAO_DADO"], {campo: valor}, corrigidos=[campo]),
                   [gravou(**{campo: esperado}), fase_e("cadastro"), so_mexeu_em(campo)])

    # 10. Localização
    for est, m, dados, esperado in LOCALIZACOES:
        checks = [gravou(**esperado), nao_mexeu_em(*ORDEM)]
        if len(esperado) == 2:
            checks.append(avanca_para("vendas"))
        yield ("localizacao", est, m, L(["LOCALIZACAO_INFORMADA"], dados), checks)

    # 11. Pedir humano e encerrar, em qualquer etapa
    for est in TODOS:
        for m in HUMANO:
            yield ("humano", est, m, L(["PEDIU_HUMANO"]), [fase_e("transferido"), nao_mexeu_em()])
    for est in [e for e in TODOS if e != "pos"]:
        for m in ENCERRAR:
            yield ("encerrar", est, m, L(["NEGACAO"]), [fase_e("finalizado"), nao_mexeu_em()])

    # 12. Horário
    for m, slot in HORARIOS:
        yield ("horario", "agenda/escolha_horario", m, L(["DADO_INFORMADO"], {"turno_escolhido": slot}),
               [lambda a, d, dec, i, msg, s=slot: None if d.get("horario_escolhido") == s else f"horário esperado {s}, ficou {d.get('horario_escolhido')!r} ({dec.objetivo_resposta})",
                fase_e("agendamento")])


def plano_nao_muda() -> Check:
    def f(a, d, dec, i, msg):
        for k in ("plano_em_negociacao", "plano_confirmado"):
            if (d.get(k) or None) != (a.get(k) or None):
                return f"{k} mudou: {a.get(k)!r} → {d.get(k)!r}"
        return None
    return f


def plano_confirmado_nao_muda() -> Check:
    """Dúvida sobre plano no cadastro: informa, sem trocar o plano nem propor troca."""
    def f(a, d, dec, i, msg):
        if (d.get("plano_confirmado") or None) != (a.get("plano_confirmado") or None):
            return f"plano_confirmado mudou: {a.get('plano_confirmado')!r} → {d.get('plano_confirmado')!r}"
        if "TROCA" in str(dec.objetivo_resposta or ""):
            return f"tratou a dúvida como pedido de troca de plano ({dec.objetivo_resposta})"
        return None
    return f


def nao_marca(*flags: str) -> Check:
    def f(a, d, dec, i, msg):
        for flag in flags:
            if d.get(flag) and not a.get(flag):
                return f"marcou {flag}={d.get(flag)!r}"
        return None
    return f


PERGUNTAS_SOBRE_PLANO = [
    "o que tem nesse plano?", "qual a velocidade desse?", "esse tem mesh?", "tem disney nesse?",
    "quantos megas são?", "qual a diferença pro infinity?", "o infinity tem o que?", "e o one+ é quanto?",
    "quanto custa o infinity?", "esse é o mais barato?", "tem fidelidade nesse plano?", "o roteador vem junto?",
    "o que é ubook?", "esse desconto é pra sempre?", "depois dos 3 meses fica quanto?",
]
PEDIDOS_DE_OPCOES = [
    ("tem outro?", ["PEDIU_TROCAR_PLANO"]), ("tem mais barato?", ["PEDIU_TROCAR_PLANO", "PERGUNTA"]),
    ("mostra todos os planos", ["PEDIU_TROCAR_PLANO"]), ("quais os planos que vocês tem?", ["PERGUNTA"]),
    ("tem plano com desconto?", ["PERGUNTA"]), ("queria ver outras opções", ["PEDIU_TROCAR_PLANO"]),
    ("esse não, tem outro?", ["NEGACAO", "PEDIU_TROCAR_PLANO"]), ("tem um mais completo?", ["PEDIU_TROCAR_PLANO", "PERGUNTA"]),
]
DUAS_INTENCOES = [
    # (estado, mensagem, llm, checagens)
    ("vendas/confirmacao_plano", "sim, meu nome é João Pedro Alves", L(["CONFIRMACAO", "DADO_INFORMADO"], {"nome": "João Pedro Alves"}),
     [avanca_para("cadastro"), gravou(nome="João Pedro Alves"), nao_pede_de_novo("nome")]),
    ("vendas/confirmacao_plano", "pode ser, Edrei Maciel", L(["CONFIRMACAO", "DADO_INFORMADO"], {"nome": "Edrei Maciel"}),
     [avanca_para("cadastro"), gravou(nome="Edrei Maciel"), nao_pede_de_novo("nome")]),
    ("vendas/confirmacao_plano", "quero o infinity, tem fidelidade?", L(["PLANO_INFORMADO", "PERGUNTA"], {"plano": "infinity"}, pergunta="tem fidelidade?"),
     [nao_confirma_outro_plano("MOV INFINITY"), nao_mexeu_em()]),
    ("vendas/confirmacao_plano", "sim, mas tem multa se eu cancelar?", L(["CONFIRMACAO", "PERGUNTA"], pergunta="tem multa se eu cancelar?"),
     [nao_mexeu_em(), fase_e("cadastro")]),
    ("cad/nome", "boa tarde\nmeu nome é João Pedro Alves", L(["SAUDACAO", "DADO_INFORMADO"], {"nome": "João Pedro Alves"}),
     [gravou(nome="João Pedro Alves"), nao_pede_de_novo("nome"), fase_e("cadastro")]),
    ("cad/cpf", "oi, meu cpf é 604.210.790-96", L(["SAUDACAO", "DADO_INFORMADO"], {"cpf": "60421079096"}),
     [gravou(cpf="60421079096"), nao_pede_de_novo("cpf"), fase_e("cadastro")]),
    ("cad/email", "é edrei@gmail.com, obrigado", L(["DADO_INFORMADO", "CONVERSA_SOCIAL"], {"email": "edrei@gmail.com"}),
     [gravou(email="edrei@gmail.com"), nao_pede_de_novo("email"), fase_e("cadastro")]),
    ("cad/telefone", "93992219098 pode ligar nesse", L(["DADO_INFORMADO"], {"telefone": "93992219098"}),
     [gravou(telefone="93992219098"), nao_pede_de_novo("telefone"), fase_e("cadastro")]),
    ("cad/cep", "68020000, é perto do aeroporto", L(["DADO_INFORMADO"], {"cep": "68020000"}),
     [gravou(cep="68020000"), nao_pede_de_novo("cep"), fase_e("cadastro")]),
    ("cad/rua", "Rua das Flores, 123, casa dos fundos", L(["DADO_INFORMADO"], {"rua": "Rua das Flores", "numero": "123", "complemento": "casa dos fundos"}),
     [gravou(rua="Rua das Flores", numero="123"), nao_pede_de_novo("rua"), nao_pede_de_novo("numero")]),
    ("cad/email", "errei meu nome, é João Carlos Silva. meu email é joao@gmail.com", L(["CORRECAO_DADO", "DADO_INFORMADO"], {"nome": "João Carlos Silva", "email": "joao@gmail.com"}, corrigidos=["nome"]),
     [gravou(nome="João Carlos Silva", email="joao@gmail.com"), nao_pede_de_novo("email")]),
    ("cad/confirmacao_dados", "tá tudo certo, só o número que é 892", L(["CORRECAO_DADO"], {"numero": "892"}, corrigidos=["numero"]),
     [gravou(numero="892"), nao_avanca(), fase_e("cadastro")]),
    ("cad/confirmacao_dados", "sim, mas o email é joao2@gmail.com", L(["CORRECAO_DADO"], {"email": "joao2@gmail.com"}, corrigidos=["email"]),
     [gravou(email="joao2@gmail.com"), nao_avanca(), fase_e("cadastro")]),
    ("agenda/escolha_horario", "pode ser 14h, o técnico liga antes?", L(["DADO_INFORMADO", "PERGUNTA"], {"turno_escolhido": "14h às 15h"}, pergunta="o técnico liga antes?"),
     [fase_e("agendamento"), nao_marca("agendamento_confirmado")]),
]
DADOS_INVALIDOS = [
    # (estado, mensagem, dados do LLM, campo que NÃO pode ficar gravado)
    ("cad/cpf", "123.456.789-00", {"cpf": "12345678900"}, "cpf"),
    ("cad/cpf", "111.111.111-11", {"cpf": "11111111111"}, "cpf"),
    ("cad/cpf", "6042107909", {"cpf": "6042107909"}, "cpf"),
    ("cad/email", "edrei@gmail", {"email": "edrei@gmail"}, "email"),
    ("cad/email", "edrei.gmail.com", {"email": "edrei.gmail.com"}, "email"),
    ("cad/telefone", "99221-9098", {"telefone": "992219098"}, "telefone"),
    ("cad/cep", "6802000", {"cep": "6802000"}, "cep"),
    ("cad/data_nascimento", "16/08", {"data_nascimento": "16/08"}, "data_nascimento"),
    ("cad/nome", "Edrei", {"nome": "Edrei"}, "nome"),
]
AGENDA_NAO_CONFIRMA = [
    ("não posso amanhã", ["NEGACAO"]), ("tem outro dia?", ["NEGACAO", "PERGUNTA"]), ("pode ser sábado?", ["PERGUNTA"]),
    ("só posso depois das 18", ["NEGACAO"]), ("qualquer horário serve?", ["PERGUNTA"]), ("vou ver com meu chefe", ["OUTRO"]),
    ("amanhã não vou estar em casa", ["NEGACAO"]), ("tem como ser semana que vem?", ["PERGUNTA"]),
]
TYPOS_CONFIRMA = ["simm", "siim", "sim!!", "SIM", "Sim.", "okk", "okay", "blz", "ta bom", "tabom", "isso msm", "pode ser sim", "sim sim sim", "👍", "✅"]
TYPOS_NEGA = [("nn", ["NEGACAO"]), ("nao", ["NEGACAO"]), ("NÃO", ["NEGACAO"]), ("naum", ["NEGACAO"]), ("não não", ["NEGACAO"]), ("👎", ["NEGACAO"])]
FORA_DE_HORA = [
    # dado de cadastro mandado antes da hora, na confirmação do plano: não confirma o plano por tabela
    ("vendas/confirmacao_plano", "604.210.790-96", L(["DADO_INFORMADO"], {"cpf": "60421079096"})),
    ("vendas/confirmacao_plano", "edrei@gmail.com", L(["DADO_INFORMADO"], {"email": "edrei@gmail.com"})),
    ("vendas/confirmacao_plano", "93992219098", L(["DADO_INFORMADO"], {"telefone": "93992219098"})),
    ("vendas/escolha_plano", "Rua das Flores, 123", L(["DADO_INFORMADO"], {"rua": "Rua das Flores", "numero": "123"})),
]
POS_VENDA = [
    ("não, só isso", ["NEGACAO"], "finalizado"), ("não, obrigado", ["NEGACAO"], "finalizado"), ("tudo certo", ["CONFIRMACAO"], "finalizado"),
    ("sem dúvidas", ["NEGACAO"], "finalizado"), ("era só isso mesmo", ["NEGACAO"], "finalizado"),
    ("o técnico leva o roteador?", ["PERGUNTA"], "pos_venda"), ("posso mudar o horário depois?", ["PERGUNTA"], "pos_venda"),
    ("como pago a primeira fatura?", ["PERGUNTA"], "pos_venda"), ("tenho sim, quanto tempo dura a instalação?", ["PERGUNTA"], "pos_venda"),
    ("sim", ["CONFIRMACAO"], "pos_venda"), ("tenho uma dúvida", ["OUTRO"], "pos_venda"),
]


def casos_rodada_2() -> Iterator[Caso]:
    # 13. Dúvida sobre plano durante a venda: não confirma nem troca de plano
    for est in ("vendas/confirmacao_plano", "vendas/escolha_plano"):
        for p in PERGUNTAS_SOBRE_PLANO:
            yield ("duvida_plano", est, p, L(["PERGUNTA"], pergunta=p),
                   [nao_mexeu_em(), fase_e("vendas"), nao_marca("plano_confirmado")])
        for m, ev in PEDIDOS_DE_OPCOES:
            yield ("opcoes_plano", est, m, L(ev, pergunta=m if "PERGUNTA" in ev else ""),
                   [nao_mexeu_em(), fase_e("vendas"), nao_marca("plano_confirmado")])
    # no cadastro, a dúvida sobre o plano não troca o plano confirmado nem sai do cadastro
    for est in ("cad/cpf", "cad/rua", "cad/confirmacao_dados"):
        for p in PERGUNTAS_SOBRE_PLANO:
            yield ("duvida_plano", est, p, L(["PERGUNTA"], pergunta=p),
                   [nao_mexeu_em(), plano_confirmado_nao_muda(), fase_e("cadastro"), nao_marca("ixc_cliente_id")])

    # 14. Duas intenções na mesma mensagem
    for est, m, llm, checks in DUAS_INTENCOES:
        yield ("duas_intencoes", est, m, llm, checks)

    # 15. Dado inválido: pede de novo, não grava nem valida
    for est, m, dados, campo in DADOS_INVALIDOS:
        yield ("dado_invalido", est, m, L(["DADO_INFORMADO"], dados),
               [lambda a, d, dec, i, msg, c=campo: None if not d.get(c) or (c == "cpf" and not d.get("documento_cpf_validado")) else f"gravou {c} inválido: {d.get(c)!r}",
                lambda a, d, dec, i, msg, c=campo: None if dec.aguardando == c else f"deveria continuar pedindo {c}, foi para {dec.aguardando}",
                fase_e("cadastro")])

    # 16. Agendamento: indisponibilidade ou dúvida não confirma horário
    for est in ("agenda/escolha_horario", "agenda/confirmacao_horario"):
        for m, ev in AGENDA_NAO_CONFIRMA:
            yield ("agenda", est, m, L(ev, pergunta=m if "PERGUNTA" in ev else ""),
                   [nao_marca("agendamento_confirmado"), nao_mexeu_em(),
                    lambda a, d, dec, i, msg: None if dec.fase in {"agendamento", "transferido"} else f"foi para {dec.fase} ({dec.objetivo_resposta})"])

    # 17. Confirmações e negações com erro de digitação / emoji
    destino = {"vendas/confirmacao_plano": "cadastro", "cad/confirmacao_dados": "termos",
               "agenda/confirmacao_horario": "pos_venda", "termos": "agendamento"}
    for est, fase_ok in destino.items():
        for m in TYPOS_CONFIRMA:
            yield ("typo", est, m, L(["CONFIRMACAO"]), [fase_e(fase_ok), nao_mexeu_em()])
        for m, ev in TYPOS_NEGA:
            if est == "termos":
                continue
            yield ("typo", est, m, L(ev), [nao_avanca(), nao_mexeu_em()])

    # 18. Dado de cadastro mandado antes da hora
    for est, m, llm in FORA_DE_HORA:
        yield ("antes_da_hora", est, m, llm, [nao_marca("plano_confirmado", "ixc_cliente_id"), fase_e("vendas")])

    # 19. Pós-venda
    for m, ev, fase_ok in POS_VENDA:
        yield ("pos_venda", "pos", m, L(ev, pergunta=m if "PERGUNTA" in ev else ""), [fase_e(fase_ok), nao_mexeu_em()])


def todos_os_casos() -> Iterator[Caso]:
    yield from casos()
    yield from casos_rodada_2()


# ── Conversas completas ──────────────────────────────────────────────────────
# (mensagem, interpretação correta, {fase/aguardando esperados depois do turno})

CONVERSAS: dict[str, dict[str, Any]] = {
    "direta": {
        "passos": [
            ("oi", L(["SAUDACAO"]), {"fase": "viabilidade"}),
            ("Santarém, Diamantino", L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém", "bairro": "Diamantino"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
            ("sim", L(["CONFIRMACAO"]), {"fase": "cadastro", "aguardando": "nome"}),
            ("Edrei Maciel, 604.210.790-96", L(["DADO_INFORMADO"], {"nome": "Edrei Maciel", "cpf": "60421079096"}), {"aguardando": "email"}),
            ("edrei@gmail.com 93992219098", L(["DADO_INFORMADO"], {"email": "edrei@gmail.com", "telefone": "93992219098"}), {"aguardando": "data_nascimento"}),
            ("16/08/2000 68020000", L(["DADO_INFORMADO"], {"data_nascimento": "16/08/2000", "cep": "68020000"}), {"aguardando": "rua"}),
            ("Rua das Flores, 123", L(["DADO_INFORMADO"], {"rua": "Rua das Flores", "numero": "123"}), {"aguardando": "confirmacao_dados"}),
            ("sim", L(["CONFIRMACAO"]), {"fase": "termos", "aguardando": "aceite_termos"}),
            ("aceito", L(["CONFIRMACAO"]), {"fase": "agendamento", "aguardando": "escolha_horario"}),
            ("14h", L(["DADO_INFORMADO"], {"turno_escolhido": "14h às 15h"}), {"aguardando": "confirmacao_horario"}),
            ("sim", L(["CONFIRMACAO"]), {"fase": "pos_venda"}),
            ("não, obrigado", L(["NEGACAO"]), {"fase": "finalizado"}),
        ],
        "final": {"nome": "Edrei Maciel", "cpf": "60421079096", "email": "edrei@gmail.com", "telefone": "93992219098",
                  "data_nascimento": "16/08/2000", "cep": "68020000", "rua": "Rua das Flores", "numero": "123",
                  "horario_escolhido": "14h às 15h", "fase": "finalizado"},
    },
    "atendimento real de 07/10": {
        "passos": [
            ("Opa tudo bem com você?", L(["SAUDACAO"]), {"fase": "viabilidade"}),
            ("Quero ver os planos ai\nAqui em santarém", L(["PEDIDO_CONTRATACAO", "LOCALIZACAO_INFORMADA"], {"cidade": "Santarém"}), {"fase": "viabilidade"}),
            ("Diamantino", L(["LOCALIZACAO_INFORMADA"], {"bairro": "Diamantino"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
            ("Beleza, eu queria o que tem disney", L(["PEDIU_TROCAR_PLANO"], pergunta="qual plano tem disney?"), {"fase": "vendas"}),
            ("Pode ser o infinity", L(["PLANO_INFORMADO"], {"plano": "infinity"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
            ("sim", L(["CONFIRMACAO"]), {"fase": "cadastro", "aguardando": "nome"}),
            ("Edrei testes, 604.210.790-96", L(["DADO_INFORMADO"], {"nome": "Edrei testes", "cpf": "60421079096"}), {"aguardando": "email"}),
            ("edreitestes@gmail.com", L(["DADO_INFORMADO"], {"email": "edreitestes@gmail.com"}), {"aguardando": "telefone"}),
            ("93992219098", L(["DADO_INFORMADO"], {"telefone": "93992219098"}), {"aguardando": "data_nascimento"}),
            ("16 de agosto de 2000\n68020000", L(["DADO_INFORMADO"], {"data_nascimento": "16/08/2000", "cep": "68020000"}), {"aguardando": "rua"}),
            ("Ségio henn, 891\né um condomínio", L(["DADO_INFORMADO"], {"rua": "Ségio henn", "numero": "891", "complemento": "condomínio"}), {"aguardando": "confirmacao_dados"}),
            ("Bairro é o aparecida na verdade", L(["CORRECAO_DADO"], {"bairro": "Aparecida"}, corrigidos=["bairro"]), {"fase": "cadastro", "aguardando": "confirmacao_dados"}),
            ("Certo", L(["CONFIRMACAO"]), {"fase": "termos"}),
            ("Sim", L(["CONFIRMACAO"]), {"fase": "agendamento", "aguardando": "escolha_horario"}),
            ("8", L(["DADO_INFORMADO"], {"turno_escolhido": "8h às 9h"}), {"aguardando": "confirmacao_horario"}),
            ("Sim", L(["CONFIRMACAO"]), {"fase": "pos_venda"}),
            ("Tudo certo", L(["CONFIRMACAO"]), {"fase": "finalizado"}),
            ("Obrigado", L(["CONVERSA_SOCIAL"]), {"fase": "finalizado"}),
        ],
        "final": {"plano_confirmado": "MOV INFINITY", "nome": "Edrei testes", "cpf": "60421079096",
                  "email": "edreitestes@gmail.com", "telefone": "93992219098", "data_nascimento": "16/08/2000",
                  "cep": "68020000", "rua": "Ségio henn", "numero": "891", "bairro": "Aparecida",
                  "horario_escolhido": "8h às 9h", "fase": "finalizado"},
    },
    "cliente com dúvidas, objeções e correções": {
        "passos": [
            ("boa noite", L(["SAUDACAO"]), {"fase": "viabilidade"}),
            ("tem internet no diamantino?", L(["PERGUNTA", "LOCALIZACAO_INFORMADA"], {"bairro": "Diamantino"}, pergunta="tem internet no diamantino?"), {"fase": "viabilidade"}),
            ("santarém", L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
            ("tá caro", L(["OUTRO"]), {"fase": "vendas"}),
            ("tem mais barato?", L(["PEDIU_TROCAR_PLANO", "PERGUNTA"], pergunta="tem mais barato?"), {"fase": "vendas"}),
            ("quero o flex", L(["PLANO_INFORMADO"], {"plano": "flex"}), {"fase": "cadastro", "aguardando": "nome"}),
            ("pra que precisa do cpf?", L(["PERGUNTA"], pergunta="pra que precisa do cpf?"), {"fase": "cadastro", "aguardando": "nome"}),
            ("João Pedro Alves", L(["DADO_INFORMADO"], {"nome": "João Pedro Alves"}), {"aguardando": "cpf"}),
            ("tem multa se cancelar?", L(["PERGUNTA"], pergunta="tem multa se cancelar?"), {"aguardando": "cpf"}),
            ("529.982.247-25", L(["DADO_INFORMADO"], {"cpf": "52998224725"}), {"aguardando": "email"}),
            ("93991112222", L(["DADO_INFORMADO"], {"telefone": "93991112222"}), {"aguardando": "email"}),
            ("joao@gmail.com", L(["DADO_INFORMADO"], {"email": "joao@gmail.com"}), {"aguardando": "data_nascimento"}),
            ("1 de março de 1985", L(["DADO_INFORMADO"], {"data_nascimento": "01/03/1985"}), {"aguardando": "cep"}),
            ("não sei o cep", L(["OUTRO"]), {"aguardando": "cep"}),
            ("68005120", L(["DADO_INFORMADO"], {"cep": "68005120"}), {"aguardando": "rua"}),
            ("Av. Mendonça Furtado, 2040", L(["DADO_INFORMADO"], {"rua": "Av. Mendonça Furtado", "numero": "2040"}), {"aguardando": "confirmacao_dados"}),
            ("o email tá errado, é joao.alves@gmail.com", L(["CORRECAO_DADO"], {"email": "joao.alves@gmail.com"}, corrigidos=["email"]), {"fase": "cadastro", "aguardando": "confirmacao_dados"}),
            ("agora sim", L(["CONFIRMACAO"]), {"fase": "termos"}),
            ("e se eu mudar de endereço?", L(["PERGUNTA"], pergunta="e se eu mudar de endereço?"), {"fase": "termos", "aguardando": "aceite_termos"}),
            ("aceito", L(["CONFIRMACAO"]), {"fase": "agendamento", "aguardando": "escolha_horario"}),
            ("pode ser às 9", L(["DADO_INFORMADO"], {"turno_escolhido": "9h às 10h"}), {"aguardando": "confirmacao_horario"}),
            ("isso", L(["CONFIRMACAO"]), {"fase": "pos_venda"}),
            ("o técnico leva o roteador?", L(["PERGUNTA"], pergunta="o técnico leva o roteador?"), {"fase": "pos_venda"}),
            ("não, só isso", L(["NEGACAO"]), {"fase": "finalizado"}),
        ],
        "final": {"plano_confirmado": "MOV FLEX", "nome": "João Pedro Alves", "cpf": "52998224725",
                  "email": "joao.alves@gmail.com", "telefone": "93991112222", "data_nascimento": "01/03/1985",
                  "cep": "68005120", "rua": "Mendonça Furtado", "numero": "2040", "horario_escolhido": "9h às 10h",
                  "fase": "finalizado"},
    },
    # Nome de lugar solto: nunca vira cidade se não for cidade atendida — a Eva pergunta
    "bairro desconhecido, confirmado em duas mensagens": {
        "passos": [
            ("Maracanã", L(["LOCALIZACAO_INFORMADA"], {"cidade": "Maracanã"}), {"fase": "viabilidade", "aguardando": "confirmar_local"}),
            ("sim", L(["CONFIRMACAO"]), {"fase": "viabilidade", "aguardando": "localizacao"}),
            ("Santarém", L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
        ],
        "final": {"cidade": "Santarém", "bairro": "Maracanã"},
    },
    "bairro desconhecido, confirmado já com a cidade": {
        "passos": [
            ("moro no maracanã", L(["LOCALIZACAO_INFORMADA"], {"bairro": "Maracanã"}), {"fase": "viabilidade", "aguardando": "confirmar_local"}),
            ("sim, santarém", L(["CONFIRMACAO", "LOCALIZACAO_INFORMADA"], {"cidade": "Santarém"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
        ],
        "final": {"cidade": "Santarém", "bairro": "Maracanã"},
    },
    "lugar solto era uma cidade fora da área": {
        "passos": [
            ("Óbidos", L(["LOCALIZACAO_INFORMADA"], {"cidade": "Óbidos"}), {"fase": "viabilidade", "aguardando": "confirmar_local"}),
            ("não, é a cidade", L(["NEGACAO"]), {"fase": "sem_cobertura"}),
        ],
        "final": {"cidade": "Óbidos", "fase": "sem_cobertura"},
    },
    "bairro conhecido não precisa de confirmação": {
        "passos": [
            ("Aqui no diamantino", L(["LOCALIZACAO_INFORMADA"], {"bairro": "Diamantino"}), {"fase": "viabilidade", "aguardando": "localizacao"}),
            ("Santarém", L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
        ],
        "final": {"cidade": "Santarém", "bairro": "Diamantino"},
    },
    "cidade atendida e depois o bairro, mesmo desconhecido": {
        "passos": [
            ("Santarém", L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém"}), {"fase": "viabilidade", "aguardando": "localizacao"}),
            ("Maracanã", L(["LOCALIZACAO_INFORMADA"], {"bairro": "Maracanã"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
        ],
        "final": {"cidade": "Santarém", "bairro": "Maracanã"},
    },
    "tudo numa mensagem só": {
        "passos": [
            ("oi, quero internet em santarém no diamantino", L(["SAUDACAO", "PEDIDO_CONTRATACAO", "LOCALIZACAO_INFORMADA"], {"cidade": "Santarém", "bairro": "Diamantino"}), {"fase": "vendas", "aguardando": "confirmacao_plano"}),
            ("pode ser", L(["CONFIRMACAO"]), {"fase": "cadastro", "aguardando": "nome"}),
            ("Maria Souza, cpf 529.982.247-25, maria@gmail.com, 93991112222",
             L(["DADO_INFORMADO"], {"nome": "Maria Souza", "cpf": "52998224725", "email": "maria@gmail.com", "telefone": "93991112222"}),
             {"fase": "cadastro", "aguardando": "data_nascimento"}),
            ("5/7/1992, cep 68005-120, Rua Rui Barbosa 77",
             L(["DADO_INFORMADO"], {"data_nascimento": "05/07/1992", "cep": "68005120", "rua": "Rua Rui Barbosa", "numero": "77"}),
             {"fase": "cadastro", "aguardando": "confirmacao_dados"}),
        ],
        "final": {"nome": "Maria Souza", "cpf": "52998224725", "email": "maria@gmail.com", "telefone": "93991112222",
                  "data_nascimento": "05/07/1992", "cep": "68005120", "rua": "Rui Barbosa", "numero": "77"},
    },
}


def auditar_conversas() -> list[str]:
    erros: list[str] = []
    for nome, conversa in CONVERSAS.items():
        estado: dict[str, Any] = {"id_cliente": "auditoria", "fase": "inicio"}
        for n, (msg, llm, esperado) in enumerate(conversa["passos"], 1):
            try:
                estado, dec, _ = turno(estado, msg, llm)
                if dec.acao != "AGUARDAR":
                    texto_da_eva(dec, estado, msg)
            except Exception as e:  # noqa: BLE001
                erros.append(f"[{nome}] passo {n} {msg!r}: EXCEÇÃO {type(e).__name__}: {e}")
                break
            falhou = False
            for chave, valor in esperado.items():
                obtido = dec.fase if chave == "fase" else dec.aguardando
                if obtido != valor:
                    erros.append(
                        f"[{nome}] passo {n} {msg!r}: {chave} esperado {valor!r}, veio {obtido!r} ({dec.objetivo_resposta})"
                    )
                    falhou = True
            # nunca pedir de novo um campo que acabou de ser informado e gravado
            for campo in llm["dados"]:
                if campo in ORDEM and dec.aguardando == campo and _igual(campo, llm["dados"][campo], estado.get(campo)):
                    erros.append(f"[{nome}] passo {n} {msg!r}: gravou {campo} e pediu de novo")
                    falhou = True
            if falhou:
                break  # os passos seguintes dependem deste
        else:
            for campo, valor in conversa["final"].items():
                if campo in {"fase", "plano_confirmado", "horario_escolhido"}:
                    ok = str(estado.get(campo) or "").casefold() == valor.casefold()
                else:
                    ok = _igual(campo, valor, estado.get(campo))
                if not ok:
                    erros.append(f"[{nome}] no fim, {campo} deveria ser {valor!r} e ficou {estado.get(campo)!r}")
    return erros


def _texto_sem_erro(a, d, dec, i, msg):
    if dec.acao == "AGUARDAR":
        return None
    try:
        texto_da_eva(dec, d, msg)
    except Exception as e:  # noqa: BLE001
        return f"erro ao montar a resposta: {type(e).__name__}: {e}"
    return None


def auditar() -> tuple[int, list[tuple[str, str, str, str]]]:
    violacoes: list[tuple[str, str, str, str]] = []
    total = 0
    for cat, est, msg, llm, checks in todos_os_casos():
        total += 1
        antes = E(est)
        try:
            depois, dec, interp = turno(antes, msg, llm)
        except Exception as e:  # noqa: BLE001
            violacoes.append((cat, est, msg, f"EXCEÇÃO {type(e).__name__}: {e}"))
            continue
        for check in [*checks, _texto_sem_erro, texto_pede_o_aguardado()]:
            erro = check(antes, depois, dec, interp, msg)
            if erro:
                violacoes.append((cat, est, msg, f"{erro}  [{dec.objetivo_resposta}]"))
                break
    return total, violacoes


def exportar(caminho: str) -> int:
    """Casos da auditoria no formato do eval_interpretador (para medir o LLM real)."""
    ultima_eva = {
        "inicio": "", "viab": "Me passa sua cidade e bairro para eu ver a cobertura?",
        "viab/tem_cidade": "Anotei Santarém. Qual o bairro?",
        "vendas/confirmacao_plano": "📦 COMBO MOV SUPER+ – R$ 139,00/mês\n✅ Repetidor Mesh\n\nEsse plano te atende? Quer fechar com ele ou tem outra preferência?",
        "vendas/escolha_plano": "📦 Opção 1 — MOV FLEX — R$ 119/mês\n\n📦 Opção 2 — MOV SUPER+ — R$ 139/mês\n\n📦 Opção 3 — MOV INFINITY — R$ 189/mês\n\nQual desses você prefere? Pode falar o nome ou o valor.",
        "cad/confirmacao_dados": "📋 Confira seus dados cadastrais\n\n👤 Nome: João Silva\n🪪 CPF: 123.456.789-09\n\n✅ Está tudo correto?",
        "termos": "Te enviei o áudio e o PDF do termo de fidelidade. Você aceita os termos pra gente seguir?",
        "agenda/escolha_horario": "📅 Horários para 08/10/2026:\n🌅 Manhã\n• 8h às 9h\n• 9h às 10h\n• 10h às 11h\n🌇 Tarde\n• 14h às 15h\n• 15h às 16h\n\nQual horário você prefere?",
        "agenda/confirmacao_horario": "Perfeito! Anotei 14h às 15h no dia 08/10/2026.\n\nPosso confirmar esse agendamento?",
        "pos": "✅ Agendamento confirmado!\n\nAntes de encerrar, tem mais alguma dúvida?",
    }
    for c in ORDEM:
        ultima_eva[f"cad/{c}"] = f"Me informa {ROTULO[c]}, por favor."
    from app.interpreter import snapshot_estado

    linhas: list[str] = []
    vistos: set[tuple[str, str]] = set()
    # O que a interpretação do LLM precisa trazer (o resto é detalhe de classificação)
    sempre = {"DADO_INFORMADO", "PLANO_INFORMADO", "LOCALIZACAO_INFORMADA", "PEDIU_HUMANO", "CORRECAO_DADO"}
    campos_dado = set(ORDEM) | {"cidade", "bairro"}
    for n, (cat, est, msg, llm, _) in enumerate(todos_os_casos(), 1):
        if (est, msg) in vistos:
            continue
        vistos.add((est, msg))
        exigidos = [e for e in llm["eventos"] if e in sempre]
        if cat in {"confirmacao", "typo"} and "CONFIRMACAO" in llm["eventos"]:
            exigidos.append("CONFIRMACAO")
        if cat in {"duvida", "duvida_plano"}:
            exigidos.append("PERGUNTA")
        esperado: dict[str, Any] = {"eventos": exigidos}
        dados = {k: v for k, v in llm["dados"].items() if k in campos_dado}
        if dados and cat != "dado_invalido":
            esperado["dados"] = dados
        esperado["dados_vazios"] = [c for c in ("nome", "cpf", "email", "telefone", "rua") if c not in llm["dados"]]
        if "CONFIRMACAO" not in llm["eventos"]:
            esperado["eventos_proibidos"] = ["CONFIRMACAO"]
        hist = [{"remetente": "eva", "mensagem": ultima_eva[est]}] if ultima_eva.get(est) else []
        linhas.append(json.dumps({
            "id": f"aud-{cat}-{n}", "estado": snapshot_estado(E(est)), "historico": hist,
            "mensagem": msg, "esperado": esperado,
        }, ensure_ascii=False))
    # Embaralhado (sempre igual) para que --limite pegue uma amostra de todas as categorias
    import random

    random.Random(7).shuffle(linhas)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    return len(linhas)


def main() -> None:
    if "--exportar" in sys.argv:
        destino = os.path.join(BACKEND, "eval", "casos_auditoria.jsonl")
        print(f"{exportar(destino)} casos exportados para {destino}")
        return
    total, violacoes = auditar()
    por_cat = Counter(v[0] for v in violacoes)
    casos_por_cat = Counter(c[0] for c in todos_os_casos())
    for cat in casos_por_cat:
        marca = "OK    " if not por_cat[cat] else "FALHOU"
        print(f"  {marca} {cat:<14} {casos_por_cat[cat] - por_cat[cat]}/{casos_por_cat[cat]}")
    if "--resumo" not in sys.argv:
        for cat, est, msg, erro in violacoes:
            print(f"  ✗ [{cat}] {est:<27} {msg!r}: {erro}")
    erros_conversas = auditar_conversas()
    marca = "OK    " if not erros_conversas else "FALHOU"
    print(f"  {marca} conversas      {len(CONVERSAS)} completas, do 'oi' ao encerramento")
    for e in erros_conversas:
        print(f"  ✗ {e}")
    if violacoes or erros_conversas:
        print(f"\n❌ {len(violacoes) + len(erros_conversas)} violação(ões) em {total} casos e {len(CONVERSAS)} conversas")
        sys.exit(1)
    print(f"\n✅ Auditoria de interpretação OK ({total} casos e {len(CONVERSAS)} conversas completas)")


if __name__ == "__main__":
    main()
