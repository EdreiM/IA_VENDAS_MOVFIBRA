# -*- coding: utf-8 -*-
"""Conversa no meio do funil — o que a Eva faz quando o cliente não responde ao passo pedido.

Roda sem LLM e sem rede (o harness da auditoria bloqueia toda chamada HTTP). Cobre:
pedido de tempo, "não tenho esse dado", objeção de preço, áudio, quem já é cliente,
alteração depois do cadastro, reenvio dos termos, transferência quando trava, cliente
que volta depois do encerramento, notas da conversa e a marca de base sem resposta.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import test_auditoria_interpretacao as aud  # bloqueia a rede e simula as integrações

from app import conversa, response
from app.db import aplicar_transicao
from app.models import Decisao
from app.parser import parse_interpretacao

E, L, turno = aud.E, aud.L, aud.turno
OUTRO = L(["OUTRO"], {})


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


def _seguir(estado: dict, passos: list[tuple[str, dict]]) -> list[tuple[dict, Decisao]]:
    """Vários turnos seguidos; devolve (estado depois, decisão) de cada um."""
    saida = []
    for msg, llm in passos:
        estado, dec, _ = turno(estado, msg, llm)
        saida.append((estado, dec))
    return saida


def _sinais(dec: Decisao) -> list[str]:
    return list((dec.contexto_resposta or {}).get("sinais") or [])


class _Chat:
    """Substitui response.chat: guarda o prompt e devolve a resposta combinada."""

    def __init__(self, resposta: str = "resposta do modelo"):
        self.resposta = resposta
        self.prompts: list[str] = []

    def __call__(self, system, user, **k):
        self.prompts.append(user)
        return self.resposta

    def __enter__(self):
        self._antes = response.chat
        response.chat = self
        return self

    def __exit__(self, *exc):
        response.chat = self._antes


# ── Classificação da reação do cliente ───────────────────────────────────────


def test_classificar_pelas_regras() -> None:
    cad = E("cad/cep")
    casos = {
        "pera aí": conversa.ESPERA,
        "já mando": conversa.ESPERA,
        "vou procurar aqui": conversa.ESPERA,
        "não tenho agora": conversa.ESPERA,
        "vou pensar": conversa.ADIAMENTO,
        "depois eu vejo": conversa.ADIAMENTO,
        "vou falar com minha esposa": conversa.ADIAMENTO,
        "não sei meu cep": conversa.IMPEDIMENTO,
        "não tenho email": conversa.IMPEDIMENTO,
        "não consegui abrir": conversa.IMPEDIMENTO,
        "tá caro": conversa.OBJECAO_PRECO,
        "a concorrente faz por 99": conversa.OBJECAO_PRECO,
        "não entendi": conversa.NAO_ENTENDEU,
        "como assim?": conversa.NAO_ENTENDEU,
        "[audio]": conversa.MIDIA,
        "[image]": conversa.MIDIA,
        "68020-000": "",
        "Rua das Flores, 123": "",
        "sim": "",
    }
    for msg, esperado in casos.items():
        _assert(conversa.classificar(msg, cad) == esperado, (msg, conversa.classificar(msg, cad)))


def test_suporte_so_quando_ja_e_cliente() -> None:
    inicio, cad = E("inicio"), E("cad/cep")
    for msg in ("minha internet caiu, já sou cliente", "preciso da segunda via do boleto",
                "estou sem internet desde ontem", "o técnico não veio"):
        _assert(conversa.classificar(msg, inicio) == conversa.SUPORTE, msg)
    # Dúvida de quem está contratando não é suporte
    for msg in ("a internet cai muito?", "tem suporte 24h?", "como vou pagar a fatura?"):
        _assert(conversa.classificar(msg, inicio) != conversa.SUPORTE, msg)
    # No meio da compra, a leitura do modelo sozinha não encaminha para o suporte
    _assert(conversa.classificar("e se a internet cair?", cad, "SUPORTE") != conversa.SUPORTE, "cad")
    _assert(conversa.classificar("quero ajuda com meu plano atual", inicio, "SUPORTE") == conversa.SUPORTE, "llm")


def test_situacao_e_nota_vem_do_interpretador() -> None:
    raw = json.dumps({**L(["OUTRO"], {}), "situacao": "impedimento", "nota": "só pode receber o técnico à tarde"})
    interp = parse_interpretacao(raw, "não tenho, e só posso de tarde", E("cad/email"))
    _assert(interp.situacao == "IMPEDIMENTO", interp.situacao)
    _assert(interp.nota == "só pode receber o técnico à tarde", interp.nota)
    # Valor fora da lista, dado de cadastro na nota e nota igual à mensagem são descartados
    for extra in ({"situacao": "QUALQUER"}, {"nota": "CPF 604.210.790-96"}, {"nota": "edrei@gmail.com"},
                  {"nota": "não tenho"}):
        raw = json.dumps({**L(["OUTRO"], {}), "situacao": "", "nota": "", **extra})
        interp = parse_interpretacao(raw, "não tenho", E("cad/email"))
        _assert(interp.situacao == "" and interp.nota == "", (extra, interp.situacao, interp.nota))


def test_ok_solto_no_cadastro_nao_vira_pergunta() -> None:
    # "tá" / "ok" depois de um pedido de dado marcava PERGUNTA e a Eva ia consultar a base
    for msg in ("tá", "ok", "blz", "certo"):
        _, dec, interp = turno(E("cad/cep"), msg, OUTRO)
        _assert("PERGUNTA" not in interp.eventos and not interp.pergunta, (msg, interp.eventos))
        _assert(dec.objetivo_resposta != "RESPONDER_PERGUNTA_E_RETOMAR", (msg, dec.objetivo_resposta))


def test_preco_da_concorrente_nao_escolhe_plano() -> None:
    antes = E("vendas/confirmacao_plano")
    depois, dec, _ = turno(antes, "tá caro, a concorrente faz por 99", OUTRO)
    _assert(depois.get("plano_em_negociacao") == antes.get("plano_em_negociacao"), depois.get("plano_em_negociacao"))
    _assert("objecao_preco" in _sinais(dec), _sinais(dec))
    conv = (dec.contexto_resposta or {}).get("conversa") or {}
    _assert(conv.get("situacao") == conversa.OBJECAO_PRECO, conv)
    _assert("planos_mais_em_conta" in conv, conv)


# ── Tentativas sem avanço e transferência ────────────────────────────────────


def test_nao_ter_o_dado_duas_vezes_chama_a_equipe() -> None:
    r = _seguir(E("cad/email"), [("não tenho email", OUTRO), ("não tenho mesmo", OUTRO)])
    (e1, d1), (e2, d2) = r
    _assert(d1.acao == "RESPONDER" and e1.get("tentativas_travadas") == 2, (d1.acao, e1.get("tentativas_travadas")))
    _assert((d1.contexto_resposta or {}).get("conversa", {}).get("situacao") == conversa.IMPEDIMENTO, d1.contexto_resposta)
    _assert(d2.acao == "TRANSFERIR_HUMANO" and e2.get("fase") == "transferido", (d2.acao, e2.get("fase")))
    _assert("email" in d2.motivo, d2.motivo)
    _assert("transferido_por_travar" in _sinais(d2), _sinais(d2))


def test_pedir_tempo_nao_conta_como_travado() -> None:
    r = _seguir(E("cad/cep"), [("pera aí", OUTRO), ("já mando", OUTRO), ("ok", OUTRO), ("um momento", OUTRO),
                               ("vou pensar", OUTRO)])
    for estado, dec in r:
        _assert(dec.acao == "RESPONDER" and estado.get("fase") == "cadastro", (dec.acao, estado.get("fase")))
        _assert(not estado.get("tentativas_travadas"), estado.get("tentativas_travadas"))


def test_avancar_zera_a_contagem() -> None:
    r = _seguir(E("cad/cep"), [("kkk", OUTRO), ("não sei", OUTRO),
                               ("68020-000", L(["DADO_INFORMADO"], {"cep": "68020000"})), ("kkk", OUTRO)])
    _assert([e.get("tentativas_travadas") or 0 for e, _ in r] == [1, 3, 0, 1],
            [e.get("tentativas_travadas") for e, _ in r])
    _assert(r[-1][0].get("fase") == "cadastro", r[-1][0].get("fase"))


def test_conversa_solta_quatro_vezes_chama_a_equipe() -> None:
    r = _seguir(E("cad/cpf"), [("kkk", OUTRO), ("hum", OUTRO), ("sei lá", OUTRO), ("rsrs", OUTRO)])
    _assert([d.acao for _, d in r] == ["RESPONDER"] * 3 + ["TRANSFERIR_HUMANO"], [d.acao for _, d in r])


def test_pergunta_nao_conta_como_travado() -> None:
    pergunta = L(["PERGUNTA"], {}, pergunta="tem multa de cancelamento?")
    r = _seguir(E("cad/telefone"), [("tem multa de cancelamento?", pergunta)] * 5)
    for estado, dec in r:
        _assert(dec.acao == "RESPONDER" and not estado.get("tentativas_travadas"), (dec.acao, estado.get("tentativas_travadas")))
        _assert("conversa" not in (dec.contexto_resposta or {}), dec.contexto_resposta)


def test_recusar_horarios_duas_vezes_chama_a_equipe_com_a_preferencia() -> None:
    nega = L(["NEGACAO"], {})
    r = _seguir(E("agenda/escolha_horario"), [("só posso sábado", nega), ("nenhum desses dá", nega)])
    _assert(r[0][1].acao == "RESPONDER", r[0][1].acao)
    _assert(r[1][1].acao == "TRANSFERIR_HUMANO", r[1][1].acao)
    _assert("escolha horario" in r[1][1].motivo, r[1][1].motivo)


# ── Áudio, suporte, alteração depois do cadastro, termos ─────────────────────


def test_audio_avisa_e_pede_texto() -> None:
    estado, dec, _ = turno(E("cad/nome"), "[audio]", OUTRO)
    _assert(estado.get("aguardando") == "nome" and not estado.get("nome"), estado)
    texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="[audio]")
    _assert("áudio" in texto and "nome" in texto.casefold(), texto)
    # Primeira mensagem do cliente já é áudio: cumprimenta e avisa
    estado, dec, _ = turno(E("inicio"), "[audio]", OUTRO)
    texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="[audio]")
    _assert("áudio" in texto and "Eva" in texto, texto)
    _assert("[audio]" not in texto, texto)


def test_quem_ja_e_cliente_vai_para_a_equipe() -> None:
    estado, dec, _ = turno(E("inicio"), "minha internet caiu, já sou cliente", OUTRO)
    _assert(dec.acao == "TRANSFERIR_HUMANO" and estado.get("fase") == "transferido", (dec.acao, estado.get("fase")))
    _assert("suporte" in dec.motivo.casefold() and "internet caiu" in dec.motivo, dec.motivo)
    texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="minha internet caiu")
    _assert("encaminh" in texto.casefold() and "cidade" not in texto.casefold(), texto)


def test_alterar_dados_depois_do_cadastro_encaminha_sem_perguntar() -> None:
    # Antes: "posso te encaminhar para um atendente?" — e o "sim" virava aceite dos termos
    for estado0, msg, llm in (
        (E("termos"), "quero mudar o endereço da instalação", OUTRO),
        (E("termos"), "meu email é outro@mail.com", L(["DADO_INFORMADO", "CORRECAO_DADO"], {"email": "outro@mail.com"}, corrigidos=["email"])),
        (E("agenda/escolha_horario"), "errei o número da casa", OUTRO),
    ):
        estado, dec, _ = turno(estado0, msg, llm)
        _assert(dec.acao == "TRANSFERIR_HUMANO", (msg, dec.acao, dec.objetivo_resposta))
        _assert(estado.get("email") == estado0.get("email"), (msg, estado.get("email")))
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente=msg)
        _assert("?" not in texto and ("equipe" in texto or "atendente" in texto), texto)
    # Pergunta sobre mudança de endereço continua sendo só uma dúvida
    _, dec, _ = turno(E("termos"), "e se eu mudar de endereço depois?",
                      L(["PERGUNTA"], {}, pergunta="e se eu mudar de endereço depois?"))
    _assert(dec.acao == "RESPONDER", dec.acao)


def test_termos_nao_abriu_reenvia_em_vez_de_recusar() -> None:
    enviados = []
    original = aud.pipeline.enviar_termos
    aud.pipeline.enviar_termos = lambda estado: enviados.append(1) or original(estado)
    try:
        r = _seguir(E("termos"), [("não consegui abrir o pdf", OUTRO), ("não abre", OUTRO)])
    finally:
        aud.pipeline.enviar_termos = original
    (e1, d1), (e2, d2) = r
    _assert(len(enviados) == 1, enviados)
    _assert(e1.get("fase") == "termos" and d1.objetivo_resposta == "PEDIR_ACEITE_TERMOS", (e1.get("fase"), d1.objetivo_resposta))
    # Segunda vez: chama a equipe — e não é tratado como recusa dos termos
    _assert(d2.acao == "TRANSFERIR_HUMANO" and d2.objetivo_resposta == "INFORMAR_TRANSFERENCIA_AJUDA", (d2.acao, d2.objetivo_resposta))


# ── Cliente que volta depois do atendimento encerrado ────────────────────────


def test_volta_apos_venda_concluida_tira_duvida() -> None:
    fim = dict(E("pos"), fase="finalizado", aguardando=None)
    estado, dec, _ = turno(fim, "o técnico leva o roteador?", L(["PERGUNTA"], {}, pergunta="o técnico leva o roteador?"))
    _assert(dec.acao == "RESPONDER" and estado.get("fase") == "pos_venda", (dec.acao, estado.get("fase")))
    _assert("voltou_apos_encerrar" in _sinais(dec), _sinais(dec))
    # Agradecimento continua sendo só a cortesia de despedida
    estado, dec, _ = turno(fim, "obrigado", L(["CONVERSA_SOCIAL"], {}))
    _assert(dec.objetivo_resposta == "CORTESIA_POS_ENCERRAMENTO" and estado.get("fase") == "finalizado", dec.objetivo_resposta)


def test_volta_apos_inatividade_retoma_de_onde_parou() -> None:
    fim = dict(E("cad/cep"), fase="finalizado", aguardando=None,
               retorno_estado={"fase": "cadastro", "aguardando": "cep"})
    estado, dec, _ = turno(fim, "oi, voltei", L(["SAUDACAO"], {}))
    _assert((estado.get("fase"), estado.get("aguardando")) == ("cadastro", "cep"), (estado.get("fase"), estado.get("aguardando")))
    _assert(estado.get("nome") == fim.get("nome") and not estado.get("retorno_estado"), estado.get("retorno_estado"))
    texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="oi, voltei")
    # Retoma só o que falta: a data de nascimento já tinha sido informada
    _assert("CEP" in texto and "nascimento" not in texto, texto)
    estado, dec, _ = turno(estado, "68020-000", L(["DADO_INFORMADO"], {"cep": "68020000"}))
    _assert(estado.get("aguardando") == "rua", estado.get("aguardando"))


def test_volta_sem_ponto_de_retomada_comeca_atendimento_novo() -> None:
    fim = dict(E("cad/cep"), fase="finalizado", aguardando=None, notas_conversa="mora de aluguel")
    estado, dec, _ = turno(fim, "oi", L(["SAUDACAO"], {}))
    _assert(estado.get("fase") == "viabilidade", estado.get("fase"))
    for campo in ("nome", "cpf", "plano_confirmado", "cidade", "cadastro_completo"):
        _assert(not estado.get(campo), (campo, estado.get(campo)))
    _assert(estado.get("notas_conversa") == "mora de aluguel", estado.get("notas_conversa"))
    _assert(estado.get("id_cliente") == fim.get("id_cliente"), estado.get("id_cliente"))


def test_transferido_continua_em_silencio() -> None:
    _, dec, _ = turno(dict(E("cad/cep"), fase="transferido", aguardando=None), "oi", L(["SAUDACAO"], {}))
    _assert(dec.acao == "AGUARDAR", dec.acao)


# ── A resposta escrita pelo modelo ───────────────────────────────────────────


def test_conversa_e_escrita_pelo_modelo_com_os_fatos_e_as_notas() -> None:
    antes = dict(E("vendas/confirmacao_plano"), notas_conversa="trabalha em home office")
    estado, dec, _ = turno(antes, "tá caro", OUTRO)
    with _Chat("Entendo, o valor pesa mesmo.") as chat:
        texto = response.gerar_resposta(dec, estado, historico=[
            {"remetente": "eva", "mensagem": "Esse plano te atende?"},
            {"remetente": "cliente", "mensagem": "tá caro"},
        ], mensagem_cliente="tá caro")
    prompt = chat.prompts[0]
    _assert("MENSAGEM DO CLIENTE: tá caro" in prompt, prompt[:300])
    _assert("achou caro" in prompt and "Não invente desconto" in prompt, prompt)
    _assert("MOV SUPER+" in prompt and "trabalha em home office" in prompt, prompt)
    _assert("Cliente: tá caro" in prompt, prompt)
    # O código garante que o próximo passo foi pedido
    _assert(texto.startswith("Entendo, o valor pesa mesmo.") and "MOV SUPER+" in texto, texto)


def test_pedido_de_tempo_nao_repete_o_pedido_inteiro() -> None:
    estado, dec, _ = turno(E("cad/cep"), "pera aí", OUTRO)
    with _Chat("Sem pressa, fico no aguardo do CEP.") as chat:
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="pera aí")
    _assert(texto == "Sem pressa, fico no aguardo do CEP.", texto)
    _assert("pediu um tempo" in chat.prompts[0], chat.prompts[0])


def test_sem_modelo_cai_no_texto_de_sempre() -> None:
    estado, dec, _ = turno(E("cad/cep"), "não sei meu cep", OUTRO)
    with _Chat(""):
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="não sei meu cep")
    _assert("CEP" in texto, texto)


def test_marca_de_base_sem_resposta_some_do_texto_e_fica_registrada() -> None:
    pergunta = L(["PERGUNTA"], {}, pergunta="tem multa de cancelamento?")
    estado, dec, _ = turno(E("cad/telefone"), "tem multa de cancelamento?", pergunta)
    with _Chat("[SEM_BASE] Esse detalhe eu prefiro confirmar com a equipe."):
        texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="tem multa de cancelamento?")
    _assert("SEM_BASE" not in texto and texto.startswith("Esse detalhe"), texto)
    _assert((dec.contexto_resposta or {}).get("sem_base") is True, dec.contexto_resposta)
    # "confirmar com a equipe" não conta como pedido de confirmação ao cliente
    _assert("telefone" in texto.casefold(), texto)
    retomada = "Quer confirmar o *MOV SUPER+* pra gente seguir com o cadastro?"
    garantido = response._garantir_retomada(
        "Isso eu prefiro confirmar com a equipe.", "confirmacao_plano", retomada)
    _assert(garantido.endswith(retomada), garantido)


# ── Notas e reinício ─────────────────────────────────────────────────────────


def test_notas_nao_repetem_e_guardam_as_mais_recentes() -> None:
    notas = conversa.juntar_nota("", "só pode receber o técnico à tarde")
    notas = conversa.juntar_nota(notas, "Só pode receber o técnico à tarde.")
    _assert(notas == "só pode receber o técnico à tarde", notas)
    for i in range(12):
        notas = conversa.juntar_nota(notas, f"fato número {i} da conversa")
    linhas = notas.split("\n")
    _assert(len(linhas) == 8 and linhas[-1] == "fato número 11 da conversa", linhas)


def test_reiniciar_atendimento_limpa_o_funil_e_mantem_a_identificacao() -> None:
    antes = dict(E("termos"), conversation_id="77", contact_id="5", notas_conversa="mora de aluguel",
                 tentativas_travadas=3)
    depois = aplicar_transicao(antes, "viabilidade", "localizacao", {"reiniciar_atendimento": True})
    for campo in ("nome", "cpf", "cidade", "plano_confirmado", "ixc_cliente_id", "cadastro_completo",
                  "termos_enviados", "tentativas_travadas"):
        _assert(not depois.get(campo), (campo, depois.get(campo)))
    _assert(depois.get("conversation_id") == "77" and depois.get("contact_id") == "5", depois)
    _assert(depois.get("notas_conversa") == "mora de aluguel", depois.get("notas_conversa"))
    _assert((depois.get("fase"), depois.get("aguardando")) == ("viabilidade", "localizacao"), depois.get("fase"))


def main() -> None:
    tests = [
        test_classificar_pelas_regras,
        test_suporte_so_quando_ja_e_cliente,
        test_situacao_e_nota_vem_do_interpretador,
        test_ok_solto_no_cadastro_nao_vira_pergunta,
        test_preco_da_concorrente_nao_escolhe_plano,
        test_nao_ter_o_dado_duas_vezes_chama_a_equipe,
        test_pedir_tempo_nao_conta_como_travado,
        test_avancar_zera_a_contagem,
        test_conversa_solta_quatro_vezes_chama_a_equipe,
        test_pergunta_nao_conta_como_travado,
        test_recusar_horarios_duas_vezes_chama_a_equipe_com_a_preferencia,
        test_audio_avisa_e_pede_texto,
        test_quem_ja_e_cliente_vai_para_a_equipe,
        test_alterar_dados_depois_do_cadastro_encaminha_sem_perguntar,
        test_termos_nao_abriu_reenvia_em_vez_de_recusar,
        test_volta_apos_venda_concluida_tira_duvida,
        test_volta_apos_inatividade_retoma_de_onde_parou,
        test_volta_sem_ponto_de_retomada_comeca_atendimento_novo,
        test_transferido_continua_em_silencio,
        test_conversa_e_escrita_pelo_modelo_com_os_fatos_e_as_notas,
        test_pedido_de_tempo_nao_repete_o_pedido_inteiro,
        test_sem_modelo_cai_no_texto_de_sempre,
        test_marca_de_base_sem_resposta_some_do_texto_e_fica_registrada,
        test_notas_nao_repetem_e_guardam_as_mais_recentes,
        test_reiniciar_atendimento_limpa_o_funil_e_mantem_a_identificacao,
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
    print("\n✅ Conversa natural OK")


if __name__ == "__main__":
    main()
