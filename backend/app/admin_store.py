"""Store admin — promoções, exceções e config operacional (PostgreSQL)."""

from __future__ import annotations

from typing import Any

from app.db import _now, get_connection


def init_admin_schema() -> None:
    """Schema admin já criado em db.init_schema()."""
    return


def get_config(chave: str, default: str = "", *, unidade_id: int | None = None) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if unidade_id is not None:
                cur.execute(
                    """
                    SELECT valor FROM sofia_config
                    WHERE chave = %s AND (unidade_id = %s OR unidade_id IS NULL)
                    ORDER BY CASE WHEN unidade_id = %s THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (chave, unidade_id, unidade_id),
                )
            else:
                cur.execute(
                    """
                    SELECT valor FROM sofia_config
                    WHERE chave = %s AND unidade_id IS NULL
                    LIMIT 1
                    """,
                    (chave,),
                )
            row = cur.fetchone()
            return str(row["valor"]) if row else default


def set_config(
    chave: str,
    valor: str,
    *,
    unidade_id: int | None = None,
) -> dict[str, Any]:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            if unidade_id is None:
                cur.execute(
                    """
                    SELECT id FROM sofia_config
                    WHERE chave = %s AND unidade_id IS NULL
                    LIMIT 1
                    """,
                    (chave,),
                )
            else:
                cur.execute(
                    """
                    SELECT id FROM sofia_config
                    WHERE chave = %s AND unidade_id = %s
                    LIMIT 1
                    """,
                    (chave, unidade_id),
                )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE sofia_config
                    SET valor = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (valor, now, row["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO sofia_config (unidade_id, chave, valor, updated_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (unidade_id, chave, valor, now),
                )
    return {"chave": chave, "valor": valor, "unidade_id": unidade_id, "updated_at": now}


def listar_config(*, unidade_id: int | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if unidade_id is not None:
                cur.execute(
                    """
                    SELECT id, unidade_id, chave, valor, updated_at
                    FROM sofia_config
                    WHERE unidade_id IS NULL OR unidade_id = %s
                    ORDER BY chave, unidade_id NULLS FIRST
                    """,
                    (unidade_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, unidade_id, chave, valor, updated_at
                    FROM sofia_config
                    ORDER BY chave, unidade_id NULLS FIRST
                    """
                )
            return [dict(r) for r in cur.fetchall()]


def listar_config_mapa(*, unidade_id: int | None = None) -> dict[str, str]:
    items = listar_config(unidade_id=unidade_id)
    out: dict[str, str] = {}
    for item in items:
        # unidade específica sobrescreve global
        k = str(item["chave"])
        if k not in out or item.get("unidade_id") is not None:
            out[k] = str(item["valor"])
    return out


def listar_promocoes(
    *,
    apenas_ativas: bool = False,
    unidade_id: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if apenas_ativas:
        clauses.append("ativo = 1")
    if unidade_id is not None:
        clauses.append("(unidade_id IS NULL OR unidade_id = %s)")
        params.append(unidade_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM promocoes {where} ORDER BY id DESC"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]


def upsert_promocao(dados: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    codigo = str(dados.get("codigo") or "").strip().upper()
    if not codigo:
        raise ValueError("codigo obrigatório")
    titulo = str(dados.get("titulo") or codigo).strip()
    descricao = str(dados.get("descricao") or "").strip()
    ativo = 1 if dados.get("ativo", True) else 0
    valido_ate = str(dados.get("valido_ate") or "").strip() or None
    unidade_id = dados.get("unidade_id")
    promo_id = dados.get("id")

    with get_connection() as conn:
        with conn.cursor() as cur:
            if promo_id:
                cur.execute(
                    """
                    UPDATE promocoes SET
                        codigo = %s,
                        titulo = %s,
                        descricao = %s,
                        ativo = %s,
                        valido_ate = %s,
                        unidade_id = %s,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (codigo, titulo, descricao, ativo, valido_ate, unidade_id, now, promo_id),
                )
                row = cur.fetchone()
                return dict(row) if row else {}

            if unidade_id is None:
                cur.execute(
                    """
                    SELECT id FROM promocoes
                    WHERE codigo = %s AND unidade_id IS NULL
                    LIMIT 1
                    """,
                    (codigo,),
                )
            else:
                cur.execute(
                    """
                    SELECT id FROM promocoes
                    WHERE codigo = %s AND unidade_id = %s
                    LIMIT 1
                    """,
                    (codigo, unidade_id),
                )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    """
                    UPDATE promocoes SET
                        titulo = %s,
                        descricao = %s,
                        ativo = %s,
                        valido_ate = %s,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (titulo, descricao, ativo, valido_ate, now, existing["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO promocoes (
                        codigo, titulo, descricao, ativo, valido_ate, unidade_id, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (codigo, titulo, descricao, ativo, valido_ate, unidade_id, now, now),
                )
            row = cur.fetchone()
            return dict(row) if row else {}


def deletar_promocao(promo_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM promocoes WHERE id = %s", (promo_id,))
            return cur.rowcount > 0


def listar_excecoes(*, apenas_ativas: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM excecoes"
    if apenas_ativas:
        sql += " WHERE ativo = 1"
    sql += " ORDER BY id DESC"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [dict(r) for r in cur.fetchall()]


def criar_excecao(dados: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    tipo = str(dados.get("tipo") or "").strip().lower()
    valor = str(dados.get("valor") or "").strip()
    if not tipo or not valor:
        raise ValueError("tipo e valor obrigatórios")
    motivo = str(dados.get("motivo") or "").strip()
    ativo = 1 if dados.get("ativo", True) else 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO excecoes (tipo, valor, motivo, ativo, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (tipo, valor, motivo, ativo, now, now),
            )
            row = cur.fetchone()
            return dict(row) if row else {}


def desativar_excecao(excecao_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE excecoes SET ativo = 0, updated_at = %s WHERE id = %s",
                (_now(), excecao_id),
            )
            return cur.rowcount > 0
