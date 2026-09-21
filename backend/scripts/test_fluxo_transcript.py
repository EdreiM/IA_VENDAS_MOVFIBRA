# -*- coding: utf-8 -*-
"""
Teste do fluxo da conversa Sofia (transcript MOV FIBRA).

Uso:
  py scripts/test_fluxo_transcript.py           # parser + state machine (sem LLM)
  py scripts/test_fluxo_transcript.py --live    # pipeline completo (precisa LLM)

Cenários cobertos:
  - Mostre todos → LISTAR_TODOS_PLANOS
  - sim] → confirma plano
  - Dado + pergunta (email + roteador)
  - Mudança de endereço pós-contratação → PERGUNTA/RAG (não viabilidade)
  - Nome no cadastro após pergunta de cancelamento
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import get_settings

get_settings.cache_clear()

from app.contexto_conversa import enriquecer_pergunta
from app.models import Evento
from app.parser import parse_interpretacao
from app.resolver import resolver
from app.state_machine import decidir
from app.pipeline import _executar_acao

# Respostas simuladas do interpretador LLM (inclui erros típicos que o parser corrige)
LLM_SIMULADO: dict[str, dict[str, Any]] = {
    "oi": {
        "eventos": ["SAUDACAO"],
        "dados": {},
        "pergunta": "",
        "confianca": 0.9,
    },
    "quero ver os planos": {
        "eventos": ["PEDIDO_CONTRATACAO", "PERGUNTA"],
        "dados": {},
        "pergunta": "quero ver os planos",
        "confianca": 0.85,
    },
    "Santarém": {
        "eventos": ["LOCALIZACAO_INFORMADA"],
        "dados": {"cidade": "Santarém"},
        "confianca": 0.9,
    },
    "Diamantino": {
        "eventos": ["LOCALIZACAO_INFORMADA"],
        "dados": {"bairro": "Diamantino"},
        "confianca": 0.9,
    },
    "Mostre todos": {
        "eventos": ["PERGUNTA"],
        "dados": {},
        "pergunta": "mostre todos os planos",
        "confianca": 0.8,
    },
    "O que tem disney?": {
        "eventos": ["PERGUNTA"],
        "dados": {},
        "pergunta": "O que tem disney?",
        "confianca": 0.9,
    },
    "mov one": {
        "eventos": ["PLANO_INFORMADO"],
        "dados": {"plano": "mov one"},
        "confianca": 0.9,
    },
    "sim]": {
        "eventos": ["CONFIRMACAO"],
        "dados": {},
        "confianca": 0.9,
    },
    "E se eu cancelar?": {
        "eventos": ["PERGUNTA"],
        "dados": {},
        "pergunta": "E se eu cancelar?",
        "confianca": 0.9,
    },
    "Edrei tester": {
        "eventos": ["PERGUNTA"],
        "dados": {},
        "pergunta": "",
        "confianca": 0.5,
    },
    "604.210.790-96": {
        "eventos": ["DADO_INFORMADO"],
        "dados": {"cpf": "60421079096"},
        "confianca": 0.95,
    },
    "edreiteste@gmail.com MAS E EU TENHO DIREITO A ROTEADOR?": {
        "eventos": ["DADO_INFORMADO"],
        "dados": {"email": "edreiteste@gmail.com"},
        "confianca": 0.9,
    },
    "93992219098": {
        "eventos": ["DADO_INFORMADO"],
        "dados": {"telefone": "93992219098"},
        "confianca": 0.95,
    },
    "E se eu quiser mudar de endereço?": {
        "eventos": ["PEDIU_TROCAR_LOCALIZACAO", "PERGUNTA"],
        "dados": {},
        "pergunta": "E se eu quiser mudar de endereço?",
        "confianca": 0.85,
    },
    "Não, to falando se eu tiver contratado e quiser outro endereço": {
        "eventos": ["PEDIU_TROCAR_LOCALIZACAO", "OUTRO"],
        "dados": {},
        "pergunta": "",
        "confianca": 0.7,
    },
    "16/08/2000": {
        "eventos": ["DADO_INFORMADO"],
        "dados": {"data_nascimento": "16/08/2000"},
        "confianca": 0.95,
    },
}

FLUXO_TRANSCRIPT = [
    "oi",
    "quero ver os planos",
    "Santarém",
    "Diamantino",
    "Mostre todos",
    "O que tem disney?",
    "mov one",
    "sim]",
    "E se eu cancelar?",
    "Edrei tester",
    "604.210.790-96",
    "edreiteste@gmail.com MAS E EU TENHO DIREITO A ROTEADOR?",
    "93992219098",
    "E se eu quiser mudar de endereço?",
    "Não, to falando se eu tiver contratado e quiser outro endereço",
    "16/08/2000",
]

# Asserções por mensagem (índice ou texto)
ASSERTS: dict[str, dict[str, Any]] = {
    "Mostre todos": {
        "eventos": {Evento.PEDIU_TROCAR_PLANO.value, Evento.PERGUNTA.value},
        "objetivo": "APRESENTAR_LISTA_COMPLETA_PLANOS",
        "fase": "vendas",
    },
    "sim]": {
        "eventos": {Evento.CONFIRMACAO.value},
        "objetivo": "CONFIRMAR_PLANO_E_AVANCAR",
        "fase": "cadastro",
        "aguardando": "nome",
    },
    "E se eu cancelar?": {
        "eventos": {Evento.PERGUNTA.value},
        "objetivo": "RESPONDER_PERGUNTA_E_RETOMAR",
        "fase": "cadastro",
        "aguardando": "nome",
        "topico": "cancelamento",
    },
    "Edrei tester": {
        "eventos": {Evento.DADO_INFORMADO.value},
        "nao_eventos": {Evento.PEDIU_TROCAR_LOCALIZACAO.value},
        "objetivo_in": {"ANOTAR_E_PEDIR_PROXIMO", "PEDIR_CPF"},
        "fase": "cadastro",
        "aguardando": "cpf",
    },
    "edreiteste@gmail.com MAS E EU TENHO DIREITO A ROTEADOR?": {
        "eventos": {Evento.DADO_INFORMADO.value, Evento.PERGUNTA.value},
        "objetivo": "RESPONDER_PERGUNTA_E_RETOMAR",
        "topico": "beneficio_plano",
        "fase": "cadastro",
        "aguardando_in": {"email", "telefone"},
        "estado_depois": {"email": "edreiteste@gmail.com"},
    },
    "E se eu quiser mudar de endereço?": {
        "nao_eventos": {Evento.PEDIU_TROCAR_LOCALIZACAO.value},
        "eventos": {Evento.PERGUNTA.value},
        "objetivo": "RESPONDER_PERGUNTA_E_RETOMAR",
        "fase": "cadastro",
        "nao_fase": "viabilidade",
        "topico": "mudanca_endereco",
    },
    "Não, to falando se eu tiver contratado e quiser outro endereço": {
        "nao_eventos": {Evento.PEDIU_TROCAR_LOCALIZACAO.value},
        "eventos": {Evento.PERGUNTA.value},
        "fase": "cadastro",
        "nao_fase": "viabilidade",
    },
    "16/08/2000": {
        "eventos": {Evento.DADO_INFORMADO.value},
        "fase": "cadastro",
        "nao_fase": "viabilidade",
        "aguardando_in": {"cep", "rua", "numero", "confirmacao_dados"},
    },
}


class FalhaTeste(AssertionError):
    pass


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise FalhaTeste(msg)


def _raw_llm(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _turno(estado: dict[str, Any], mensagem: str) -> tuple[Any, Any, Any, dict[str, Any]]:
    payload = LLM_SIMULADO.get(mensagem, {"eventos": ["OUTRO"], "dados": {}, "confianca": 0})
    raw = _raw_llm(payload)
    interp = parse_interpretacao(raw, mensagem, estado)

    plano_nome = str(
        estado.get("plano_em_negociacao") or estado.get("plano_confirmado") or ""
    )
    ctx_perg = enriquecer_pergunta(
        mensagem,
        pergunta=interp.pergunta or mensagem,
        historico=[],
        plano_nome=plano_nome,
    )
    if ctx_perg.get("pergunta"):
        interp.pergunta = str(ctx_perg["pergunta"])

    resolucao = resolver(estado, interp)
    resolucao["mensagem"] = mensagem
    resolucao["pergunta"] = interp.pergunta
    resolucao["topico_contexto"] = ctx_perg.get("topico")
    resolucao["pergunta_original"] = ctx_perg.get("mensagem_original") or mensagem

    decisao = decidir(estado, resolucao)
    for _ in range(5):
        if decisao.acao in {"RESPONDER", "TRANSFERIR_HUMANO", "AGUARDAR"}:
            break
        estado = _aplicar_estado(estado, decisao)
        decisao = _executar_acao(estado, decisao)

    estado = _aplicar_estado(estado, decisao)
    return interp, decisao, resolucao, estado


def _aplicar_estado(estado: dict[str, Any], decisao: Any) -> dict[str, Any]:
    novo = dict(estado)
    novo["fase"] = decisao.fase
    novo["aguardando"] = decisao.aguardando
    atualizar = dict(decisao.atualizar_dados or {})
    for k in ("limpar_desvio", "resetar_cobertura", "invalidar_plano", "limpar_plano_em_negociacao"):
        atualizar.pop(k, None)
    if decisao.atualizar_dados.get("resetar_cobertura"):
        novo.pop("tem_cobertura", None)
    novo.update({k: v for k, v in atualizar.items() if v is not None})
    return novo


def _checar(msg: str, interp: Any, decisao: Any, resolucao: dict[str, Any], estado: dict[str, Any] | None = None) -> None:
    exp = ASSERTS.get(msg)
    if not exp:
        return

    ev = set(interp.eventos)
    if "eventos" in exp:
        for e in exp["eventos"]:
            _assert(e in ev, f"[{msg}] faltou evento {e}; got {ev}")
    if "nao_eventos" in exp:
        for e in exp["nao_eventos"]:
            _assert(e not in ev, f"[{msg}] não deveria ter evento {e}; got {ev}")
    if "acao" in exp:
        _assert(decisao.acao == exp["acao"], f"[{msg}] acao={decisao.acao}, esperado {exp['acao']}")
    if "objetivo" in exp:
        _assert(
            decisao.objetivo_resposta == exp["objetivo"],
            f"[{msg}] objetivo={decisao.objetivo_resposta}, esperado {exp['objetivo']}",
        )
    if "objetivo_in" in exp:
        _assert(
            decisao.objetivo_resposta in exp["objetivo_in"],
            f"[{msg}] objetivo={decisao.objetivo_resposta}, esperado um de {exp['objetivo_in']}",
        )
    if "fase" in exp:
        _assert(decisao.fase == exp["fase"], f"[{msg}] fase={decisao.fase}, esperado {exp['fase']}")
    if "nao_fase" in exp:
        _assert(decisao.fase != exp["nao_fase"], f"[{msg}] fase não deveria ser {exp['nao_fase']}")
    if "aguardando" in exp:
        _assert(
            decisao.aguardando == exp["aguardando"],
            f"[{msg}] aguardando={decisao.aguardando}, esperado {exp['aguardando']}",
        )
    if "aguardando_in" in exp:
        _assert(
            decisao.aguardando in exp["aguardando_in"],
            f"[{msg}] aguardando={decisao.aguardando}, esperado um de {exp['aguardando_in']}",
        )
    if "topico" in exp:
        top = resolucao.get("topico_contexto") or (decisao.contexto_resposta or {}).get("topico_contexto")
        _assert(top == exp["topico"], f"[{msg}] topico={top}, esperado {exp['topico']}")
    if "estado_depois" in exp and estado:
        for k, v in exp["estado_depois"].items():
            _assert(estado.get(k) == v, f"[{msg}] estado[{k}]={estado.get(k)!r}, esperado {v!r}")


def test_parser_isolado() -> None:
    print("── Parser isolado ──")
    estado = {"fase": "vendas", "aguardando": "confirmacao_plano", "tem_cobertura": True}
    raw = json.dumps({"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.8})
    interp = parse_interpretacao(raw, "Mostre todos", estado)
    _assert(Evento.PEDIU_TROCAR_PLANO.value in interp.eventos, "Mostre todos → PEDIU_TROCAR_PLANO")
    _assert(Evento.PERGUNTA.value in interp.eventos, "Mostre todos → PERGUNTA")

    raw2 = json.dumps({"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9})
    interp2 = parse_interpretacao(raw2, "sim]", {"fase": "vendas", "aguardando": "confirmacao_plano"})
    _assert(Evento.CONFIRMACAO.value in interp2.eventos, "sim] → CONFIRMACAO")

    estado_cad = {"fase": "cadastro", "aguardando": "nome", "plano_confirmado": "MOV ONE+"}
    raw3 = json.dumps({"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.5})
    interp3 = parse_interpretacao(raw3, "Edrei tester", estado_cad)
    _assert(Evento.DADO_INFORMADO.value in interp3.eventos, "Edrei tester → DADO_INFORMADO")
    _assert(interp3.dados.nome == "Edrei tester", "nome extraído")

    estado_email = {"fase": "cadastro", "aguardando": "email", "plano_confirmado": "MOV ONE+"}
    raw4 = json.dumps(
        {"eventos": ["DADO_INFORMADO"], "dados": {"email": "edreiteste@gmail.com"}, "confianca": 0.9}
    )
    msg4 = "edreiteste@gmail.com MAS E EU TENHO DIREITO A ROTEADOR?"
    interp4 = parse_interpretacao(raw4, msg4, estado_email)
    _assert(Evento.PERGUNTA.value in interp4.eventos, "email+roteador → PERGUNTA")
    _assert(
        Evento.PEDIU_TROCAR_LOCALIZACAO.value not in interp4.eventos,
        "email+roteador ≠ PEDIU_TROCAR_LOCALIZACAO",
    )

    raw5 = json.dumps({"eventos": ["PEDIU_TROCAR_LOCALIZACAO"], "dados": {}, "confianca": 0.8})
    interp5 = parse_interpretacao(
        raw5,
        "E se eu quiser mudar de endereço?",
        {"fase": "cadastro", "aguardando": "data_nascimento", "plano_confirmado": "MOV ONE+"},
    )
    _assert(
        Evento.PEDIU_TROCAR_LOCALIZACAO.value not in interp5.eventos,
        "mudança endereço hipotética ≠ PEDIU_TROCAR_LOCALIZACAO",
    )
    _assert(Evento.PERGUNTA.value in interp5.eventos, "mudança endereço → PERGUNTA")
    print("  OK parser isolado")


def test_fluxo_simulado() -> None:
    print("── Fluxo simulado (transcript) ──")
    estado: dict[str, Any] = {
        "fase": "inicio",
        "aguardando": None,
        "cumprimento_feito": False,
    }

    for i, msg in enumerate(FLUXO_TRANSCRIPT, 1):
        interp, decisao, resolucao, estado = _turno(estado, msg)
        _checar(msg, interp, decisao, resolucao, estado)
        print(
            f"  {i:02d}. {msg[:50]:50} → fase={decisao.fase} aguardando={decisao.aguardando} "
            f"acao={decisao.acao} obj={decisao.objetivo_resposta or '-'}"
        )

    _assert(estado.get("fase") == "cadastro", f"fase final deveria ser cadastro, got {estado.get('fase')}")
    _assert(estado.get("nome") == "Edrei tester", "nome deveria estar salvo")
    _assert(estado.get("email") == "edreiteste@gmail.com", "email deveria estar salvo")
    _assert(estado.get("data_nascimento") == "16/08/2000", "data nascimento deveria estar salva")
    print("  OK fluxo simulado")


def test_live() -> None:
    print("── Pipeline live (LLM + RAG mock) ──")
    os.environ.setdefault("RAG_PROVIDER", "mock")
    get_settings.cache_clear()

    from app import db
    from app.pipeline import process_message

    client_id = "teste-transcript-fluxo"
    db.resetar_cliente(client_id)

    erros: list[str] = []
    for i, msg in enumerate(FLUXO_TRANSCRIPT, 1):
        try:
            r = process_message(client_id, msg)
            d = r.decisao
            print(
                f"  {i:02d}. {msg[:45]:45} → fase={d.fase} aguardando={d.aguardando} "
                f"obj={d.objetivo_resposta or '-'}"
            )
            exp = ASSERTS.get(msg)
            if exp and "nao_fase" in exp and d.fase == exp["nao_fase"]:
                erros.append(f"{msg}: fase={d.fase} (proibida)")
            if exp and "objetivo" in exp and d.objetivo_resposta != exp["objetivo"]:
                erros.append(f"{msg}: objetivo={d.objetivo_resposta}")
            if exp and "acao" in exp and d.acao != exp["acao"]:
                erros.append(f"{msg}: acao={d.acao}")
        except Exception as e:
            erros.append(f"{msg}: {type(e).__name__}: {e}")
            print(f"  {i:02d}. ERRO: {e}")

    if erros:
        raise FalhaTeste("Falhas no modo live:\n  - " + "\n  - ".join(erros))
    print("  OK pipeline live")


def main() -> None:
    parser = argparse.ArgumentParser(description="Teste do fluxo Sofia (transcript)")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Roda pipeline completo com LLM (OPENAI_API_KEY ou Ollama)",
    )
    args = parser.parse_args()

    falhas = 0
    for nome, fn in [
        ("parser", test_parser_isolado),
        ("fluxo", test_fluxo_simulado),
    ]:
        try:
            fn()
        except FalhaTeste as e:
            falhas += 1
            print(f"FALHOU {nome}: {e}")
        except Exception as e:
            falhas += 1
            print(f"ERRO {nome}: {type(e).__name__}: {e}")

    if args.live:
        try:
            test_live()
        except FalhaTeste as e:
            falhas += 1
            print(f"FALHOU live: {e}")
        except Exception as e:
            falhas += 1
            print(f"ERRO live: {type(e).__name__}: {e}")

    print()
    if falhas:
        print(f"❌ {falhas} suite(s) com falha")
        sys.exit(1)
    print("✅ Todos os testes passaram")
    if not args.live:
        print("   Dica: py scripts/test_fluxo_transcript.py --live  (pipeline + LLM)")


if __name__ == "__main__":
    main()
