# -*- coding: utf-8 -*-
"""Venda consultiva — a Eva conduz o cliente ao plano certo, contorna objeções e fecha.

Sem LLM de verdade e sem rede: o modelo é simulado e o harness da auditoria bloqueia
toda chamada HTTP. Cobre o consultor de planos (indicar, reforçar, perguntar), a
abertura personalizada, o contorno de objeções e da recusa dos termos, a condução ao
fechamento, a base de conhecimento sem as linhas de preço e o cadastro conversado.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import test_auditoria_interpretacao as aud  # bloqueia a rede e simula as integrações

from app import conversa, consultor, llm, pipeline, response
from app.plans_catalog import listar_planos
from app.rag import formatar_sem_catalogo, sem_linhas_de_plano
from app.state_machine import decidir
from app.resolver import resolver
from app.parser import parse_interpretacao

E, L, turno = aud.E, aud.L, aud.turno
VENDA = "vendas/confirmacao_plano"  # MOV SUPER+ em conversa


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


class _Modelo:
    """Simula o modelo: `consultor` responde a recomendação; `texto` responde os redatores."""

    def __init__(self, consultor_json: dict | str | None = None, texto: str = "resposta do modelo"):
        self.consultor_json, self.texto = consultor_json, texto
        self.prompts_consultor: list[str] = []
        self.prompts_texto: list[str] = []

    def _chat_llm(self, system, user, **k):
        self.prompts_consultor.append(user)
        if self.consultor_json is None:
            raise RuntimeError("modelo fora do ar")
        return self.consultor_json if isinstance(self.consultor_json, str) else json.dumps(self.consultor_json, ensure_ascii=False)

    def _chat_texto(self, system, user, **k):
        self.prompts_texto.append(user)
        return self.texto

    def __enter__(self):
        self._antes = (llm.chat, response.chat, pipeline.consultar_rag)
        llm.chat, response.chat = self._chat_llm, self._chat_texto
        pipeline._KIT_DE_VENDA.update(quando=0.0, rag=None)
        pipeline.consultar_rag = lambda **k: {
            "encontrado": True,
            "chunks": [{"titulo": "Fidelidade", "conteudo": "Fidelidade de 12 meses em todos os planos. A fidelidade garante a instalação gratuita."}],
        }
        return self

    def __exit__(self, *exc):
        llm.chat, response.chat, pipeline.consultar_rag = self._antes


def _texto(dec, estado, msg: str) -> str:
    return response.gerar_resposta(dec, estado, historico=[], mensagem_cliente=msg)


# ── Classificação ────────────────────────────────────────────────────────────


def test_necessidade_e_objecao_sao_reconhecidas() -> None:
    venda = E(VENDA)
    for msg in ("somos 8 pessoas em casa", "tenho 3 celulares e 2 tvs", "queria um com disney", "quero pra jogar",
                "só quero internet", "tem um mais barato?", "moro sozinho", "uso pra trabalhar em home office"):
        _assert(conversa.classificar(msg, venda) == conversa.NECESSIDADE, (msg, conversa.classificar(msg, venda)))
    for msg in ("não quero fidelidade", "já tenho internet da claro", "ouvi falar mal de vocês"):
        _assert(conversa.classificar(msg, venda) == conversa.OBJECAO, (msg, conversa.classificar(msg, venda)))
    _assert(conversa.classificar("tá caro", venda) == conversa.OBJECAO_PRECO, "preço")
    for msg in ("sim", "quero o infinity", "quantos megas?", "tem outro?"):
        _assert(conversa.classificar(msg, venda) == "", (msg, conversa.classificar(msg, venda)))


# ── Consultor de planos ──────────────────────────────────────────────────────


def test_cliente_conta_o_que_precisa_e_recebe_o_plano_certo() -> None:
    abertura = "Como são 8 aparelhos aí, o ideal é o INFINITY, que comporta até 12 dispositivos."
    with _Modelo({"plano": "MOV INFINITY", "abertura": abertura}) as modelo:
        estado, dec, _ = turno(E(VENDA), "somos 8 aparelhos em casa", L(["OUTRO"], {}))
        texto = _texto(dec, estado, "somos 8 aparelhos em casa")
    _assert(estado.get("plano_em_negociacao") == "MOV INFINITY", estado.get("plano_em_negociacao"))
    _assert(estado.get("fase") == "vendas" and estado.get("aguardando") == "confirmacao_plano", estado.get("aguardando"))
    _assert(not estado.get("plano_confirmado"), "confirmou sem o cliente aceitar")
    # A abertura é do consultor; a ficha (preço e benefícios) vem do painel
    _assert(texto.startswith(abertura), texto[:160])
    _assert("189" in texto and texto.rstrip().endswith("?"), texto[-200:])
    prompt = modelo.prompts_consultor[0]
    _assert("MOV INFINITY — R$ 189,00/mês" in prompt and "até 12 dispositivos" in prompt, prompt[:600])
    _assert("PLANO JÁ EM CONVERSA: MOV SUPER+" in prompt and "somos 8 aparelhos em casa" in prompt, prompt[-400:])
    _assert("plano_recomendado" in (dec.contexto_resposta or {}).get("sinais", []), dec.contexto_resposta)


def test_plano_atual_ja_atende_e_reforcado_sem_repetir_a_ficha() -> None:
    abertura = "Pra 4 aparelhos o SUPER+ dá conta com folga, ele comporta até 6 dispositivos."
    with _Modelo({"plano": "MOV SUPER+", "abertura": abertura}):
        estado, dec, _ = turno(E(VENDA), "são 4 aparelhos aqui", L(["OUTRO"], {}))
        texto = _texto(dec, estado, "são 4 aparelhos aqui")
    _assert(dec.objetivo_resposta == "REFORCAR_PLANO" and estado.get("plano_em_negociacao") == "MOV SUPER+", dec.objetivo_resposta)
    _assert(texto.startswith(abertura) and "✅" not in texto, texto)
    _assert("MOV SUPER+" in texto and texto.rstrip().endswith("?"), texto)


def test_sem_saber_o_que_o_cliente_quer_a_eva_pergunta() -> None:
    pergunta = "Claro! Me conta: quantos aparelhos usam a internet aí e o que você procura no plano?"
    with _Modelo({"plano": "", "abertura": pergunta}):
        estado, dec, _ = turno(E(VENDA), "esse não, tem outro?", L(["PEDIU_TROCAR_PLANO"], {}))
        texto = _texto(dec, estado, "esse não, tem outro?")
    _assert(dec.objetivo_resposta == "PERGUNTAR_NECESSIDADE" and texto == pergunta, (dec.objetivo_resposta, texto))
    _assert(estado.get("plano_em_negociacao") == "MOV SUPER+" and estado.get("aguardando") == "confirmacao_plano", estado.get("aguardando"))


def test_consultor_nao_inventa_plano_nem_numero() -> None:
    # Plano que não existe: a indicação é descartada e vale o fluxo de sempre
    with _Modelo({"plano": "MOV TURBO 1 GIGA", "abertura": "Tenho o plano perfeito pra você."}):
        estado, dec, _ = turno(E(VENDA), "somos 8 aparelhos em casa", L(["OUTRO"], {}))
    _assert(estado.get("plano_em_negociacao") in aud.PLANOS and dec.acao == "RESPONDER", estado.get("plano_em_negociacao"))
    # Abertura com desconto que não está no catálogo: a frase cai, a ficha do painel fica
    with _Modelo({"plano": "MOV INFINITY", "abertura": "Consigo o INFINITY com 30% de desconto pra você."}):
        estado, dec, _ = turno(E(VENDA), "somos 8 aparelhos em casa", L(["OUTRO"], {}))
        texto = _texto(dec, estado, "somos 8 aparelhos em casa")
    _assert(estado.get("plano_em_negociacao") == "MOV INFINITY" and "30%" not in texto and "189" in texto, texto[:200])


def test_sem_modelo_o_fluxo_de_sempre_continua() -> None:
    with _Modelo(None):
        estado, dec, _ = turno(E(VENDA), "queria um com disney", L(["PERGUNTA"], {}, pergunta="queria um com disney"))
    _assert(dec.acao == "RESPONDER" and estado.get("fase") == "vendas", (dec.acao, estado.get("fase")))


def test_consultor_nao_entra_quando_o_cliente_ja_decidiu() -> None:
    for msg, llm_ in (
        ("sim", L(["CONFIRMACAO"], {})),
        ("quero o infinity", L(["PLANO_INFORMADO"], {"plano": "infinity"})),
        ("me mostra todos os planos", L(["PERGUNTA"], {}, pergunta="me mostra todos os planos")),
        ("tem multa?", L(["PERGUNTA"], {}, pergunta="tem multa?")),
    ):
        estado = E(VENDA)
        interp = parse_interpretacao(json.dumps(llm_, ensure_ascii=False), msg, estado)
        res = resolver(estado, interp)
        res.update(mensagem=msg, pergunta=interp.pergunta, pergunta_original=msg, confianca=0.95)
        _assert(decidir(estado, res).acao != "RECOMENDAR_PLANO", msg)
    # Fora da venda (cadastro), contar que são 8 aparelhos vira nota, não troca de plano
    with _Modelo({"plano": "MOV INFINITY", "abertura": "x"}) as modelo:
        estado, _, _ = turno(E("cad/cpf"), "somos 8 aparelhos em casa", L(["OUTRO"], {}))
    _assert(estado.get("plano_confirmado") == "MOV SUPER+" and not modelo.prompts_consultor, estado.get("plano_confirmado"))


def test_primeiro_plano_ja_vem_indicado_quando_o_cliente_contou_antes() -> None:
    abertura = "Como vocês são 8 aparelhos, o INFINITY é o que comporta todo mundo."
    antes = dict(E("viab"), notas_conversa="são 8 aparelhos na casa")
    loc = L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém", "bairro": "Diamantino"})
    with _Modelo({"plano": "MOV INFINITY", "abertura": abertura}):
        estado, dec, _ = turno(antes, "Santarém, Diamantino", loc)
        texto = _texto(dec, estado, "Santarém, Diamantino")
    _assert(estado.get("plano_em_negociacao") == "MOV INFINITY", estado.get("plano_em_negociacao"))
    _assert(abertura in texto and "189" in texto, texto[:300])
    # Sem nada contado antes: o plano em destaque, com a pergunta que investiga
    with _Modelo({"plano": "MOV INFINITY", "abertura": abertura}) as modelo:
        estado, dec, _ = turno(E("viab"), "Santarém, Diamantino", loc)
        texto = _texto(dec, estado, "Santarém, Diamantino")
    _assert(not modelo.prompts_consultor and "quantos aparelhos" in texto, texto[-220:])


def test_catalogo_do_consultor_vem_do_painel() -> None:
    txt = consultor.catalogo_em_texto(listar_planos({}))
    _assert("MOV INFINITY — R$ 189,00/mês" in txt and "até 12 dispositivos" in txt, txt[:300])
    _assert("\n- MOV ESSENCIAL" in txt and "até 4 dispositivos" in txt, txt[-400:])


# ── Objeções e fechamento ────────────────────────────────────────────────────


def test_objecao_e_respondida_com_os_fatos_da_base_e_conduz_ao_fechamento() -> None:
    with _Modelo(texto="Entendo. A fidelidade é o que garante a instalação gratuita. Posso seguir com ele pra você?") as modelo:
        estado, dec, _ = turno(E(VENDA), "não quero fidelidade", L(["OUTRO"], {}))
        dec = pipeline._enriquecer_com_rag(dec, estado, "não quero fidelidade")
        texto = _texto(dec, estado, "não quero fidelidade")
    _assert(estado.get("aguardando") == "confirmacao_plano" and not estado.get("plano_confirmado"), estado.get("aguardando"))
    prompt = modelo.prompts_texto[0]
    _assert("objeção que não é o preço" in prompt, prompt[:500])
    _assert("A fidelidade garante a instalação gratuita" in prompt, prompt)
    _assert("CONDUÇÃO DA VENDA" in prompt and "urgência inventada" in prompt, prompt)
    _assert(texto.startswith("Entendo."), texto)


def test_duvida_na_venda_conduz_ao_fechamento_e_no_cadastro_nao() -> None:
    pergunta = L(["PERGUNTA"], {}, pergunta="a instalação é paga?")
    with _Modelo(texto="Não, a instalação é gratuita. Posso seguir com o SUPER+ pra você?") as modelo:
        estado, dec, _ = turno(E(VENDA), "a instalação é paga?", pergunta)
        _texto(dec, estado, "a instalação é paga?")
        _assert("CONDUÇÃO DA VENDA" in modelo.prompts_texto[-1], modelo.prompts_texto[-1][:300])
        estado, dec, _ = turno(E("cad/telefone"), "a instalação é paga?", pergunta)
        _texto(dec, estado, "a instalação é paga?")
        _assert("CONDUÇÃO DA VENDA" not in modelo.prompts_texto[-1], "bloco de venda no cadastro")


def test_recusa_dos_termos_e_contornada_uma_vez_e_depois_transfere() -> None:
    with _Modelo(texto="Entendo. A fidelidade de 12 meses é o que garante a instalação gratuita. Sabendo disso, quer seguir?") as modelo:
        e1, d1, _ = turno(E("termos"), "não aceito", L(["NEGACAO"], {}))
        d1 = pipeline._enriquecer_com_rag(d1, e1, "não aceito")
        texto = _texto(d1, e1, "não aceito")
        _assert(d1.objetivo_resposta == "CONTORNAR_RECUSA_TERMOS" and e1.get("fase") == "termos", (d1.objetivo_resposta, e1.get("fase")))
        _assert("não aceita o termo de fidelidade" in modelo.prompts_texto[0], modelo.prompts_texto[0][:400])
        _assert("Não ofereça plano sem fidelidade" in modelo.prompts_texto[0], "guia")
        _assert("12 meses" in texto, texto)
        e2, d2, _ = turno(e1, "não quero mesmo", L(["NEGACAO"], {}))
    _assert(d2.acao == "TRANSFERIR_HUMANO" and e2.get("fase") == "transferido", (d2.acao, e2.get("fase")))
    # Aceitar depois do contorno segue normalmente
    e3, d3, _ = turno(e1, "tá bom, aceito", L(["CONFIRMACAO"], {}))
    _assert(e3.get("fase") == "agendamento", e3.get("fase"))
    # Pedir para encerrar não é recusa a contornar
    e4, d4, _ = turno(E("termos"), "quero encerrar", L(["NEGACAO"], {}))
    _assert(e4.get("fase") == "finalizado", e4.get("fase"))


# ── Base de conhecimento ─────────────────────────────────────────────────────

TRECHO_PLANOS = """A MOV FIBRA vende conexão 100% fibra e ILIMITADA — não vendemos por megas.
O plano é dimensionado pela quantidade de dispositivos que usam a internet na casa.
- MOV ESSENCIAL — R$ 129/mês — até 4 dispositivos — Amazon Prime ou Globoplay
- MOV INFINITY — R$ 189/mês — até 12 dispositivos — Disney+, Max ou Globoplay
📖 O QUE É CADA BENEFÍCIO:
- ExitLag: ajuda a melhorar a rota da conexão em jogos online
- Desconto de pontualidade: benefício do MOV SUPER que reduz a mensalidade de R$ 139 para R$ 119"""


def test_base_perde_so_as_linhas_de_preco_de_plano() -> None:
    limpo = sem_linhas_de_plano(TRECHO_PLANOS)
    _assert("não vendemos por megas" in limpo and "quantidade de dispositivos" in limpo, limpo)
    _assert("ExitLag: ajuda a melhorar" in limpo, limpo)
    _assert("R$ 129" not in limpo and "R$ 189" not in limpo and "MOV SUPER" not in limpo, limpo)
    rag = {"encontrado": True, "chunks": [{"titulo": "Planos", "conteudo": TRECHO_PLANOS},
                                          {"titulo": "Instalação", "conteudo": "Instalação grátis com fidelidade."}]}
    txt = formatar_sem_catalogo(rag)
    # Antes, um trecho com dois nomes de plano fazia a base inteira ser descartada
    _assert("não vendemos por megas" in txt and "Instalação grátis" in txt and "R$ 189" not in txt, txt)


def test_base_de_venda_junta_a_mensagem_com_os_fatos_da_oferta() -> None:
    consultas = []

    def fake(*, pergunta, mensagem, estado, plano):
        consultas.append(pergunta)
        if "fibra" in pergunta:
            return {"encontrado": True, "chunks": [{"titulo": "Oferta", "conteudo": "Conexão 100% fibra e ilimitada."}]}
        return {"encontrado": False}

    original = pipeline.consultar_rag
    pipeline.consultar_rag = fake
    pipeline._KIT_DE_VENDA.update(quando=0.0, rag=None)
    try:
        r1 = pipeline.base_de_venda({}, "já tenho internet da claro")
        r2 = pipeline.base_de_venda({}, "tá caro")
    finally:
        pipeline.consultar_rag = original
        pipeline._KIT_DE_VENDA.update(quando=0.0, rag=None)
    _assert(r1["encontrado"] and "100% fibra" in r1["chunks"][0]["conteudo"], r1)
    # Os fatos gerais da oferta são buscados uma vez e reaproveitados
    _assert(len([c for c in consultas if "fibra" in c]) == 1 and len(consultas) == 3, consultas)
    _assert(r2["encontrado"], r2)


# ── Cadastro conversado ──────────────────────────────────────────────────────


def test_confirmacao_do_dado_varia_ao_longo_do_cadastro() -> None:
    frases = []
    estado = E("cad/cpf")
    passos = [
        ("529.982.247-25", {"cpf": "52998224725"}),
        ("maria@gmail.com", {"email": "maria@gmail.com"}),
        ("93992219098", {"telefone": "93992219098"}),
        ("16/08/2000", {"data_nascimento": "16/08/2000"}),
        ("68020-000", {"cep": "68020000"}),
    ]
    for msg, dados in passos:
        estado, dec, _ = turno(estado, msg, L(["DADO_INFORMADO"], dados))
        if dec.objetivo_resposta == "ANOTAR_E_PEDIR_PROXIMO":
            frases.append(_texto(dec, estado, msg).split(".")[0].split("!")[0])
    _assert(len(set(frases)) >= 3, frases)
    _assert(estado.get("aguardando") == "rua", estado.get("aguardando"))


def test_comentario_junto_do_dado_recebe_reacao_e_o_pedido_certo() -> None:
    msg = "529.982.247-25, desculpa a demora, tava no hospital com minha mãe"
    with _Modelo(texto="Imagina, espero que ela esteja bem! Já anotei aqui.") as modelo:
        estado, dec, _ = turno(E("cad/cpf"), msg, L(["DADO_INFORMADO", "CONVERSA_SOCIAL"], {"cpf": "52998224725"}))
        texto = _texto(dec, estado, msg)
    _assert(estado.get("cpf") == "52998224725" and estado.get("aguardando") == "email", estado.get("aguardando"))
    if dec.objetivo_resposta == "ANOTAR_E_PEDIR_PROXIMO":
        _assert(texto.startswith("Imagina, espero que ela esteja bem!"), texto)
        _assert("e-mail" in texto and modelo.prompts_texto, texto)
    # Dado seco: nenhuma chamada ao modelo para confirmar
    with _Modelo(texto="não devia ser usado") as modelo:
        estado, dec, _ = turno(E("cad/cpf"), "529.982.247-25", L(["DADO_INFORMADO"], {"cpf": "52998224725"}))
        texto = _texto(dec, estado, "529.982.247-25")
    _assert(not modelo.prompts_texto and "e-mail" in texto, (modelo.prompts_texto, texto))


# ── Dúvida na oferta do plano (atendimento real de 10/10/2026) ────────────────

RAG_PLANOS = """A MOV FIBRA vende conexão 100% fibra e ILIMITADA — não vendemos por megas.
O plano é dimensionado pela quantidade de dispositivos que usam a internet na casa.
Se o cliente perguntar sobre velocidade/megas: explicar que a conexão é 100% fibra e ilimitada e perguntar quantos aparelhos usam a internet para indicar o plano ideal.
Formas de pagamento para todos os planos: cartão de crédito, boleto e Pix.
- MOV SUPER+ — R$ 139/mês — até 6 dispositivos — Imagina Só, Ubook e repetidor Mesh"""


def test_pergunta_na_oferta_e_respondida_pelo_modelo_e_nao_por_tabela_pronta() -> None:
    """ "Qual a velocidade? quantos megas?" saía com a tabela de preços."""
    perguntas = [
        "Tá, mas qual a velocidade? quantos megas?", "quantos megas?", "é fibra mesmo?", "o roteador é bom?",
        "quanto fica no cartão?", "tem taxa de instalação?", "o que vem nesse plano?",
        "quanto é?", "e depois dos 3 meses fica quanto?", "posso pagar no pix?",
    ]
    for msg in perguntas:
        antes = E(VENDA)
        estado, dec, _ = turno(antes, msg, L(["PERGUNTA"], {}, pergunta=msg))
        _assert(dec.objetivo_resposta == "RESPONDER_DUVIDA_NA_VENDA", (msg, dec.objetivo_resposta))
        # Pergunta não muda nada no atendimento: mesmo passo, mesmo plano
        _assert(estado.get("aguardando") == "confirmacao_plano" and not estado.get("plano_confirmado"), (msg, estado.get("aguardando")))
        _assert(estado.get("plano_em_negociacao") == antes.get("plano_em_negociacao"), (msg, estado.get("plano_em_negociacao")))


def test_pergunta_dos_megas_recebe_a_base_e_o_catalogo() -> None:
    msg = "Tá, mas qual a velocidade? quantos megas?"
    resposta = "A nossa conexão é 100% fibra e ilimitada, a gente não vende por megas. Quantos aparelhos usam a internet aí?"
    with _Modelo(texto=resposta) as modelo:
        pipeline.consultar_rag = lambda **k: {"encontrado": True, "chunks": [{"titulo": "Planos", "conteudo": RAG_PLANOS}]}
        estado, dec, _ = turno(E(VENDA), msg, L(["PERGUNTA"], {}, pergunta=msg))
        dec = pipeline._enriquecer_com_rag(dec, estado, msg)
        texto = _texto(dec, estado, msg)
    prompt = modelo.prompts_texto[0]
    _assert("não vendemos por megas" in prompt and "perguntar quantos aparelhos" in prompt, prompt[:700])
    # O preço de plano que a base traz sai; o do painel entra, com todos os planos
    _assert("R$ 139/mês — até 6" not in prompt and "MOV SUPER+ — R$ 139,00/mês" in prompt, prompt)
    _assert("velocidade: Ilimitada" in prompt and "MOV INFINITY" in prompt and "CONDUÇÃO DA VENDA" in prompt, prompt)
    # A resposta do modelo já termina puxando o próximo passo: nada é acrescentado
    _assert(texto == resposta, texto)


def test_sem_modelo_a_pergunta_na_oferta_usa_a_resposta_pronta() -> None:
    with _Modelo(texto=""):
        estado, dec, _ = turno(E(VENDA), "o que vem nesse plano?", L(["PERGUNTA"], {}, pergunta="o que vem nesse plano?"))
        texto = _texto(dec, estado, "o que vem nesse plano?")
        _assert("MOV SUPER+" in texto and "✅" in texto, texto[:200])
        estado, dec, _ = turno(E(VENDA), "é fibra mesmo?", L(["PERGUNTA"], {}, pergunta="é fibra mesmo?"))
        texto = _texto(dec, estado, "é fibra mesmo?")
        _assert(texto.strip() and "MOV SUPER+" in texto, texto)


def test_escolha_com_duvida_e_pedido_de_lista_seguem_o_caminho_de_sempre() -> None:
    for msg, llm_ in (
        ("quero o infinity, tem disney?", L(["PLANO_INFORMADO", "PERGUNTA"], {"plano": "infinity"}, pergunta="tem disney?")),
        ("me mostra todos os planos?", L(["PERGUNTA"], {}, pergunta="me mostra todos os planos?")),
        ("sim, pode ser", L(["CONFIRMACAO"], {})),
    ):
        _, dec, _ = turno(E(VENDA), msg, llm_)
        _assert(dec.objetivo_resposta != "RESPONDER_DUVIDA_NA_VENDA", (msg, dec.objetivo_resposta))
    # Fora da oferta (cadastro), a dúvida continua no redator de dúvidas de sempre
    _, dec, _ = turno(E("cad/telefone"), "quantos megas?", L(["PERGUNTA"], {}, pergunta="quantos megas?"))
    _assert(dec.objetivo_resposta != "RESPONDER_DUVIDA_NA_VENDA", dec.objetivo_resposta)


def test_resposta_so_com_o_numero_de_aparelhos_vai_para_o_consultor() -> None:
    venda = dict(E(VENDA), ultima_mensagem_sofia="A conexão é ilimitada. Quantos aparelhos usam a internet aí?")
    for msg in ("uns 5", "são oito", "8", "3 ou 4"):
        _assert(conversa.classificar(msg, venda) == conversa.NECESSIDADE, (msg, conversa.classificar(msg, venda)))
    # Sem a pergunta dos aparelhos antes, um número solto não é necessidade
    _assert(conversa.classificar("8", E(VENDA)) == "", conversa.classificar("8", E(VENDA)))
    with _Modelo({"plano": "MOV INFINITY", "abertura": "Pra 8 aparelhos o INFINITY é o que comporta: até 12 dispositivos."}):
        estado, _, _ = turno(venda, "são oito", L(["OUTRO"], {}))
    _assert(estado.get("plano_em_negociacao") == "MOV INFINITY", estado.get("plano_em_negociacao"))


def test_bairro_que_o_cliente_disse_vale_mais_que_o_do_mapa() -> None:
    from app.state_machine import decidir_resultado_cobertura

    mapa = {"resultado": "cobertura_confirmada", "tem_cobertura": True,
            "cidade_normalizada": "Santarém", "bairro_normalizado": "Aparecida"}
    # Cliente disse Diamantino e depois mandou a localização: o bairro continua Diamantino
    dec = decidir_resultado_cobertura(mapa, dict(E("viab"), bairro="Diamantino"))
    _assert(dec.atualizar_dados.get("bairro") == "Diamantino", dec.atualizar_dados.get("bairro"))
    # Sem bairro informado, vale o do mapa
    dec = decidir_resultado_cobertura(mapa, E("viab"))
    _assert(dec.atualizar_dados.get("bairro") == "Aparecida", dec.atualizar_dados.get("bairro"))


def test_abertura_reconhece_quem_ja_chegou_pedindo_plano() -> None:
    msg = "Opa bom dia\nQueria ver os planos que tem"
    estado, dec, _ = turno(E("inicio"), msg, L(["SAUDACAO", "PERGUNTA"], {}))
    texto = _texto(dec, estado, msg)
    _assert("Bom dia" in texto and "te mostrar os planos" in texto, texto[:200])
    estado, dec, _ = turno(E("inicio"), "oi", L(["SAUDACAO"], {}))
    _assert("te mostrar os planos" not in _texto(dec, estado, "oi"), "abertura comum")


def main() -> None:
    tests = [
        test_necessidade_e_objecao_sao_reconhecidas,
        test_cliente_conta_o_que_precisa_e_recebe_o_plano_certo,
        test_plano_atual_ja_atende_e_reforcado_sem_repetir_a_ficha,
        test_sem_saber_o_que_o_cliente_quer_a_eva_pergunta,
        test_consultor_nao_inventa_plano_nem_numero,
        test_sem_modelo_o_fluxo_de_sempre_continua,
        test_consultor_nao_entra_quando_o_cliente_ja_decidiu,
        test_primeiro_plano_ja_vem_indicado_quando_o_cliente_contou_antes,
        test_catalogo_do_consultor_vem_do_painel,
        test_objecao_e_respondida_com_os_fatos_da_base_e_conduz_ao_fechamento,
        test_duvida_na_venda_conduz_ao_fechamento_e_no_cadastro_nao,
        test_recusa_dos_termos_e_contornada_uma_vez_e_depois_transfere,
        test_base_perde_so_as_linhas_de_preco_de_plano,
        test_base_de_venda_junta_a_mensagem_com_os_fatos_da_oferta,
        test_confirmacao_do_dado_varia_ao_longo_do_cadastro,
        test_comentario_junto_do_dado_recebe_reacao_e_o_pedido_certo,
        test_pergunta_na_oferta_e_respondida_pelo_modelo_e_nao_por_tabela_pronta,
        test_pergunta_dos_megas_recebe_a_base_e_o_catalogo,
        test_sem_modelo_a_pergunta_na_oferta_usa_a_resposta_pronta,
        test_escolha_com_duvida_e_pedido_de_lista_seguem_o_caminho_de_sempre,
        test_resposta_so_com_o_numero_de_aparelhos_vai_para_o_consultor,
        test_bairro_que_o_cliente_disse_vale_mais_que_o_do_mapa,
        test_abertura_reconhece_quem_ja_chegou_pedindo_plano,
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
    print("\n✅ Venda consultiva OK")


if __name__ == "__main__":
    main()
