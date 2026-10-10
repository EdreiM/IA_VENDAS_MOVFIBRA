# -*- coding: utf-8 -*-
"""Custo da IA — tokens de cada chamada viram custo por cliente, por mês e por venda.

Sem rede: o cliente da OpenAI é simulado. Usa o banco local e apaga o que criar.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import test_auditoria_interpretacao as aud  # noqa: F401 — bloqueia a rede

from app import admin_store, custos, db, llm, metrics, transcricao

CLIENTE_A, CLIENTE_B = "teste-custos-a", "teste-custos-b"


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


def _perto(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


def _limpar() -> None:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM uso_ia WHERE id_cliente IN (%s, %s)", (CLIENTE_A, CLIENTE_B))


def _usage(entrada: int, saida: int, cache: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=entrada, completion_tokens=saida,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cache),
    )


def _do_cliente(resultado: dict, cid: str) -> dict:
    return next((c for c in resultado["clientes"] if c["id_cliente"] == cid), {})


def test_custo_sai_dos_tokens_e_do_preco_do_modelo() -> None:
    cfg = {"cotacao_dolar": 5.0, "modelos": dict(custos.PRECOS_PADRAO), "transcricao_usd_hora": {}}
    # 8.000 tokens de entrada cheios + 2.000 em cache + 500 de saída no gpt-4.1-mini
    esperado = (8000 * 0.40 + 2000 * 0.10 + 500 * 1.60) / 1_000_000
    _assert(_perto(custos.custo_de_tokens("gpt-4.1-mini", 10000, 2000, 500, cfg), esperado), esperado)
    # O nome com data ("gpt-4.1-mini-2025-04-14") usa o preço do modelo, não o do "gpt-4.1"
    _assert(_perto(custos.custo_de_tokens("gpt-4.1-mini-2025-04-14", 10000, 2000, 500, cfg), esperado), "prefixo")
    _assert(custos.custo_de_tokens("gpt-4.1", 1_000_000, 0, 0, cfg) == 2.0, "gpt-4.1")
    # Modelo sem preço cadastrado não vira zero: fica sem custo, para aparecer no painel
    _assert(custos.custo_de_tokens("modelo-novo-x", 1000, 0, 1000, cfg) is None, "sem preço")


def test_cada_chamada_e_gravada_para_o_cliente_do_turno() -> None:
    _limpar()
    try:
        custos.definir_cliente(CLIENTE_A)
        custos.marcar("interpretador")
        custos.registrar_chat("openai", "gpt-4.1-mini", _usage(10000, 500, 2000))
        custos.marcar("resposta")
        custos.registrar_chat("openai", "gpt-4.1-mini", _usage(4000, 300))
        custos.definir_cliente(CLIENTE_B)
        custos.marcar("consultor")
        custos.registrar_chat("openai", "gpt-4.1-mini", _usage(6000, 200))

        r = metrics.custos(6)
        a, b = _do_cliente(r, CLIENTE_A), _do_cliente(r, CLIENTE_B)
        custo_a = (8000 * 0.40 + 2000 * 0.10 + 500 * 1.60 + 4000 * 0.40 + 300 * 1.60) / 1_000_000
        custo_b = (6000 * 0.40 + 200 * 1.60) / 1_000_000
        _assert(abs(a["usd"] - custo_a) < 1e-4 and a["chamadas"] == 2, a)
        _assert(abs(b["usd"] - custo_b) < 1e-4 and b["chamadas"] == 1, b)
        _assert(abs(a["brl"] - round(custo_a * r["cotacao_dolar"], 2)) < 0.011, (a["brl"], r["cotacao_dolar"]))
        _assert(r["total"]["usd"] >= custo_a + custo_b - 1e-4 and r["mes"]["chamadas"] >= 3, r["total"])
        _assert(r["por_mes"] and r["por_mes"][-1]["mes"] == r["mes_atual"], r["por_mes"])
        finalidades = {f["finalidade"] for f in r["por_finalidade"]}
        _assert({"interpretador", "resposta", "consultor"} <= finalidades, finalidades)
        _assert(r["clientes_atendidos"] >= 2 and r["media_por_cliente"]["usd"] > 0, r["media_por_cliente"])
    finally:
        custos.definir_cliente("")
        _limpar()


def test_chat_grava_o_uso_que_a_openai_devolve() -> None:
    _limpar()

    class _ClienteFalso:
        def __init__(self, **k):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **k):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=_usage(1200, 80, 1000),
                model=k.get("model"),
            )

    antes = (llm.OpenAI, llm.ia_config.resolver_openai_api_key, llm.ia_config.resolver_llm_provider)
    llm.OpenAI = _ClienteFalso
    llm.ia_config.resolver_openai_api_key = lambda **k: "sk-teste"
    llm.ia_config.resolver_llm_provider = lambda **k: "openai"
    try:
        custos.definir_cliente(CLIENTE_A)
        custos.marcar("interpretador")
        _assert(llm.chat("sistema", "usuario") == "ok", "resposta")
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM uso_ia WHERE id_cliente = %s", (CLIENTE_A,))
                linhas = [dict(x) for x in cur.fetchall()]
        _assert(len(linhas) == 1, linhas)
        linha = linhas[0]
        _assert((linha["tokens_entrada"], linha["tokens_cache"], linha["tokens_saida"]) == (1200, 1000, 80), linha)
        _assert(linha["finalidade"] == "interpretador" and linha["provedor"] == "openai", linha)
        _assert(linha["custo_usd"] is not None and linha["custo_usd"] > 0, linha)
    finally:
        llm.OpenAI, llm.ia_config.resolver_openai_api_key, llm.ia_config.resolver_llm_provider = antes
        custos.definir_cliente("")
        _limpar()


def test_transcricao_custa_pelo_tempo_de_audio() -> None:
    _limpar()
    antes = (transcricao.chave_de_transcricao, transcricao._baixar_audio, transcricao._enviar_para_transcricao)
    transcricao.chave_de_transcricao = lambda **k: "gsk_teste"
    transcricao._baixar_audio = lambda url: (b"x" * 9000, "audio/ogg")
    transcricao._enviar_para_transcricao = lambda *a, **k: ("quero contratar", 90.0)
    try:
        r = transcricao.transcrever_audio("https://chatwoot.mov.pro.br/a/audio.oga", id_cliente=CLIENTE_A)
        _assert(r["ok"], r)
        # Áudio curto: a Groq cobra no mínimo 10 segundos
        transcricao._enviar_para_transcricao = lambda *a, **k: ("oi", 3.0)
        transcricao.transcrever_audio("https://chatwoot.mov.pro.br/a/audio.oga", id_cliente=CLIENTE_A)
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT segundos_audio, custo_usd, finalidade FROM uso_ia WHERE id_cliente = %s ORDER BY id", (CLIENTE_A,))
                linhas = [dict(x) for x in cur.fetchall()]
        _assert([round(x["segundos_audio"]) for x in linhas] == [90, 10], linhas)
        _assert(_perto(linhas[0]["custo_usd"], 90 / 3600 * 0.04) and linhas[0]["finalidade"] == "transcricao", linhas[0])
        _assert(_perto(linhas[1]["custo_usd"], 10 / 3600 * 0.04), linhas[1])
    finally:
        transcricao.chave_de_transcricao, transcricao._baixar_audio, transcricao._enviar_para_transcricao = antes
        _limpar()


def test_precos_e_cotacao_vem_do_painel() -> None:
    antes = admin_store.get_config(custos.CHAVE_CONFIG, "")
    _limpar()
    try:
        cfg = custos.salvar_configuracao({
            "cotacao_dolar": 6.0,
            "modelos": {"gpt-4.1-mini": {"entrada": 1.0, "cache": 0.5, "saida": 2.0}},
            "transcricao_usd_hora": {"groq": 0.08},
        })
        _assert(cfg["cotacao_dolar"] == 6.0 and cfg["modelos"]["gpt-4.1-mini"]["saida"] == 2.0, cfg)
        _assert(cfg["modelos"]["gpt-4.1"]["entrada"] == 2.0, "padrões continuam para os outros modelos")
        _assert(custos.custo_de_tokens("gpt-4.1-mini", 1_000_000, 0, 1_000_000) == 3.0, "preço novo")

        # Modelo ainda sem preço: aparece como pendente; cadastrado o preço, o custo é calculado
        custos.definir_cliente(CLIENTE_B)
        custos.registrar_chat("openai", "modelo-novo-x", _usage(1_000_000, 0))
        r = metrics.custos(6)
        _assert("modelo-novo-x" in r["modelos_sem_preco"] and r["cotacao_dolar"] == 6.0, r["modelos_sem_preco"])
        custos.salvar_configuracao({"cotacao_dolar": 6.0, "modelos": {"modelo-novo-x": {"entrada": 3.0, "cache": 0, "saida": 0}}})
        r = metrics.custos(6)
        b = _do_cliente(r, CLIENTE_B)
        _assert("modelo-novo-x" not in r["modelos_sem_preco"], r["modelos_sem_preco"])
        _assert(abs(b["usd"] - 3.0) < 1e-6 and abs(b["brl"] - 18.0) < 0.011, b)
    finally:
        admin_store.set_config(custos.CHAVE_CONFIG, antes)
        custos._cache_config.update(quando=0.0, valor=None)
        custos.definir_cliente("")
        _limpar()


def test_registro_que_falha_nao_derruba_a_chamada() -> None:
    original = db.registrar_uso_ia
    db.registrar_uso_ia = lambda **k: (_ for _ in ()).throw(RuntimeError("banco fora"))
    try:
        custos.registrar_chat("openai", "gpt-4.1-mini", _usage(10, 5))  # não pode levantar
        custos.registrar_transcricao("groq", "whisper-large-v3-turbo", 12.0, id_cliente=CLIENTE_A)
    finally:
        db.registrar_uso_ia = original


def main() -> None:
    db.init_schema()
    tests = [
        test_custo_sai_dos_tokens_e_do_preco_do_modelo,
        test_cada_chamada_e_gravada_para_o_cliente_do_turno,
        test_chat_grava_o_uso_que_a_openai_devolve,
        test_transcricao_custa_pelo_tempo_de_audio,
        test_precos_e_cotacao_vem_do_painel,
        test_registro_que_falha_nao_derruba_a_chamada,
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
    print("\n✅ Custos OK")


if __name__ == "__main__":
    main()
