# -*- coding: utf-8 -*-
"""Claude (Anthropic) como provedor da IA — o pedido sai no formato que a API aceita.

Sem rede: o cliente da Anthropic é simulado e guarda o pedido para conferir.
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import anthropic  # noqa: E402

import test_auditoria_interpretacao as aud  # noqa: E402,F401 — bloqueia a rede

from app import admin_store, custos, ia_config, interpreter, llm  # noqa: E402

TEXTO = "Oi! Me passa sua cidade e bairro pra eu ver a cobertura?"


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


class _Anthropic:
    """Substitui anthropic.Anthropic: devolve `resposta` e guarda os pedidos."""

    pedidos: list[dict] = []
    clientes: list[dict] = []
    resposta: SimpleNamespace | None = None

    def __init__(self, **kwargs):
        _Anthropic.clientes.append(kwargs)
        self.messages = SimpleNamespace(create=self._create(beta=False))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create(beta=True)))

    @staticmethod
    def _create(beta: bool):
        def criar(**pedido):
            _Anthropic.pedidos.append({**pedido, "_beta": beta})
            return _Anthropic.resposta

        return criar


def _resposta(texto: str = TEXTO, stop: str = "end_turn", modelo: str = "claude-haiku-5-5") -> SimpleNamespace:
    return SimpleNamespace(
        model=modelo,
        stop_reason=stop,
        stop_details=SimpleNamespace(category="cyber") if stop == "refusal" else None,
        content=[
            SimpleNamespace(type="thinking", thinking="", signature="x"),
            SimpleNamespace(type="text", text=texto),
        ],
        usage=SimpleNamespace(
            input_tokens=300, output_tokens=120, cache_read_input_tokens=2000, cache_creation_input_tokens=0
        ),
    )


class _Provedor:
    """Painel configurado com o Claude, sem gravar nada no banco."""

    def __init__(self, modelo: str = "claude-haiku-5-5", esforco: str = "low", chave: str = "sk-ant-teste"):
        self.valores = {"llm_provider": "anthropic", "anthropic_model": modelo,
                        "anthropic_effort": esforco, "anthropic_api_key": chave}

    def __enter__(self):
        self._antes = (ia_config._cfg, anthropic.Anthropic, custos._gravar)
        self.gravados: list[dict] = []
        ia_config._cfg = lambda chave, default="", unidade_id=None: self.valores.get(chave, default)
        anthropic.Anthropic = _Anthropic
        custos._gravar = lambda **c: self.gravados.append(c)
        _Anthropic.pedidos, _Anthropic.clientes = [], []
        _Anthropic.resposta = _resposta(modelo=self.valores["anthropic_model"])
        return self

    def __exit__(self, *exc):
        ia_config._cfg, anthropic.Anthropic, custos._gravar = self._antes


def test_pedido_sai_no_formato_da_anthropic() -> None:
    with _Provedor() as p:
        texto = llm.chat("Você é a Eva.", "oi", temperature=0.4)
        ativo = llm.modelo_ativo()
    _assert(ativo == "anthropic:claude-haiku-5-5", ativo)
    _assert(texto == TEXTO, texto)  # o bloco de raciocínio não entra no texto
    pedido = _Anthropic.pedidos[0]
    _assert(pedido["model"] == "claude-haiku-5-5" and not pedido["_beta"], pedido)
    # Claude 5.5 recusa temperatura fora do padrão: não vai
    _assert("temperature" not in pedido and "top_p" not in pedido, pedido)
    _assert(pedido["output_config"] == {"effort": "low"}, pedido["output_config"])
    _assert(pedido["system"][0]["cache_control"] == {"type": "ephemeral"} and pedido["system"][0]["text"] == "Você é a Eva.", pedido["system"])
    _assert(pedido["messages"] == [{"role": "user", "content": "oi"}], pedido["messages"])
    _assert(pedido["max_tokens"] >= 2048, pedido["max_tokens"])
    _assert(_Anthropic.clientes[0]["api_key"] == "sk-ant-teste" and _Anthropic.clientes[0]["max_retries"] == 1, _Anthropic.clientes)
    _assert(p.gravados and p.gravados[0]["provedor"] == "anthropic", p.gravados)


def test_schema_do_interpretador_vira_output_config() -> None:
    lido = {"eventos": ["SAUDACAO"], "dados": {c: "" for c in interpreter.CAMPOS_DADOS}, "campos_corrigidos": [],
            "pergunta": "", "situacao": "", "nota": "", "confianca": 0.95}
    with _Provedor():
        _Anthropic.resposta = _resposta(json.dumps(lido))
        bruto = interpreter.interpretar("oi", aud.E("inicio"), historico=[])
    _assert(json.loads(bruto)["eventos"] == ["SAUDACAO"], bruto)
    pedido = _Anthropic.pedidos[0]
    formato = pedido["output_config"]["format"]
    _assert(formato["type"] == "json_schema", formato)
    _assert(formato["schema"] is interpreter.SCHEMA_INTERPRETACAO["json_schema"]["schema"], "schema diferente")
    _assert(len(_Anthropic.pedidos) == 1, "uma chamada só quando o JSON vem válido")


def test_schema_recusado_pela_anthropic_cai_no_json_livre() -> None:
    import httpx2

    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    erro = anthropic.BadRequestError(
        "output_config.format: schema not supported", response=httpx2.Response(400, request=req), body=None
    )
    lido = json.dumps({"eventos": ["OUTRO"], "dados": {}, "campos_corrigidos": [], "pergunta": "",
                       "situacao": "", "nota": "", "confianca": 0.9})
    chamadas: list = []

    def chat_falso(system, user, **k):
        chamadas.append(k.get("response_format"))
        if k.get("response_format") is not None:
            raise erro
        return lido

    antes, interpreter.chat = interpreter.chat, chat_falso
    try:
        with _Provedor(modelo="claude-teste-sem-schema"):
            _assert(interpreter.interpretar("oi", aud.E("inicio"), historico=[]) == lido, "fallback")
    finally:
        interpreter.chat = antes
        interpreter._SEM_SCHEMA.discard("anthropic:claude-teste-sem-schema")
    _assert(chamadas[0] is not None and chamadas[1] is None, chamadas)


def test_recusa_do_modelo_vira_falha_e_nao_texto_vazio() -> None:
    with _Provedor():
        _Anthropic.resposta = _resposta("", stop="refusal")
        try:
            llm.chat("sistema", "mensagem")
            raise AssertionError("a recusa deveria virar erro")
        except llm.RecusaDoModelo as exc:
            _assert("cyber" in str(exc), exc)


def test_sonnet_usa_o_fallback_da_propria_api() -> None:
    with _Provedor(modelo="claude-sonnet-5-5", esforco="medium"):
        llm.chat("sistema", "mensagem")
    pedido = _Anthropic.pedidos[0]
    _assert(pedido["_beta"] and pedido["betas"] == ["server-side-fallback-2026-07-01"] and pedido["fallbacks"] == "default", pedido)
    _assert(pedido["output_config"]["effort"] == "medium", pedido["output_config"])


def test_sem_chave_da_anthropic_avisa_o_que_falta() -> None:
    with _Provedor(chave=""):
        try:
            llm.chat("s", "u")
            raise AssertionError("sem chave deveria falhar")
        except RuntimeError as exc:
            _assert("Anthropic" in str(exc), exc)
        _assert(not _Anthropic.pedidos, "não deveria chamar a API sem chave")


def test_custo_do_claude_conta_cache_lido_e_gravado() -> None:
    cfg = {"cotacao_dolar": 5.0, "modelos": dict(custos.PRECOS_PADRAO), "transcricao_usd_hora": {}}
    # 300 sem cache + 2000 lidos do cache + 1000 gravados; 120 de saída
    custo = custos.custo_de_tokens("claude-haiku-5-5", 3300, 2000, 120, cfg, cache_escrita=1000)
    esperado = (300 * 0.10 + 2000 * 0.01 + 1000 * 0.10 * 1.25 + 120 * 0.50) / 1_000_000
    _assert(abs(custo - esperado) < 1e-12, (custo, esperado))
    with _Provedor() as p:
        uso = SimpleNamespace(input_tokens=300, output_tokens=120, cache_read_input_tokens=2000, cache_creation_input_tokens=1000)
        custos.registrar_chat("anthropic", "claude-haiku-5-5", uso)
    g = p.gravados[-1]
    _assert(g["tokens_entrada"] == 3300 and g["tokens_cache"] == 2000 and g["tokens_saida"] == 120, g)
    _assert(abs(g["custo_usd"] - esperado) < 1e-12, g)
    # O Haiku 5.5 sai mais barato que o gpt-4.1-mini para a mesma conversa
    gpt = custos.custo_de_tokens("gpt-4.1-mini", 3300, 2000, 120, cfg)
    _assert(custo < gpt, (custo, gpt))


def test_preco_do_claude_e_buscado_na_tabela_da_anthropic() -> None:
    urls: list[str] = []

    def http_falso(url, params=None):
        urls.append(url)
        return {"data": {"endpoints": [
            {"provider_name": "Google", "pricing": {"prompt": "0.0000009", "completion": "0.000009"}},
            {"provider_name": "Anthropic", "pricing": {"prompt": "0.0000001", "completion": "0.0000005", "input_cache_read": "0.00000001"}},
        ]}}

    antes, custos._http_json = custos._http_json, http_falso
    try:
        preco = custos.buscar_preco_do_modelo("claude-haiku-5-5")
    finally:
        custos._http_json = antes
    _assert(urls == ["https://openrouter.ai/api/v1/models/anthropic/claude-haiku-5-5/endpoints"], urls)
    _assert(preco == {"entrada": 0.1, "cache": 0.01, "saida": 0.5}, preco)


def test_painel_guarda_a_escolha_do_claude() -> None:
    gravado: dict = {}
    antes = (admin_store.set_config, ia_config._cfg)
    admin_store.set_config = lambda chave, valor, unidade_id=None: gravado.__setitem__(chave, valor)
    ia_config._cfg = lambda chave, default="", unidade_id=None: gravado.get(chave, default)
    try:
        cfg = ia_config.salvar_config_ia({
            "llm_provider": "anthropic", "anthropic_model": "claude-sonnet-5-5", "anthropic_effort": "medium",
            "anthropic_api_key": "sk-ant-api03-abcdefghijkl", "openai_model": "gpt-4.1-mini",
        })
        _assert(gravado["llm_provider"] == "anthropic" and gravado["anthropic_api_key"] == "sk-ant-api03-abcdefghijkl", gravado)
        _assert(cfg["anthropic_model"] == "claude-sonnet-5-5" and cfg["anthropic_effort"] == "medium", cfg)
        _assert(cfg["anthropic_api_key_configured"] and "abcdefghijkl" not in cfg["anthropic_api_key_mask"], cfg["anthropic_api_key_mask"])
        _assert(ia_config.resolver_modelo_em_uso() == "claude-sonnet-5-5", ia_config.resolver_modelo_em_uso())
        # A máscara devolvida pelo painel não substitui a chave; valores inválidos voltam ao padrão
        ia_config.salvar_config_ia({"llm_provider": "x", "anthropic_model": "gpt-9", "anthropic_effort": "max",
                                    "anthropic_api_key": "••••"})
        _assert(gravado["anthropic_api_key"] == "sk-ant-api03-abcdefghijkl", "máscara sobrescreveu a chave")
        _assert(gravado["llm_provider"] == "openai" and gravado["anthropic_model"] == "claude-haiku-5-5"
                and gravado["anthropic_effort"] == "low", gravado)
    finally:
        admin_store.set_config, ia_config._cfg = antes


def main() -> None:
    tests = [
        test_pedido_sai_no_formato_da_anthropic,
        test_schema_do_interpretador_vira_output_config,
        test_schema_recusado_pela_anthropic_cai_no_json_livre,
        test_recusa_do_modelo_vira_falha_e_nao_texto_vazio,
        test_sonnet_usa_o_fallback_da_propria_api,
        test_sem_chave_da_anthropic_avisa_o_que_falta,
        test_custo_do_claude_conta_cache_lido_e_gravado,
        test_preco_do_claude_e_buscado_na_tabela_da_anthropic,
        test_painel_guarda_a_escolha_do_claude,
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
    print("\n✅ Claude OK")


if __name__ == "__main__":
    main()
