from __future__ import annotations

from typing import Any

from .db import _now, get_connection


def listar_unidades(*, apenas_ativas: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM unidades"
    params: tuple[Any, ...] = ()
    if apenas_ativas:
        sql += " WHERE ativo = 1"
    sql += " ORDER BY nome ASC"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def obter_unidade(unidade_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM unidades WHERE id = %s", (unidade_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def criar_unidade(*, codigo: str, nome: str, ativo: bool = True) -> dict[str, Any]:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO unidades (codigo, nome, ativo, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (codigo.strip().upper(), nome.strip(), 1 if ativo else 0, now, now),
            )
            return dict(cur.fetchone())


def atualizar_unidade(
    unidade_id: int,
    *,
    codigo: str | None = None,
    nome: str | None = None,
    ativo: bool | None = None,
) -> dict[str, Any] | None:
    atual = obter_unidade(unidade_id)
    if not atual:
        return None
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE unidades SET
                    codigo = %s,
                    nome = %s,
                    ativo = %s,
                    updated_at = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    (codigo or atual["codigo"]).strip().upper(),
                    (nome or atual["nome"]).strip(),
                    (1 if ativo else 0) if ativo is not None else int(atual["ativo"]),
                    now,
                    unidade_id,
                ),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def deletar_unidade(unidade_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM unidades WHERE id = %s", (unidade_id,))
            return cur.rowcount > 0
