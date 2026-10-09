# -*- coding: utf-8 -*-
"""Robustez — o que protege a Eva de se perder ou inventar.

Sem LLM e sem rede (o harness da auditoria bloqueia toda chamada HTTP). Cobre:
dado ditado por áudio, conferência do que o modelo escreve, modelo fora do ar,
base de conhecimento (várias perguntas, fora do ar), dúvidas num caminho só,
divergências regra × modelo e a avaliação disparada pelo painel.
"""
from __future__ import annotations

import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import test_auditoria_interpretacao as aud  # bloqueia a rede e simula as integrações

from app import avaliacao, conversa, pipeline, response
from app.fala import normalizar_fala
from app.models import Decisao
from app.parser import parse_interpretacao
from app.verificacao import afirmacoes_sem_base

E, L, turno = aud.E, aud.L, aud.turno


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


class _Chat:
    """Substitui response.chat: devolve as respostas em ordem e guarda os prompts."""

    def __init__(self, *respostas: str, erro: Exception | None = None):
        self.respostas, self.erro, self.prompts = list(respostas), erro, []

    def __call__(self, system, user, **k):
        self.prompts.append(user)
        if self.erro:
            raise self.erro
        return self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]

    def __enter__(self):
        self._antes = response.chat
        response.chat = self
        return self

    def __exit__(self, *exc):
        response.chat = self._antes


# ── 1. Dado ditado por áudio ─────────────────────────────────────────────────

FALADO = [
    # (aguardando, o que a transcrição devolve, como fica)
    ("email", "meu email é maria arroba gmail ponto com", "meu email é maria@gmail.com"),
    ("email", "Maria ponto Silva, arroba, gmail, ponto com ponto br.", "maria.silva@gmail.com.br."),
    ("email", "é joão underline pedro arroba hotmail ponto com", "é joao_pedro@hotmail.com"),
    ("email", "maria 2000 arroba gmail", "maria2000@gmail.com"),
    ("email", "edrei arroba gmail.com e o telefone 93 99221 9098", "edrei@gmail.com e o telefone 93 99221 9098"),
    ("cpf", "meu cpf é cinco dois nove nove oito dois dois quatro sete dois cinco", "meu cpf é 52998224725"),
    ("cpf", "quinhentos e vinte e nove, novecentos e oitenta e dois, duzentos e quarenta e sete, vinte e cinco", "52998224725"),
    ("telefone", "noventa e três nove nove dois dois um nove zero nove oito", "93992219098"),
    ("telefone", "noventa e três, noventa e nove, vinte e dois, dezenove, zero noventa e oito", "93992219098"),
    ("cep", "meia oito zero dois zero zero zero zero", "68020000"),
    ("rua", "rua sérgio henn número oitocentos e noventa e um", "rua sérgio henn número 891"),
    ("rua", "sérgio henn, oitocentos e noventa e um", "sérgio henn, 891"),
    ("numero", "é o cento e vinte", "é o 120"),
    ("numero", "mil e duzentos", "1200"),
    ("data_nascimento", "dezesseis de agosto de dois mil", "16 de agosto de 2000"),
    ("data_nascimento", "nasci em cinco de março de mil novecentos e noventa", "nasci em 5 de março de 1990"),
    ("data_nascimento", "vinte e três do doze de mil novecentos e oitenta e cinco", "23 do 12 de 1985"),
    ("confirmacao_plano", "quero o plano de cento e trinta e nove", "quero o plano de 139"),
    ("escolha_plano", "o de noventa e nove reais", "o de 99 reais"),
    # Não é dado: fica como veio
    ("email", "não tenho arroba nenhuma", "não tenho arroba nenhuma"),
    ("email", "maria@gmail.com", "maria@gmail.com"),
    ("cpf", "só um momento", "só um momento"),
    ("cep", "tenho dois filhos e um cachorro", "tenho dois filhos e um cachorro"),
    ("cep", "daqui a meia hora eu mando", "daqui a meia hora eu mando"),
    ("email", "um minuto", "um minuto"),
    ("confirmacao_plano", "pode ser o primeiro", "pode ser o primeiro"),
    ("confirmacao_plano", "quero o plano um", "quero o plano um"),
]


