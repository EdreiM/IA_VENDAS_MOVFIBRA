"""Testes de persistência de URLs de ferramentas entre deploys."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _assert(cond: bool, msg: str = "") -> None:
    if not cond:
        raise AssertionError(msg or "assertion failed")


def test_seed_nao_altera_ferramenta_existente() -> None:
    from app.ferramentas_catalog import seed_ferramentas_do_catalogo

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 7, "webhook_url": "https://painel.exemplo/webhook/cadastro"},
        {"id": 8, "webhook_url": ""},
    ] + [{"id": i, "webhook_url": ""} for i in range(9, 20)]

    criadas = seed_ferramentas_do_catalogo(cur)
    _assert(criadas == 0, f"criadas={criadas}")
    updates = [
        c
        for c in cur.execute.call_args_list
        if "UPDATE ferramentas SET webhook_url" in str(c.args[0])
    ]
    _assert(not updates, f"seed alterou URL existente: {updates}")


def test_atualizar_ferramenta_nao_apaga_url_vazia() -> None:
    from app.ferramentas import atualizar_ferramenta

    atual = {
        "id": 1,
        "tool_key": "cadastrar_cliente",
        "nome": "Cadastrar",
        "descricao": "",
        "webhook_url": "https://n8n2.mov.pro.br/webhook/cadastrar_cliente_sofia",
        "integracao": "global",
        "unidade_id": None,
        "destaque_dashboard": True,
        "ativo": True,
    }
    row = dict(atual)
    row["created_at"] = row["updated_at"] = "2026-01-01T00:00:00+00:00"
    row["chamadas_sucesso"] = 0

    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.ferramentas.obter_ferramenta", return_value=atual), patch(
        "app.ferramentas.get_connection", return_value=conn
    ), patch("app.ferramentas._salvar_parametros"), patch(
        "app.ferramentas._row_to_tool", return_value=atual
    ), patch(
        "app.ferramentas_catalog.gravar_backup_url_ferramenta"
    ):
        out = atualizar_ferramenta(1, {"webhook_url": ""})
    _assert(out is not None)
    args = cur.execute.call_args_list[0].args[1]
    _assert(
        args[3] == "https://n8n2.mov.pro.br/webhook/cadastrar_cliente_sofia",
        f"url apagada: {args[3]}",
    )


def test_resolver_usa_backup_quando_painel_vazio() -> None:
    from app.ferramentas_catalog import resolver_url_ferramenta

    with patch("app.ferramentas.obter_ferramenta_por_key", return_value={"webhook_url": ""}), patch(
        "app.ferramentas_catalog.ler_backup_url_ferramenta",
        return_value="https://backup.exemplo/termos",
    ):
        url = resolver_url_ferramenta("enviar_termos", fallback_env="")
    _assert(url == "https://backup.exemplo/termos", url)


if __name__ == "__main__":
    tests = [
        test_seed_nao_altera_ferramenta_existente,
        test_atualizar_ferramenta_nao_apaga_url_vazia,
        test_resolver_usa_backup_quando_painel_vazio,
    ]
    falhas = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK {fn.__name__}")
        except Exception as e:
            falhas += 1
            print(f"  FALHOU {fn.__name__}: {e}")
    if falhas:
        print(f"\n❌ {falhas} falha(s)")
        sys.exit(1)
    print("\nPersistencia de ferramentas OK")
