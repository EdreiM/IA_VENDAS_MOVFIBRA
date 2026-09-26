from __future__ import annotations

from typing import Any

import httpx

from .db import _now, get_connection


def _parametros_da_ferramenta(cur: Any, ferramenta_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT id, nome, tipo, descricao, obrigatorio, ordem
        FROM ferramenta_parametros
        WHERE ferramenta_id = %s
        ORDER BY ordem ASC, id ASC
        """,
        (ferramenta_id,),
    )
    return [
        {
            "id": int(r["id"]),
            "nome": r["nome"],
            "tipo": r["tipo"],
            "descricao": r["descricao"] or "",
            "obrigatorio": bool(r["obrigatorio"]),
            "ordem": int(r["ordem"] or 0),
        }
        for r in cur.fetchall()
    ]


def _row_to_tool(cur: Any, row: Any) -> dict[str, Any]:
    fid = int(row["id"])
    return {
        "id": fid,
        "tool_key": row["tool_key"],
        "nome": row["nome"],
        "descricao": row["descricao"] or "",
        "webhook_url": row["webhook_url"] or "",
        "integracao": row["integracao"] or "global",
        "unidade_id": row["unidade_id"],
        "destaque_dashboard": bool(row["destaque_dashboard"]),
        "ativo": bool(row["ativo"]),
        "chamadas_sucesso": int(row["chamadas_sucesso"] or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "parametros": _parametros_da_ferramenta(cur, fid),
    }


def listar_ferramentas(*, unidade_id: int | None = None, apenas_ativas: bool = False) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if unidade_id is not None:
        clauses.append("(unidade_id IS NULL OR unidade_id = %s)")
        params.append(unidade_id)
    if apenas_ativas:
        clauses.append("ativo = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM ferramentas {where} ORDER BY destaque_dashboard DESC, nome ASC",
                tuple(params),
            )
            return [_row_to_tool(cur, r) for r in cur.fetchall()]


def obter_ferramenta(ferramenta_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM ferramentas WHERE id = %s", (ferramenta_id,))
            row = cur.fetchone()
            return _row_to_tool(cur, row) if row else None


def obter_ferramenta_por_key(
    tool_key: str,
    *,
    unidade_id: int | None = None,
) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if unidade_id is not None:
                cur.execute(
                    """
                    SELECT * FROM ferramentas
                    WHERE tool_key = %s AND ativo = 1
                      AND (unidade_id = %s OR unidade_id IS NULL)
                    ORDER BY CASE WHEN unidade_id = %s THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (tool_key, unidade_id, unidade_id),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM ferramentas
                    WHERE tool_key = %s AND ativo = 1 AND unidade_id IS NULL
                    LIMIT 1
                    """,
                    (tool_key,),
                )
            row = cur.fetchone()
            return _row_to_tool(cur, row) if row else None


def _salvar_parametros(cur: Any, ferramenta_id: int, parametros: list[dict[str, Any]]) -> None:
    cur.execute("DELETE FROM ferramenta_parametros WHERE ferramenta_id = %s", (ferramenta_id,))
    for i, p in enumerate(parametros or []):
        nome = str(p.get("nome") or "").strip()
        if not nome:
            continue
        cur.execute(
            """
            INSERT INTO ferramenta_parametros (
                ferramenta_id, nome, tipo, descricao, obrigatorio, ordem
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                ferramenta_id,
                nome,
                str(p.get("tipo") or "texto"),
                str(p.get("descricao") or ""),
                1 if p.get("obrigatorio") else 0,
                int(p.get("ordem") if p.get("ordem") is not None else i),
            ),
        )