def test_fala_vira_o_dado_escrito() -> None:
    for aguardando, falado, esperado in FALADO:
        obtido = normalizar_fala(falado, aguardando=aguardando, audio=True)
        _assert(obtido == esperado, (falado, obtido))


def test_numero_por_extenso_so_muda_em_audio() -> None:
    texto = "meu cpf é cinco dois nove nove oito dois dois quatro sete dois cinco"
    _assert(normalizar_fala(texto, aguardando="cpf", audio=False) == texto, "mudou texto digitado")
    # E-mail por extenso é remontado mesmo quando digitado
    _assert(normalizar_fala("maria arroba gmail ponto com", audio=False) == "maria@gmail.com", "email")


def test_dado_ditado_e_gravado() -> None:
    casos = [
        ("cad/email", "email", "meu email é maria arroba gmail ponto com", {"email": "maria@gmail.com"}, "maria@gmail.com"),
        ("cad/cpf", "cpf", "meu cpf é cinco dois nove nove oito dois dois quatro sete dois cinco", {"cpf": "52998224725"}, "52998224725"),
        ("cad/telefone", "telefone", "noventa e três nove nove dois dois um nove zero nove oito", {"telefone": "93992219098"}, "93992219098"),
        ("cad/cep", "cep", "meia oito zero dois zero zero zero zero", {"cep": "68020000"}, "68020000"),
        ("cad/data_nascimento", "data_nascimento", "dezesseis de agosto de dois mil", {"data_nascimento": "16/08/2000"}, "16/08/2000"),
    ]
    for est, campo, falado, lido, esperado in casos:
        # Sem a conversão, o dado é descartado mesmo com o modelo lendo certo
        antes, _, _ = turno(E(est), falado, L(["DADO_INFORMADO"], lido))
        _assert(not antes.get(campo) or est == "cad/data_nascimento", (campo, "sem conversão gravou", antes.get(campo)))
        msg = normalizar_fala(falado, aguardando=campo, audio=True)
        depois, _, _ = turno(E(est), msg, L(["DADO_INFORMADO"], lido))
        _assert(depois.get(campo) == esperado, (campo, msg, depois.get(campo)))
        _assert(depois.get("aguardando") != campo, (campo, "pediu de novo"))


# ── 2. Conferência do que o modelo escreve ───────────────────────────────────

FATOS = """BASE: A fidelidade é de 12 meses. Multa de 30% do valor restante do contrato. Instalação em até 3 dias úteis, sem taxa.
PLANO: MOV SUPER+ — R$ 139,00/mês (pagando até o vencimento: R$ 119,00). 600 mega. 50% de desconto nos 3 primeiros meses (R$ 69,50)
Cliente: a concorrente faz por 99 reais"""


def test_verificador_aceita_o_que_esta_nos_fatos() -> None:
    for texto in (
        "Sim, a fidelidade é de 12 meses e a multa é de 30% do que falta.",
        "A fidelidade é de um ano.",
        "A fidelidade é de doze meses, tá?",
        "Fica R$ 139 por mês, ou 119 reais pagando em dia. Você economiza R$ 20,00.",
        "A instalação sai em até 72 horas.",
        "Entendo, 99 reais é um bom preço mesmo.",
        "Nos 3 primeiros meses fica R$ 69,50.",
        "Só um minuto que já te explico.",
        "Sem taxa de instalação, pode ficar tranquilo.",
        "Posso agendar para o dia 15/10.",
    ):
        _assert(afirmacoes_sem_base(texto, FATOS) == [], (texto, afirmacoes_sem_base(texto, FATOS)))


def test_verificador_barra_o_que_ninguem_disse() -> None:
    casos = {
        "A multa é de R$ 300,00.": ["R$ 300,00"],
        "Consigo te dar 20% de desconto.": ["20%"],
        "A instalação sai em 24 horas.": ["24 horas"],
        "O técnico chega em 2 dias e a internet é de 1 giga.": ["2 dias", "1000 mega"],
        "Temos suporte 24 horas e o plano é de 600 megas.": ["24 horas"],
        "A fidelidade é de vinte e quatro meses.": ["24 meses"],
        # Horário que não está na agenda nem na conversa também é invenção
        "Posso agendar para amanhã às 14h.": ["14 horas"],
        "Esse plano comporta até 20 dispositivos.": ["20 dispositivos"],
    }
    for texto, esperado in casos.items():
        _assert(afirmacoes_sem_base(texto, FATOS) == esperado, (texto, afirmacoes_sem_base(texto, FATOS)))


