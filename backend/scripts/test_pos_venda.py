# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import get_settings

get_settings.cache_clear()

from app.pos_venda_mensagens import mensagem_sem_duvidas
from app.state_machine import (
    decidir,
    decidir_resultado_inserir_agenda,
    decidir_resultado_encerrar,
)
from app.parser import parse_interpretacao
from app.response import gerar_resposta

d = decidir_resultado_inserir_agenda(
    {"resultado": "ok", "os_id": "1"},
    {"horario_escolhido": "8h as 9h", "data_agendamento": "28/08/2026", "nome": "Ana"},
)
assert d.fase == "pos_venda", d.fase
assert d.objetivo_resposta == "AGENDAMENTO_CONFIRMADO_E_PEDIR_DUVIDAS"
txt = gerar_resposta(
    d,
    {
        "nome": "Ana Silva",
        "horario_escolhido": "8h as 9h",
        "data_agendamento": "28/08/2026",
    },
)
assert "duvida" in txt.casefold() or "dúvida" in txt.casefold()

estado = {"fase": "pos_venda", "aguardando": "duvidas", "nome": "Ana"}
base = {
    "eventos": [],
    "dados": {"para_salvar": {}},
    "localizacao": {},
    "plano": {},
    "cpf": {},
    "cadastro": {},
    "invalidar": {},
}

d2 = decidir(estado, {**base, "flags": {"negacao": True}, "mensagem": "nao"})
assert d2.acao == "ENCERRAR_ATENDIMENTO", d2.acao

d3 = decidir(
    estado,
    {
        **base,
        "flags": {"tem_pergunta": True},
        "pergunta": "tem fidelidade?",
        "mensagem": "tem fidelidade?",
    },
)
assert d3.objetivo_resposta == "RESPONDER_DUVIDA_E_RETOMAR"

d4 = decidir_resultado_encerrar({"resultado": "ok"}, estado)
assert d4.fase == "finalizado"
assert d4.objetivo_resposta == "DESPEDIDA_ENCERRAMENTO"

os.environ["ENCERRAR_PROVIDER"] = "mock"
get_settings.cache_clear()
from app.encerrar import encerrar_atendimento

r = encerrar_atendimento({"id_cliente": "teste", "conversation_id": "123"})
assert r["resultado"] == "ok", r

assert mensagem_sem_duvidas("tudo certo")
assert mensagem_sem_duvidas("Não tenho nãoobrigado")
assert mensagem_sem_duvidas("Pode encerrar")

for msg in ("Não", "Pode encerrar", "Não tenho nãoobrigado"):
    i = parse_interpretacao(
        '{"eventos":["PERGUNTA"],"dados":{},"confianca":0.5}',
        msg,
        {"fase": "pos_venda", "aguardando": "duvidas"},
    )
    assert "NEGACAO" in i.eventos, f"{msg} → {i.eventos}"
    d = decidir(
        estado,
        {
            **base,
            "flags": {"negacao": "NEGACAO" in i.eventos},
            "mensagem": msg,
        },
    )
    assert d.acao == "ENCERRAR_ATENDIMENTO", f"{msg} → {d.acao}"

# PERGUNTA do LLM não bloqueia encerramento quando cliente não tem dúvidas
d5 = decidir(
    estado,
    {
        **base,
        "flags": {"tem_pergunta": True, "negacao": True},
        "pergunta": "nao",
        "mensagem": "Não",
    },
)
assert d5.acao == "ENCERRAR_ATENDIMENTO", d5.acao

print("OK")
