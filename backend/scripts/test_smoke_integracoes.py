# -*- coding: utf-8 -*-
"""Smoke — integrações mock (IXC, agenda, encerrar) sem rede."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("COVERAGE_PROVIDER", "mock")
os.environ.setdefault("CPF_PROVIDER", "mock")
os.environ.setdefault("CADASTRO_PROVIDER", "mock")
os.environ.setdefault("AGENDA_PROVIDER", "mock")
os.environ.setdefault("ENCERRAR_PROVIDER", "mock")

from app.config import get_settings

get_settings.cache_clear()

from app.cadastro_ixc import cadastrar_cliente
from app.coverage import checar_cobertura
from app.cpf_validation import validar_cpf
from app.agenda import consultar_horarios
from app.agenda_inserir import inserir_agendamento
from app.encerrar import encerrar_atendimento
from app import db


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> None:
    settings = get_settings()
    _assert(settings.coverage_provider == "mock", "COVERAGE_PROVIDER deve ser mock")
    _assert(settings.cpf_provider == "mock", "CPF_PROVIDER deve ser mock")
    _assert(settings.cadastro_provider == "mock", "CADASTRO_PROVIDER deve ser mock")
    _assert(settings.agenda_provider == "mock", "AGENDA_PROVIDER deve ser mock")
    _assert(settings.encerrar_provider == "mock", "ENCERRAR_PROVIDER deve ser mock")

    cob = checar_cobertura(cidade="Santarém", bairro="Diamantino", id_cliente="smoke")
    _assert(cob.get("tem_cobertura") is True, f"cobertura: {cob}")

    cpf = validar_cpf(cpf_cnpj="60421079096", id_cliente="smoke")
    _assert(cpf.get("erro") is False and not cpf.get("ja_cadastrado"), f"cpf: {cpf}")

    estado = {
        "id_cliente": "smoke",
        "nome": "Ana Silva",
        "cpf": "60421079096",
        "email": "ana@test.com",
        "telefone": "93992219098",
        "data_nascimento": "16/08/2000",
        "cep": "68010010",
        "rua": "Rua Teste",
        "numero": "123",
        "plano_confirmado": "MOV ONE+",
        "cidade": "Santarém",
        "bairro": "Diamantino",
    }
    cad = cadastrar_cliente(estado)
    _assert(cad.get("ok") is True and not cad.get("erro"), f"cadastro: {cad}")
    estado["ixc_cliente_id"] = cad.get("id_cliente_ixc") or "mock-1"

    hor = consultar_horarios(estado)
    _assert(hor.get("resultado") == "ok", f"agenda: {hor}")
    estado["horarios_manha"] = hor.get("manha") or ["8h às 9h"]
    estado["data_agendamento"] = hor.get("data") or "01/09/2026"
    estado["horario_escolhido"] = estado["horarios_manha"][0]
    estado["tecnico_id"] = hor.get("tecnico_id") or "mock-tecnico"

    ins = inserir_agendamento(estado)
    _assert(ins.get("resultado") == "ok", f"inserir agenda: {ins}")

    enc = encerrar_atendimento({**estado, "os_id": ins.get("os_id") or "1"})
    _assert(enc.get("resultado") == "ok", f"encerrar: {enc}")

    db.init_schema()
    db.log_turno(
        "smoke",
        mensagem_cliente="teste",
        eventos=["OUTRO"],
        acao="RESPONDER",
        objetivo="CONTINUAR_CONVERSA",
        fase="inicio",
        topico="teste",
        rag_hit=False,
        duracao_ms=1,
        message_id="msg-smoke-1",
    )
    _assert(db.mensagem_ja_processada("") is False, "message_id vazio não deduplica")
    db.marcar_mensagem_processada("msg-smoke-dedupe", "smoke")
    _assert(db.mensagem_ja_processada("msg-smoke-dedupe"), "dedupe deve marcar processada")

    print("✅ Smoke integrações OK")


if __name__ == "__main__":
    main()