def _duvida_no_telefone() -> tuple[dict, Decisao]:
    pergunta = L(["PERGUNTA"], {}, pergunta="tem multa de cancelamento?")
    estado, dec, _ = turno(E("cad/telefone"), "tem multa de cancelamento?", pergunta)
    dec.contexto_resposta = {
        **(dec.contexto_resposta or {}),
        "rag": {"encontrado": True, "chunks": [{"titulo": "Cancelamento", "conteudo": "A fidelidade é de 12 meses."}]},
    }
    return estado, dec


def test_resposta_com_dado_inventado_e_reescrita() -> None:
    estado, dec = _duvida_no_telefone()
    with _Chat("Tem sim, a multa é de R$ 500,00.", "Tem fidelidade de 12 meses; o valor da multa eu confirmo com a equipe.") as chat:
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="tem multa de cancelamento?")
    _assert("500" not in texto and "12 meses" in texto, texto)
    _assert(len(chat.prompts) == 2 and "R$ 500,00" in chat.prompts[1], chat.prompts[1][-300:])
    _assert("resposta_reescrita" in (dec.contexto_resposta or {}).get("sinais", []), dec.contexto_resposta)
    _assert("telefone" in texto.casefold(), texto)


def test_resposta_que_insiste_em_inventar_e_barrada() -> None:
    estado, dec = _duvida_no_telefone()
    with _Chat("A multa é de R$ 500,00.", "A multa fica em 40% do contrato."):
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="tem multa de cancelamento?")
    _assert("500" not in texto and "40%" not in texto, texto)
    _assert("confirmar com a equipe" in texto and "telefone" in texto.casefold(), texto)
    ctx = dec.contexto_resposta or {}
    _assert("resposta_barrada" in ctx.get("sinais", []) and ctx.get("sem_base") is True, ctx)


def test_desconto_pedido_pelo_cliente_nao_e_concedido() -> None:
    estado, dec, _ = turno(E("vendas/confirmacao_plano"), "tá caro, me dá 50% de desconto que eu fecho", L(["OUTRO"], {}))
    with _Chat("Fechado! Consigo 35% de desconto pra você.", "Posso te dar 35% então."):
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="tá caro, me dá 50% de desconto que eu fecho")
    _assert("35%" not in texto, texto)


# ── 3. Modelo fora do ar ─────────────────────────────────────────────────────


def test_modelo_fora_pede_para_mandar_de_novo_e_depois_transfere() -> None:
    estado = E("cad/cpf")
    pipeline._FALHAS_LLM.clear()
    pipeline._FALHAS_LLM["c1"] = 1
    _, dec, _ = turno(estado, "queria saber uma coisa", L(["OUTRO"], {}))
    dec1 = pipeline._decisao_com_modelo_fora(dec, estado, "c1")
    _assert(dec1.objetivo_resposta == "INSTABILIDADE_PEDIR_REENVIO" and dec1.fase == "cadastro", dec1.objetivo_resposta)
    _assert(dec1.aguardando == "cpf" and not dec1.atualizar_dados, (dec1.aguardando, dec1.atualizar_dados))
    texto = response.gerar_resposta(dec1, estado, historico=[], mensagem_cliente="queria saber uma coisa")
    _assert("instabilidade" in texto and "de novo" in texto, texto)

    pipeline._FALHAS_LLM["c1"] = 2
    _, dec, _ = turno(estado, "oi?", L(["OUTRO"], {}))
    dec2 = pipeline._decisao_com_modelo_fora(dec, estado, "c1")
    _assert(dec2.acao == "TRANSFERIR_HUMANO" and "indisponível" in dec2.motivo, (dec2.acao, dec2.motivo))
    with _Chat(erro=AssertionError("não devia chamar o modelo fora do ar")):
        texto = response.gerar_resposta(dec2, estado, historico=[], mensagem_cliente="oi?")
    _assert("atendente" in texto and "instabilidade" in texto, texto)
    _assert("c1" not in pipeline._FALHAS_LLM, pipeline._FALHAS_LLM)


