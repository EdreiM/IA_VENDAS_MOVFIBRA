# -*- coding: utf-8 -*-
"""Testes do follow-up de inatividade (mensagens + elegibilidade + timing)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.inactivity_followup import (
    _elegivel,
    _referencia_espera,
    processar_estado_inatividade,
)
from app.inactivity_mensagens import (
    mensagem_encerramento_inatividade,
    mensagem_followup_inatividade,
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_mensagens_contextualizadas() -> None:
    estado = {
        "nome": "Maria Silva",
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "plano_confirmado": "MOV ONE+",
    }
    m1 = mensagem_followup_inatividade(estado, 1)
    _assert("Maria" in m1, "1ª tentativa deve cumprimentar pelo nome")
    _assert("MOV ONE+" in m1 or "plano" in m1.lower(), "1ª tentativa deve citar contexto")

    m3 = mensagem_followup_inatividade(estado, 3)
    _assert("encerrar" in m3.lower(), "3ª tentativa deve avisar encerramento")

    enc = mensagem_encerramento_inatividade(estado)
    _assert("encerrar" in enc.lower(), "Despedida de encerramento")


def test_elegibilidade() -> None:
    base = {
        "conversation_id": "123",
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "transferido_humano": 0,
    }
    _assert(_elegivel(base), "Estado normal deve ser elegível")
    _assert(not _elegivel({**base, "conversation_id": ""}), "Sem conversation_id")
    _assert(not _elegivel({**base, "fase": "finalizado"}), "Finalizado")
    _assert(not _elegivel({**base, "aguardando": "resultado_cadastro"}), "Aguardando sistema")
    _assert(not _elegivel({**base, "transferido_humano": 1}), "Transferido humano")


def test_referencia_espera_usa_updated_apos_eva() -> None:
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    estado = {
        "followup_count": 0,
        "last_client_message_at": _iso(t0),
        "updated_at": _iso(t1),
    }
    ref = _referencia_espera(estado)
    _assert(ref == t1, "Referência deve ser updated_at (Eva respondeu depois do cliente)")


def test_processar_estado_envia_followup() -> None:
    agora = datetime.now(timezone.utc)
    antigo = agora - timedelta(minutes=30)
    estado = {
        "id_cliente": "teste-followup",
        "conversation_id": "999",
        "fase": "cadastro",
        "aguardando": "nome",
        "followup_count": 0,
        "updated_at": _iso(antigo),
        "last_client_message_at": _iso(antigo - timedelta(minutes=2)),
    }
    enviados: list[str] = []

    def fake_enviar(est: dict, texto: str) -> bool:
        enviados.append(texto)
        return True

    import app.db as db_mod
    import app.inactivity_followup as mod

    original = mod._enviar_texto
    mod._enviar_texto = fake_enviar
    db_mod.registrar_followup_enviado = lambda _id: None  # type: ignore[assignment]
    try:
        acao = processar_estado_inatividade(estado, delay_minutes=15, max_followups=3)
        _assert(acao == "followup_1", f"Esperado followup_1, veio {acao}")
        _assert(len(enviados) == 1, "Deve enviar uma mensagem")
    finally:
        mod._enviar_texto = original


def test_processar_estado_encerra_apos_max() -> None:
    agora = datetime.now(timezone.utc)
    antigo = agora - timedelta(minutes=60)
    estado = {
        "id_cliente": "teste-encerrar",
        "conversation_id": "888",
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "followup_count": 3,
        "last_followup_at": _iso(antigo),
        "updated_at": _iso(antigo),
    }
    enviados: list[str] = []
    encerrados: list[str] = []

    import app.inactivity_followup as mod

    def fake_enviar(est: dict, texto: str) -> bool:
        enviados.append(texto)
        return True

    def fake_encerrar(est: dict) -> None:
        encerrados.append(str(est.get("id_cliente")))

    original_env = mod._enviar_texto
    original_enc = mod._encerrar_estado
    mod._enviar_texto = fake_enviar
    mod._encerrar_estado = fake_encerrar
    try:
        acao = processar_estado_inatividade(estado, delay_minutes=15, max_followups=3)
        _assert(acao == "encerrado", f"Esperado encerrado, veio {acao}")
        _assert(len(encerrados) == 1, "Deve chamar encerramento")
    finally:
        mod._enviar_texto = original_env
        mod._encerrar_estado = original_enc


def main() -> None:
    tests = [
        test_mensagens_contextualizadas,
        test_elegibilidade,
        test_referencia_espera_usa_updated_apos_eva,
        test_processar_estado_envia_followup,
        test_processar_estado_encerra_apos_max,
    ]
    ok = 0
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
        ok += 1
    print(f"\n{ok}/{len(tests)} testes passaram")


if __name__ == "__main__":
    main()
