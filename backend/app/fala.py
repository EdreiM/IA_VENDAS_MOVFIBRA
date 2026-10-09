"""Fala → escrita: o que o cliente dita por áudio vira o dado como ele o digitaria.

A transcrição devolve o que foi falado: "maria arroba gmail ponto com", "cinco dois nove
nove oito...", "oitocentos e noventa e um". As regras de cadastro só aceitam um valor que
esteja escrito na mensagem, então sem esta conversão o dado ditado nunca era gravado.

- e-mail por extenso ("arroba", "ponto", "underline") é remontado em qualquer mensagem;
- número por extenso só é convertido em mensagem de áudio, e só quando é claramente um
  dado: três ou mais números seguidos, logo depois de "CPF", "telefone", "número"..., ou
  quando a Eva está esperando um número. "Um momento" e "tenho dois filhos" ficam como estão.
"""

from __future__ import annotations

import re
import unicodedata

_UNIDADES = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "meia": 6, "sete": 7, "oito": 8, "nove": 9,
}
_DEZ_A_DEZENOVE = {
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14, "quinze": 15,
    "dezesseis": 16, "dezasseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
}
_DEZENAS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
    "oitenta": 80, "noventa": 90,
}
_CENTENAS = {
    "cem": 100, "cento": 100, "duzentos": 200, "trezentos": 300, "quatrocentos": 400,
    "quinhentos": 500, "seiscentos": 600, "setecentos": 700, "oitocentos": 800, "novecentos": 900,
}
_MESES = {
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro",
    "outubro", "novembro", "dezembro",
}
# Palavras que anunciam um número de cadastro logo em seguida
_ANUNCIA_NUMERO = {
    "cpf", "cep", "telefone", "celular", "fone", "whatsapp", "zap", "numero", "casa", "apartamento",
    "apto", "bloco", "lote", "quadra", "ddd", "rg",
}
_ESPERA_NUMERO_LONGO = {"cpf", "telefone", "cep"}
_ESPERA_ENDERECO = {"rua", "numero"}

_PROVEDORES_COM = {"gmail", "hotmail", "outlook", "yahoo", "icloud", "live", "bol", "uol"}
_FIM_DE_DOMINIO = {"com", "br", "net", "org", "gov", "edu", "io", "co", "me", "info", "pt"}
_SEPARADOR_FALADO = {
    "ponto": ".", "underline": "_", "underscore": "_", "anderlaine": "_", "traco": "-",
    "hifen": "-", "tracinho": "-",
}


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn"
    )


def _chave(palavra: str) -> str:
    return _sem_acento(palavra).casefold()


# ── E-mail ───────────────────────────────────────────────────────────────────

_RE_PALAVRA = r"[A-Za-zÀ-ÿ0-9]+"
_RE_ARROBA = re.compile(r"[\s,.;]*\b(?:arroba|aroba)\b[\s,.;]*|\s+@\s*|\s*@\s+", re.I)


def emails_por_extenso(texto: str) -> str:
    """ "maria ponto silva arroba gmail ponto com" → "maria.silva@gmail.com"."""
    if not texto or not re.search(r"(?i)\barr?oba\b|\s@|@\s", texto):
        return texto
    # Marca provisória: só vira "@" se um e-mail for montado em volta ("não tenho arroba" fica)
    marca = "\x00"
    original = texto
    texto = _RE_ARROBA.sub(marca, texto)
    saida = texto
    for m in reversed(list(re.finditer(marca, texto))):
        pos = m.start()
        antes, depois = texto[:pos], texto[pos + 1:]

        # Parte local: a palavra antes do @ e as que vêm ligadas por "ponto", "underline", "traço"
        local = ""
        ini = len(antes)
        mm = re.search(rf"({_RE_PALAVRA})$", antes)
        if not mm:
            continue
        local, ini = mm.group(1), mm.start()
        while True:
            mm = re.search(
                rf"({_RE_PALAVRA})[\s,]*\b(ponto|underline|underscore|anderlaine|tra[cç]o|h[ií]fen|tracinho)\b[\s,]*$"
                rf"|({_RE_PALAVRA})([._-])$",
                antes[:ini],
                re.I,
            )
            if not mm:
                break
            if mm.group(1):
                local = f"{mm.group(1)}{_SEPARADOR_FALADO[_chave(mm.group(2))]}{local}"
            else:
                local = f"{mm.group(3)}{mm.group(4)}{local}"
            ini = mm.start()
        # "maria 2000 arroba": o número faz parte do nome do e-mail
        if local.isdigit():
            mm = re.search(rf"({_RE_PALAVRA})\s+$", antes[:ini])
            if mm and not mm.group(1).isdigit() and _chave(mm.group(1)) not in {"e", "é", "email", "mail"}:
                local, ini = mm.group(1) + local, mm.start()

        # Domínio: palavra + ("ponto" palavra)* enquanto for terminação de domínio
        mm = re.match(rf"({_RE_PALAVRA}(?:-{_RE_PALAVRA})*)", depois)
        if not mm:
            continue
        dominio, fim = mm.group(1), mm.end()
        while True:
            mm = re.match(rf"(?:[\s,]*\bponto\b[\s,]*|\.)({_RE_PALAVRA})", depois[fim:], re.I)
            if not mm or _chave(mm.group(1)) not in _FIM_DE_DOMINIO:
                break
            dominio += "." + mm.group(1)
            fim += mm.end()
        if "." not in dominio and _chave(dominio) in _PROVEDORES_COM:
            dominio += ".com"
        if "." not in dominio:
            continue  # não parece e-mail: deixa a frase como veio

        email = _sem_acento(f"{local}@{dominio}").lower()
        saida = saida[:ini] + email + saida[pos + 1 + fim:]
    if marca not in saida:
        return saida
    # Sobrou "arroba" que não era e-mail: sem nenhum e-mail montado, a frase volta como veio
    return saida.replace(marca, " arroba ") if "@" in saida else original