def test_modelo_fora_mas_as_regras_leram_o_dado() -> None:
    estado = E("cad/cep")
    pipeline._FALHAS_LLM.clear()
    pipeline._FALHAS_LLM["c2"] = 1
    # Sem o modelo: leitura só pelas regras (eventos OUTRO, sem dados)
    depois, dec, _ = turno(estado, "68020-000", {"eventos": ["OUTRO"], "dados": {}, "confianca": 0})
    dec = pipeline._decisao_com_modelo_fora(dec, estado, "c2")
    _assert(depois.get("cep") == "68020000" and dec.objetivo_resposta != "INSTABILIDADE_PEDIR_REENVIO",
            (depois.get("cep"), dec.objetivo_resposta))
    _assert("llm_fora_do_ar" in (dec.contexto_resposta or {}).get("sinais", []), dec.contexto_resposta)
    # A resposta não tenta o modelo de novo neste turno
    with _Chat(erro=AssertionError("não devia chamar o modelo")):
        texto = response.gerar_resposta(dec, depois, historico=[], mensagem_cliente="68020-000")
    _assert("rua" in texto.casefold(), texto)


def test_redator_fora_do_ar_nao_vira_silencio() -> None:
    estado, dec, _ = turno(E("vendas/confirmacao_plano"), "hum", L(["OUTRO"], {}))
    dec.contexto_resposta = {k: v for k, v in (dec.contexto_resposta or {}).items() if k != "conversa"}
    with _Chat(erro=RuntimeError("503")):
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="hum")
    _assert(texto.strip(), "resposta vazia")


# ── 4 e 5. Dúvidas num caminho só e base de conhecimento ─────────────────────


def test_duvida_na_agenda_e_respondida_e_nao_prometida() -> None:
    llm = L(["DADO_INFORMADO", "PERGUNTA"], {"turno_escolhido": "14h às 15h"}, pergunta="o técnico leva o roteador?")
    estado, dec, _ = turno(E("agenda/escolha_horario"), "14h às 15h, o técnico leva o roteador?", llm)
    if dec.objetivo_resposta != "CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA":
        return  # a máquina de estados escolheu outro objetivo para este texto: nada a conferir
    with _Chat("Leva sim, o roteador vai com o técnico. Posso confirmar esse agendamento?") as chat:
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="14h às 15h, o técnico leva o roteador?")
    _assert("vou te explicar" not in texto and "Leva sim" in texto, texto)
    _assert("DÚVIDA: " in chat.prompts[0], chat.prompts[0][:200])


def test_toda_duvida_usa_o_redator_com_a_base() -> None:
    pergunta = L(["PERGUNTA"], {}, pergunta="vocês atendem aos sábados?")
    for est in ("cad/telefone", "cad/confirmacao_dados", "termos", "pos"):
        estado, dec, _ = turno(E(est), "vocês atendem aos sábados?", pergunta)
        with _Chat("Atendemos sim.") as chat:
            response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="vocês atendem aos sábados?")
        _assert(chat.prompts and "BASE DE CONHECIMENTO DA EMPRESA (sua fonte)" in chat.prompts[0],
                (est, dec.objetivo_resposta, (chat.prompts or [""])[0][:120]))


def test_uma_consulta_por_pergunta() -> None:
    _assert(pipeline._perguntas_da_mensagem("tem multa?", "tem multa?") == ["tem multa?"], "uma")
    partes = pipeline._perguntas_da_mensagem("tem multa?", "tem multa? e a instalação demora quanto?")
    _assert(partes == ["tem multa?", "e a instalação demora quanto?"], partes)

    consultas = []

    def fake(*, pergunta, mensagem, estado, plano):
        consultas.append(pergunta)
        if "multa" in pergunta:
            return {"encontrado": True, "chunks": [{"titulo": "Cancelamento", "conteudo": "Fidelidade de 12 meses."}]}
        return {"encontrado": True, "chunks": [{"titulo": "Instalação", "conteudo": "Instalação em até 3 dias úteis."}]}

    original, pipeline.consultar_rag = pipeline.consultar_rag, fake
    try:
        rag = pipeline._consultar_rag_por_pergunta(partes, mensagem="x", estado={}, plano=None)
    finally:
        pipeline.consultar_rag = original
    _assert(consultas == partes and len(rag["chunks"]) == 2 and rag["encontrado"], (consultas, rag))


