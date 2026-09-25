"""Resolver de referência de plano — determinístico, sem LLM."""

from __future__ import annotations

import re
from typing import Any


def _norm(texto: str) -> str:
    t = str(texto or "").casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    t = t.replace("+", " plus ")
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _alias(nome: str) -> str:
    genericas = {"mov", "plano", "combo"}
    return " ".join(p for p in _norm(nome).split() if p and p not in genericas)


def _lev(a: str, b: str) -> int:
    s, t = a, b
    if s == t:
        return 0
    if not s:
        return len(t)
    if not t:
        return len(s)
    prev = list(range(len(t) + 1))
    for i, ca in enumerate(s, 1):
        curr = [i]
        for j, cb in enumerate(t, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _precos(texto: str, *, minimo: float = 50) -> list[float]:
    nums = re.findall(r"\d+(?:[.,]\d{1,2})?", str(texto or ""))
    out: list[float] = []
    for n in nums:
        try:
            v = float(n.replace(",", "."))
        except ValueError:
            continue
        if v >= minimo:
            out.append(v)
    return out


def _preco_compativel(alvo: float, candidato: float) -> bool:
    """Igualdade ou '69' referindo-se a promo R$ 69,50."""
    if abs(alvo - candidato) < 0.011:
        return True
    if alvo == int(alvo) and abs(candidato - alvo) < 1.0:
        return True
    return False


def _precos_do_plano(plano: dict[str, Any]) -> set[float]:
    """Todos os valores citados no plano (mensal, pontualidade, promo na descrição)."""
    precos: set[float] = set()
    try:
        valor = float(plano.get("valor") or 0)
        if valor > 0:
            precos.add(valor)
    except (TypeError, ValueError):
        pass
    pont = plano.get("valor_pontualidade")
    if pont is not None and str(pont).strip() != "":
        try:
            precos.add(float(pont))
        except (TypeError, ValueError):
            pass
    blob = " ".join(
        str(plano.get(campo) or "")
        for campo in ("descricao", "beneficios", "condicao_valor_pontualidade")
    )
    for p in _precos(blob, minimo=30):
        precos.add(p)
    return precos


def _plano_tem_preco(plano: dict[str, Any], alvo: float) -> tuple[bool, str]:
    """Verifica se o preço pedido bate com valor, pontualidade ou promo no texto."""
    try:
        valor = float(plano.get("valor") or 0)
        if _preco_compativel(alvo, valor):
            return True, "PRECO_EXATO"
    except (TypeError, ValueError):
        pass
    pont = plano.get("valor_pontualidade")
    if pont is not None and str(pont).strip() != "":
        try:
            if _preco_compativel(alvo, float(pont)):
                return True, "PRECO_PONTUALIDADE"
        except (TypeError, ValueError):
            pass
    extras = _precos_do_plano(plano) - {float(plano.get("valor") or 0)}
    try:
        if pont is not None:
            extras.discard(float(pont))
    except (TypeError, ValueError):
        pass
    for p in extras:
        if _preco_compativel(alvo, p):
            return True, "PRECO_PROMOCIONAL"
    return False, "SEM_CORRESPONDENCIA"


INTENCOES_TAG: list[tuple[tuple[str, ...], str]] = [
    (("mais barato", "mais barata", "economico", "economica", "menor preco", "mais em conta", "o mais barato"), "mais_barato"),
    (("mais caro", "premium", "top", "melhor plano", "mais completo", "mais rapido", "mais veloz", "mais forte", "plano forte", "mais potente", "mais velocidade"), "premium"),
    (("mesh", "repetidor", "roteador", "roteadores", "dois roteadores", "2 roteadores", "dois wifi"), "mesh"),
    (("telemedicina",), "telemedicina"),
    (("exitlag", "jogos", "jogo", "games", "games"), "exitlag"),
    (("kaspersky",), "kaspersky"),
    (("disney",), "disney"),
    (("pontualidade", "desconto no boleto"), "pontualidade"),
    (("chip", "celular", "linha movel"), "chip"),
    (("12gb", "12 gb"), "chip_12gb"),
    (("22gb", "22 gb"), "chip_22gb"),
    (("one plus", "one+"), "one_plus"),
    (("up plus", "up+"), "up_plus"),
    (("super plus", "super+"), "super_plus"),
    (
        (
            "primeiros meses",
            "primeiro mes",
            "3 primeiros",
            "tres primeiros",
            "desconto nos 3",
            "50 por cento",
            "50%",
            "promocao inicial",
            "promo inicial",
        ),
        "promo_inicial",
    ),
    (("infinity",), "infinity"),
    (("essencial",), "essencial"),
    (("flex",), "flex"),
    (("combo",), "combo"),
]

# Tags de catálogo equivalentes à intenção de preço
_TAGS_ALIAS: dict[str, tuple[str, ...]] = {
    "mais_barato": ("mais_barato", "economico"),
    "premium": ("premium", "infinity", "muitos_dispositivos"),
}


def _preco_comparacao(plano: dict[str, Any]) -> float:
    """Menor preço efetivo (pontualidade quando existir)."""
    valor = float(plano.get("valor") or 0)
    pont = plano.get("valor_pontualidade")
    if pont is not None and str(pont).strip() != "":
        try:
            return min(valor, float(pont))
        except (TypeError, ValueError):
            pass
    return valor


def _tags_plano(plano: dict[str, Any]) -> set[str]:
    return {str(t).casefold() for t in (plano.get("tags") or [])}


def _resolver_por_preco(
    intencao: str,
    planos: list[dict[str, Any]],
    *,
    plano_atual_id: int | None = None,
) -> dict[str, Any] | None:
    """'mais barato' / 'premium' → 1 plano (ou poucos empates), nunca o catálogo inteiro."""
    if not planos:
        return None

    pool = list(planos)
    if plano_atual_id is not None:
        try:
            ref = next(p for p in planos if int(p["id"]) == int(plano_atual_id))
        except StopIteration:
            ref = None
        if ref is not None:
            ref_preco = _preco_comparacao(ref)
            if intencao == "mais_barato":
                abaixo = [
                    p
                    for p in planos
                    if int(p["id"]) != int(plano_atual_id)
                    and _preco_comparacao(p) < ref_preco - 0.001
                ]
                if abaixo:
                    pool = abaixo
            elif intencao == "premium":
                acima = [
                    p
                    for p in planos
                    if int(p["id"]) != int(plano_atual_id)
                    and _preco_comparacao(p) > ref_preco + 0.001
                ]
                if acima:
                    pool = acima

    reverse = intencao == "premium"
    ordered = sorted(pool, key=_preco_comparacao, reverse=reverse)
    melhor = ordered[0]
    alvo = _preco_comparacao(melhor)
    empates = [
        p for p in ordered if abs(_preco_comparacao(p) - alvo) < 0.011
    ][:3]

    criterio = "MAIS_BARATO" if intencao == "mais_barato" else "PREMIUM"
    if len(empates) == 1:
        return {
            "evento": "PLANO_RESOLVIDO",
            "plano": _plano_resolvido(empates[0], criterio, 95),
            "candidatos": [],
        }
    return {
        "evento": "PLANO_AMBIGUO",
        "plano": None,
        "candidatos": [_plano_resolvido(p, criterio, 90) for p in empates],
    }


def _tags_da_referencia(ref: str) -> list[str]:
    tags: list[str] = []
    for keywords, tag in INTENCOES_TAG:
        if any(k in ref for k in keywords):
            tags.append(tag)
    return tags


def _plano_resolvido(plano: dict[str, Any], criterio: str, score: int) -> dict[str, Any]:
    return {
        "id": int(plano["id"]),
        "nome": plano["nome"],
        "valor": float(plano.get("valor") or 0),
        "velocidade": plano.get("velocidade") or "",
        "modalidade": plano.get("modalidade") or "",
        "requer_cartao": bool(plano.get("requer_cartao")),
        "descricao": plano.get("descricao") or "",
        "beneficios": plano.get("beneficios") or "",
        "dispositivos_max": plano.get("dispositivos_max"),
        "valor_pontualidade": plano.get("valor_pontualidade"),
        "condicao_valor_pontualidade": plano.get("condicao_valor_pontualidade"),
        "tags": plano.get("tags") or [],
        "criterio_resolucao": criterio,
        "score_resolucao": score,
    }


def _resolver_por_tags(
    ref: str,
    planos: list[dict[str, Any]],
    *,
    plano_atual_id: int | None = None,
) -> dict[str, Any] | None:
    tags = _tags_da_referencia(ref)
    if not tags:
        return None

    # Preço: resolve por valor, não por tag solta (evita dump do catálogo)
    if "mais_barato" in tags:
        return _resolver_por_preco("mais_barato", planos, plano_atual_id=plano_atual_id)
    if "premium" in tags:
        return _resolver_por_preco("premium", planos, plano_atual_id=plano_atual_id)

    matches = list(planos)
    for tag in tags:
        aliases = _TAGS_ALIAS.get(tag, (tag,))
        filtrados = [
            p for p in matches if _tags_plano(p).intersection(aliases)
        ]
        if filtrados:
            matches = filtrados
        else:
            # Tag pedida sem match → não “soltar” o catálogo inteiro
            return None

    if not matches:
        return None
    if len(matches) == 1:
        return {
            "evento": "PLANO_RESOLVIDO",
            "plano": _plano_resolvido(matches[0], "TAG_" + tags[-1].upper(), 85),
            "candidatos": [],
        }
    # No máx. 3 candidatos (ordem por preço)
    matches = sorted(matches, key=_preco_comparacao)[:3]
    return {
        "evento": "PLANO_AMBIGUO",
        "plano": None,
        "candidatos": [
            _plano_resolvido(p, "TAG_" + tags[-1].upper(), 80) for p in matches
        ],
    }


def resolver_plano(
    referencia: str,
    planos: list[dict[str, Any]],
    *,
    plano_atual_id: int | None = None,
) -> dict[str, Any]:
    ref_orig = str(referencia or "").strip()
    ref = _norm(ref_orig)
    precos = _precos(ref_orig)

    if not ref:
        return {"evento": "PLANO_NAO_ENCONTRADO", "plano": None, "candidatos": []}

    por_tags = _resolver_por_tags(ref, planos, plano_atual_id=plano_atual_id)
    if por_tags and por_tags.get("evento") == "PLANO_RESOLVIDO":
        return por_tags
    # Intenção de preço/benefício já veio ambígua com poucos candidatos
    if por_tags and por_tags.get("evento") == "PLANO_AMBIGUO":
        tags = _tags_da_referencia(ref)
        if any(t in {"mais_barato", "premium", "mesh", "chip", "telemedicina"} for t in tags):
            return por_tags

    avaliados = []
    for plano in planos:
        nome = _norm(plano.get("nome") or "")
        alias = _alias(plano.get("nome") or "")
        valor = float(plano.get("valor") or 0)
        score = 0
        criterio = "SEM_CORRESPONDENCIA"

        if ref == nome:
            score, criterio = 110, "NOME_COMPLETO_EXATO"
        elif ref == alias:
            score, criterio = 100, "ALIAS_EXATO"
        elif precos:
            for p_alvo in precos:
                bate, crit = _plano_tem_preco(plano, p_alvo)
                if bate:
                    score, criterio = 95, crit
                    break
        elif len(ref) >= 3 and (ref in nome or ref in alias):
            score, criterio = 90, "REFERENCIA_CONTIDA"
        elif len(alias) >= 3 and alias in ref:
            score, criterio = 88, "NOME_CONTIDO"
        elif len(ref) >= 4 and len(alias) >= 4:
            d = _lev(ref, alias)
            if d == 1:
                score, criterio = 82, "ERRO_DIGITACAO_1"
            elif d == 2 and max(len(ref), len(alias)) >= 7:
                score, criterio = 76, "ERRO_DIGITACAO_2"

        avaliados.append({"plano": plano, "score": score, "criterio": criterio})

    avaliados.sort(key=lambda x: (-x["score"], _preco_comparacao(x["plano"])))
    melhor = avaliados[0]["score"] if avaliados else 0
    tops = [a for a in avaliados if a["score"] == melhor and a["score"] >= 70]

    if not tops:
        if por_tags:
            return por_tags
        return {"evento": "PLANO_NAO_ENCONTRADO", "plano": None, "candidatos": []}
    if len(tops) > 1:
        return {
            "evento": "PLANO_AMBIGUO",
            "plano": None,
            "candidatos": [
                _plano_resolvido(t["plano"], t["criterio"], t["score"]) for t in tops[:3]
            ],
        }

    v = tops[0]
    p = v["plano"]
    return {
        "evento": "PLANO_RESOLVIDO",
        "plano": _plano_resolvido(p, v["criterio"], v["score"]),
        "candidatos": [],
    }


def alternativas(planos: list[dict[str, Any]], plano_ref_id: int | None) -> list[dict[str, Any]]:
    candidatos = [p for p in planos if plano_ref_id is None or int(p["id"]) != int(plano_ref_id)]
    if not candidatos:
        return []

    ref_valor = None
    for p in planos:
        if plano_ref_id is not None and int(p["id"]) == int(plano_ref_id):
            ref_valor = float(p["valor"])
            break

    escolhidos: list[dict[str, Any]] = []
    usados: set[int] = set()

    if ref_valor is not None:
        abaixo = [p for p in candidatos if float(p["valor"]) < ref_valor]
        if abaixo:
            e = max(abaixo, key=lambda p: float(p["valor"]))
            escolhidos.append({**e, "perfil": "ECONOMICO"})
            usados.add(int(e["id"]))

    resto = [p for p in candidatos if int(p["id"]) not in usados]
    if resto:
        if ref_valor is None:
            a = min(resto, key=lambda p: float(p["valor"]))
        else:
            a = min(resto, key=lambda p: abs(float(p["valor"]) - ref_valor))
        escolhidos.append({**a, "perfil": "ALTERNATIVA"})
        usados.add(int(a["id"]))

    resto = [p for p in candidatos if int(p["id"]) not in usados]
    if resto:
        prem = max(resto, key=lambda p: float(p["valor"]))
        escolhidos.append({**prem, "perfil": "PREMIUM"})

    return escolhidos
