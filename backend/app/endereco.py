"""Endereço do cliente no formato que o cadastro (IXC) aceita.

Dois problemas vistos em atendimento real (08/10/2026):

1. O cliente manda o endereço inteiro com rótulos, uma linha por campo:

       Cidade: Santarém/PA
       Rua: Rua São Marco
       Bairro: Nova Vitória
       Número da residência: nº 729, Bloco 04, Apartamento 104 (cond. boulevard tapajós)
       CEP ou localização fixa: 68038-040
       Ponto de referência: próximo ao supermercado Atacadão

   e a Eva pedia cidade e bairro de novo. `extrair_endereco_rotulado` lê esse bloco.

2. O campo número guardava "nº 729, Bloco 04, Apartamento 104 (cond. boulevard tapajós)".
   O IXC só aceita o número da casa nesse campo. `separar_numero` deixa no número só o
   número (ou S/N) e devolve o resto para o complemento.
"""

from __future__ import annotations

import re
import unicodedata

SEM_NUMERO = "S/N"
_MAX_COMPLEMENTO = 140

# Palavras que abrem um complemento, não o número da casa
_MARCAS_SEM_NUMERO = ("lote", "lt", "quadra", "qd", "km")
_MARCAS_DE_COMPLEMENTO = (
    "bloco", "bl", "apto", "apt", "ap", "apartamento", "sala", "loja", "andar", "torre",
    "edificio", "ed", "condominio", "cond", "residencial", "fundos", "altos", "kitnet",
)
_RE_PREFIXO_NUMERO = re.compile(
    r"^\s*(?:(?:n[ºo°]\.?|n[uú]m(?:ero)?\.?|casa)\s*)?(?:n[ºo°]\.?\s*)?", re.I
)
_RE_NUMERO_PURO = re.compile(r"^\d{1,6}[A-Za-z]?$")
_RE_SEM_NUMERO = re.compile(r"(?i)^\s*(s\s*/?\s*n|sn|sem\s+n[uú]mero|n[aã]o\s+tem(\s+n[uú]mero)?)\s*$")


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn"
    ).casefold()


def juntar_complemento(*partes: str) -> str:
    """Junta trechos de complemento sem repetir o que já está contido em outro."""
    limpos: list[str] = []
    for parte in partes:
        p = re.sub(r"\s+", " ", str(parte or "")).strip(" ,;.-–")
        if not p:
            continue
        chave = _sem_acento(p)
        if any(chave in _sem_acento(x) for x in limpos):
            continue
        limpos = [x for x in limpos if _sem_acento(x) not in chave]
        limpos.append(p)
    return ", ".join(limpos)[:_MAX_COMPLEMENTO]


def separar_numero(valor: str) -> tuple[str, str]:
    """(número da casa, resto que é complemento).

    "nº 729, Bloco 04, Apto 104" → ("729", "Bloco 04, Apto 104")
    "729-B"                      → ("729B", "")
    "casa 12 fundos"             → ("12", "fundos")
    "lote 5 quadra 12", "km 14"  → ("S/N", o texto inteiro)
    "s/n", "sem número"          → ("S/N", "")
    Texto sem nenhum número vira ("", texto): o número continua faltando.
    """
    bruto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if not bruto:
        return "", ""
    if _RE_SEM_NUMERO.match(bruto):
        return SEM_NUMERO, ""
    compacto = re.sub(r"(?<=\d)\s*-\s*(?=[A-Za-z]$)", "", bruto)  # "729-B" → "729B"
    if _RE_NUMERO_PURO.match(compacto):
        return compacto.upper() if compacto[-1].isalpha() else compacto, ""

    primeira = re.match(r"[a-z]+", _sem_acento(bruto))
    if primeira and primeira.group(0) in _MARCAS_SEM_NUMERO:
        # Endereço por lote/quadra/km: não há número de casa
        return SEM_NUMERO, bruto
    if primeira and primeira.group(0) in _MARCAS_DE_COMPLEMENTO:
        # "bloco B apto 3": é complemento; o número do prédio ainda falta
        return "", bruto
    sem_prefixo = _RE_PREFIXO_NUMERO.sub("", bruto, count=1)
    m = re.match(r"(\d{1,6})(?:\s*-?\s*([A-Za-z])(?![A-Za-zÀ-ÿ]))?[\s,;.\-–]*(.*)$", sem_prefixo)
    if not m:
        return "", bruto
    numero = m.group(1) + (m.group(2) or "").upper()
    return numero, m.group(3).strip(" ,;.-–")