# ── Números ──────────────────────────────────────────────────────────────────

_RE_TOKEN = re.compile(r"[A-Za-zÀ-ÿ]+|\d+|\s+|[^\w\s]")


def _eh_numero(palavra: str) -> bool:
    k = _chave(palavra)
    return k in _UNIDADES or k in _DEZ_A_DEZENOVE or k in _DEZENAS or k in _CENTENAS or k == "mil"


class _Leitor:
    """Lê frases numéricas ("oitocentos e noventa e um", "dois mil e cinco") numa lista de tokens."""

    def __init__(self, tokens: list[str]):
        self.t = tokens
        self.k = [_chave(x) for x in tokens]

    def _prox_palavra(self, i: int) -> int:
        """Índice do próximo token que não é espaço, ou len."""
        while i < len(self.t) and self.t[i].isspace():
            i += 1
        return i

    def _apos_e(self, i: int, aceitos: tuple[dict, ...]) -> int:
        """Se vier "e <número de ordem menor>" (ou o número direto), devolve o índice dele; senão -1."""
        j = self._prox_palavra(i)
        if j < len(self.t) and self.k[j] == "e":
            j = self._prox_palavra(j + 1)
        if j < len(self.t) and any(self.k[j] in d for d in aceitos) and self.k[j] not in {"zero", "meia"}:
            return j
        return -1

    def _ate_999(self, i: int) -> tuple[int, int] | None:
        """(valor, índice depois) de um número até 999 começando em i."""
        if i >= len(self.t):
            return None
        k = self.k[i]
        if k == "zero":
            return 0, i + 1
        valor, fim = None, i
        if k in _CENTENAS:
            valor, fim = _CENTENAS[k], i + 1
            j = self._apos_e(fim, (_DEZENAS, _DEZ_A_DEZENOVE, _UNIDADES)) if k != "cem" else -1
            if j < 0:
                return valor, fim
            i, k = j, self.k[j]
        if k in _DEZENAS:
            valor, fim = (valor or 0) + _DEZENAS[k], i + 1
            j = self._apos_e(fim, (_UNIDADES,))
            if j >= 0:
                valor, fim = valor + _UNIDADES[self.k[j]], j + 1
            return valor, fim
        if k in _DEZ_A_DEZENOVE:
            return (valor or 0) + _DEZ_A_DEZENOVE[k], i + 1
        if k in _UNIDADES:
            return (valor or 0) + _UNIDADES[k], i + 1
        return (valor, fim) if valor is not None else None

    def frase(self, i: int) -> tuple[str, int] | None:
        """(dígitos, índice depois) da frase numérica que começa em i."""
        if i >= len(self.t):
            return None
        if self.k[i] == "mil":
            lido = (1, i)  # "mil novecentos e noventa"
        else:
            lido = self._ate_999(i)
            if lido is None:
                return None
        valor, fim = lido
        zero_solto = self.k[i] == "zero"
        j = self._prox_palavra(fim)
        if not zero_solto and j < len(self.t) and self.k[j] == "mil":
            valor, fim = max(valor, 1) * 1000, j + 1
            resto_i = self._prox_palavra(fim)
            if resto_i < len(self.t) and self.k[resto_i] == "e":
                resto_i = self._prox_palavra(resto_i + 1)
            if resto_i < len(self.t) and self.k[resto_i] not in {"zero", "mil", "meia"}:
                resto = self._ate_999(resto_i)
                if resto is not None:
                    valor, fim = valor + resto[0], resto[1]
        return str(valor), fim


