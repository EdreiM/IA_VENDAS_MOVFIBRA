"""Conferência do que o modelo escreveu contra os fatos que ele recebeu.

O prompt manda não inventar, mas instrução não é garantia. Aqui o texto gerado é lido
atrás de afirmações que custam caro se estiverem erradas — valor em reais, percentual,
prazo (dias, meses, anos, horas) e velocidade — e cada uma precisa existir nos fatos do
prompt (RAG, plano, horários, conversa, mensagem do cliente). O que não existir é
devolvido para quem chamou, que pede uma reescrita ou cai numa resposta segura.

Não confere afirmação sem número ("a instalação é grátis"): isso continua dependendo
do prompt e da base de conhecimento.
"""

from __future__ import annotations

import re
import unicodedata

from app.fala import numeros_por_extenso

# "R$ 150,00", "$400,00" (a base escreve assim) e "150 reais"
_RE_DINHEIRO = re.compile(
    r"r?\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"|(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(?:reais|real)\b"
)
_RE_PERCENTUAL = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|por cento)")
# "12h a 24h uteis" conta como horas; "14h" de um horário de agenda também (precisa estar nos fatos)
_RE_PRAZO = re.compile(
    r"(?<![\d/.,:])(\d{1,4})\s*(dias?|meses|mes|anos?|horas?|hrs?|h|minutos?|semanas?)\b(?!\d)"
)
_RE_QUANTIDADE = re.compile(
    r"(?<![\d/.,])(\d{1,3})\s*(dispositivos?|aparelhos?|gb de internet|gb)\b"
)
_RE_VELOCIDADE = re.compile(r"(?<![\d/.,])(\d{1,5})\s*(megas?|mb|mbps|gigas?|gb)\b")

Afirmacao = tuple[str, float]


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn"
    )
    # "doze meses", "trinta por cento" → dígitos, para comparar igual dos dois lados
    return numeros_por_extenso(sem_acento.casefold(), tudo=True)


def _valor(bruto: str) -> float:
    b = bruto.strip()
    if "," in b:
        b = b.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", b):
        b = b.replace(".", "")
    try:
        return round(float(b), 2)
    except ValueError:
        return -1.0


def afirmacoes(texto: str) -> set[Afirmacao]:
    """Valores, percentuais, prazos e velocidades citados no texto, em forma comparável."""
    t = _normalizar(texto)
    out: set[Afirmacao] = set()
    for m in _RE_DINHEIRO.finditer(t):
        out.add(("dinheiro", _valor(m.group(1) or m.group(2))))
    for m in _RE_PERCENTUAL.finditer(t):
        out.add(("percentual", _valor(m.group(1))))
    for m in _RE_PRAZO.finditer(t):
        n, unidade = float(m.group(1)), m.group(2)
        if unidade.startswith("ano"):
            out.add(("mes", n * 12))
        elif unidade.startswith("semana"):
            out.add(("dia", n * 7))
        elif unidade.startswith("mes"):
            out.add(("mes", n))
        elif unidade.startswith("dia"):
            out.add(("dia", n))
        elif unidade.startswith("h"):
            out.add(("hora", n))
        else:
            out.add(("minuto", n))
    for m in _RE_QUANTIDADE.finditer(t):
        if m.group(2).startswith(("dispositivo", "aparelho")):
            out.add(("dispositivo", float(m.group(1))))
    for m in _RE_VELOCIDADE.finditer(t):
        n, unidade = float(m.group(1)), m.group(2)
        out.add(("mega", n * 1000 if unidade.startswith("g") else n))
    return out


def _equivalentes(af: Afirmacao) -> set[Afirmacao]:
    """A mesma afirmação em outra unidade (30 dias = 1 mês, 24 horas = 1 dia...)."""
    tipo, n = af
    eq = {af}
    if tipo == "dia":
        if n % 30 == 0:
            eq.add(("mes", n / 30))
        eq.add(("hora", n * 24))
    elif tipo == "mes":
        eq.add(("dia", n * 30))
    elif tipo == "hora":
        if n % 24 == 0:
            eq.add(("dia", n / 24))
        eq.add(("minuto", n * 60))
    elif tipo == "minuto" and n % 60 == 0:
        eq.add(("hora", n / 60))
    return eq


# Modo de falar, não promessa: "só um minuto", "um momento"
_IGNORADAS: set[Afirmacao] = {("minuto", 1.0)}


def _rotulo(af: Afirmacao) -> str:
    tipo, n = af
    num = f"{n:.2f}".replace(".", ",") if tipo == "dinheiro" else f"{n:g}"
    return {
        "dinheiro": f"R$ {num}",
        "percentual": f"{num}%",
        "mes": f"{num} meses",
        "dia": f"{num} dias",
        "hora": f"{num} horas",
        "minuto": f"{num} minutos",
        "mega": f"{num} mega",
        "dispositivo": f"{num} dispositivos",
    }[tipo]


def afirmacoes_sem_base(resposta: str, fatos: str) -> list[str]:
    """O que a resposta afirma com número e não aparece nos fatos. Lista vazia = pode enviar."""
    ditas = afirmacoes(resposta) - _IGNORADAS
    if not ditas:
        return []
    base = afirmacoes(fatos)
    valores = sorted({n for tipo, n in base if tipo == "dinheiro"})
    # Diferença entre dois valores dos fatos ("você economiza R$ 20") é conta, não invenção
    diferencas = {round(a - b, 2) for a in valores for b in valores if a > b}
    # "8 aparelhos" que o próprio cliente disse aparece nos fatos (mensagem, notas, conversa)
    sem_base: list[str] = []
    for af in sorted(ditas):
        if _equivalentes(af) & base:
            continue
        if af[0] == "dinheiro" and af[1] in diferencas:
            continue
        sem_base.append(_rotulo(af))
    return sem_base
