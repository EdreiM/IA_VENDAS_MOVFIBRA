# -*- coding: utf-8 -*-
"""
Nome importado dentro de uma função e usado onde esse import não foi executado.

Em Python, um `from x import nome` dentro da função torna `nome` local na função
inteira. Se o import fica dentro de um `if` e outro trecho da mesma função usa o
`nome` (antes dele, ou em outro `if`), estoura UnboundLocalError em produção — foi o
que derrubava a resposta a qualquer dúvida feita na etapa de aceite dos termos.

Regra conferida: todo uso de um nome importado dentro da função precisa estar depois
de um import desse nome feito no mesmo bloco ou num bloco que contém o uso.
"""
from __future__ import annotations

import ast
import glob
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ESCOPOS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _blocos(fn: ast.AST):
    """Percorre a função (sem entrar em funções aninhadas) guardando o bloco de cada nó.

    O "caminho" de um nó é a sequência de listas de comandos (corpo de if/for/try...)
    em que ele está; um import alcança um uso se o bloco do import faz parte do
    caminho do uso.
    """
    imports: list[tuple[str, int, int]] = []  # (nome, linha, id do bloco)
    usos: list[tuple[str, int, tuple[int, ...]]] = []  # (nome, linha, caminho de blocos)

    def visitar(no: ast.AST, caminho: tuple[int, ...]) -> None:
        if isinstance(no, (ast.Import, ast.ImportFrom)):
            for alias in no.names:
                imports.append(((alias.asname or alias.name).split(".")[0], no.lineno, caminho[-1]))
            return
        if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Load):
            usos.append((no.id, no.lineno, caminho))
        for campo, valor in ast.iter_fields(no):
            if isinstance(valor, list) and valor and all(isinstance(x, ast.stmt) for x in valor):
                # O corpo de `with` e de `try` sempre executa: conta como o bloco de fora
                sempre_executa = campo == "body" and isinstance(
                    no, (ast.With, ast.AsyncWith, ast.Try)
                )
                novo = caminho if sempre_executa else caminho + (id(valor),)
                for filho in valor:
                    if not isinstance(filho, _ESCOPOS):
                        visitar(filho, novo)
            elif isinstance(valor, list):
                for filho in valor:
                    if isinstance(filho, ast.AST) and not isinstance(filho, _ESCOPOS):
                        visitar(filho, caminho)
            elif isinstance(valor, ast.AST) and not isinstance(valor, _ESCOPOS):
                visitar(valor, caminho)

    corpo = getattr(fn, "body", [])
    raiz = (id(corpo),)
    for comando in corpo:
        if not isinstance(comando, _ESCOPOS):
            visitar(comando, raiz)
    return imports, usos


def achados() -> list[str]:
    out: list[str] = []
    for arq in sorted(glob.glob(os.path.join(BACKEND, "app", "**", "*.py"), recursive=True)):
        with open(arq, encoding="utf-8") as f:
            arvore = ast.parse(f.read())
        rel = os.path.relpath(arq, BACKEND)
        for fn in ast.walk(arvore):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            imports, usos = _blocos(fn)
            if not imports:
                continue
            nomes = {n for n, _, _ in imports}
            vistos: set[tuple[str, int]] = set()
            for nome, linha, caminho in usos:
                if nome not in nomes or (nome, linha) in vistos:
                    continue
                alcanca = any(
                    n == nome and l_imp < linha and bloco in caminho for n, l_imp, bloco in imports
                )
                if not alcanca:
                    vistos.add((nome, linha))
                    onde = sorted(l_imp for n, l_imp, _ in imports if n == nome)
                    out.append(
                        f"{rel}:{linha} usa {nome!r} fora do alcance do import interno "
                        f"(linha(s) {', '.join(map(str, onde))}; função {fn.name})"
                    )
    return out


def main() -> None:
    problemas = achados()
    for p in problemas:
        print(f"  FALHOU {p}")
    if problemas:
        print(f"\n❌ {len(problemas)} uso(s) fora do alcance do import interno")
        sys.exit(1)
    print("  OK todo nome importado dentro de função é usado ao alcance do import")
    print("\n✅ Imports internos OK")


if __name__ == "__main__":
    main()
