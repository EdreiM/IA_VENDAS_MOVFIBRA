from __future__ import annotations

import json
from typing import Any

from .db import get_connection


def _parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(t) for t in data]
        except json.JSONDecodeError:
            return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _row_plano(r: Any) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "nome": r["nome"],
        "velocidade": r["velocidade"],
        "modalidade": r["modalidade"],
        "requer_cartao": bool(r["requer_cartao"]),
        "valor": float(r["valor"]),
        "parcelas": r["parcelas"],
        "descricao": r["descricao"] or "",
        "dispositivos_max": r["dispositivos_max"] or r["max_dispositivos"],
        "beneficios": r["beneficios"] or "",
        "ordem": int(r["ordem"] or 100),
        "ativo": bool(r["ativo"]),
        "destaque": bool(r["destaque"]),
        "unidade_id": r["unidade_id"],
        "imagem_url": r["imagem_url"] or "",
        "valor_pontualidade": (
            float(r["valor_pontualidade"])
            if r.get("valor_pontualidade") is not None
            else None
        ),
        "condicao_valor_pontualidade": r.get("condicao_valor_pontualidade") or "",
        "tags": _parse_tags(r.get("tags")),
    }


def _definir_plano_inicial(cur: Any, plano_id: int) -> None:
    """Garante um único plano inicial (destaque) entre planos globais."""
    cur.execute("UPDATE planos SET destaque = 0 WHERE unidade_id IS NULL")
    cur.execute(
        "UPDATE planos SET destaque = 1 WHERE id = %s",
        (plano_id,),
    )


