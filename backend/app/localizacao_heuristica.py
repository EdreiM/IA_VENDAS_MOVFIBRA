"""Heurísticas de cidade/bairro — evita Diamantino, Diamantino."""

from __future__ import annotations

import re
from typing import Any


def _texto(valor: Any) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def _norm(valor: str) -> str:
    """Normaliza; vírgula vira espaço (uso geral)."""
    t = _norm_keep_sep(valor)
    t = t.replace(",", " ")
    return re.sub(r"\s+", " ", t).strip()


def _norm_keep_sep(valor: str) -> str:
    """Normaliza mantendo vírgula / barra para split cidade,bairro."""
    t = _texto(valor).casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    t = re.sub(r"[!?.;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _titulo(valor: str) -> str:
    v = _texto(valor)
    if not v:
        return ""
    return " ".join(p.capitalize() for p in v.split())


CIDADES_CONHECIDAS = {
    "santarem",
    "santarem pa",
    "maceio",
}

BAIRROS_CONHECIDOS = {
    "diamantino",
    "prainha",
    "aldeia",
    "santissimo",
    "jatiuca",
    "ponta verde",
    "pajucara",
}


def _limpar_nome_local(nome: str, *, preferir: str | None = None) -> str:
    """Remove ruído; preferir='cidade'|'bairro' escolhe lista conhecida."""
    n = _norm(nome)
    n = re.sub(
        r"^(?:na\s+verdade|na\s+real|alias|ali+as|olha|tipo|entao|ai+|ah+|bom|"
        r"quero\s+dizer|digo|cidade|bairro)\s+",
        "",
        n,
    ).strip()
    n = re.sub(r"^(?:o|a|de|do|da|que)\s+", "", n).strip()

    ordem_bairro = sorted(BAIRROS_CONHECIDOS, key=len, reverse=True)
    ordem_cidade = sorted(CIDADES_CONHECIDAS, key=len, reverse=True)

    def _acha(lista: set[str] | list[str]) -> str | None:
        for item in lista:
            if item == n or re.search(rf"\b{re.escape(item)}\b", n):
                return _titulo(item)
        return None

    if preferir == "cidade":
        return _acha(ordem_cidade) or _titulo(n)
    if preferir == "bairro":
        return _acha(ordem_bairro) or _titulo(n)

    # genérico: cidade antes de bairro só se match exato de cidade
    hit_c = _acha(ordem_cidade)
    hit_b = _acha(ordem_bairro)
    if hit_c and (not hit_b or _norm(hit_c) == n):
        return hit_c
    if hit_b:
        return hit_b
    return _titulo(n)


def extrair_par_cidade_bairro(mensagem: str) -> dict[str, str] | None:
    """
    'Cidade santarém, diamantino' → cidade=Santarem, bairro=Diamantino
    'santarem, diamantino' / 'santarem - diamantino'
    'cidade santarem bairro diamantino'
    """
    msg = _norm_keep_sep(mensagem)
    if not msg:
        return None

    # cidade X bairro Y
    m = re.search(
        r"(?:^|\b)cidade\s+(.+?)\s+bairro\s+(.+)$",
        msg,
    )
    if m:
        return {
            "cidade": _limpar_nome_local(m.group(1), preferir="cidade"),
            "bairro": _limpar_nome_local(m.group(2), preferir="bairro"),
            "papel": "par",
        }

    # cidade X, Y  |  cidade X - Y  |  cidade X / Y
    m = re.search(
        r"(?:^|\b)cidade\s+([^,/]+?)\s*[,/\-]\s*(?:bairro\s+)?(.+)$",
        msg,
    )
    if m:
        return {
            "cidade": _limpar_nome_local(m.group(1), preferir="cidade"),
            "bairro": _limpar_nome_local(m.group(2), preferir="bairro"),
            "papel": "par",
        }

    # X, Y (dois lugares) — sem a palavra cidade
    m = re.search(r"^([^,/]{2,40}?)\s*[,/\-]\s*([^,/]{2,40})$", msg)
    if m:
        esq = _limpar_nome_local(m.group(1), preferir="cidade")
        dir_ = _limpar_nome_local(m.group(2), preferir="bairro")
        # Se à esquerda é bairro conhecido e à direita cidade, inverte
        if classificar_token_unico(m.group(1).strip()) == "bairro" and classificar_token_unico(
            m.group(2).strip()
        ) == "cidade":
            esq, dir_ = dir_, esq
        if esq and dir_ and _norm(esq) != _norm(dir_):
            return {"cidade": esq, "bairro": dir_, "papel": "par"}

    return None


def extrair_clarificacao_localizacao(mensagem: str) -> dict[str, str] | None:
    """
    'Diamantino é o bairro' / 'Na verdade diamantino é o bairro' → bairro
    'Santarém é a cidade' → cidade
    """
    # Par completo tem prioridade (evita 'cidade santarem, diamantino' virar só cidade)
    par = extrair_par_cidade_bairro(mensagem)
    if par:
        return par

    msg = _norm(mensagem)
    if not msg:
        return None
    msg = re.sub(
        r"^(?:na\s+verdade|na\s+real|alias|ali+as|olha|tipo|entao|ai+|ah+|bom)\s+",
        "",
        msg,
    ).strip()

    m = re.search(
        r"^(?:o\s+)?bairro\s*(?:e|eh|:|-)?\s+(.+)$|"
        r"^(.+?)\s+(?:e|eh)\s+(?:o\s+)?bairro$|"
        r"^(?:e|eh)\s+(?:o\s+)?bairro\s+(.+)$",
        msg,
    )
    if m:
        nome = next((g for g in m.groups() if g), "").strip()
        nome = _limpar_nome_local(nome, preferir="bairro")
        if nome and _norm(nome) not in {"bairro", "cidade"}:
            return {"bairro": nome, "papel": "bairro"}

    # "cidade santarem" sozinho (sem segundo lugar)
    m = re.search(
        r"^(?:a\s+)?cidade\s*(?:e|eh|:|-)?\s+(.+)$|"
        r"^(.+?)\s+(?:e|eh)\s+(?:a\s+)?cidade$|"
        r"^(?:e|eh)\s+(?:a\s+)?cidade\s+(.+)$",
        msg,
    )
    if m:
        nome = next((g for g in m.groups() if g), "").strip()
        # Se veio "santarem diamantino" sem vírgula, tenta separar conhecidos
        n = _norm(nome)
        for c in sorted(CIDADES_CONHECIDAS, key=len, reverse=True):
            if n.startswith(c + " "):
                resto = n[len(c) :].strip()
                if resto:
                    return {
                        "cidade": _titulo(c),
                        "bairro": _limpar_nome_local(resto, preferir="bairro"),
                        "papel": "par",
                    }
        nome = _limpar_nome_local(nome, preferir="cidade")
        if nome and _norm(nome) not in {"bairro", "cidade"}:
            return {"cidade": nome, "papel": "cidade"}

    return None


def classificar_token_unico(token: str) -> str | None:
    n = _norm(token)
    if not n or "," in n or " e " in n or len(n.split()) > 3:
        return None
    em_cidade = n in CIDADES_CONHECIDAS
    em_bairro = n in BAIRROS_CONHECIDOS
    if em_bairro and not em_cidade:
        return "bairro"
    if em_cidade and not em_bairro:
        return "cidade"
    return None


def aplicar_heuristica_localizacao(
    *,
    mensagem: str,
    dados: Any,
    estado: dict[str, Any],
    aguardando: str,
    fase: str,
) -> dict[str, Any]:
    """Ajusta dados.cidade/bairro. Retorna {limpar_cidade, ajustou}."""
    flags: dict[str, Any] = {"limpar_cidade": False, "ajustou": False}

    fase_ok = fase in {"inicio", "viabilidade", "sem_cobertura", "vendas"}
    aguardando_ok = aguardando in {"localizacao", "confirmar_bairro"}
    if not fase_ok and not aguardando_ok:
        return flags
    if fase == "vendas" and not aguardando_ok:
        return flags

    cidade_est = _texto(estado.get("cidade"))
    clar = extrair_clarificacao_localizacao(mensagem)

    if clar and clar.get("papel") == "par":
        dados.cidade = clar["cidade"]
        dados.bairro = clar["bairro"]
        flags["ajustou"] = True
        return flags

    if clar and clar.get("papel") == "bairro":
        nome = clar["bairro"]
        dados.bairro = nome
        dados.cidade = ""
        if cidade_est and _norm(cidade_est) == _norm(nome):
            flags["limpar_cidade"] = True
        flags["ajustou"] = True
        return flags

    if clar and clar.get("papel") == "cidade":
        nome = clar["cidade"]
        dados.cidade = nome
        if _texto(dados.bairro) and _norm(dados.bairro) == _norm(nome):
            dados.bairro = ""
        flags["ajustou"] = True
        return flags

    # Já veio cidade+bairro do LLM coerentes → não bagunçar
    so_cidade = _texto(dados.cidade)
    so_bairro = _texto(dados.bairro)
    if so_cidade and so_bairro and _norm(so_cidade) != _norm(so_bairro):
        # Só corrige se LLM inverteu conhecido (cidade=Diamantino, bairro=Santarem)
        if (
            classificar_token_unico(so_cidade) == "bairro"
            and classificar_token_unico(so_bairro) == "cidade"
        ):
            dados.cidade, dados.bairro = so_bairro, so_cidade
            flags["ajustou"] = True
        return flags

    msg_n = _norm(mensagem)
    token = so_cidade or so_bairro
    if not token and msg_n and len(msg_n.split()) <= 3 and "," not in mensagem:
        token = mensagem.strip()

    um_campo = bool(so_cidade) ^ bool(so_bairro)
    so_mensagem_curta = bool(msg_n) and len(msg_n.split()) <= 3 and "," not in mensagem

    if token and (um_campo or (so_mensagem_curta and not (so_cidade and so_bairro))):
        papel = classificar_token_unico(token)
        if papel == "bairro":
            dados.bairro = _titulo(so_bairro or token)
            dados.cidade = ""
            if cidade_est and _norm(cidade_est) == _norm(dados.bairro):
                flags["limpar_cidade"] = True
            flags["ajustou"] = True
        elif papel == "cidade":
            dados.cidade = _titulo(so_cidade or token)
            if so_bairro and _norm(so_bairro) == _norm(dados.cidade):
                dados.bairro = ""
            flags["ajustou"] = True

    if (
        _texto(dados.cidade)
        and _texto(dados.bairro)
        and _norm(dados.cidade) == _norm(dados.bairro)
    ):
        if classificar_token_unico(dados.bairro) == "bairro":
            dados.cidade = ""
            flags["limpar_cidade"] = True
        else:
            dados.bairro = ""
        flags["ajustou"] = True

    return flags