def criar_ferramenta(payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    webhook_url = str(payload.get("webhook_url") or "").strip()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ferramentas (
                    tool_key, nome, descricao, webhook_url, integracao,
                    unidade_id, destaque_dashboard, ativo, chamadas_sucesso,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
                RETURNING *
                """,
                (
                    str(payload["tool_key"]).strip(),
                    str(payload["nome"]).strip(),
                    str(payload.get("descricao") or ""),
                    webhook_url,
                    str(payload.get("integracao") or "global"),
                    payload.get("unidade_id"),
                    1 if payload.get("destaque_dashboard") else 0,
                    1 if payload.get("ativo", True) else 0,
                    now,
                    now,
                ),
            )
            row = cur.fetchone()
            fid = int(row["id"])
            _salvar_parametros(cur, fid, list(payload.get("parametros") or []))
            cur.execute("SELECT * FROM ferramentas WHERE id = %s", (fid,))
            tool = _row_to_tool(cur, cur.fetchone())
    if webhook_url and not payload.get("unidade_id"):
        from app.ferramentas_catalog import gravar_backup_url_ferramenta

        gravar_backup_url_ferramenta(str(tool["tool_key"]), webhook_url)
    return tool


def atualizar_ferramenta(ferramenta_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    atual = obter_ferramenta(ferramenta_id)
    if not atual:
        return None
    now = _now()
    if "webhook_url" in payload:
        nova_url = str(payload.get("webhook_url") or "").strip()
        url_atual = str(atual.get("webhook_url") or "").strip()
        # Campo vazio no formulário não apaga URL já salva (mesmo padrão das API keys).
        webhook_url = nova_url if nova_url or not url_atual else url_atual
    else:
        webhook_url = str(atual.get("webhook_url") or "").strip()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ferramentas SET
                    tool_key = %s,
                    nome = %s,
                    descricao = %s,
                    webhook_url = %s,
                    integracao = %s,
                    unidade_id = %s,
                    destaque_dashboard = %s,
                    ativo = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    str(payload.get("tool_key") or atual["tool_key"]).strip(),
                    str(payload.get("nome") or atual["nome"]).strip(),
                    str(payload.get("descricao") if "descricao" in payload else atual["descricao"]),
                    webhook_url,
                    str(payload.get("integracao") or atual["integracao"]),
                    payload.get("unidade_id") if "unidade_id" in payload else atual["unidade_id"],
                    1
                    if (
                        payload.get("destaque_dashboard")
                        if "destaque_dashboard" in payload
                        else atual["destaque_dashboard"]
                    )
                    else 0,
                    1 if (payload.get("ativo") if "ativo" in payload else atual["ativo"]) else 0,
                    now,
                    ferramenta_id,
                ),
            )
            if "parametros" in payload:
                _salvar_parametros(cur, ferramenta_id, list(payload.get("parametros") or []))
            cur.execute("SELECT * FROM ferramentas WHERE id = %s", (ferramenta_id,))
            row = cur.fetchone()
            tool = _row_to_tool(cur, row) if row else None
    if tool and webhook_url and not tool.get("unidade_id"):
        from app.ferramentas_catalog import gravar_backup_url_ferramenta

        gravar_backup_url_ferramenta(str(tool["tool_key"]), webhook_url)
    return tool


def deletar_ferramenta(ferramenta_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ferramentas WHERE id = %s", (ferramenta_id,))
            return cur.rowcount > 0


def registrar_chamada(
    ferramenta_id: int,
    *,
    ok: bool,
    conversation_id: str | None = None,
    motivo: str | None = None,
) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ferramenta_chamadas (ferramenta_id, ok, conversation_id, motivo, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (ferramenta_id, 1 if ok else 0, conversation_id, motivo, now),
            )
            if ok:
                cur.execute(
                    """
                    UPDATE ferramentas
                    SET chamadas_sucesso = COALESCE(chamadas_sucesso, 0) + 1, updated_at = %s
                    WHERE id = %s
                    """,
                    (now, ferramenta_id),
                )


def metricas_ferramentas_destaque() -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tool_key, nome, chamadas_sucesso, destaque_dashboard
                FROM ferramentas
                WHERE destaque_dashboard = 1 AND ativo = 1
                ORDER BY chamadas_sucesso DESC, nome ASC
                """
            )
            return [
                {
                    "id": int(r["id"]),
                    "tool_key": r["tool_key"],
                    "nome": r["nome"],
                    "chamadas_sucesso": int(r["chamadas_sucesso"] or 0),
                }
                for r in cur.fetchall()
            ]


async def executar_webhook_ferramenta(
    ferramenta: dict[str, Any],
    payload: dict[str, Any],
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    url = str(ferramenta.get("webhook_url") or "").strip()
    if not url:
        return {"ok": False, "erro": "ferramenta sem webhook_url configurada"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
        ok = 200 <= resp.status_code < 300
        registrar_chamada(
            int(ferramenta["id"]),
            ok=ok,
            conversation_id=str(payload.get("conversation_id") or "") or None,
            motivo=str(payload.get("motivo") or "") or None,
        )
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "body": (resp.text or "")[:2000],
        }
    except Exception as exc:
        registrar_chamada(
            int(ferramenta["id"]),
            ok=False,
            conversation_id=str(payload.get("conversation_id") or "") or None,
            motivo=str(exc)[:300],
        )
        return {"ok": False, "erro": str(exc)}