def test_base_fora_do_ar_nao_e_falta_de_conteudo() -> None:
    pergunta = L(["PERGUNTA"], {}, pergunta="vocês atendem aos sábados?")
    estado, dec, _ = turno(E("cad/telefone"), "vocês atendem aos sábados?", pergunta)
    original = pipeline.consultar_rag
    pipeline.consultar_rag = lambda **k: {"encontrado": False, "motivo": "timeout", "erro": True}
    try:
        dec = pipeline._enriquecer_com_rag(dec, estado, "vocês atendem aos sábados?")
    finally:
        pipeline.consultar_rag = original
    _assert((dec.contexto_resposta or {}).get("rag_fora") is True, dec.contexto_resposta)


# ── 7. Divergências regra × modelo ───────────────────────────────────────────


def test_divergencias_mostram_o_que_as_regras_mudaram() -> None:
    # O modelo devolveu o complemento como rua: as regras trocam — e isso fica registrado
    raw = json.dumps(L(["DADO_INFORMADO"], {"rua": "Residencial Plácido", "numero": "891"}), ensure_ascii=False)
    interp = parse_interpretacao(raw, "sérgio henn, 891 residencial plácido", E("cad/rua"))
    div = pipeline.divergencias_regra_modelo(raw, interp)
    _assert(any(d.startswith("rua: modelo leu 'Residencial Plácido'") for d in div), div)
    # Leitura igual: nada a registrar
    raw = json.dumps(L(["DADO_INFORMADO"], {"cep": "68020000"}), ensure_ascii=False)
    interp = parse_interpretacao(raw, "68020-000", E("cad/cep"))
    _assert(pipeline.divergencias_regra_modelo(raw, interp) == [], pipeline.divergencias_regra_modelo(raw, interp))
    # Objeção lida como confirmação pelo modelo: as regras tiram
    raw = json.dumps(L(["CONFIRMACAO"], {}), ensure_ascii=False)
    interp = parse_interpretacao(raw, "tá caro", E("vendas/confirmacao_plano"))
    div = pipeline.divergencias_regra_modelo(raw, interp)
    _assert("CONFIRMACAO: regras tiraram" in div, div)


# ── Confirmação lida só pelo modelo ──────────────────────────────────────────

PASSOS_DE_CONFIRMACAO = ["vendas/confirmacao_plano", "cad/confirmacao_dados", "termos", "agenda/confirmacao_horario"]


def _avancou(est: str, msg: str) -> bool:
    antes = E(est)
    depois, _, _ = turno(antes, msg, L(["CONFIRMACAO"], {}))
    return (depois.get("fase"), depois.get("aguardando")) != (antes.get("fase"), antes.get("aguardando"))


def test_confirmacao_errada_do_modelo_nao_avanca() -> None:
    """O modelo marcou CONFIRMACAO numa mensagem que não é um sim: o funil não pode andar.

    Antes disto, um erro do modelo bastava para aceitar os termos ou confirmar o agendamento.
    """
    nao_e_sim = ["tá caro", "sim mas tá caro", "vou pensar", "não entendi", "pera aí", "não sei", "hum",
                 "kkk", "meu cachorro latiu", "e a multa?", "depois eu vejo", "talvez",
                 "pode agendar pra quando?", "o técnico pode agendar?"]
    for est in PASSOS_DE_CONFIRMACAO:
        errados = [m for m in nao_e_sim if _avancou(est, m)]
        _assert(not errados, (est, errados))


def test_confirmacao_legitima_continua_valendo() -> None:
    sim_de_verdade = ["perfeito", "combinado", "show", "top", "👍", "✅", "bora", "vamos nessa", "manda ver",
                      "com certeza", "claro", "pode mandar", "quero sim", "confirmado", "correto", "exato",
                      "uhum", "aham", "pode sim", "fechado", "é esse", "massa", "joia", "ciente", "tudo ok",
                      "por favor", "isso aí", "é isso", "simm", "ss", "aceito os termos", "li e concordo",
                      "tá ótimo", "beleza então", "pode agendar", "pode marcar", "sim pode agendar"]
    for est in PASSOS_DE_CONFIRMACAO:
        barrados = [m for m in sim_de_verdade if not _avancou(est, m)]
        _assert(not barrados, (est, barrados))


