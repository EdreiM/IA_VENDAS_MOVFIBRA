# -*- coding: utf-8 -*-
"""
Nome importado dentro de uma função e usado antes desse import.

Em Python, um `from x import nome` dentro da função torna `nome` local na função
inteira. Se outro trecho da mesma função usa o `nome` importado no topo do módulo
antes da linha do import interno, estoura UnboundLocalError em produção — foi o que
derrubava a resposta a qualquer dúvida feita na etapa de aceite dos termos.
"""
from __future__ import annotations

import ast
import glob
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _escopos_internos(fn: ast.AST) -> set[int]:
    ids: set[int] = set()
    for n in ast.walk(fn):
        if n is not fn and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            ids |= {id(x) for x in ast.walk(n) if x is not n}
    return ids


def achados() -> list[str]:
    out: list[str] = []
    for arq in sorted(glob.glob(os.path.join(BACKEND, "app", "**", "*.py"), recursive=True)):
        with open(arq, encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        for fn in ast.walk(arvore):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            aninhados = _escopos_internos(fn)
            internos: dict[str, int] = {}
            for n in ast.walk(fn):
                if id(n) in aninhados or not isinstance(n, (ast.Import, ast.ImportFrom)):
                    continue
                for alias in n.names:
                    nome = (alias.asname or alias.name).split(".")[0]
                    internos[nome] = min(internos.get(nome, n.lineno), n.lineno)
            for n in ast.walk(fn):
                if (
                    isinstance(n, ast.Name)
                    and isinstance(n.ctx, ast.Load)
                    and n.id in internos
                    and id(n) not in aninhados
                    and n.lineno < internos[n.id]
                ):
                    rel = os.path.relpath(arq, BACKEND)
                    out.append(
                        f"{rel}:{n.lineno} usa {n.id!r} antes do import interno da linha "
                        f"{internos[n.id]} (função {fn.name})"
                    )
    return out


def main() -> None:
    problemas = achados()
    for p in problemas:
        print(f"  FALHOU {p}")
    if problemas:
        print(f"\n❌ {len(problemas)} uso(s) antes do import interno")
        sys.exit(1)
    print("  OK nenhum nome usado antes do import interno")
    print("\n✅ Imports internos OK")


if __name__ == "__main__":
    main()
