# -*- coding: utf-8 -*-
"""Interpretador — histórico no prompt, schema estrito, fallback e casos de avaliação (sem LLM)."""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from openai import BadRequestError

import eval_interpretador as ev
from app import interpreter
from app.localizacao_heuristica import extrair_par_cidade_bairro
from app.models import CAMPOS_DADOS
from app.parser import eh_so_saudacao, parse_interpretacao, tem_duvida_informativa

JSON_OK = json.dumps(
    {
        "eventos": ["CONFIRMACAO"],
        "dados": {c: "" for c in CAMPOS_DADOS},
        "campos_corrigidos": [],
        "pergunta": "",
        "confianca": 0.95,
    }
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _bad_request(texto: str) -> BadRequestError:
    resp = httpx.Response(400, request=httpx.Request("POST", "http://llm.test/v1/chat/completions"))
    return BadRequestError(texto, response=resp, body=None)


class _ChatFalso:
    """Substitui app.interpreter.chat: devolve as respostas em ordem e guarda as chamadas."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas: list[dict] = []

    def __call__(self, system, user, *, temperature=None, response_format=None):
        self.chamadas.append({"user": user, "response_format": response_format})
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _interpretar(chat_falso: _ChatFalso, mensagem: str, estado: dict, historico=None, modelo="teste:m1"):
    with patch.object(interpreter, "chat", chat_falso), patch.object(
        interpreter, "modelo_ativo", return_value=modelo
    ):
        return interpreter.interpretar(mensagem, estado, historico=historico)


def test_historico_descarta_mensagem_atual() -> None:
    hist = [
        {"remetente": "eva", "mensagem": "Qual seu nome completo?"},
        {"remetente": "cliente", "mensagem": "João Silva"},
    ]
    bloco = interpreter._historico_bloco(hist, "João Silva")
    _assert("Eva: Qual seu nome completo?" in bloco, bloco)
    _assert("Cliente: João Silva" not in bloco, "mensagem atual não pode repetir no histórico")


def test_historico_vazio() -> None:
    _assert("sem mensagens anteriores" in interpreter._historico_bloco([], "oi"), "vazio")
    _assert("sem mensagens anteriores" in interpreter._historico_bloco(None, "oi"), "None")


def test_historico_estourado_mantem_o_mais_recente() -> None:
    hist = [{"remetente": "eva", "mensagem": f"antiga {i} " + "x" * 3000} for i in range(6)]
    hist.append({"remetente": "eva", "mensagem": "RECENTE: Opção 1 — MOV FLEX"})
    bloco = interpreter._historico_bloco(hist, "o primeiro")
    _assert("RECENTE: Opção 1" in bloco, "a mensagem mais recente da Eva precisa estar no prompt")
    _assert("antiga 0" not in bloco, "a mais antiga deve cair quando estoura o limite")
    _assert(len(bloco) < interpreter._MAX_CHARS_HISTORICO + 4200, f"bloco grande demais: {len(bloco)}")


def test_prompt_leva_historico_e_schema() -> None:
    chat = _ChatFalso(JSON_OK)
    hist = [
        {"remetente": "eva", "mensagem": "📦 Opção 1 — MOV FLEX\n\n📦 Opção 2 — MOV SUPER+"},
        {"remetente": "cliente", "mensagem": "o segundo"},
    ]
    raw = _interpretar(chat, "o segundo", {"fase": "vendas", "aguardando": "escolha_plano"}, hist)
    _assert(raw == JSON_OK, raw)
    _assert(len(chat.chamadas) == 1, f"uma chamada só quando o schema responde: {len(chat.chamadas)}")
    c = chat.chamadas[0]
    _assert(c["response_format"] is interpreter.SCHEMA_INTERPRETACAO, "schema não foi enviado")
    _assert("Opção 2 — MOV SUPER+" in c["user"], "histórico não entrou no prompt")
    _assert("Cliente: o segundo" not in c["user"], "mensagem atual duplicada no histórico")
    _assert("MENSAGEM ATUAL DO CLIENTE:\no segundo" in c["user"], "mensagem atual fora do prompt")
    _assert("fase: vendas" in c["user"], "estado não entrou no prompt")


def test_schema_estrito_bem_formado() -> None:
    js = interpreter.SCHEMA_INTERPRETACAO["json_schema"]
    _assert(js["strict"] is True, "strict")

    def checar(obj: dict, onde: str) -> None:
        if obj.get("type") == "object":
            _assert(obj.get("additionalProperties") is False, f"{onde}: additionalProperties")
            _assert(
                sorted(obj["required"]) == sorted(obj["properties"]),
                f"{onde}: no modo estrito todo campo precisa estar em required",
            )
            for nome, sub in obj["properties"].items():
                checar(sub, f"{onde}.{nome}")

    checar(js["schema"], "raiz")
    _assert(list(js["schema"]["properties"]["dados"]["properties"]) == list(CAMPOS_DADOS), "campos")


def test_modelo_sem_schema_cai_no_json_livre() -> None:
    erro = _bad_request("Invalid parameter: 'response_format' of type 'json_schema' is not supported")
    interpreter._SEM_SCHEMA.discard("teste:sem-schema")
    chat = _ChatFalso(erro, JSON_OK)
    raw = _interpretar(chat, "sim", {"fase": "vendas"}, modelo="teste:sem-schema")
    _assert(raw == JSON_OK, raw)
    _assert(chat.chamadas[1]["response_format"] is None, "fallback deve ir sem schema")

    # Próximo turno não tenta schema de novo nesse modelo
    chat2 = _ChatFalso(JSON_OK)
    _interpretar(chat2, "sim", {"fase": "vendas"}, modelo="teste:sem-schema")
    _assert(len(chat2.chamadas) == 1 and chat2.chamadas[0]["response_format"] is None, "memoriza")
    interpreter._SEM_SCHEMA.discard("teste:sem-schema")


def test_erro_400_de_outro_tipo_nao_desliga_schema() -> None:
    chat = _ChatFalso(_bad_request("context_length_exceeded"), JSON_OK)
    _interpretar(chat, "sim", {"fase": "vendas"}, modelo="teste:m2")
    _assert("teste:m2" not in interpreter._SEM_SCHEMA, "erro sem relação com schema não deve desligar")


def test_json_invalido_refaz_pedido() -> None:
    chat = _ChatFalso("", "isso não é json", JSON_OK)
    raw = _interpretar(chat, "sim", {"fase": "vendas"}, modelo="teste:m3")
    _assert(raw == JSON_OK, raw)
    _assert(len(chat.chamadas) == 3, f"schema + livre + retry: {len(chat.chamadas)}")
    _assert("não era JSON válido" in chat.chamadas[2]["user"], "retry sem aviso")


def test_snapshot_estado_so_campos_preenchidos() -> None:
    snap = interpreter.snapshot_estado(
        {
            "fase": "cadastro",
            "aguardando": "cpf",
            "nome": "João",
            "email": "",
            "cpf": None,
            "ultima_mensagem_sofia": "texto longo",
            "id_cliente": "5593999999999",
        }
    )
    _assert(snap == {"fase": "cadastro", "aguardando": "cpf", "nome": "João"}, str(snap))
    json.dumps(snap)


def test_virgula_de_conversa_nao_e_cidade_bairro() -> None:
    for msg in (
        "oi, quero instalar internet",
        "olá, tudo bem?",
        "bom dia, gostaria de saber os planos",
        "sim, pode ser",
        "oi, vocês atendem em Santarém?",
        "Santarém, quero ver os planos",
    ):
        _assert(extrair_par_cidade_bairro(msg) is None, f"{msg!r} virou {extrair_par_cidade_bairro(msg)}")
        i = parse_interpretacao(
            json.dumps({"eventos": ["SAUDACAO"], "dados": {}, "confianca": 0.95}),
            msg,
            {"fase": "inicio"},
        )
        _assert(not i.dados.bairro, f"{msg!r}: bairro indevido {i.dados.bairro!r}")
        _assert(i.dados.cidade in ("", "Santarém"), f"{msg!r}: cidade indevida {i.dados.cidade!r}")


def test_par_cidade_bairro_real_continua_valendo() -> None:
    for msg in ("Santarém, Diamantino", "moro em Santarém, no Diamantino", "Belterra, Centro", "Boa Vista, Centro"):
        par = extrair_par_cidade_bairro(msg)
        _assert(bool(par) and par.get("cidade") and par.get("bairro"), f"{msg!r} → {par}")


def test_saudacao_com_interrogacao_nao_e_duvida() -> None:
    for msg in ("oi tudo bem?", "Olá, tudo bom?", "e aí, beleza?", "boa tarde, como vai?"):
        _assert(eh_so_saudacao(msg), f"{msg!r} deveria ser só saudação")
        _assert(not tem_duvida_informativa(msg, msg), f"{msg!r} não é dúvida")
        # LLM marcando PERGUNTA por causa do "?" — parser tira
        i = parse_interpretacao(
            json.dumps({"eventos": ["PERGUNTA"], "dados": {}, "pergunta": msg, "confianca": 0.9}),
            msg,
            {"fase": "inicio"},
        )
        _assert(i.eventos == ["SAUDACAO"] and not i.pergunta, f"{msg!r} → {i.eventos} / {i.pergunta!r}")
    for msg in ("oi, tem plano de 500 mega?", "bom dia, quanto custa?", "beleza?", "tudo bem, pode ser"):
        _assert(not eh_so_saudacao(msg), f"{msg!r} tem conteúdo além da saudação")
    _assert(tem_duvida_informativa("bom dia, quanto custa?", "bom dia, quanto custa?"), "dúvida real")


def test_conferir_do_avaliador() -> None:
    esperado = {
        "eventos": ["DADO_INFORMADO"],
        "eventos_proibidos": ["PERGUNTA"],
        "dados": {"cpf": "123.456.789-09", "nome": "joão"},
        "dados_vazios": ["telefone"],
    }
    ok = ev.conferir(esperado, ["DADO_INFORMADO"], {"cpf": "12345678909", "nome": "João Silva", "telefone": ""})
    _assert(ok == [], str(ok))
    ruim = ev.conferir(esperado, ["PERGUNTA"], {"cpf": "111", "nome": "", "telefone": "9399"})
    _assert(len(ruim) == 5, str(ruim))


def test_casos_de_avaliacao_batem_com_o_parser() -> None:
    """Com o LLM respondendo exatamente o esperado, o parser não pode desfazer o caso."""
    casos = ev.carregar_casos(ev.CASOS_PADRAO)
    _assert(len(casos) >= 40, f"poucos casos: {len(casos)}")
    ids = [c["id"] for c in casos]
    _assert(len(ids) == len(set(ids)), "ids repetidos")
    for c in casos:
        esp = c["esperado"]
        eventos = list(esp.get("eventos") or [])
        raw = json.dumps(
            {
                "eventos": eventos,
                "dados": esp.get("dados") or {},
                "campos_corrigidos": list(esp.get("dados") or {}) if "CORRECAO_DADO" in eventos else [],
                "pergunta": c["mensagem"] if "PERGUNTA" in eventos else "",
                "confianca": 0.95,
            },
            ensure_ascii=False,
        )
        final = parse_interpretacao(raw, c["mensagem"], ev._estado_do_caso(c))
        problemas = ev.conferir(esp, list(final.eventos), final.dados.model_dump())
        _assert(not problemas, f"{c['id']}: {problemas}")


def test_avaliador_roda_ponta_a_ponta_com_llm_falso() -> None:
    caso = {
        "id": "x",
        "estado": {"fase": "vendas", "aguardando": "confirmacao_plano"},
        "historico": [{"remetente": "eva", "mensagem": "Posso seguir com esse plano?"}],
        "mensagem": "sim",
        "esperado": {"eventos": ["CONFIRMACAO"], "dados_vazios": ["plano"]},
        "registrado": {"eventos": ["NEGACAO"]},
    }
    chat = _ChatFalso(JSON_OK)
    with patch.object(interpreter, "chat", chat), patch.object(
        interpreter, "modelo_ativo", return_value="teste:m4"
    ):
        r = ev.avaliar_caso(caso)
    _assert(r["problemas_llm"] == [] and r["problemas_final"] == [], str(r))
    _assert(r["divergiu_do_registrado"] is True, "deveria apontar divergência do registro")
    _assert("ÚLTIMA MENSAGEM DA EVA: Posso seguir" in chat.chamadas[0]["user"], "última msg da Eva")
    resumo = ev.resumir([r])
    _assert(resumo["acerto_llm_mais_parser"] == 1 and resumo["divergentes_do_registro"] == 1, str(resumo))


def main() -> None:
    tests = [
        test_historico_descarta_mensagem_atual,
        test_historico_vazio,
        test_historico_estourado_mantem_o_mais_recente,
        test_prompt_leva_historico_e_schema,
        test_schema_estrito_bem_formado,
        test_modelo_sem_schema_cai_no_json_livre,
        test_erro_400_de_outro_tipo_nao_desliga_schema,
        test_json_invalido_refaz_pedido,
        test_snapshot_estado_so_campos_preenchidos,
        test_virgula_de_conversa_nao_e_cidade_bairro,
        test_par_cidade_bairro_real_continua_valendo,
        test_saudacao_com_interrogacao_nao_e_duvida,
        test_conferir_do_avaliador,
        test_casos_de_avaliacao_batem_com_o_parser,
        test_avaliador_roda_ponta_a_ponta_com_llm_falso,
    ]
    falhas = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK {fn.__name__}")
        except Exception as e:
            falhas += 1
            print(f"  FALHOU {fn.__name__}: {type(e).__name__}: {e}")
    if falhas:
        print(f"\n❌ {falhas} falha(s)")
        sys.exit(1)
    print("\n✅ Interpretador OK")


if __name__ == "__main__":
    main()
