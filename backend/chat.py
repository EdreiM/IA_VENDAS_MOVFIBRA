"""Chat no terminal — útil sem abrir o browser."""

from __future__ import annotations

import sys

from app.config import get_settings
from app.db import init_schema, resetar_cliente
from app.pipeline import process_message


def main() -> None:
    settings = get_settings()
    id_cliente = settings.default_client_id
    print("Eva local — digite /sair ou /reset")
    print(f"cliente={id_cliente} | llm={settings.llm_provider}")
    init_schema()

    while True:
        try:
            msg = input("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg.lower() in {"/sair", "/exit", "sair"}:
            break
        if msg.lower() in {"/reset", "reset"}:
            resetar_cliente(id_cliente)
            print("Eva: conversa reiniciada.")
            continue
        try:
            r = process_message(id_cliente, msg)
        except Exception as exc:  # noqa: BLE001
            print(f"ERRO: {exc}", file=sys.stderr)
            continue
        print(f"Eva: {r.resposta}")
        st = r.estado
        print(
            f"  [{st.get('fase')}/{st.get('aguardando')}] "
            f"eventos={r.interpretacao.eventos} "
            f"acao={r.decisao.acao}"
        )


if __name__ == "__main__":
    main()