def listar_planos_admin(
    *,
    unidade_id: int | None = None,
    apenas_ativos: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if apenas_ativos:
        clauses.append("ativo = 1")
    if unidade_id is not None:
        clauses.append("(unidade_id IS NULL OR unidade_id = %s)")
        params.append(unidade_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM planos {where} ORDER BY ordem ASC, valor ASC, id ASC",
                tuple(params),
            )
            return [_row_plano(r) for r in cur.fetchall()]


def obter_plano(plano_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM planos WHERE id = %s", (plano_id,))
            row = cur.fetchone()
            return _row_plano(row) if row else None


def criar_plano(dados: dict[str, Any]) -> dict[str, Any]:
    from app.plans_catalog import invalidar_cache_planos

    tags = dados.get("tags") or []
    if isinstance(tags, str):
        tags = _parse_tags(tags)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO planos (
                    nome, velocidade, modalidade, requer_cartao, valor, parcelas,
                    descricao, dispositivos_max, max_dispositivos, beneficios,
                    ordem, ativo, destaque, unidade_id, imagem_url,
                    valor_pontualidade, condicao_valor_pontualidade, tags
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    str(dados["nome"]).strip(),
                    str(dados.get("velocidade") or "").strip() or None,
                    str(dados.get("modalidade") or "").strip() or None,
                    1 if dados.get("requer_cartao") else 0,
                    float(dados["valor"]),
                    dados.get("parcelas"),
                    str(dados.get("descricao") or ""),
                    dados.get("dispositivos_max") or dados.get("max_dispositivos"),
                    dados.get("max_dispositivos") or dados.get("dispositivos_max"),
                    str(dados.get("beneficios") or ""),
                    int(dados.get("ordem") or 100),
                    1 if dados.get("ativo", True) else 0,
                    1 if dados.get("destaque") else 0,
                    dados.get("unidade_id"),
                    str(dados.get("imagem_url") or "").strip() or None,
                    dados.get("valor_pontualidade"),
                    str(dados.get("condicao_valor_pontualidade") or "").strip() or None,
                    json.dumps(list(tags), ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
            plano = _row_plano(row)
            if dados.get("destaque"):
                _definir_plano_inicial(cur, int(plano["id"]))
                plano = obter_plano(int(plano["id"])) or plano
    invalidar_cache_planos()
    return plano


def atualizar_plano(plano_id: int, dados: dict[str, Any]) -> dict[str, Any] | None:
    from app.plans_catalog import invalidar_cache_planos

    atual = obter_plano(plano_id)
    if not atual:
        return None
    tags = dados.get("tags") if "tags" in dados else atual.get("tags") or []
    if isinstance(tags, str):
        tags = _parse_tags(tags)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE planos SET
                    nome = %s,
                    velocidade = %s,
                    modalidade = %s,
                    requer_cartao = %s,
                    valor = %s,
                    parcelas = %s,
                    descricao = %s,
                    dispositivos_max = %s,
                    max_dispositivos = %s,
                    beneficios = %s,
                    ordem = %s,
                    ativo = %s,
                    destaque = %s,
                    unidade_id = %s,
                    imagem_url = %s,
                    valor_pontualidade = %s,
                    condicao_valor_pontualidade = %s,
                    tags = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    str(dados.get("nome") or atual["nome"]).strip(),
                    str(
                        dados.get("velocidade")
                        if "velocidade" in dados
                        else atual["velocidade"] or ""
                    )
                    or None,
                    str(
                        dados.get("modalidade")
                        if "modalidade" in dados
                        else atual["modalidade"] or ""
                    )
                    or None,
                    1
                    if (
                        dados.get("requer_cartao")
                        if "requer_cartao" in dados
                        else atual["requer_cartao"]
                    )
                    else 0,
                    float(dados["valor"] if "valor" in dados else atual["valor"]),
                    dados.get("parcelas") if "parcelas" in dados else atual["parcelas"],
                    str(
                        dados.get("descricao")
                        if "descricao" in dados
                        else atual["descricao"]
                    ),
                    dados.get("dispositivos_max")
                    if "dispositivos_max" in dados
                    else atual["dispositivos_max"],
                    dados.get("dispositivos_max")
                    if "dispositivos_max" in dados
                    else atual["dispositivos_max"],
                    str(
                        dados.get("beneficios")
                        if "beneficios" in dados
                        else atual["beneficios"]
                    ),
                    int(dados.get("ordem") if "ordem" in dados else atual["ordem"]),
                    1 if (dados.get("ativo") if "ativo" in dados else atual["ativo"]) else 0,
                    1
                    if (dados.get("destaque") if "destaque" in dados else atual["destaque"])
                    else 0,
                    dados.get("unidade_id") if "unidade_id" in dados else atual["unidade_id"],
                    (
                        str(dados.get("imagem_url") or "").strip() or None
                        if "imagem_url" in dados
                        else (atual["imagem_url"] or None)
                    ),
                    (
                        dados.get("valor_pontualidade")
                        if "valor_pontualidade" in dados
                        else atual.get("valor_pontualidade")
                    ),
                    (
                        str(
                            dados.get("condicao_valor_pontualidade")
                            if "condicao_valor_pontualidade" in dados
                            else atual.get("condicao_valor_pontualidade") or ""
                        ).strip()
                        or None
                    ),
                    json.dumps(list(tags), ensure_ascii=False),
                    plano_id,
                ),
            )
            if not cur.fetchone():
                return None
            if dados.get("destaque"):
                _definir_plano_inicial(cur, plano_id)
            plano = obter_plano(plano_id)
    invalidar_cache_planos()
    return plano


def deletar_plano(plano_id: int) -> bool:
    from app.plans_catalog import invalidar_cache_planos

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM planos WHERE id = %s", (plano_id,))
            ok = cur.rowcount > 0
    if ok:
        invalidar_cache_planos()
    return ok


def definir_plano_inicial(plano_id: int) -> dict[str, Any] | None:
    from app.plans_catalog import invalidar_cache_planos

    atual = obter_plano(plano_id)
    if not atual:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            _definir_plano_inicial(cur, plano_id)
    invalidar_cache_planos()
    return obter_plano(plano_id)
