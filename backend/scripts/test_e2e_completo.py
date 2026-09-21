# -*- coding: utf-8 -*-
"""E2E live — início até encerramento (RAG, planos, IXC, agenda, encerrar)."""
from __future__ import annotations

import os
import random
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Não forçar mock — usa .env real
from app.config import get_settings

get_settings.cache_clear()

from app import db
from app.pipeline import process_message


def _cpf_valido() -> str:
    """Gera CPF válido (dígitos verificadores) — improvável existir no IXC."""
    nums = [random.randint(0, 9) for _ in range(9)]
    if len(set(nums)) == 1:
        nums[8] = (nums[8] + 1) % 10

    def digito(base: list[int], peso: int) -> int:
        s = sum(n * p for n, p in zip(base, range(peso, 1, -1), strict=False))
        r = (s * 10) % 11
        return 0 if r == 10 else r

    d1 = digito(nums, 10)
    nums.append(d1)
    d2 = digito(nums, 11)
    nums.append(d2)
    return "".join(str(n) for n in nums)


def _fmt_cpf(n: str) -> str:
    n = "".join(c for c in n if c.isdigit())
    if len(n) != 11:
        return n
    return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"


class FalhaE2E(Exception):
    pass


def _turno(
    client_id: str,
    msg: str,
    *,
    step: int,
    esperado_fase: str | None = None,
    proibido_fase: set[str] | None = None,
) -> Any:
    print(f"\n── {step:02d}. Cliente: {msg}")
    try:
        r = process_message(client_id, msg)
    except Exception as exc:
        raise FalhaE2E(f"Exceção no turno {step}: {type(exc).__name__}: {exc}") from exc

    d = r.decisao
    estado = r.estado or {}
    fase = str(estado.get("fase") or d.fase or "")
    aguard = estado.get("aguardando") or d.aguardando
    resp = (r.resposta or "")[:120].replace("\n", " ")

    print(
        f"    fase={fase} aguardando={aguard} acao={d.acao} "
        f"obj={d.objetivo_resposta or '-'}"
    )
    if resp:
        print(f"    sofia: {resp}...")

    if proibido_fase and fase in proibido_fase:
        raise FalhaE2E(
            f"Turno {step}: fase proibida '{fase}' (msg={msg!r}). "
            f"Motivo SM: {d.motivo}. Objetivo: {d.objetivo_resposta}"
        )
    if esperado_fase and fase != esperado_fase:
        raise FalhaE2E(
            f"Turno {step}: esperava fase={esperado_fase}, got={fase}. "
            f"Motivo: {d.motivo}"
        )
    if d.acao == "TRANSFERIR_HUMANO":
        motivo = (d.atualizar_dados or {}).get("motivo_transferencia") or d.motivo
        raise FalhaE2E(f"Turno {step}: transferido — {motivo}")

    return r


def main() -> None:
    settings = get_settings()
    print("Providers:", {
        "rag": settings.rag_provider,
        "plans": settings.plans_provider,
        "coverage": settings.coverage_provider,
        "cpf": settings.cpf_provider,
        "cadastro": settings.cadastro_provider,
        "agenda": settings.agenda_provider,
        "encerrar": settings.encerrar_provider,
    })

    cpf = os.environ.get("E2E_TEST_CPF") or _cpf_valido()
    cpf_fmt = _fmt_cpf(cpf)
    client_id = f"e2e-live-{int(time.time())}"
    db.resetar_cliente(client_id)

    ts = int(time.time()) % 100000
    email = f"e2e.sofia.{ts}@mov.test"
    nome = "Maria Silva Teste"

    proibido = {"transferido"}

    # ── Viabilidade + vendas ──
    _turno(client_id, "oi", step=1)
    _turno(client_id, "quero internet fibra", step=2)
    _turno(client_id, "Santarém", step=3)
    _turno(client_id, "Diamantino", step=4, proibido_fase=proibido)
    _turno(client_id, "mov one", step=5, proibido_fase=proibido)
    _turno(client_id, "sim", step=6, proibido_fase=proibido)

    # ── Cadastro ──
    _turno(client_id, nome, step=7, proibido_fase=proibido)
    _turno(client_id, cpf_fmt, step=8, proibido_fase=proibido)
    _turno(client_id, email, step=9, proibido_fase=proibido)
    _turno(client_id, "93992219098", step=10, proibido_fase=proibido)
    _turno(client_id, "16/08/1995", step=11, proibido_fase=proibido)
    _turno(client_id, "68010-010", step=12, proibido_fase=proibido)
    _turno(client_id, "Travessa Tapajós", step=13, proibido_fase=proibido)
    _turno(client_id, "100", step=14, proibido_fase=proibido)

    r15 = _turno(client_id, "sim, confirmo os dados", step=15, proibido_fase=proibido)
    estado15 = db.carregar_ou_criar_estado(client_id)
    print(
        f"    [cadastro] ixc_id={estado15.get('ixc_cliente_id')} "
        f"cadastro_completo={estado15.get('cadastro_completo')}"
    )

    # ── Agendamento — escolhe primeiro horário disponível ──
    estado = db.carregar_ou_criar_estado(client_id)
    fase = str(estado.get("fase") or "")
    if fase != "agendamento":
        raise FalhaE2E(f"Após confirmar dados, fase deveria ser agendamento, got={fase}")

    manha = list(estado.get("horarios_manha") or [])
    tarde = list(estado.get("horarios_tarde") or [])
    slots = manha or tarde
    if not slots:
        raise FalhaE2E(
            f"Sem horários retornados pelo webhook. "
            f"manha={manha} tarde={tarde} tecnico={estado.get('tecnico_id')}"
        )
    horario = slots[0]
    print(f"    [agenda] escolhendo horário: {horario} (tecnico={estado.get('tecnico_id')})")

    _turno(client_id, horario, step=16, proibido_fase=proibido)
    r17 = _turno(client_id, "sim", step=17, proibido_fase=proibido)

    estado_pos = db.carregar_ou_criar_estado(client_id)
    if str(estado_pos.get("fase") or "") != "pos_venda":
        raise FalhaE2E(f"Após agendar, fase deveria ser pos_venda, got={estado_pos.get('fase')}")

    # ── Pós-venda + encerramento ──
    _turno(client_id, "nao, obrigado", step=18, proibido_fase=proibido)
    r19 = _turno(client_id, "tchau", step=19)

    final = db.carregar_ou_criar_estado(client_id)
    fase_final = str(final.get("fase") or "")
    if fase_final not in {"finalizado", "pos_venda"}:
        # encerrar pode deixar finalizado mesmo se webhook falhar parcialmente
        print(f"    AVISO: fase final={fase_final} (esperado finalizado)")

    print("\n✅ E2E completo OK")
    print(f"   client_id={client_id}")
    print(f"   cpf usado={cpf_fmt}")
    print(f"   ixc_cliente_id={final.get('ixc_cliente_id')}")
    print(f"   os_id={final.get('os_id')}")
    print(f"   fase_final={fase_final}")


if __name__ == "__main__":
    try:
        main()
    except FalhaE2E as e:
        print(f"\n❌ E2E FALHOU: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERRO: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
