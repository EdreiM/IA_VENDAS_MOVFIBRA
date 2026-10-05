# -*- coding: utf-8 -*-
"""
Avaliação do interpretador com o LLM de verdade.

Os testes de regressão injetam um JSON escrito à mão no parser; este script chama
o modelo configurado e mede o que ele realmente devolve.

Uso:
  py scripts/eval_interpretador.py rodar
  py scripts/eval_interpretador.py rodar --casos eval/reais/turnos.jsonl --saida eval/reais/relatorio.json
  py scripts/eval_interpretador.py exportar --limite 500

`rodar` mede dois acertos por caso:
  - LLM sozinho   → o que o modelo devolveu, antes do parser
  - LLM + parser  → o que chega na máquina de estados
A diferença mostra quanto o parser ainda está corrigindo o modelo.

`exportar` lê os turnos reais do PostgreSQL e grava em eval/reais/ (fora do Git —
contém dados pessoais dos clientes). Para virar caso de avaliação, acrescente
"esperado" na linha. Sem "esperado", `rodar` só aponta onde a interpretação de
hoje diverge da que foi registrada na época.

Formato de um caso (uma linha JSON):
  {"id": "...", "estado": {"fase": "...", "aguardando": "..."},
   "historico": [{"remetente": "eva", "mensagem": "..."}],
   "mensagem": "...",
   "esperado": {"eventos": [...], "eventos_proibidos": [...],
                "dados": {"campo": "valor"}, "dados_vazios": ["campo"]}}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.interpreter import _strip_markdown, interpretar
from app.models import CAMPOS_DADOS
from app.parser import parse_interpretacao
from app.resolver import normalizar_campo

CASOS_PADRAO = os.path.join(BACKEND, "eval", "casos_interpretador.jsonl")
DIR_REAIS = os.path.join(BACKEND, "eval", "reais")

# Campos em que basta o valor esperado estar contido no extraído
_CAMPOS_TEXTO_LIVRE = {"nome", "rua", "plano", "cidade", "bairro", "complemento", "turno_escolhido"}


def carregar_casos(caminho: str) -> list[dict[str, Any]]:
    casos: list[dict[str, Any]] = []
    with open(caminho, encoding="utf-8") as f:
        for n, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha or linha.startswith("//"):
                continue
            try:
                casos.append(json.loads(linha))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{caminho}:{n} — JSON inválido: {e}")
    return casos


def _estado_do_caso(caso: dict[str, Any]) -> dict[str, Any]:
    estado = dict(caso.get("estado") or {})
    estado.setdefault("fase", "inicio")
    if not estado.get("ultima_mensagem_sofia"):
        for h in reversed(caso.get("historico") or []):
            if str(h.get("remetente") or "") != "cliente":
                estado["ultima_mensagem_sofia"] = str(h.get("mensagem") or "")
                break
    return estado


def _bruto_do_llm(raw: str) -> tuple[list[str], dict[str, str]]:
    try:
        data = json.loads(_strip_markdown(raw))
    except json.JSONDecodeError:
        return [], {}
    if not isinstance(data, dict):
        return [], {}
    eventos = [str(e).upper() for e in (data.get("eventos") or []) if isinstance(e, str)]
    dados_in = data.get("dados") if isinstance(data.get("dados"), dict) else {}
    dados = {c: str(dados_in.get(c) or "").strip() for c in CAMPOS_DADOS}
    return eventos, dados


def _valor_confere(campo: str, esperado: str, obtido: str) -> bool:
    e = normalizar_campo(campo, esperado)
    o = normalizar_campo(campo, obtido)
    if not e:
        return not o
    if campo in _CAMPOS_TEXTO_LIVRE:
        return bool(o) and e in o
    return e == o


def conferir(
    esperado: dict[str, Any], eventos: list[str], dados: dict[str, str]
) -> list[str]:
    """Lista de problemas; vazia = acertou."""
    problemas: list[str] = []
    for ev in esperado.get("eventos") or []:
        if ev not in eventos:
            problemas.append(f"faltou evento {ev}")
    for ev in esperado.get("eventos_proibidos") or []:
        if ev in eventos:
            problemas.append(f"evento indevido {ev}")
    for campo, valor in (esperado.get("dados") or {}).items():
        obtido = str(dados.get(campo) or "")
        if not _valor_confere(campo, str(valor), obtido):
            problemas.append(f"{campo}: esperado {valor!r}, veio {obtido!r}")
    for campo in esperado.get("dados_vazios") or []:
        if str(dados.get(campo) or "").strip():
            problemas.append(f"{campo} deveria estar vazio, veio {dados.get(campo)!r}")
    return problemas


def avaliar_caso(caso: dict[str, Any]) -> dict[str, Any]:
    estado = _estado_do_caso(caso)
    mensagem = str(caso.get("mensagem") or "")
    historico = list(caso.get("historico") or [])

    raw = interpretar(mensagem, estado, historico=historico)
    eventos_llm, dados_llm = _bruto_do_llm(raw)
    final = parse_interpretacao(raw, mensagem, estado)
    eventos_final = list(final.eventos)
    dados_final = final.dados.model_dump()

    out: dict[str, Any] = {
        "id": caso.get("id"),
        "fase": estado.get("fase"),
        "aguardando": estado.get("aguardando"),
        "mensagem": mensagem,
        "eventos_llm": eventos_llm,
        "eventos_final": eventos_final,
        "dados_final": {k: v for k, v in dados_final.items() if v},
        "pergunta": final.pergunta,
        "confianca": final.confianca,
    }
    esperado = caso.get("esperado")
    if isinstance(esperado, dict):
        out["problemas_llm"] = conferir(esperado, eventos_llm, dados_llm)
        out["problemas_final"] = conferir(esperado, eventos_final, dados_final)
    registrado = (caso.get("registrado") or {}).get("eventos")
    if isinstance(registrado, list):
        out["eventos_registrados"] = registrado
        out["divergiu_do_registrado"] = set(registrado) != set(eventos_final)
    return out


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({(100 * a / b):.0f}%)" if b else "0/0"


def resumir(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    rotulados = [r for r in resultados if "problemas_final" in r]
    ok_llm = [r for r in rotulados if not r["problemas_llm"]]
    ok_final = [r for r in rotulados if not r["problemas_final"]]
    por_fase: dict[str, list[int]] = {}
    for r in rotulados:
        tot = por_fase.setdefault(str(r.get("fase") or ""), [0, 0])
        tot[1] += 1
        if not r["problemas_final"]:
            tot[0] += 1
    comparaveis = [r for r in resultados if "divergiu_do_registrado" in r]
    return {
        "casos": len(resultados),
        "rotulados": len(rotulados),
        "acerto_llm_sozinho": len(ok_llm),
        "acerto_llm_mais_parser": len(ok_final),
        "parser_corrigiu": len(
            [r for r in rotulados if r["problemas_llm"] and not r["problemas_final"]]
        ),
        "parser_estragou": len(
            [r for r in rotulados if not r["problemas_llm"] and r["problemas_final"]]
        ),
        "por_fase": {f: {"ok": v[0], "total": v[1]} for f, v in sorted(por_fase.items())},
        "comparados_com_registro": len(comparaveis),
        "divergentes_do_registro": len(
            [r for r in comparaveis if r["divergiu_do_registrado"]]
        ),
    }


def imprimir(resumo: dict[str, Any], resultados: list[dict[str, Any]]) -> None:
    n = resumo["rotulados"]
    print(f"\nCasos: {resumo['casos']}  (com resposta esperada: {n})")
    if n:
        print(f"  LLM sozinho   : {_pct(resumo['acerto_llm_sozinho'], n)}")
        print(f"  LLM + parser  : {_pct(resumo['acerto_llm_mais_parser'], n)}")
        print(f"  parser corrigiu o LLM : {resumo['parser_corrigiu']}")
        print(f"  parser estragou o LLM : {resumo['parser_estragou']}")
        print("  por fase:")
        for fase, v in resumo["por_fase"].items():
            print(f"    {fase or '(sem fase)':<14} {_pct(v['ok'], v['total'])}")
    if resumo["comparados_com_registro"]:
        print(
            "  divergentes do que foi registrado na época: "
            f"{_pct(resumo['divergentes_do_registro'], resumo['comparados_com_registro'])}"
        )

    falhas = [r for r in resultados if r.get("problemas_final")]
    if falhas:
        print("\nErros (LLM + parser):")
        for r in falhas:
            print(f"  ✗ {r['id']}  [{r['fase']}/{r['aguardando']}]  {r['mensagem'][:70]!r}")
            for p in r["problemas_final"]:
                print(f"      {p}")
            print(f"      LLM: {r['eventos_llm']}  final: {r['eventos_final']}")
    so_llm = [r for r in resultados if r.get("problemas_llm") and not r.get("problemas_final")]
    if so_llm:
        print("\nLLM errou, parser consertou:")
        for r in so_llm:
            print(f"  ~ {r['id']}  {r['mensagem'][:60]!r}: {'; '.join(r['problemas_llm'])}")
    diverg = [r for r in resultados if r.get("divergiu_do_registrado")]
    if diverg:
        print("\nDivergências do registrado (conferir à mão):")
        for r in diverg[:40]:
            print(
                f"  ? {r['id']}  {r['mensagem'][:50]!r}: "
                f"antes {sorted(r['eventos_registrados'])} → agora {sorted(r['eventos_final'])}"
            )
        if len(diverg) > 40:
            print(f"  … e mais {len(diverg) - 40}")


def cmd_rodar(args: argparse.Namespace) -> int:
    casos = carregar_casos(args.casos)
    if args.limite:
        casos = casos[: args.limite]
    resultados: list[dict[str, Any]] = []
    for i, caso in enumerate(casos, 1):
        try:
            resultados.append(avaliar_caso(caso))
        except Exception as e:  # erro de rede/chave não deve perder o que já rodou
            print(f"ERRO no caso {caso.get('id')}: {type(e).__name__}: {e}")
            if i == 1:
                return 2
            break
        if i % 10 == 0:
            print(f"  … {i}/{len(casos)}")
    resumo = resumir(resultados)
    imprimir(resumo, resultados)
    if args.saida:
        os.makedirs(os.path.dirname(os.path.abspath(args.saida)), exist_ok=True)
        with open(args.saida, "w", encoding="utf-8") as f:
            json.dump({"resumo": resumo, "resultados": resultados}, f, ensure_ascii=False, indent=2)
        print(f"\nRelatório: {args.saida}")
    n = resumo["rotulados"]
    if n and args.minimo and (100 * resumo["acerto_llm_mais_parser"] / n) < args.minimo:
        print(f"\n❌ Abaixo do mínimo de {args.minimo:.0f}%")
        return 1
    return 0


def _eventos_do_raw(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    eventos, _ = _bruto_do_llm(raw)
    return eventos


def cmd_exportar(args: argparse.Namespace) -> int:
    from app import db

    turnos = db.turnos_para_avaliacao(limite=args.limite)
    ultimo_por_cliente: dict[str, dict[str, Any]] = {}
    linhas: list[str] = []
    for t in turnos:
        cid = str(t.get("id_cliente") or "")
        estado = t.get("estado_antes")
        inferido = False
        if not isinstance(estado, dict):
            # Turnos antigos não guardavam o estado — usa fase/aguardando do turno anterior
            ant = ultimo_por_cliente.get(cid)
            estado = (
                {"fase": ant.get("fase"), "aguardando": ant.get("aguardando")}
                if ant
                else {"fase": "inicio"}
            )
            inferido = True
        ultimo_por_cliente[cid] = t
        caso = {
            "id": f"turno-{t.get('id')}",
            "conversa": hashlib.sha1(cid.encode("utf-8")).hexdigest()[:10],
            "estado": estado,
            "estado_inferido": inferido,
            "historico": t.get("historico") or [],
            "mensagem": t.get("mensagem_cliente") or "",
            "registrado": {
                "eventos": t.get("eventos") or [],
                "eventos_llm": _eventos_do_raw(t.get("interpretacao_llm")),
                "acao": t.get("acao"),
                "objetivo": t.get("objetivo"),
                "fase_depois": t.get("fase"),
                "aguardando_depois": t.get("aguardando"),
                "confianca": t.get("confianca"),
            },
        }
        linhas.append(json.dumps(caso, ensure_ascii=False))
    saida = args.saida or os.path.join(DIR_REAIS, "turnos.jsonl")
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + ("\n" if linhas else ""))
    print(f"{len(linhas)} turno(s) exportado(s) para {saida}")
    if linhas:
        print("Contém dados pessoais de clientes — não envie esse arquivo para o Git.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rodar", help="chama o LLM real em cada caso e mede os acertos")
    r.add_argument("--casos", default=CASOS_PADRAO)
    r.add_argument("--saida", default="")
    r.add_argument("--limite", type=int, default=0)
    r.add_argument("--minimo", type=float, default=0, help="%% mínimo de acerto (LLM + parser)")
    r.set_defaults(fn=cmd_rodar)

    e = sub.add_parser("exportar", help="exporta turnos reais do PostgreSQL")
    e.add_argument("--limite", type=int, default=500)
    e.add_argument("--saida", default="")
    e.set_defaults(fn=cmd_exportar)

    args = ap.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
