"""Métricas agregadas (PostgreSQL) — base do dashboard."""

from __future__ import annotations

from typing import Any

from app.db import get_connection


def _status_operacional(r: dict[str, Any]) -> str:
    fase = str(r.get("fase") or "")
    if r.get("transferido_humano") or fase == "transferido":
        return "transferido"
    if fase in ("finalizado", "pos_venda") and r.get("agendamento_confirmado"):
        return "finalizado"
    if fase == "finalizado":
        return "finalizado"
    return "com_ia"


def resumo() -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM estado_cliente_ia")
            total = cur.fetchone()["n"]
            cur.execute(
                """
                SELECT COALESCE(fase, 'inicio') AS fase, COUNT(*) AS n
                FROM estado_cliente_ia
                GROUP BY COALESCE(fase, 'inicio')
                ORDER BY n DESC
                """
            )
            por_fase = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE agendamento_confirmado = 1"
            )
            agendados = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE transferido_humano = 1"
            )
            transferidos = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE tem_cobertura = 1"
            )
            cobertura = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE cadastro_completo = 1"
            )
            cadastros = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM historico_mensagens_ia")
            msgs = cur.fetchone()["n"]
            cur.execute(
                """
                SELECT COUNT(*) AS n FROM estado_cliente_ia
                WHERE COALESCE(transferido_humano, 0) = 0
                  AND COALESCE(fase, '') NOT IN ('transferido', 'finalizado')
                """
            )
            com_ia = cur.fetchone()["n"]

    ferramentas_destaque: list[dict[str, Any]] = []
    try:
        from app.ferramentas import metricas_ferramentas_destaque

        ferramentas_destaque = metricas_ferramentas_destaque()
    except Exception:
        ferramentas_destaque = []

    return {
        "conversas": total,
        "mensagens": msgs,
        "com_cobertura": cobertura,
        "cadastro_completo": cadastros,
        "agendamentos_confirmados": agendados,
        "transferidos_humano": transferidos,
        "com_ia": com_ia,
        "por_fase": {str(r["fase"]): int(r["n"]) for r in por_fase},
        "ferramentas_destaque": ferramentas_destaque,
    }


def funil() -> dict[str, Any]:
    ordem = [
        "inicio",
        "viabilidade",
        "sem_cobertura",
        "vendas",
        "cadastro",
        "termos",
        "agendamento",
        "pos_venda",
        "finalizado",
        "transferido",
    ]
    dados = resumo()["por_fase"]
    etapas = [{"fase": f, "quantidade": int(dados.get(f, 0))} for f in ordem]
    extras = [
        {"fase": k, "quantidade": v}
        for k, v in dados.items()
        if k not in ordem
    ]
    return {"etapas": etapas + extras, "totais": resumo()}


def conversas(
    limite: int = 50,
    *,
    unidade_id: int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite or 50), 200))
    clauses: list[str] = []
    params: list[Any] = []
    if unidade_id is not None:
        clauses.append("unidade_id = %s")
        params.append(unidade_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limite)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id_cliente, fase, aguardando, cidade, bairro, plano_confirmado,
                       nome, telefone, tem_cobertura, cadastro_completo,
                       agendamento_confirmado, transferido_humano,
                       conversation_id, contact_id, unidade_id, updated_at
                FROM estado_cliente_ia
                {where}
                ORDER BY updated_at DESC NULLS LAST
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                item = dict(r)
                if item.get("updated_at") is not None and not isinstance(item["updated_at"], str):
                    item["updated_at"] = item["updated_at"].isoformat()
                item["status"] = _status_operacional(item)
                if status and item["status"] != status:
                    continue
                out.append(item)
            return out