def numero_e_complemento(estado: dict) -> tuple[str, str]:
    """Número e complemento como devem sair para o cadastro e para o resumo.

    Trava final: mesmo que um atendimento antigo tenha gravado texto no campo número,
    o que vai para o IXC e o que o cliente confere é só o número, com o resto no complemento.
    """
    numero_bruto = str(estado.get("numero") or "").strip()
    complemento = str(estado.get("complemento") or "").strip()
    if not numero_bruto:
        return "", complemento
    numero, resto = separar_numero(numero_bruto)
    return numero, juntar_complemento(resto, complemento) if resto else complemento


_ROTULOS: tuple[tuple[str, str], ...] = (
    ("cidade", r"cidade|municipio"),
    ("bairro", r"bairro"),
    ("cep", r"cep"),
    ("numero", r"n[uú]mero|n[ºo°]\.?|num\.?"),
    ("complemento", r"complemento|compl\.?"),
    ("referencia", r"ponto\s+de\s+refer[eê]ncia|refer[eê]ncia|ref\.?|perto\s+de|pr[oó]ximo"),
    ("rua", r"rua|endere[cç]o|logradouro|avenida|travessa"),
)
_RE_LINHA_ROTULADA = re.compile(r"^\s*[-•*]?\s*([^:\n]{2,40}?)\s*:\s*(\S.*?)\s*$")
_RE_UF_NO_FIM = re.compile(r"\s*[/,\-–]\s*[A-Za-z]{2}\s*$")


def _campo_do_rotulo(rotulo: str) -> str:
    r = _sem_acento(rotulo)
    for campo, padrao in _ROTULOS:
        if re.match(rf"(?:{_sem_acento(padrao)})\b", r):
            return campo
    return ""


def extrair_endereco_rotulado(mensagem: str) -> dict[str, str]:
    """Campos de endereço de uma mensagem com um rótulo por linha. Vazio se não for esse formato.

    Devolve as chaves: cidade, bairro, rua, numero, complemento, cep (as que existirem).
    O número já sai separado do complemento; o ponto de referência entra no complemento.
    """
    achados: dict[str, str] = {}
    for linha in str(mensagem or "").splitlines():
        m = _RE_LINHA_ROTULADA.match(linha)
        if not m:
            continue
        campo = _campo_do_rotulo(m.group(1))
        valor = m.group(2).strip()
        if campo and valor and campo not in achados:
            achados[campo] = valor
    if len(achados) < 2:
        return {}

    out: dict[str, str] = {}
    if achados.get("cidade"):
        out["cidade"] = _RE_UF_NO_FIM.sub("", achados["cidade"]).strip()
    if achados.get("bairro"):
        out["bairro"] = achados["bairro"].strip(" .")
    if achados.get("rua"):
        out["rua"] = achados["rua"].strip(" .")
    if achados.get("cep"):
        digitos = re.sub(r"\D", "", achados["cep"])
        if len(digitos) == 8:
            out["cep"] = digitos
    resto_numero = ""
    if achados.get("numero"):
        numero, resto_numero = separar_numero(achados["numero"])
        if numero:
            out["numero"] = numero
    referencia = achados.get("referencia", "")
    complemento = juntar_complemento(
        resto_numero, achados.get("complemento", ""), f"ref.: {referencia}" if referencia else ""
    )
    if complemento:
        out["complemento"] = complemento
    return out