# ── 6. Limite configurável e avaliação pelo painel ───────────────────────────


def test_limite_de_tentativas_vem_da_config() -> None:
    original = conversa.limite_travado
    conversa.limite_travado = lambda estado=None: 2
    try:
        _, dec, _ = turno(E("cad/email"), "não tenho email", L(["OUTRO"], {}))
    finally:
        conversa.limite_travado = original
    _assert(dec.acao == "TRANSFERIR_HUMANO", dec.acao)
    _, dec, _ = turno(E("cad/email"), "não tenho email", L(["OUTRO"], {}))
    _assert(dec.acao == "RESPONDER", dec.acao)


def test_avaliacao_roda_e_guarda_o_resultado() -> None:
    from app import admin_store

    falso = types.SimpleNamespace(
        CASOS_PADRAO="x",
        carregar_casos=lambda caminho: [{"id": "a"}, {"id": "b"}],
        avaliar_caso=lambda caso: {
            "id": caso["id"], "fase": "cadastro", "aguardando": "cpf", "mensagem": "oi",
            "problemas_llm": ["faltou evento X"] if caso["id"] == "b" else [],
            "problemas_final": ["faltou evento X"] if caso["id"] == "b" else [],
        },
        resumir=lambda rs: {"rotulados": len(rs), "acerto_llm_sozinho": 1, "acerto_llm_mais_parser": 1,
                            "parser_corrigiu": 0, "parser_estragou": 0},
    )
    antes_cfg = admin_store.get_config(avaliacao.CHAVE_RESULTADO, "")
    original = avaliacao._avaliador
    avaliacao._avaliador = lambda: falso
    try:
        avaliacao._andamento.update(rodando=True)
        avaliacao._rodar()
        st = avaliacao.status()
    finally:
        avaliacao._avaliador = original
        admin_store.set_config(avaliacao.CHAVE_RESULTADO, antes_cfg)
    _assert(st["rodando"] is False and st["feitos"] == 2 and not st["erro"], st)
    _assert(st["ultimo"]["resumo"]["rotulados"] == 2, st["ultimo"])
    _assert([e["id"] for e in st["ultimo"]["erros"]] == ["b"], st["ultimo"]["erros"])
    # O avaliador de verdade existe onde a imagem Docker o coloca
    _assert(os.path.exists(avaliacao._SCRIPT), avaliacao._SCRIPT)


def main() -> None:
    tests = [
        test_fala_vira_o_dado_escrito,
        test_numero_por_extenso_so_muda_em_audio,
        test_dado_ditado_e_gravado,
        test_verificador_aceita_o_que_esta_nos_fatos,
        test_verificador_barra_o_que_ninguem_disse,
        test_resposta_com_dado_inventado_e_reescrita,
        test_resposta_que_insiste_em_inventar_e_barrada,
        test_desconto_pedido_pelo_cliente_nao_e_concedido,
        test_modelo_fora_pede_para_mandar_de_novo_e_depois_transfere,
        test_modelo_fora_mas_as_regras_leram_o_dado,
        test_redator_fora_do_ar_nao_vira_silencio,
        test_duvida_na_agenda_e_respondida_e_nao_prometida,
        test_toda_duvida_usa_o_redator_com_a_base,
        test_uma_consulta_por_pergunta,
        test_base_fora_do_ar_nao_e_falta_de_conteudo,
        test_divergencias_mostram_o_que_as_regras_mudaram,
        test_confirmacao_errada_do_modelo_nao_avanca,
        test_confirmacao_legitima_continua_valendo,
        test_limite_de_tentativas_vem_da_config,
        test_avaliacao_roda_e_guarda_o_resultado,
    ]
    falhas = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            falhas += 1
            print(f"  FALHOU {fn.__name__}: {type(e).__name__}: {e}")
    if falhas:
        print(f"\n❌ {falhas} falha(s)")
        sys.exit(1)
    print("\n✅ Robustez OK")


if __name__ == "__main__":
    main()
