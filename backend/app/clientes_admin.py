"""Listagem e ficha de clientes (estado_cliente_ia) — painel admin."""

from __future__ import annotations

from typing import Any

from app.db import _row_to_dict, carregar_ou_criar_estado, get_connection, salvar_transicao
from app.metrics import _status_operacional

CAMPOS_EDITAVEIS = frozenset({
    "nome",
    "cpf",
    "email",
    "telefone",
    "data_nascimento",
    "rg",
    "cep",
    "rua",
    "numero",
    "complemento",
    "cidade",
    "bairro",
    "metodo_pagamento",
})


def _label_cliente(row: dict[str, Any]) -> str:
    nome = str(row.get("nome") or "").strip()
    if nome:
        return nome
    tel = str(row.get("telefone") or "").strip()
    if tel:
        return tel
    return str(row.get("id_cliente") or "")


def _serializar_estado(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    item = _row_to_dict(row) or dict(row)
    item["status"] = _status_operacional(item)
    item["label"] = _label_cliente(item)
    return item


def listar_clientes(
    *,
    q: str = "",
    fase: str | None = None,
    status: str | None = None,
    unidade_id: int | None = None,
    limite: int = 80,
    offset: int = 0,
) -> dict[str, Any]:
    limite = max(1, min(int(limite or 80), 200))
    offset = max(0, int(offset or 0))
    clauses: list[str] = []
    params: list[Any] = []

    busca = (q or "").strip()
    if busca:
        like = f"%{busca}%"
        clauses.append(
            "(id_cliente ILIKE %s OR COALESCE(nome, '') ILIKE %s OR COALESCE(telefone, '') ILIKE %s "
            "OR COALESCE(cpf, '') ILIKE %s OR COALESCE(email, '') ILIKE %s)"
        )
        params.extend([like, like, like, like, like])

    if fase:
        clauses.append("COALESCE(fase, 'inicio') = %s")
        params.append(fase.strip())

    if unidade_id is not None:
        clauses.append("unidade_id = %s")
        params.append(unidade_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM estado_cliente_ia {where}",
                tuple(params),
            )
            total = int(cur.fetchone()["n"])
            cur.execute(
                f"""
                SELECT id_cliente, fase, aguardando, nome, telefone, cpf, email,
                       cidade, bairro, plano_confirmado, cadastro_completo,
                       agendamento_confirmado, transferido_humano,
                       conversation_id, contact_id, unidade_id,
                       created_at, updated_at
                FROM estado_cliente_ia
                {where}
                ORDER BY updated_at DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                tuple(params + [limite, offset]),
            )
            rows = cur.fetchall()

    items: list[dict[str, Any]] = []
    for r in rows:
        item = _serializar_estado(dict(r))
        if status and item.get("status") != status:
            continue
        items.append(item)

    return {"items": items, "total": total, "limite": limite, "offset": offset}


def obter_cliente(id_cliente: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM estado_cliente_ia WHERE id_cliente = %s", (id_cliente,))
            row = cur.fetchone()
    if not row:
        return None
    return _serializar_estado(dict(row))


def historico_mensagens(id_cliente: str, limite: int = 100) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite or 100), 500))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, remetente, mensagem, created_at
                FROM historico_mensagens_ia
                WHERE id_cliente = %s
                ORDER BY id ASC
                LIMIT %s
                """,
                (id_cliente, limite),
            )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        if item.get("created_at") is not None and not isinstance(item["created_at"], str):
            item["created_at"] = item["created_at"].isoformat()
        out.append(item)
    return out


def atualizar_cliente(id_cliente: str, dados: dict[str, Any]) -> dict[str, Any]:
    estado = carregar_ou_criar_estado(id_cliente)
    patch = {
        k: str(v).strip() if v is not None else ""
        for k, v in dados.items()
        if k in CAMPOS_EDITAVEIS
    }
    if not patch:
        return _serializar_estado(estado)
    return _serializar_estado(
        salvar_transicao(
            id_cliente,
            str(estado.get("fase") or "inicio"),
            estado.get("aguardando"),
            patch,
        )
    )