def numeros_por_extenso(texto: str, *, aguardando: str = "", tudo: bool = False) -> str:
    """Converte para dígitos os números ditados que são dado de cadastro (ver topo do módulo).

    `tudo=True` converte todo número, um a um — usado só para comparar textos (app/verificacao.py).
    """
    if not texto or not any(_eh_numero(p) for p in re.findall(r"[A-Za-zÀ-ÿ]+", texto)):
        return texto
    tokens = _RE_TOKEN.findall(texto)
    leitor = _Leitor(tokens)
    k = leitor.k
    saida: list[str] = []
    i = 0
    while i < len(tokens):
        if not (tokens[i][0].isalpha() and _eh_numero(tokens[i])):
            saida.append(tokens[i])
            i += 1
            continue

        if tudo:
            # Para comparar textos: cada número vira dígito, um a um ("doze meses" → "12 meses")
            lido = leitor.frase(i) if k[i] != "meia" else None
            if lido is None:
                saida.append(tokens[i])
                i += 1
            else:
                saida.append(lido[0])
                i = lido[1]
            continue

        # Sequência de frases numéricas separadas só por espaço, vírgula, ponto ou traço
        frases: list[str] = []
        j = i
        fim_seq = i
        while j < len(tokens):
            if k[j] == "meia":
                # "meia" só é 6 no meio de uma sequência ("meia oito zero dois")
                prox = leitor._prox_palavra(j + 1)
                vizinho = bool(frases) or (prox < len(tokens) and _eh_numero(tokens[prox]) and k[prox] != "meia")
                if not vizinho:
                    break
            lido = leitor.frase(j) if tokens[j][0].isalpha() and _eh_numero(tokens[j]) else None
            if lido is None:
                break
            frases.append(lido[0])
            fim_seq = lido[1]
            j = fim_seq
            while j < len(tokens) and (tokens[j].isspace() or tokens[j] in {",", ".", "-", "–"}):
                j += 1
        if not frases:
            saida.append(tokens[i])
            i += 1
            continue

        palavras_antes = [x for x in k[max(0, i - 8):i] if x.strip() and x[0].isalnum()][-3:]
        palavras_depois = [x for x in k[fim_seq:fim_seq + 6] if x.strip() and x[0].isalnum()][:2]
        digitos = "".join(frases)
        anunciado = any(p in _ANUNCIA_NUMERO for p in palavras_antes)
        resto_e_pontuacao = all(not x.strip() or not x[0].isalnum() for x in k[fim_seq:])
        perto_de_mes = (
            (len(palavras_depois) == 2 and palavras_depois[0] == "de" and palavras_depois[1] in _MESES)
            or (len(palavras_antes) >= 2 and palavras_antes[-1] == "de" and palavras_antes[-2] in _MESES)
        )
        # "o de cento e trinta e nove reais", "o plano de noventa e nove"
        valor_de_plano = (palavras_depois[:1] or [""])[0] in {"reais", "real"} or (
            "plano" in palavras_antes and len(digitos) >= 2
        )
        converter = (
            len(frases) >= 3
            or anunciado
            or perto_de_mes
            or valor_de_plano
            or (aguardando in _ESPERA_NUMERO_LONGO and len(digitos) >= 4)
            # "vinte e três do doze de..." — mas não o "um" de "um momento"
            or (
                aguardando == "data_nascimento"
                and (digitos != "1" or (palavras_depois[:1] or [""])[0] in {"de", "do"})
            )
            or (aguardando in _ESPERA_ENDERECO and resto_e_pontuacao and digitos not in {"1"})
        )
        if converter:
            saida.append(digitos)
            i = fim_seq
        else:
            saida.append(tokens[i])
            i += 1
    return "".join(saida)


def normalizar_fala(texto: str, *, aguardando: str = "", audio: bool = False) -> str:
    """Mensagem como o cliente a digitaria. Números só são convertidos em mensagem de áudio."""
    texto = emails_por_extenso(texto or "")
    if audio:
        texto = numeros_por_extenso(texto, aguardando=aguardando or "")
    return texto
