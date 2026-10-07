"""Parser determinístico — normaliza JSON e protege confirmações genéricas."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models import CAMPOS_DADOS, Evento, Interpretacao, DadosExtraidos
from app.utils.cpf import celular_e_nao_cpf

EVENTOS_VALIDOS = {e.value for e in Evento}

CONFIRMACOES_GENERICAS = {
    "sim",
    "pode ser",
    "pode ser esse",
    "pode ser esse mesmo",
    "esse",
    "esse mesmo",
    "quero esse",
    "quero esse mesmo",
    "fico com esse",
    "fechado",
    "fechou",
    "vamos com esse",
    "vamos nesse",
    "pode fechar",
    "confirmo",
    "ok",
    "okay",
    "blz",
    "beleza",
    "ta certo",
    "esta certo",
    "tudo certo",
    "esta tudo certo",
    "ta tudo certo",
    "tudo correto",
    "esta correto",
    "esta tudo correto",
    "dados corretos",
    "os dados estao corretos",
    "isso mesmo",
    "confere",
    "confere sim",
    "pode confirmar",
    "pode cadastrar",
    "pode seguir",
    "ta",
    "tá",
    "ta sim",
    "tá sim",
    "aceito",
    "aceita",
    "concordo",
    "de acordo",
    "li e aceito",
    "aceito os termos",
}

RECUSAS_GENERICAS = {
    "nao",
    "esse nao",
    "esse nao quero",
    "nao quero esse",
    "nao gostei",
    "nao gostei desse",
    "prefiro outro",
    "quero outro",
}

PEDIDOS_ALTERNATIVA = {
    "tem outro",
    "tem outro plano",
    "tem outra opcao",
    "tem mais plano",
    "tem mais planos",
    "tem outros planos",
    "quais outros planos",
    "quais outros planos voces tem",
    "me mostra outro",
    "me mostra outros",
    "quero outro plano",
    "quero ver outros planos",
    "muda o plano",
    "trocar de plano",
    "trocar o plano",
    "quero trocar de plano",
    "quero mudar de plano",
    "so tem esse",
    "so tem esse plano",
    "so tem esse mesmo",
    "so existe esse",
    "so esse plano",
    "apenas esse",
    "apenas esse plano",
    "somente esse",
    "nao tem outro",
    "nao tem outros",
    "tem mais opcao",
    "tem mais opcoes",
}

PEDIDOS_LISTAR_PLANOS = {
    "quais planos",
    "quais planos tem",
    "quais planos voces tem",
    "que planos tem",
    "que planos voces tem",
    "quais sao os planos",
    "lista de planos",
    "me mostra os planos",
    "me manda os planos",
    "manda os planos",
    "manda os plano",
    "envia os planos",
    "envia os plano",
    "opcoes de plano",
    "planos disponiveis",
    "so tem esse",
    "so tem esse plano",
    "tem mais planos",
    "tem outros planos",
    "me mostra todos",
    "me mostre todos",
    "mostra todos",
    "mostre todos",
    "mostrar todos",
    "ver todos",
    "quero ver todos",
    "quero ver os planos",
    "quero ver plano",
    "quero os planos",
    "todos os planos",
    "todos planos",
    "lista completa",
    "ver todos os planos",
    "quero ver todos os planos",
    "quero ver todos planos",
}

# Pedido explícito de catálogo completo (não só sugestão)
PEDIDOS_LISTA_COMPLETA = {
    "me mostra todos",
    "me mostre todos",
    "mostra todos",
    "mostre todos",
    "mostrar todos",
    "ver todos",
    "quero ver todos",
    "quero ver os planos",
    "quero os planos",
    "me manda os planos",
    "manda os planos",
    "manda os plano",
    "envia os planos",
    "todos os planos",
    "todos planos",
    "lista completa",
    "ver todos os planos",
    "quero ver todos os planos",
    "quero ver todos planos",
    "quais sao os planos",
    "quais planos",
    "lista de planos",
    "me mostra os planos",
    "me mostre os planos",
    "mostra os planos",
    "mostre os planos",
    "mostrar os planos",
    "ver os planos",
    "lista os planos",
    "quais os outros",
    "quais as outras",
    "mostra as outras opcoes",
    "mostre as outras opcoes",
    "mostra os outros",
    "mostre os outros",
    "ver as outras opcoes",
    "ver outras opcoes",
    "quais sao as outras",
    "me mostra as outras",
    "me mostre as outras",
    "todas as opcoes",
    "mostra todas as opcoes",
}

_FRAGMENTS_LISTA_COMPLETA = (
    "quais os outros",
    "quais as outras",
    "mostra as outras opcoes",
    "mostre as outras opcoes",
    "mostra os outros",
    "mostre os outros",
    "ver as outras opcoes",
    "ver outras opcoes",
    "quais sao as outras",
    "me mostra as outras",
    "me mostre as outras",
    "todas as opcoes",
    "mostra todas",
    "lista todas",
)

PERGUNTAS_PRECO = {
    "quanto e",
    "quanto custa",
    "quanto fica",
    "quanto ficam",
    "quanto sao",
    "quais os valores",
    "qual o valor",
    "qual valor",
    "qual o preco",
    "qual preco",
    "e quanto",
    "e o valor",
    "valor desse",
    "valor desses",
    "valor desse plano",
    "preco desse",
    "preco desses",
    "e esses",
    "e dessas",
}

# "O que tem nesse plano?" — pergunta de benefícios, não escolha
PERGUNTAS_DETALHE_PLANO = {
    "o que tem",
    "o que inclui",
    "o que vem",
    "o que acompanha",
    "quais beneficios",
    "quais os beneficios",
    "me fala o que tem",
    "me mostra o que tem",
    "me explica o que tem",
    "detalhes do plano",
    "detalhe do plano",
    "o que tem nesse",
    "o que tem no",
    "o que tem nessa",
    "conta o que tem",
    "fala o que tem",
}

# Cliente descreve o que quer → vira referência de plano (resolver por tags)
INTENCAO_PLANO_KEYWORDS = (
    "roteador",
    "roteadores",
    "mesh",
    "repetidor",
    "mais barato",
    "mais em conta",
    "mais barata",
    "mais velocidade",
    "mais rapido",
    "mais completo",
    "mais forte",
    "plano forte",
    "mais potente",
    "telemedicina",
    "exitlag",
    "dois wifi",
    "plano simples",
    "mais simples",
)


# Palavras que identificam plano mesmo se o LLM errar (ordem: + antes do nome base)
PLANOS_MENCAO = [
    (r"\bsuper\s*\+", "SUPER+"),
    (r"\bmov\s+super\s*\+|\bmov\s+super\b", "SUPER+"),
    (r"\bmovup\b|\bmov\s*up\b|\bmov\s+up\b|\bup\s*\+", "UP+"),
    (r"\bmovone\b|\bmov\s*one\b|\bmov\s+one\b|\bone\s*\+|one\s+plus\b", "ONE+"),
    (r"\bmov\s+infinity\b|\binfinity\b", "INFINITY"),
    (r"\bmov\s+essencial\b|\bessencial\b", "ESSENCIAL"),
    (r"\bmov\s+flex\b|\bflex\b", "FLEX"),
    (r"\bcombo.*12\s*gb|12\s*gb", "COMBO TOTAL 12GB"),
    (r"\bcombo.*22\s*gb|22\s*gb", "COMBO TOTAL 22GB"),
    (r"\bcombo\b", "COMBO"),
    (r"\b(?:mov\s+)?super\b", "SUPER"),
]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _extrair_email(bruto: str) -> str:
    s = (bruto or "").strip()
    # Remove prefixos comuns em mensagens partidas ("é erei teste @gmail.com")
    # O "é/e" opcional precisa terminar a palavra, senão come a 1ª letra ("email edrei@...")
    s = re.sub(r"^(?:meu\s+)?(?:e-?mail|email)\s*(?:(?:é|eh|e)(?=\s)|:|-)?\s*", "", s, flags=re.I)
    s = re.sub(r"^(?:é|e|eh)\s+", "", s, flags=re.I)
    m = EMAIL_RE.search(s)
    if m:
        return m.group(0).lower()
    # Espaços só dentro do email ("nome @ gmail.com") — não cola o resto da frase
    if "@" in s:
        candidato = re.sub(r"\s+", "", s.split()[0]) if s.split() else ""
        m2 = EMAIL_RE.fullmatch(candidato) or (EMAIL_RE.search(candidato) if candidato else None)
        if m2:
            return m2.group(0).lower()
    return ""


# Cliente insiste que já informou o dado pendente
REPETICAO_DADO = {
    "ja disse",
    "já disse",
    "ja falei",
    "já falei",
    "ja informei",
    "já informei",
    "ja passei",
    "já passei",
    "eu ja disse",
    "eu já disse",
    "eu ja falei",
    "eu já falei",
}


def _somente_digitos(msg: str) -> str:
    return re.sub(r"\D", "", msg or "")


def _parece_cpf_cnpj(msg: str, bruto: str = "") -> bool:
    n = _somente_digitos(bruto or msg)
    # Celular com DDD também tem 11 dígitos — não é CPF se os dígitos não fecham
    return len(n) in {11, 14} and not celular_e_nao_cpf(n)


def _extrair_cpf(msg: str, bruto: str = "") -> str:
    n = _somente_digitos(bruto or msg)
    if len(n) in {11, 14} and not celular_e_nao_cpf(n):
        return n
    return ""


def extrair_referencia_plano_na_mensagem(msg: str, msg_bruto: str = "") -> str:
    """Extrai nome/referência de plano citado na mensagem (ex.: 'mov up' → UP+)."""
    bruto = texto(msg_bruto or msg)
    t = normalizar_texto(bruto)
    return _detectar_plano_na_mensagem(t)


_PLANOS_GENERICOS = frozenset(
    {"ESSENCIAL", "FLEX", "SUPER", "COMBO", "COMBO TOTAL 12GB", "COMBO TOTAL 22GB"}
)
_CONTEXTO_PLANO_RE = re.compile(
    r"\b(?:plano|mov|mega|fibra|internet|contratar|confirmar|trocar|escolher|combo|chip)\b"
)


_RE_POSICAO_LISTA = re.compile(
    r"\b(?:primeir[oa]|segund[oa]|terceir[oa]|quart[oa]|quint[oa]|sext[oa]|"
    r"penultim[oa]|ultim[oa]|opcao\s+\d|numero\s+\d)\b"
)


def _detectar_plano_na_mensagem(msg: str) -> str:
    """Retorna referência de plano se a mensagem citar um plano conhecido."""
    tem_contexto = bool(_CONTEXTO_PLANO_RE.search(msg))
    for padrao, rotulo in PLANOS_MENCAO:
        if re.search(padrao, msg):
            if rotulo in _PLANOS_GENERICOS and not tem_contexto:
                continue
            return rotulo
    # Preço só com contexto explícito de plano — evita confundir CPF (604...) com plano
    if re.search(r"\b(?:plano|de|por)\s+\d{2,3}(?:[.,]\d{2})?\b", msg):
        m = re.search(r"\b(\d{2,3}(?:[.,]\d{2})?)\b", msg)
        if m:
            try:
                if float(m.group(1).replace(",", ".")) >= 50:
                    return m.group(1)
            except ValueError:
                pass
    if re.search(r"\b\d{2,3}(?:[.,]\d{2})?\s*(?:reais|rs)\b", msg):
        m = re.search(r"\b(\d{2,3}(?:[.,]\d{2})?)\b", msg)
        if m:
            return m.group(1)
    return ""


def texto(valor: Any) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def normalizar_texto(valor: str) -> str:
    t = texto(valor).casefold()
    t = (
        t.replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )
    t = re.sub(r"[\]\[\)\(\}\{]+", " ", t)
    t = re.sub(r"[!?.,;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def eh_pedido_lista_completa_planos(msg: str) -> bool:
    """Cliente quer ver o catálogo inteiro, não só uma sugestão."""
    n = normalizar_texto(msg)
    if not n:
        return False
    if any(p in n for p in PEDIDOS_LISTA_COMPLETA):
        return True
    if any(p in n for p in _FRAGMENTS_LISTA_COMPLETA):
        return True
    return bool(re.search(r"\b(mostra|mostre|mostrar|ver|lista)\b.{0,24}\bplanos?\b", n))


_CHAVES_PEDIDO_PLANOS_DESCONTO = (
    "tem desconto",
    "com desconto",
    "que tem desconto",
    "planos com desconto",
    "plano com desconto",
    "quero desconto",
    "tem promocao",
    "com promocao",
    "promocao inicial",
    "desconto nos primeiros",
    "primeiros meses",
    "50 por cento",
    "50%",
)


def eh_esclarecimento_promo_plano(msg: str) -> bool:
    """
    Dúvida sobre a promo do plano em foco — ex.: 'Ah é só nos 3 primeiros meses'.
    Não é pedido de lista de planos com desconto.
    """
    n = normalizar_texto(msg)
    if not n:
        return False
    if re.search(
        r"\b(quero|queria|preciso|gostaria|mostra|mostre|lista|listar|quais|tem algum|que tem|me mostra)\b",
        n,
    ):
        return False
    if any(
        p in n
        for p in (
            "so nos",
            "e so nos",
            "somente nos",
            "ah e so",
            "ah, e so",
            "so por",
            "depois fica",
            "depois volta",
            "e depois",
            "apos os",
            "no quarto mes",
            "a partir do",
            "volta para",
            "volta pro",
        )
    ):
        return True
    if "primeiros meses" in n and len(n.split()) <= 12:
        return True
    if re.search(r"\b(desconto|promocao|promo)\b", n) and len(n.split()) <= 8:
        if not re.search(r"\b(quero|mostra|lista|quais|tem)\b", n):
            return True
    return False


_CHAVES_CANCELAMENTO = (
    "cancelar",
    "cancelamento",
    "multa",
    "fidelidade",
    "pagar se eu cancelar",
    "tem que pagar se",
    "tenho que pagar se",
    "pagar se cancelar",
    "e se eu cancelar",
    "se eu cancelar",
    "desistir do plano",
    "rescindir",
)


def eh_apenas_dado_cadastro(msg: str, msg_bruto: str = "") -> bool:
    """Mensagem só com dado cadastral (email, CPF, telefone, data, CEP…) — sem pergunta."""
    bruto = texto(msg_bruto or msg)
    t = normalizar_texto(bruto)
    if not t:
        return False
    if "?" in bruto:
        return False
    if any(p in t for p in _CHAVES_CANCELAMENTO):
        return False
    if any(
        p in t
        for p in (
            "quanto",
            "como ",
            "tem ",
            "posso ",
            "consigo ",
            "instalar",
            "instala",
        )
    ):
        return False
    if _extrair_email(bruto):
        resto = EMAIL_RE.sub("", bruto).strip()
        resto = re.sub(r"(?i)^(?:meu\s+)?(?:e-?mail|email)\s*(?:é|e|eh|:|-)?\s*", "", resto).strip()
        if not resto or len(normalizar_texto(resto).split()) <= 2:
            return True
    if _parece_cpf_cnpj(msg, bruto):
        return True
    digits = _somente_digitos(bruto)
    if len(digits) in {10, 11} and len(t.split()) <= 3:
        return True
    compacto = re.sub(r"\s+", "", t)
    if re.fullmatch(r"\d{8}", compacto):
        return True
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", t.strip()):
        return True
    if re.fullmatch(r"\d{1,6}", compacto) and len(t.split()) <= 2:
        return True
    return False


def eh_pergunta_cancelamento(
    msg: str,
    msg_bruto: str = "",
    *,
    topico: str | None = None,
) -> bool:
    """Dúvida sobre cancelamento, multa ou fidelidade — não é dado de cadastro."""
    bruto = (msg_bruto or msg or "").strip()
    t = normalizar_texto(bruto)
    if not t:
        return False
    if eh_apenas_dado_cadastro(msg, bruto):
        return False
    if any(p in t for p in _CHAVES_CANCELAMENTO):
        return True
    # Follow-up curto sobre o assunto anterior (ex.: "nesse caso quanto ficaria?")
    top = (topico or "").strip().casefold()
    if top == "cancelamento":
        from app.contexto_conversa import eh_followup_curto

        if eh_followup_curto(t) and any(
            x in t
            for x in (
                "quanto",
                "multa",
                "taxa",
                "cancelar",
                "fidelidade",
                "paga",
                "ficaria",
                "custa",
                "valor",
                "nesse caso",
                "opcoes",
                "opções",
                "devolver",
            )
        ):
            return True
    return False


def eh_pedido_planos_com_desconto(msg: str) -> bool:
    """Cliente quer planos com pontualidade ou promo (ex.: 50% nos 3 primeiros meses)."""
    if eh_esclarecimento_promo_plano(msg):
        return False
    n = normalizar_texto(msg)
    if not n:
        return False
    if any(p in n for p in _CHAVES_PEDIDO_PLANOS_DESCONTO):
        return True
    return bool(re.search(r"\b(desconto|promocao|promo)\b", n))


def eh_pedido_plano_promocional(msg: str) -> bool:
    """Cliente quer o plano promocional (ex.: 50% nos 3 primeiros meses), não confirmar o atual."""
    n = normalizar_texto(msg)
    if not n:
        return False
    if re.search(r"\b(quero|queria|preciso|gostaria)\b", n) and re.search(
        r"\b(promocao|promo)\b", n
    ):
        return True
    return any(
        p in n
        for p in (
            "um na promocao",
            "na promocao",
            "o da promocao",
            "o promocional",
            "plano promocional",
            "plano da promocao",
        )
    )


def cliente_confirmou_ver_planos_desconto(
    msg: str,
    ultima_eva: str,
    *,
    contexto_plano: str = "",
) -> bool:
    """'Sim' após Eva oferecer mostrar planos com desconto — não confirmação de plano único."""
    if not eh_confirmacao(msg):
        return False
    ctx = normalizar_texto(contexto_plano)
    if ctx == "confirmacao_unico" or ctx == "apresentacao_inicial":
        return False
    if ctx == "oferta_lista_desconto":
        return True
    if ctx == "escolha_catalogo":
        return False
    u = normalizar_texto(ultima_eva)
    if not u:
        return False
    # Confirmação de um plano já apresentado (benefícios citam pontualidade, mas não é lista).
    if any(
        p in u
        for p in (
            "pode confirmar esse",
            "quer confirmar esse",
            "confirmar esse pra gente",
            "ficou este",
            "esse plano te atende",
        )
    ):
        return False
    ofertas_lista = (
        "planos com desconto",
        "planos com esse beneficio",
        "mostrar os planos",
        "mostre os planos",
        "te mostro os planos",
        "te mostre os planos",
        "mostro os planos com",
        "ver os planos com",
        "ver planos com",
        "quer que eu te mostre",
        "quer ver os planos",
        "listar os planos",
    )
    if any(p in u for p in ofertas_lista):
        return True
    if any(p in u for p in ("desconto de pontualidade", "beneficio de pontualidade")):
        return any(
            q in u
            for q in (
                "quer ver",
                "te mostro",
                "te mostre",
                "mostro os",
                "mostrar os",
                "ver os planos",
                "outras opcoes",
                "outros planos",
                "planos com",
            )
        )
    return False


# Pergunta informativa sobre mudança de endereço pós-contratação (≠ trocar cobertura agora)
CHAVES_MUDANCA_ENDERECO = (
    "mudar de endereco",
    "mudanca de endereco",
    "trocar de endereco",
    "trocar endereco",
    "outro endereco",
    "novo endereco",
    "mudar endereco",
    "se eu quiser mudar",
    "se eu mudar",
    "e se eu mudar",
    "e se eu quiser mudar",
    "se eu tiver contratado",
    "depois de contratar",
    "apos contratar",
    "ja contratei",
    "depois que contratar",
    "quando ja tiver contratado",
)

CHAVES_DUVIDA_INFORMATIVA = (
    "cancelar",
    "cancelamento",
    "multa",
    "taxa",
    "quanto",
    "roteador",
    "disney",
    "fidelidade",
    "tem mais",
    "o que tem",
    "inclui",
    "direito",
    "comodato",
    "devolver",
    "mesh",
    "beneficio",
    "e se",
    "se eu",
    "instalar",
    "instalacao",
    "instalação",
    "agendar",
    "agendamento",
    "horario",
    "horário",
    "tecnico",
    "técnico",
    "visita",
    "quando vem",
    "quando instala",
    "vir instalar",
    "pra instalar",
    "quanto tempo",
    "demora",
    "prazo",
    "cobertura",
    "funciona no",
    "tem fibra",
) + CHAVES_MUDANCA_ENDERECO

# Instalação / visita do técnico (vendas e cadastro)
CHAVES_INSTALACAO = (
    "instalar",
    "instalacao",
    "instalação",
    "agendamento",
    "agendar",
    "tecnico",
    "técnico",
    "visita",
    "quando vem",
    "quando vai ser",
    "quando sera",
    "quando instala",
    "vir instalar",
    "pra instalar",
    "conseguem instalar",
    "consegue instalar",
    "instala hj",
    "instalar hj",
    "instalar hoje",
    "instalar amanha",
    "instalar amanhã",
    "pra hoje",
    "ainda hoje",
    "hoje mesmo",
)

CHAVES_CUSTO_INSTALACAO = (
    "gratis",
    "grátis",
    "graca",
    "de graca",
    "de graça",
    "taxa de instala",
    "taxa instalacao",
    "taxa instalação",
    "custo da instala",
    "custo instalacao",
    "custo instalação",
    "paga instala",
    "pagar instala",
    "cobra instala",
    "cobram instala",
    "quanto custa a instala",
    "quanto e a instala",
    "quanto é a instala",
    "tem taxa de instala",
    "tem taxa para instala",
    "tem taxa instalacao",
    "instalacao gratuita",
    "instalação gratuita",
    "instala gratis",
    "instala grátis",
)

# Fases em que pergunta informativa não deve virar troca de cobertura
FASES_PROTEGIDAS_LOC = frozenset({"cadastro", "termos", "agendamento", "pos_venda", "vendas"})

# Perguntas sobre cobertura/viabilidade sem intenção de informar novo endereço agora
CHAVES_COBERTURA_INFORMATIVA = (
    "e se nao tiver cobertura",
    "se nao tiver cobertura",
    "tem cobertura",
    "tem fibra",
    "funciona no meu",
    "funciona na minha",
    "funciona aqui",
    "meu predio",
    "meu prédio",
    "meu condominio",
    "meu condomínio",
    "bloco",
    "apartamento tem",
)


def eh_ack_curto(msg: str) -> bool:
    """Confirmação curta — sim, si, certo, ok (sem pergunta embutida)."""
    bruto = texto(msg)
    t = normalizar_texto(bruto)
    if not t or "?" in bruto:
        return False
    if t in {"sim", "si", "s", "ta", "ok", "okay", "blz", "beleza", "certo", "isso", "isso mesmo", "pode ser"}:
        return True
    if len(t.split()) <= 3 and eh_confirmacao(msg):
        return True
    return False


def eh_confirmacao(msg: str) -> bool:
    bruto = texto(msg)
    t = normalizar_texto(bruto)
    if not t:
        return False
    if t.startswith("nao ") or " nao " in f" {t} ":
        return False
    if any(
        p in t
        for p in (
            "pode encerrar",
            "pode finalizar",
            "pode fechar",
            "encerrar",
            "finalizar",
        )
    ):
        return False
    if t in CONFIRMACOES_GENERICAS or t in {"si", "s", "yes", "yep", "yeah"}:
        return True
    if any(
        p in t
        for p in (
            "tudo certo",
            "ta certo",
            "esta certo",
            "tudo correto",
            "esta correto",
            "dados corretos",
            "pode confirmar",
            "confere",
            "aceito",
            "concordo",
            "de acordo",
            "pode ser",
            "isso mesmo",
        )
    ):
        return True
    return _confirmacao_por_prefixo(bruto, t)


# Depois de "tá" / "ok" / "sim": palavras que mostram objeção, erro ou adiamento
_MARCAS_NAO_CONFIRMA = frozenset({
    "caro", "cara", "carinho", "salgado", "errado", "errada", "erro", "incorreto", "incorreta",
    "demora", "demorando", "demorado", "dificil", "complicado", "ruim",
    "pensar", "pensando", "depois", "espera", "esperar", "calma", "pera", "duvida", "duvidas",
    "nem", "nunca", "outro", "outra", "trocar", "troca", "mudar", "muda", "corrigir", "corrige",
    "falta", "faltou", "faltando", "vendo", "ver", "olhando", "analisando",
})


# Depois do "mas", "depois" costuma estar numa dúvida ("posso remarcar depois?")
_MARCAS_OBJECAO_APOS_MAS = (_MARCAS_NAO_CONFIRMA - {"depois"}) | {"vejo", "caros"}


def _confirmacao_por_prefixo(bruto: str, t: str) -> bool:
    """'tá bom' / 'ok pode ser' confirmam; 'tá caro' / 'ok mas...' / 'tá errado o CPF' não."""
    # "pode instalar amanhã?" / "isso inclui wifi?" — pergunta, não confirmação
    if "?" in bruto:
        return False
    palavras = t.split()
    if not palavras or palavras[0] not in {
        "sim", "si", "s", "ta", "confirmo", "ok", "blz", "beleza", "fechado", "fechou"
    }:
        return False
    # "sim, mas posso remarcar depois?" continua confirmando (o que vem após o "mas" é
    # dúvida); "sim mas tá caro" não — a ressalva é uma objeção.
    antes: list[str] = []
    depois: list[str] = []
    alvo = antes
    for p in palavras[1:]:
        if p in {"mas", "porem"} and alvo is antes:
            alvo = depois
            continue
        alvo.append(p)
    if any(p in _MARCAS_NAO_CONFIRMA for p in antes):
        return False
    return not any(p in _MARCAS_OBJECAO_APOS_MAS for p in depois)


def _confirmacao_exata(t: str) -> bool:
    """Confirmação que não depende de interpretação: a frase inteira é o 'sim'."""
    return t in CONFIRMACOES_GENERICAS or t in {
        "si", "s", "ss", "yes", "sim sim", "uhum", "aham", "isso", "certo", "claro", "positivo",
    }


def eh_aceite_termos_explicito(msg: str) -> bool:
    """Aceite do termo de fidelidade — 'sim' sozinho NÃO conta (pode ser resposta a dúvida)."""
    bruto = texto(msg)
    t = normalizar_texto(bruto)
    if not t or t.startswith("nao ") or " nao " in f" {t} ":
        return False
    if any(
        p in t
        for p in (
            "aceito os termos",
            "aceito o termo",
            "aceito a fidelidade",
            "aceito o contrato",
            "concordo com os termos",
            "concordo com o termo",
            "de acordo com os termos",
            "sim aceito",
            "aceito sim",
            "estou de acordo",
            "quero seguir",
            "vamos seguir",
            "pode seguir",
        )
    ):
        return True
    if t in {"aceito", "concordo", "confirmo", "de acordo", "aceita"}:
        return True
    if t in {"tudo certo", "ta certo", "esta certo", "tudo correto", "esta correto"}:
        return True
    if t in {"ok", "okay", "blz", "beleza"}:
        return True
    return False


def eh_recusa(msg: str) -> bool:
    t = normalizar_texto(msg)
    if not t:
        return False
    if t in RECUSAS_GENERICAS:
        return True
    palavras = t.split()
    if not palavras or palavras[0] not in {"nao", "não", "negativo"}:
        return False
    # "não entendi" / "não sei" / "não recebi" — pedido de ajuda, não recusa
    return not any(p in _MARCAS_NAO_E_RECUSA for p in palavras[1:3])


_MARCAS_NAO_E_RECUSA = frozenset({
    "entendi", "entendo", "compreendi", "sei", "lembro", "consegui", "consigo",
    "recebi", "chegou", "achei", "encontrei", "vi", "ouvi", "abriu", "carregou",
})


def eh_pergunta_cobertura_informativa(msg: str) -> bool:
    t = normalizar_texto(msg)
    if not t:
        return False
    if any(c in t for c in CHAVES_COBERTURA_INFORMATIVA):
        return True
    if "cobertura" in t and any(p in t for p in ("e se", "se eu", "tem", "funciona", "como")):
        return True
    return False


def _parte_principal_dado(msg_bruto: str) -> str:
    """Separa dado do campo pendente de pergunta na mesma linha ('93999 mas e se...')."""
    bruto = texto(msg_bruto)
    if not bruto:
        return ""
    partes = re.split(
        r"(?i)\s+(?:mas|porem|porém|e se|so que|só que)\s+",
        bruto,
        maxsplit=1,
    )
    return partes[0].strip()


def _strip_trailing_question_mark(bruto: str) -> str:
    return re.sub(r"\?\s*$", "", (bruto or "").strip())


def _extrair_telefone(bruto: str) -> str:
    principal = _parte_principal_dado(bruto)
    digitos = re.sub(r"\D", "", principal)
    m = re.search(r"(?:55)?(\d{10,11})$", digitos)
    if m:
        return m.group(1)
    if len(digitos) in {10, 11, 12, 13}:
        return digitos[-11:] if len(digitos) >= 11 else digitos[-10:]
    return ""


def _extrair_cep(bruto: str) -> str:
    principal = _parte_principal_dado(bruto)
    m = re.search(r"\b(\d{5})[\s-]?(\d{3})\b", principal)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    # "68.020-000"
    m = re.search(r"\b(\d{2})\.(\d{3})[\s-]?(\d{3})\b", principal)
    if m:
        return "".join(m.groups())
    digitos = re.sub(r"\D", "", principal)
    return digitos if len(digitos) == 8 else ""


_MESES = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
_RE_DATA_POR_EXTENSO = re.compile(
    r"\b(\d{1,2})\s*(?:de\s+)?(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\.?"
    r"\s*(?:de\s+)?(\d{4})\b"
)


def _extrair_data_nascimento(bruto: str) -> str:
    principal = _parte_principal_dado(bruto)
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", principal)
    if m:
        d, mes, ano = m.group(1), m.group(2), m.group(3)
        if len(ano) == 2:
            ano = f"19{ano}" if int(ano) > 30 else f"20{ano}"
        return f"{int(d):02d}/{int(mes):02d}/{ano}"
    # "16 de agosto de 2000" / "16 ago 2000"
    m = _RE_DATA_POR_EXTENSO.search(normalizar_texto(principal))
    if m and 1 <= int(m.group(1)) <= 31:
        return f"{int(m.group(1)):02d}/{_MESES[m.group(2)]:02d}/{m.group(3)}"
    return ""


def _extrair_numero_endereco(bruto: str) -> str:
    principal = _parte_principal_dado(bruto).strip()
    if re.fullmatch(r"\d+[a-zA-Z]?", principal):
        return principal
    m = re.search(r"\b(?:n(?:ú|u)?m(?:ero)?\.?\s*)?(\d+[a-zA-Z]?)\b", principal, re.I)
    return m.group(1) if m else ""


def _extrair_cpf_embutido(bruto: str) -> str:
    """CPF no meio da frase ('Edrei Silva 604.210.790-96'), não só mensagem só de dígitos."""
    m = re.search(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)", bruto or "")
    if not m:
        return ""
    cpf = "".join(m.groups())
    return "" if celular_e_nao_cpf(cpf) else cpf


# Palavras de quem está confirmando o plano, não dizendo o próprio nome
_PALAVRAS_CONFIRMACAO_NAO_NOME = frozenset({
    "o", "a", "os", "as", "um", "uma", "esse", "essa", "este", "esta", "isso", "isto",
    "aquele", "aquela", "mesmo", "mesma", "ai", "la", "aqui", "plano", "planos",
    "sim", "nao", "ok", "certo", "beleza", "blz", "claro", "certeza", "com", "pode", "ser",
    "quero", "queria", "vou", "vamos", "vamo", "bora", "nessa", "nesse", "entao", "agora", "ja",
    "fechou", "fechado", "fechar", "fecha", "seguir", "segue", "continuar", "prosseguir",
    "contratar", "instalar", "confirmo", "confirmado", "manda", "ver", "bala",
    "bom", "boa", "otimo", "otima", "perfeito", "show", "top", "legal",
    "obrigado", "obrigada", "valeu", "por", "favor", "pra", "para", "mim", "me",
    "primeiro", "segundo", "terceiro", "ultimo", "dia", "tarde", "noite",
    "como", "assim", "que", "qual", "quais", "quanto", "quanta", "quando", "onde", "porque",
    "voce", "voces", "vc", "vcs", "sao", "tem", "repetir", "explicar", "entendi",
})


def _parece_nome_de_pessoa(candidato: str) -> bool:
    partes = normalizar_texto(candidato).split()
    if len(partes) < 2:
        return False
    return not any(p in _PALAVRAS_CONFIRMACAO_NAO_NOME for p in partes)


_RE_LOGRADOURO = re.compile(
    r"\b(?:rua|r|av|avenida|travessa|tv|trav|alameda|estrada|rodovia|rod|br|pa|"
    r"passagem|psg|vila|beco|ramal|quadra|qd|lote|conjunto|residencial)\b"
)


def _texto_livre_parece_dado(msg_bruto: str, aguardando: str, eventos_llm: set[str]) -> bool:
    """Mesmo com o LLM lendo como conversa, o texto tem cara do dado pedido."""
    t = re.sub(r"[^\w\s]", " ", normalizar_texto(msg_bruto))
    # CPF, telefone, CEP ou e-mail na mesma mensagem ("Edrei Silva 604.210.790-96")
    if "@" in msg_bruto or len(re.sub(r"\D", "", msg_bruto)) >= 8:
        return True
    pergunta = "?" in msg_bruto
    if aguardando == "rua":
        # "rua das flores" começa pelo logradouro; "não sei o nome da rua" não.
        # Número só conta fora de pergunta ("tem suporte 24h?" não é endereço).
        return bool(_RE_LOGRADOURO.match(t.strip()) or (re.search(r"\d", t) and not pergunta))
    if aguardando == "numero":
        # "891" / "casa 12" / "nº 45" — resposta curta com número, sem ser pergunta
        return bool(re.search(r"\d", t)) and len(t.split()) <= 3 and not pergunta
    if aguardando == "nome":
        # Falha conhecida do LLM: "Maria Souza?" classificado como PERGUNTA. Só vale com
        # cara de nome próprio (iniciais maiúsculas) — "aceita pix?" não é nome.
        palavras = re.sub(r"[^\w\s]", " ", texto(msg_bruto)).split()
        return (
            Evento.PERGUNTA.value in eventos_llm
            and texto(msg_bruto).rstrip().endswith("?")
            and 2 <= len(palavras) <= 5
            and all(p[:1].isupper() or p.casefold() in {"de", "da", "do", "dos", "das", "e"} for p in palavras)
            and _parece_nome_de_pessoa(t)
        )
    return False


def _extrair_nome_apos_confirmacao(bruto: str) -> str:
    """Nome após confirmação do plano ('Pode ser, Edrei Silva' / 'Sim, meu nome é João')."""
    principal = _parte_principal_dado(bruto)
    segs = _segmentos_mensagem(principal)
    if len(segs) >= 2 and eh_confirmacao(segs[0]):
        nome = _extrair_nome_livre(",".join(segs[1:]))
        if nome and _parece_nome_de_pessoa(nome):
            return nome
    rest = re.sub(
        r"(?i)^(?:sim|si|ok|certo|beleza|blz|isso|pode ser|quero|confirmo|fechado)[,.:\s]+",
        "",
        principal,
    ).strip()
    if rest and rest != principal:
        sem_rotulo = re.sub(
            r"(?i)^(?:meu nome e|meu nome é|sou o|sou a|nome)\s+", "", rest
        ).strip()
        nome = _extrair_nome_livre(sem_rotulo)
        # "pode ser esse mesmo" / "ok vamos nessa" — confirmação, não nome
        if nome and (sem_rotulo != rest or _parece_nome_de_pessoa(nome)):
            return nome
    return ""


def _extrair_nome_livre(bruto: str) -> str:
    t = _strip_trailing_question_mark(_parte_principal_dado(bruto))
    t = re.sub(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)", " ", t)
    t = re.sub(r"(?i)\b(?:cpf|cnpj|nome)\b[:\s]*", " ", t)
    t = re.sub(r"[,;]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    if not t or "@" in t:
        return ""
    partes = [p for p in t.split() if re.search(r"[A-Za-zÀ-ÿ]", p) and not re.search(r"\d", p)]
    from app.validation import nome_parece_frase_invalida

    if len(partes) >= 2:
        candidato = " ".join(partes)[:120]
        if nome_parece_frase_invalida(candidato, bruto):
            return ""
        return candidato
    if len(partes) == 1:
        unico = partes[0]
        bloqueio = {
            "sim", "nao", "ok", "quero", "certo", "blz", "beleza", "obrigado",
            "obrigada", "valeu", "entendi", "pode", "isso", "esse", "essa",
            "logo", "mano", "po", "aff", "puts",
        }
        if len(unico) >= 2 and normalizar_texto(unico) not in bloqueio:
            candidato = unico[:120]
            if nome_parece_frase_invalida(candidato, bruto):
                return ""
            return candidato
    return ""


def _split_rua_numero(bruto: str, *, aguardando: str = "") -> tuple[str, str]:
    principal = _parte_principal_dado(bruto).strip()
    if re.fullmatch(r"\d+[A-Za-z]?", principal):
        return "", principal
    m = re.match(
        r"^(?P<rua>.+?)(?:\s*,\s*|\s+)(?:n(?:ú|u)?m(?:ero)?\.?\s*)?(?P<num>\d+[A-Za-z]?)$",
        principal,
        re.I,
    )
    if m and len(m.group("rua").strip()) >= 3:
        return m.group("rua").strip(" ,"), m.group("num")
    if (
        aguardando == "rua"
        and len(principal) >= 3
        and not _parece_cpf_cnpj("", principal)
        and not eh_mensagem_sobre_planos(normalizar_texto(principal), principal)
    ):
        return principal[:160], ""
    return "", ""


def _extrair_cep_sem_data(bruto: str) -> str:
    principal = _parte_principal_dado(bruto)
    sem_data = re.sub(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b", " ", principal)
    return _extrair_cep(sem_data)


def _segmentos_mensagem(bruto: str) -> list[str]:
    bruto = texto(bruto)
    partes = [p.strip() for p in re.split(r"[,;]", bruto) if p.strip()]
    return partes if len(partes) > 1 else [bruto]


def _extrair_cep_rotulo(bruto: str) -> str:
    m = re.search(r"(?i)\bcep\s*[:\-]?\s*(\d{5}[\s-]?\d{3}|\d{8})", bruto)
    if not m:
        return ""
    return re.sub(r"\D", "", m.group(1))


def _extrair_rua_rotulo(bruto: str) -> str:
    m = re.search(
        r"(?i)\bru[aá]\s*(?:é|e|:|-)?\s*(.+?)(?:\s*,\s*(?:\d|n(?:ú|u)?m)|\s*$)",
        bruto,
    )
    if not m:
        m = re.search(r"(?i)\bru[aá]\s*[:\-]\s*(.+?)\s*$", bruto)
    if not m:
        return ""
    rua = m.group(1).strip(" ,")
    return rua[:160] if len(rua) >= 3 else ""


def _extrair_correcoes_rotuladas(msg_bruto: str) -> dict[str, str]:
    """Correções no resumo ('Rua: X', 'A rua é X', 'Pode colocar o bairro: Y')."""
    bruto = texto(msg_bruto)
    if not bruto:
        return {}
    padroes: tuple[tuple[str, str], ...] = (
        ("rua", r"(?i)\bru[aá]\s*[:\-]\s*(.+?)\s*$"),
        ("rua", r"(?i)\b(?:a|minha|o)\s+ru[aá]\s*(?:é|e|eh)\s+(.+?)\s*$"),
        ("rua", r"(?i)\b(?:na verdade|corrigindo)[,:\s]+(?:a\s+)?ru[aá]\s*(?:é|e|eh)?\s*(.+?)\s*$"),
        ("bairro", r"(?i)(?:pode\s+colocar\s+(?:o\s+)?bairro|bairro)\s*[:\-]\s*(.+?)\s*$"),
        ("bairro", r"(?i)\b(?:o|meu)\s+bairro\s*(?:é|e|eh)\s+(.+?)\s*$"),
        ("email", r"(?i)e-?mail\s*[:\-]\s*(\S+@\S+\.\S+)"),
        ("email", r"(?i)\b(?:o|meu)\s+e?-?mail\s*(?:é|e|eh)\s+(\S+@\S+\.\S+)"),
        ("telefone", r"(?i)telefone\s*[:\-]\s*([\d\s().+-]{8,})"),
        ("telefone", r"(?i)\b(?:o|meu)\s+telefone\s*(?:é|e|eh)\s+([\d\s().+-]{8,})"),
        ("cep", r"(?i)cep\s*[:\-]\s*(\d{5}[\s-]?\d{3}|\d{8})"),
        ("cep", r"(?i)\b(?:o|meu)\s+cep\s*(?:é|e|eh)\s+(\d{5}[\s-]?\d{3}|\d{8})"),
        ("nome", r"(?i)nome\s*[:\-]\s*(.+?)\s*$"),
        ("nome", r"(?i)\b(?:o|meu)\s+nome\s*(?:é|e|eh)\s+(.+?)\s*$"),
        ("cpf", r"(?i)cpf\s*[:\-]\s*([\d.\-/]{11,18})"),
        ("cpf", r"(?i)\b(?:o|meu)\s+cpf\s*(?:é|e|eh)\s+([\d.\-/]{11,18})"),
        ("numero", r"(?i)\b(?:o|meu)\s+n[uú]mero\s*(?:é|e|eh)\s+(\d+[A-Za-z]?)\s*$"),
        ("data_nascimento", r"(?i)\b(?:minha|a)\s+data\s*(?:de nascimento)?\s*(?:é|e|eh)\s+(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})"),
    )
    out: dict[str, str] = {}
    for campo, pat in padroes:
        m = re.search(pat, bruto)
        if not m:
            continue
        val = m.group(1).strip(" ,.;")
        if campo == "cep":
            val = re.sub(r"\D", "", val)
        elif campo == "cpf":
            val = re.sub(r"\D", "", val)
        elif campo == "telefone":
            val = re.sub(r"\D", "", val)
        if val:
            out[campo] = val
    return out


_CAMPOS_RESUMO_ERRO: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rua", (r"(?i)\b(?:a\s+)?ru[aá]\s*(?:ta|esta|está)\s*(?:errad|incorret)", r"(?i)\bru[aá]\s+(?:errad|incorret|ta errad)")),
    ("nome", (r"(?i)\b(?:o|meu)\s+nome\s*(?:ta|esta|está)\s*(?:errad|incorret)", r"(?i)\bnome\s+(?:errad|incorret)")),
    ("email", (r"(?i)\b(?:o|meu)\s+e?-?mail\s*(?:ta|esta|está)\s*(?:errad|incorret)", r"(?i)\bemail\s+(?:errad|incorret)")),
    ("telefone", (r"(?i)\b(?:o|meu)\s+telefone\s*(?:ta|esta|está)\s*(?:errad|incorret)", r"(?i)\btelefone\s+(?:errad|incorret)")),
    ("cep", (r"(?i)\b(?:o|meu)\s+cep\s*(?:ta|esta|está)\s*(?:errad|incorret)", r"(?i)\bcep\s+(?:errad|incorret)")),
    ("numero", (r"(?i)\b(?:o|meu)\s+n[uú]mero\s*(?:ta|esta|está)\s*(?:errad|incorret)", r"(?i)\bn[uú]mero\s+(?:errad|incorret)")),
    ("bairro", (r"(?i)\b(?:o|meu)\s+bairro\s*(?:ta|esta|está)\s*(?:errad|incorret)", r"(?i)\bbairro\s+(?:errad|incorret)")),
)


def detectar_campo_incorreto_resumo(msg: str) -> str | None:
    """Cliente diz que um dado do resumo está errado, sem informar o valor novo."""
    bruto = texto(msg)
    if not bruto or _extrair_correcoes_rotuladas(bruto):
        return None
    for campo, padroes in _CAMPOS_RESUMO_ERRO:
        if any(re.search(p, bruto) for p in padroes):
            return campo
    return None


def eh_mensagem_correcao_cadastro(msg: str, msg_bruto: str = "") -> bool:
    """Correção de dado cadastral — não é pergunta sobre instalação/plano."""
    bruto = texto(msg_bruto or msg)
    if not bruto:
        return False
    if _extrair_correcoes_rotuladas(bruto):
        return True
    if detectar_campo_incorreto_resumo(bruto):
        return True
    t = normalizar_texto(bruto)
    if any(
        p in t
        for p in (
            "corrigir o",
            "corrigir a",
            "corrigir meu",
            "corrigir minha",
            "errei o",
            "errei a",
            "errei meu",
            "na verdade o",
            "na verdade a",
            "na verdade meu",
        )
    ):
        return any(c in t for c in ("rua", "nome", "email", "telefone", "cep", "numero", "bairro", "cpf"))
    if any(p in t for p in REPETICAO_DADO):
        return True
    return False


def _extrair_telefone_em_segmentos(bruto: str) -> str:
    for seg in _segmentos_mensagem(bruto):
        if "@" in seg or re.search(r"(?i)\b(?:cep|rua)\b", seg):
            continue
        tel = _extrair_telefone(seg)
        if tel:
            return tel
    return _extrair_telefone(bruto)


def _campos_cadastro_a_partir_de(aguardando: str) -> tuple[str, ...]:
    from app.state_machine import ORDEM_CADASTRO

    if aguardando not in ORDEM_CADASTRO:
        return ()
    idx = ORDEM_CADASTRO.index(aguardando)
    return tuple(ORDEM_CADASTRO[idx:])


def _parece_data_nascimento_msg(bruto: str) -> bool:
    return bool(
        _extrair_data_nascimento(bruto)
        or re.search(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b", bruto or "")
    )


_CHAVES_MENSAGEM_PLANO = (
    "plano",
    "planos",
    "combo",
    " mov ",
    "mov ",
    "infinity",
    "essencial",
    "flex",
    "super",
    "mais barato",
    "mais barata",
    "mais caro",
    "mais forte",
    "plano simples",
    "mais simples",
    "simples",
    "basico",
    "outro plano",
    "outros planos",
    "quero um",
    "trocar de plano",
    "mudar de plano",
    "opcoes",
    "opcao",
    "mensalidade",
    "preco",
    "quanto custa",
    "instalar",
    "instalacao",
    "taxa de instala",
    "taxa instalacao",
)


def eh_mensagem_sobre_planos(msg: str, msg_bruto: str = "") -> bool:
    t = normalizar_texto(msg_bruto or msg)
    if not t:
        return False
    if eh_pedido_contratacao(msg, msg_bruto):
        return False
    if eh_pergunta_cancelamento(msg, msg_bruto):
        return False
    if eh_pergunta_mudanca_endereco(msg_bruto or msg):
        return False
    if any(k in t for k in _CHAVES_MENSAGEM_PLANO):
        return True
    return any(p in t for p in PEDIDOS_LISTAR_PLANOS) or any(
        p in t for p in PEDIDOS_ALTERNATIVA if len(p) >= 8
    )


def _mensagem_tem_sinal_endereco(bruto: str, *, aguardando: str = "") -> bool:
    if eh_mensagem_sobre_planos("", bruto):
        return False
    if _extrair_rua_rotulo(bruto):
        return True
    if re.search(r"(?i)\bru[aá]\b", bruto or ""):
        return True
    if aguardando == "rua":
        principal = _parte_principal_dado(bruto).strip()
        if len(principal) >= 3 and re.search(r"[A-Za-zÀ-ÿ]{3,}", principal):
            return True
    return False


def _mensagem_e_apenas_cpf(bruto: str) -> bool:
    cpf = _extrair_cpf_embutido(bruto) or _extrair_cpf("", bruto)
    if not cpf:
        return False
    resto = re.sub(
        r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)",
        " ",
        bruto or "",
    )
    resto = re.sub(r"(?i)\b(?:cpf|cnpj)\b[:\s]*", " ", resto).strip(" ,.;")
    return not resto or not re.search(r"[A-Za-zÀ-ÿ]{2,}", resto)


def _valor_aparece_na_mensagem(campo: str, valor: str, bruto: str) -> bool:
    v = normalizar_texto(valor)
    b = normalizar_texto(bruto)
    if not v or not b:
        return False
    if campo in {"cpf", "telefone", "cep"}:
        dig_v = re.sub(r"\D", "", valor)
        dig_b = re.sub(r"\D", "", bruto)
        return bool(dig_v and dig_v in dig_b)
    return v in b


def _texto_parece_apenas_dado_cadastro(msg_bruto: str, aguardando: str) -> bool:
    principal = _strip_trailing_question_mark(_parte_principal_dado(msg_bruto))
    if not principal or not aguardando:
        return False
    if len(normalizar_texto(principal).split()) > 14:
        return False
    checks = {
        "nome": lambda b: bool(_extrair_nome_livre(b)) and not _mensagem_e_apenas_cpf(b),
        "cpf": lambda b: bool(_extrair_cpf_embutido(b) or _extrair_cpf("", b)),
        "email": lambda b: bool(_extrair_email(b)),
        "telefone": lambda b: bool(_extrair_telefone_em_segmentos(b)),
        "data_nascimento": lambda b: bool(_extrair_data_nascimento(b)),
        "cep": lambda b: bool(_extrair_cep_rotulo(b) or _extrair_cep(b)),
        "rua": lambda b: bool(
            _extrair_rua_rotulo(b) or _mensagem_tem_sinal_endereco(b, aguardando="rua")
        ),
        "numero": lambda b: bool(_extrair_numero_endereco(b)),
    }
    fn = checks.get(aguardando)
    return bool(fn and fn(principal))


def _limpar_ecos_estado(
    dados: DadosExtraidos,
    estado: dict[str, Any],
    msg_bruto: str,
    aguardando: str = "",
) -> None:
    """Remove valores que o LLM copiou do estado sem o cliente repetir na mensagem."""
    from app.state_machine import ORDEM_CADASTRO

    for campo in ORDEM_CADASTRO:
        val = texto(getattr(dados, campo, ""))
        if not val:
            continue
        atual = texto(estado.get(campo, ""))
        if not atual or normalizar_texto(val) != normalizar_texto(atual):
            continue
        if _valor_aparece_na_mensagem(campo, val, msg_bruto):
            continue
        setattr(dados, campo, "")


def _sanitizar_ecos_cadastro(
    dados: DadosExtraidos,
    msg_bruto: str,
    nome_estado: str = "",
) -> None:
    """Remove rua/número fantasma (eco do LLM ou dia da data de nascimento)."""
    from app.validation import rua_parece_frase_invalida

    nome_cliente = normalizar_texto(nome_estado)
    if dados.rua and rua_parece_frase_invalida(dados.rua):
        if not _extrair_rua_rotulo(msg_bruto):
            dados.rua = ""
    if dados.rua and nome_cliente and normalizar_texto(dados.rua) == nome_cliente:
        if not _extrair_rua_rotulo(msg_bruto):
            dados.rua = ""
    if dados.numero and _parece_data_nascimento_msg(msg_bruto):
        dia = (_extrair_data_nascimento(msg_bruto) or "").split("/")[0]
        num = texto(dados.numero)
        if dia and (num == dia.lstrip("0") or num == dia):
            dados.numero = ""
    if dados.nome and _mensagem_e_apenas_cpf(msg_bruto):
        dados.nome = ""
    if dados.data_nascimento and dados.cep:
        if re.sub(r"\D", "", dados.cep) == re.sub(r"\D", "", dados.data_nascimento):
            dados.data_nascimento = ""


def sanitizar_dados_cadastro(
    dados: dict[str, Any],
    estado: dict[str, Any],
    msg: str = "",
) -> dict[str, Any]:
    """Versão dict para a state machine."""
    from app.models import DadosExtraidos
    from app.validation import rua_parece_eco_nome, rua_parece_frase_invalida

    d = DadosExtraidos(**{k: dados.get(k, "") for k in CAMPOS_DADOS if k in dados})
    aguardando = texto(estado.get("aguardando"))
    _limpar_ecos_estado(d, estado, msg, aguardando)
    _sanitizar_ecos_cadastro(d, msg, str(estado.get("nome") or ""))
    nome_ref = str(estado.get("nome") or d.nome or "")
    if rua_parece_frase_invalida(d.rua) and not _extrair_rua_rotulo(msg):
        d.rua = ""
    if rua_parece_eco_nome(d.rua, nome_ref) and not _extrair_rua_rotulo(msg):
        d.rua = ""
    out = dict(dados)
    for campo in ("rua", "numero"):
        val = texto(getattr(d, campo, ""))
        if val:
            out[campo] = val
        else:
            out.pop(campo, None)
    return out


def _aplicar_extracao_campo_pendente(
    aguardando: str,
    msg_bruto: str,
    msg: str,
    dados: DadosExtraidos,
    eventos: list[str],
    nome_estado: str = "",
) -> None:
    """Extrai o campo pendente, o par dele e campos seguintes na mesma mensagem."""
    from app.cadastro_mensagens import par_de
    from app.state_machine import ORDEM_CADASTRO

    campos_alvo = set(_campos_cadastro_a_partir_de(aguardando))
    if not campos_alvo:
        return

    from app.interpretacao_campo import mensagem_tem_intencao_nao_dado

    parte_dado = _strip_trailing_question_mark(_parte_principal_dado(msg_bruto))
    tem_dado_na_frente = bool(
        parte_dado and _texto_parece_apenas_dado_cadastro(parte_dado, aguardando)
    )
    if (
        mensagem_tem_intencao_nao_dado(msg, msg_bruto, aguardando=aguardando, fase="cadastro")
        and not _texto_parece_apenas_dado_cadastro(msg_bruto, aguardando)
        and not tem_dado_na_frente
    ):
        return
    if tem_dado_na_frente and parte_dado != msg_bruto.strip():
        bruto = parte_dado
        msg = normalizar_texto(parte_dado)
        segmentos = _segmentos_mensagem(bruto)

    par = set(par_de(aguardando))
    # Dado na frente + dúvida depois ("Edrei Maciel, 604...\nMas tem multa?"):
    # extrai do trecho do dado; a dúvida é tratada à parte
    if tem_dado_na_frente and parte_dado != msg_bruto.strip():
        bruto = parte_dado
        duvida = False
    else:
        bruto = msg_bruto
        duvida = tem_duvida_informativa(msg, msg_bruto, aguardando=aguardando)
    segmentos = _segmentos_mensagem(bruto)

    if "nome" in campos_alvo and not dados.nome and not duvida and not _mensagem_e_apenas_cpf(bruto):
        nome = _extrair_nome_livre(bruto)
        if nome:
            dados.nome = nome
    if "cpf" in campos_alvo and not dados.cpf:
        cpf = _extrair_cpf_embutido(bruto) or _extrair_cpf("", bruto)
        if cpf:
            dados.cpf = cpf
    if "telefone" in campos_alvo and not dados.telefone:
        if aguardando == "cpf":
            # Pediu CPF e veio um celular: guarda como telefone e segue pedindo o CPF
            if celular_e_nao_cpf(bruto):
                dados.telefone = _somente_digitos(bruto)
        elif aguardando == "telefone":
            tel = _extrair_telefone_em_segmentos(bruto)
            if tel:
                dados.telefone = tel
        elif not _mensagem_e_apenas_cpf(bruto) and not _parece_cpf_cnpj("", bruto):
            tel = _extrair_telefone_em_segmentos(bruto)
            if tel:
                dados.telefone = tel
    if "email" in campos_alvo and not dados.email:
        for seg in segmentos + [bruto]:
            email = _extrair_email(seg)
            if email:
                dados.email = email
                break
    if "data_nascimento" in campos_alvo and not dados.data_nascimento:
        dt = _extrair_data_nascimento(bruto)
        if dt:
            dados.data_nascimento = dt
    if "cep" in campos_alvo and not dados.cep:
        cep = _extrair_cep_rotulo(bruto) or _extrair_cep_sem_data(bruto)
        if not cep:
            for seg in segmentos:
                if re.search(r"(?i)\bcep\b", seg):
                    cep = _extrair_cep(seg)
                elif "@" not in seg and not _extrair_data_nascimento(seg):
                    cep = _extrair_cep(seg)
                if cep:
                    break
        if cep:
            dados.cep = cep

    if eh_mensagem_sobre_planos(msg, bruto):
        dados.rua = ""
        dados.numero = ""
        campos_alvo.discard("rua")
        campos_alvo.discard("numero")

    if ("rua" in campos_alvo or "numero" in campos_alvo) and not duvida:
        sinal_endereco = _mensagem_tem_sinal_endereco(bruto, aguardando=aguardando)
        if aguardando in {"rua", "numero"} or sinal_endereco:
            if "rua" in campos_alvo and not dados.rua:
                rua_lbl = _extrair_rua_rotulo(bruto)
                if rua_lbl:
                    dados.rua = rua_lbl
            if "numero" in campos_alvo and not dados.numero:
                for seg in reversed(segmentos):
                    if (
                        re.search(r"(?i)\b(?:rua|cep|email|telefone)\b", seg)
                        or "@" in seg
                        or _parece_data_nascimento_msg(seg)
                    ):
                        continue
                    num = _extrair_numero_endereco(seg)
                    if num and len(re.sub(r"\D", "", num)) <= 5:
                        dados.numero = num
                        break
            if sinal_endereco:
                rua, num = _split_rua_numero(bruto, aguardando=aguardando)
                if "rua" in campos_alvo and rua and not dados.rua:
                    dados.rua = rua
                if "numero" in campos_alvo and num and not dados.numero:
                    if len(re.sub(r"\D", "", num)) <= 5:
                        dados.numero = num
    _sanitizar_ecos_cadastro(dados, msg_bruto, nome_estado)

    # Eco do LLM fora da ordem permitida (ex.: nome quando pedimos rua)
    for campo in ORDEM_CADASTRO:
        if campo not in campos_alvo and texto(getattr(dados, campo, "")):
            setattr(dados, campo, "")

    campo_map = {
        "nome": dados.nome,
        "cpf": dados.cpf,
        "email": dados.email,
        "telefone": dados.telefone,
        "data_nascimento": dados.data_nascimento,
        "cep": dados.cep,
        "rua": dados.rua,
        "numero": dados.numero,
    }
    if any(texto(campo_map.get(c)) for c in campos_alvo):
        if Evento.DADO_INFORMADO.value not in eventos:
            eventos.append(Evento.DADO_INFORMADO.value)


def _suprimir_troca_localizacao_informativa(
    eventos: list[str],
    dados: DadosExtraidos,
    msg_bruto: str,
    msg: str,
) -> list[str]:
    informativa = (
        tem_duvida_informativa(msg, msg_bruto)
        or eh_pergunta_mudanca_endereco(msg_bruto)
        or eh_pergunta_cobertura_informativa(msg_bruto)
    )
    if not informativa or dados.cidade or dados.bairro:
        return eventos
    return [
        e
        for e in eventos
        if e
        not in {
            Evento.PEDIU_TROCAR_LOCALIZACAO.value,
            Evento.LOCALIZACAO_INFORMADA.value,
        }
    ]


def eh_pergunta_mudanca_endereco(msg: str) -> bool:
    t = normalizar_texto(msg)
    if not t:
        return False
    if any(c in t for c in CHAVES_MUDANCA_ENDERECO):
        return True
    # "e se ... endereco" / "posso mudar" sem dados novos de cidade
    if ("endereco" in t or "endereço" in (msg or "").casefold()) and any(
        p in t for p in ("se eu", "e se", "posso", "consigo", "depois", "contrat")
    ):
        return True
    return False


_CHAVES_DUVIDA_COM_BORDA = frozenset(
    {"e se", "se eu", "tem mais", "o que tem", "quanto tempo", "quando vem", "quando instala"}
)


def _texto_tem_chave_duvida(t: str) -> bool:
    for k in CHAVES_DUVIDA_INFORMATIVA:
        if k in _CHAVES_DUVIDA_COM_BORDA:
            if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", t):
                return True
        elif k in t:
            return True
    return False


_RE_ABERTURA_SOCIAL = re.compile(
    r"\b(?:oi+e?|ola+|opa|e\s*ai|bom\s+dia|boa\s+tarde|boa\s+noite|"
    r"(?:tudo|td)\s+(?:bem|bom|certo|joia|tranquilo)|como\s+(?:vai|esta|estao|vao))\b"
)
_RE_COMPLEMENTO_SOCIAL = re.compile(
    r"\b(?:beleza|blz|com\s+(?:voce|vc|voces|vcs)|por\s+ai|eva|e|ai|a|o)\b"
)


def eh_so_saudacao(msg_bruto: str) -> bool:
    """'oi, tudo bem?' / 'boa tarde, como vai?' — cumprimento, não dúvida."""
    t = re.sub(r"[^\w\s]", " ", normalizar_texto(msg_bruto))
    if not _RE_ABERTURA_SOCIAL.search(t):
        return False
    resto = _RE_COMPLEMENTO_SOCIAL.sub(" ", _RE_ABERTURA_SOCIAL.sub(" ", t))
    return not resto.strip()


def tem_duvida_informativa(
    msg: str,
    msg_bruto: str = "",
    *,
    aguardando: str | None = None,
) -> bool:
    bruto = texto(msg_bruto or msg)
    if eh_so_saudacao(bruto):
        return False
    partes_sep = re.split(
        r"(?i)\s+(?:mas|porem|porém|e se|so que|só que)\s+",
        bruto,
        maxsplit=1,
    )
    if len(partes_sep) >= 2:
        parte_duvida = partes_sep[1]
        t_duvida = normalizar_texto(parte_duvida)
        if "?" in parte_duvida or _texto_tem_chave_duvida(t_duvida):
            return True
        bruto = partes_sep[0]
    t = normalizar_texto(bruto)
    if aguardando and bruto.rstrip().endswith("?"):
        if _texto_parece_apenas_dado_cadastro(bruto, aguardando):
            sem_q = _strip_trailing_question_mark(bruto)
            if not _texto_tem_chave_duvida(normalizar_texto(sem_q)):
                return False
    if "?" in bruto:
        return True
    return _texto_tem_chave_duvida(t)


def eh_pergunta_detalhe_plano(msg: str, msg_bruto: str = "") -> bool:
    t = normalizar_texto(msg_bruto or msg)
    return any(p in t for p in PERGUNTAS_DETALHE_PLANO)


def eh_pergunta_generica_plano_em_foco(msg: str, msg_bruto: str = "") -> bool:
    """Pergunta sobre o plano já em foco, sem citar outro nome."""
    t = normalizar_texto(msg_bruto or msg)
    return any(
        p in t
        for p in (
            "nesse plano",
            "nessa opcao",
            "nessa opção",
            "nesse combo",
            "esse plano",
            "essa opcao",
            "o que tem nesse",
            "o que vem nesse",
            "quanto e esse",
            "quanto custa esse",
            "valor desse",
            "preco desse",
            "preço desse",
        )
    )


def eh_pergunta_preco_plano_nomeado(msg: str, msg_bruto: str = "") -> bool:
    """'Quanto custa o mov up?' — preço de plano citado na mensagem."""
    t = normalizar_texto(msg_bruto or msg)
    if not any(p in t for p in PERGUNTAS_PRECO):
        return False
    return bool(extrair_referencia_plano_na_mensagem(t, msg_bruto or msg))


def eh_pergunta_informativa_sobre_plano(msg: str, msg_bruto: str = "") -> bool:
    """Detalhe, preço ou identificação — não é escolha/troca de plano."""
    return (
        eh_pergunta_detalhe_plano(msg, msg_bruto)
        or eh_pergunta_plano_por_preco(msg, msg_bruto)
        or eh_pergunta_preco_plano_nomeado(msg, msg_bruto)
    )


def _precos_na_mensagem(msg: str, *, minimo: float = 30) -> list[float]:
    nums = re.findall(r"\d+(?:[.,]\d{1,2})?", str(msg or ""))
    out: list[float] = []
    for n in nums:
        try:
            v = float(n.replace(",", "."))
        except ValueError:
            continue
        if v >= minimo:
            out.append(v)
    return out


def eh_pergunta_plano_por_preco(msg: str, msg_bruto: str = "") -> bool:
    """'Qual o de 69,50?' — identifica plano pelo valor, não escolha."""
    bruto = texto(msg_bruto or msg)
    t = normalizar_texto(bruto)
    if not t:
        return False
    # Evita falso positivo com telefone/CPF (93992219098 + ?)
    digitos = re.sub(r"\D", "", bruto)
    tem_valor_plano = bool(re.search(r"\b\d{2,3}[.,]\d{2}\b", bruto))
    if len(digitos) >= 10 and not tem_valor_plano:
        return False
    if not tem_valor_plano and not _precos_na_mensagem(t, minimo=50):
        return False
    if eh_confirmacao(t):
        return False
    if re.match(r"^(quero|queria|preciso|gostaria|vou de|fecho com|fico com)\b", t):
        return False
    if tem_valor_plano and (
        "?" in bruto or t.startswith("qual ") or t.startswith("quais ")
    ):
        return True
    return any(
        p in t
        for p in (
            "qual o de",
            "qual e o de",
            "qual plano e",
            "qual deles",
            "qual desses",
            "qual tem o",
        )
    )


def eh_pedido_contratacao(msg: str, msg_bruto: str = "") -> bool:
    """Intenção de contratar/instalar serviço — não é pergunta sobre instalação."""
    t = normalizar_texto(msg_bruto or msg)
    if not t:
        return False
    if re.search(r"\b(quero|queria|preciso|gostaria)\s+(instalar|contratar)\b", t):
        return True
    if re.search(r"\b(quero|queria)\s+(internet|fibra)\b", t):
        return True
    return any(
        p in t
        for p in (
            "quero instalar",
            "queria instalar",
            "preciso instalar",
            "quero contratar",
            "queria contratar",
            "preciso contratar",
            "quero internet",
            "queria internet",
            "quero fibra",
            "queria fibra",
        )
    )


def eh_pergunta_custo_instalacao(msg: str, msg_bruto: str = "") -> bool:
    """Pergunta se instalação é grátis, tem taxa ou quanto custa."""
    t = normalizar_texto(msg_bruto or msg)
    if not t:
        return False
    if not any(k in t for k in CHAVES_CUSTO_INSTALACAO):
        return False
    return any(k in t for k in ("instala", "instalar", "visita", "tecnico", "taxa"))


def eh_pergunta_instalacao(
    msg: str,
    msg_bruto: str = "",
    *,
    topico: str | None = None,
) -> bool:
    """Dúvida sobre instalação, prazo, técnico ou 'conseguem vir hoje?'."""
    if eh_pedido_contratacao(msg, msg_bruto):
        return False
    if eh_apenas_dado_cadastro(msg, msg_bruto):
        return False
    if eh_mensagem_correcao_cadastro(msg, msg_bruto):
        return False
    if eh_pergunta_custo_instalacao(msg, msg_bruto):
        return True
    t = normalizar_texto(msg_bruto or msg)
    if (topico or "").strip().casefold() == "instalacao":
        from app.contexto_conversa import eh_followup_curto

        if eh_followup_curto(t) or any(k in t for k in CHAVES_INSTALACAO):
            return True
        return False
    if not t:
        return False
    if any(k in t for k in CHAVES_INSTALACAO):
        return True
    # "horario do tecnico" / "visita tecnica"
    if "horario" in t and any(x in t for x in ("tecnico", "instala", "visita")):
        return True
    return False


def extrair_parte_pergunta(msg_bruto: str, msg: str) -> str:
    bruto = texto(msg_bruto)
    if not bruto:
        return ""
    partes_sep = re.split(
        r"(?i)\s+(?:mas|porem|porém|e se|so que|só que)\s+",
        bruto,
        maxsplit=1,
    )
    if len(partes_sep) >= 2 and tem_duvida_informativa(normalizar_texto(partes_sep[1]), partes_sep[1]):
        return partes_sep[1].strip()
    if "?" in bruto:
        partes = re.split(r"(?<=[?])\s*", bruto)
        for p in reversed(partes):
            if "?" in p and tem_duvida_informativa(normalizar_texto(p), p):
                return p.strip()
    if tem_duvida_informativa(msg, bruto):
        return bruto.strip()
    return ""


def _parece_nome_completo(msg_bruto: str, msg: str) -> bool:
    if tem_duvida_informativa(msg, msg_bruto):
        return False
    bruto = texto(msg_bruto)
    if not bruto or "@" in bruto or _parece_cpf_cnpj(msg, bruto):
        return False
    partes = [p for p in bruto.split() if p]
    if len(partes) < 2:
        return False
    return all(re.search(r"[a-zA-ZÀ-ÿ]", p) for p in partes)


def _strip_markdown(raw: str) -> str:
    s = texto(raw)
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


_CAMPOS_RECONCILIAVEIS = ("nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero")


def _canonico(campo: str, valor: str) -> str:
    v = texto(valor)
    if campo in {"cpf", "telefone", "cep"}:
        return _somente_digitos(v)
    if campo == "data_nascimento":
        return _extrair_data_nascimento(v) or v
    if campo == "email":
        return v.lower().replace(" ", "")
    return v


def _evidenciado(campo: str, valor: str, msg_bruto: str) -> bool:
    """O valor que o LLM extraiu está de fato escrito na mensagem do cliente."""
    if not valor:
        return False
    if campo in {"cpf", "telefone", "cep"}:
        return valor in _somente_digitos(msg_bruto)
    if campo == "data_nascimento":
        return _extrair_data_nascimento(msg_bruto) == valor or valor in msg_bruto
    if campo == "email":
        return valor in msg_bruto.lower().replace(" ", "")
    if campo == "numero":
        # Solto na mensagem — não um pedaço de data, CEP, CPF ou telefone
        return bool(
            re.search(rf"(?<![\w/.\-]){re.escape(valor)}(?![\w/.\-])", msg_bruto, flags=re.I)
        )
    return normalizar_texto(valor) in normalizar_texto(msg_bruto)


def _reconciliar_com_llm(
    *,
    dados: DadosExtraidos,
    dados_llm: dict[str, str],
    eventos: list[str],
    campos_corrigidos: list[str],
    corrigidos_llm: set[str],
    estado: dict[str, Any],
    aguardando: str,
    msg_bruto: str,
) -> None:
    """Última etapa do parser no cadastro: o que o LLM leu na mensagem prevalece.

    As regras acima reextraem e filtram os campos por palavra-chave e às vezes apagam
    ou trocam um valor que o LLM leu certo ("email edrei@..." virava "drei@...";
    "o nome está errado, é João Carlos" perdia o nome). Um valor do LLM volta quando:
    está escrito na mensagem, é válido para o campo, não foi movido para outro campo
    e o campo é o esperado agora (pendente, par dele ou correção declarada).
    """
    from app.cadastro_mensagens import par_de
    from app.validation import (
        nome_parece_frase_invalida,
        rua_parece_eco_nome,
        rua_parece_frase_invalida,
        validar_campo,
    )

    par = set(par_de(aguardando))
    for campo in _CAMPOS_RECONCILIAVEIS:
        v_llm = _canonico(campo, dados_llm.get(campo, ""))
        if not v_llm:
            continue
        atual = _canonico(campo, getattr(dados, campo, ""))
        if atual == v_llm:
            continue
        if not _evidenciado(campo, v_llm, msg_bruto) or validar_campo(campo, v_llm) is not None:
            continue
        # O parser moveu o mesmo valor para outro campo (rua lida como nome, celular como CPF)
        if any(
            _canonico(outro, getattr(dados, outro, "")) == v_llm
            or normalizar_texto(texto(getattr(dados, outro, ""))) == normalizar_texto(v_llm)
            for outro in _CAMPOS_RECONCILIAVEIS
            if outro != campo
        ):
            continue
        # Só o campo pedido agora, o par dele ou uma correção declarada — um valor
        # "solto" para outro campo continua passando pelos filtros normais.
        if not (campo == aguardando or campo in par or campo in corrigidos_llm):
            continue
        if campo == "nome" and (
            nome_parece_frase_invalida(v_llm) or not _parece_nome_de_pessoa(v_llm)
        ):
            continue
        if campo == "rua" and (
            rua_parece_frase_invalida(v_llm) or rua_parece_eco_nome(v_llm, texto(estado.get("nome")))
        ):
            continue
        if campo in {"cpf", "telefone"} and celular_e_nao_cpf(v_llm) != (campo == "telefone") and len(v_llm) == 11:
            continue

        setattr(dados, campo, v_llm)
        if campo in corrigidos_llm:
            if campo not in campos_corrigidos:
                campos_corrigidos.append(campo)
            if Evento.CORRECAO_DADO.value not in eventos:
                eventos.append(Evento.CORRECAO_DADO.value)
        if Evento.DADO_INFORMADO.value not in eventos:
            eventos.append(Evento.DADO_INFORMADO.value)


def parse_interpretacao(raw: str, mensagem_cliente: str, estado: dict[str, Any]) -> Interpretacao:
    try:
        data = json.loads(_strip_markdown(raw))
    except json.JSONDecodeError:
        return Interpretacao(
            eventos=[Evento.OUTRO.value],
            confianca=0.65,
            pergunta=mensagem_cliente[:200],
        )

    eventos_raw = data.get("eventos") or []
    if not isinstance(eventos_raw, list):
        eventos_raw = []

    eventos: list[str] = []
    for item in eventos_raw:
        nome = texto(item).upper()
        if nome in EVENTOS_VALIDOS and nome not in eventos:
            eventos.append(nome)

    dados_in = data.get("dados") if isinstance(data.get("dados"), dict) else {}
    dados_dict = {campo: texto(dados_in.get(campo)) for campo in CAMPOS_DADOS}
    dados = DadosExtraidos(**dados_dict)
    # Classificação original do LLM, antes das correções abaixo
    eventos_llm = set(eventos)
    llm_extraiu_dado = any(dados_dict.values())

    from app.geo_coords import extrair_gps_mensagem, parece_coordenada

    if extrair_gps_mensagem(mensagem_cliente):
        dados.cidade = ""
        dados.bairro = ""
    else:
        if parece_coordenada(dados.cidade):
            dados.cidade = ""
        if parece_coordenada(dados.bairro):
            dados.bairro = ""

    campos = data.get("campos_corrigidos") or []
    if not isinstance(campos, list):
        campos = []
    campos_corrigidos = [texto(c).lower() for c in campos if texto(c)]
    corrigidos_llm = set(campos_corrigidos)

    # Data que o LLM devolveu por extenso ("16 de agosto de 2000") → dd/mm/aaaa
    if dados.data_nascimento:
        dados.data_nascimento = (
            _extrair_data_nascimento(dados.data_nascimento) or dados.data_nascimento
        )

    # LLM pôs um celular no campo CPF (os dois têm 11 dígitos) — vai para telefone
    if dados.cpf and celular_e_nao_cpf(dados.cpf):
        if not dados.telefone:
            dados.telefone = _somente_digitos(dados.cpf)
        dados.cpf = ""
        campos_corrigidos = [c for c in campos_corrigidos if c != "cpf"]

    pergunta = texto(data.get("pergunta"))
    try:
        confianca = float(data.get("confianca") or 0)
    except (TypeError, ValueError):
        confianca = 0.0

    msg = normalizar_texto(mensagem_cliente)
    msg_bruto = texto(mensagem_cliente)
    fase = texto(estado.get("fase"))
    aguardando = texto(estado.get("aguardando"))
    aguardando_plano = fase == "vendas" and aguardando in {
        "confirmacao_plano",
        "escolha_plano",
        "lista_planos",
    }
    pode_trocar_plano = fase in {"vendas", "cadastro"} and not bool(estado.get("cadastro_completo"))
    aguardando_cadastro = aguardando in {
        "nome", "cpf", "email", "telefone", "data_nascimento",
        "cep", "rua", "numero", "confirmacao_dados",
    }
    aguardando_agenda = aguardando in {"escolha_horario", "confirmacao_horario"}

    # Confirmação só pelo começo da frase ("tá ...", "ok ...", "sim, mas ...") é fraca:
    # se o LLM classificou a mensagem e não viu confirmação, as regras não forçam.
    msg_confirma = eh_confirmacao(msg)
    if (
        msg_confirma
        and eventos_llm
        and Evento.CONFIRMACAO.value not in eventos_llm
        and not _confirmacao_exata(msg)
    ):
        msg_confirma = False

    # No cadastro, dúvida que o LLM leu como pergunta ("o roteador é de vocês?") não é
    # pedido de troca de plano, mesmo citando roteador/mesh/etc.
    duvida_no_cadastro = (
        fase == "cadastro"
        and "?" in msg_bruto
        and Evento.PERGUNTA.value in eventos_llm
        and not (eventos_llm & {Evento.PLANO_INFORMADO.value, Evento.PEDIU_TROCAR_PLANO.value})
    )
    # "pode ser o segundo" — escolha de um plano da lista (o LLM resolve o nome pelo
    # histórico), não confirmação do plano que estava em negociação
    escolha_por_posicao = (
        aguardando_plano
        and bool(_RE_POSICAO_LISTA.search(msg))
        and bool(extrair_referencia_plano_na_mensagem(dados.plano))
    )
    # "pode ser o infinity" / "sim, o one+" — a mensagem nomeia um plano: é escolha desse
    # plano. Se for o mesmo que está em negociação, a máquina de estados confirma.
    if aguardando_plano and not escolha_por_posicao:
        plano_citado = _detectar_plano_na_mensagem(msg)
        if plano_citado and not eh_pergunta_informativa_sobre_plano(msg, msg_bruto):
            escolha_por_posicao = True
            if not extrair_referencia_plano_na_mensagem(dados.plano):
                dados.plano = plano_citado
    if escolha_por_posicao:
        eventos = [e for e in eventos if e != Evento.CONFIRMACAO.value]
        if Evento.PLANO_INFORMADO.value not in eventos:
            eventos.append(Evento.PLANO_INFORMADO.value)

    # "Oi, quero instalar" — intenção de contratar, não plano/pergunta de instalação
    abertura_contratacao = eh_pedido_contratacao(msg, msg_bruto) and not (
        fase == "vendas"
        and aguardando_plano
        and (
            estado.get("plano_em_negociacao_id") is not None
            or estado.get("plano_apresentado_id") is not None
        )
    )
    if abertura_contratacao:
        if any(p in msg for p in ("oi", "ola", "olá", "bom dia", "boa tarde", "boa noite")):
            if Evento.SAUDACAO.value not in eventos:
                eventos.append(Evento.SAUDACAO.value)
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.CONFIRMACAO.value,
                Evento.PLANO_INFORMADO.value,
                Evento.PERGUNTA.value,
                Evento.OUTRO.value,
                Evento.LOCALIZACAO_INFORMADA.value,
            }
        ]
        if Evento.PEDIDO_CONTRATACAO.value not in eventos:
            eventos.append(Evento.PEDIDO_CONTRATACAO.value)
        dados.plano = ""
        # "quero internet, moro em Santarém no Diamantino" — a localização veio junto:
        # fica o que está escrito na mensagem e não é frase de conversa.
        from app.localizacao_heuristica import _parece_conversa

        for campo_loc in ("cidade", "bairro"):
            v_loc = texto(getattr(dados, campo_loc))
            if v_loc and (normalizar_texto(v_loc) not in msg or _parece_conversa(v_loc)):
                setattr(dados, campo_loc, "")
        if (dados.cidade or dados.bairro) and Evento.LOCALIZACAO_INFORMADA.value not in eventos:
            eventos.append(Evento.LOCALIZACAO_INFORMADA.value)
        pergunta = ""

    # "oi, tudo bem?" — o "?" é do cumprimento, não uma dúvida para a base de conhecimento
    if eh_so_saudacao(msg_bruto):
        eventos = [e for e in eventos if e not in {Evento.PERGUNTA.value, Evento.OUTRO.value}]
        if Evento.SAUDACAO.value not in eventos:
            eventos.append(Evento.SAUDACAO.value)
        pergunta = ""

    # CPF/CNPJ — força extração quando o pendente é CPF (evita ir para telefone)
    if _parece_cpf_cnpj(msg, msg_bruto) and aguardando == "cpf":
        cpf_val = _extrair_cpf(msg, msg_bruto)
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.PLANO_INFORMADO.value,
                Evento.PEDIU_TROCAR_PLANO.value,
                Evento.LOCALIZACAO_INFORMADA.value,
                Evento.OUTRO.value,
            }
        ]
        if Evento.DADO_INFORMADO.value not in eventos:
            eventos.append(Evento.DADO_INFORMADO.value)
        dados.cpf = cpf_val
        dados.telefone = ""
        dados.plano = ""
        campos_corrigidos = []
        pergunta = ""

    from app.pos_venda_mensagens import eh_pedido_encerrar

    pedido_encerrar = eh_pedido_encerrar(msg_bruto) and fase not in {"transferido", "finalizado"}
    if pedido_encerrar:
        for campo in (
            "cidade", "bairro", "plano", "nome", "cpf", "email", "telefone",
            "data_nascimento", "rg", "cep", "rua", "numero", "complemento",
            "metodo_pagamento", "data_vencimento_pref", "turno_escolhido",
        ):
            setattr(dados, campo, "")
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.DADO_INFORMADO.value,
                Evento.PLANO_INFORMADO.value,
                Evento.LOCALIZACAO_INFORMADA.value,
                Evento.CONFIRMACAO.value,
                Evento.PERGUNTA.value,
                Evento.OUTRO.value,
                Evento.CONVERSA_SOCIAL.value,
                Evento.PEDIDO_CONTRATACAO.value,
            }
        ]
        if Evento.NEGACAO.value not in eventos:
            eventos.append(Evento.NEGACAO.value)
        campos_corrigidos = []
        pergunta = ""

    elif aguardando_cadastro and any(p in msg for p in REPETICAO_DADO):
        # "já disse o nome" — reutiliza dado que já está no estado
        campo_map = {
            "nome": "nome",
            "cpf": "cpf",
            "email": "email",
            "telefone": "telefone",
            "data_nascimento": "data_nascimento",
            "cep": "cep",
            "rua": "rua",
            "numero": "numero",
        }
        campo = None
        for chave in campo_map:
            if chave in msg:
                campo = chave
                break
        if not campo:
            campo = campo_map.get(aguardando)
        if campo and estado.get(campo):
            eventos = [e for e in eventos if e != Evento.OUTRO.value]
            if Evento.DADO_INFORMADO.value not in eventos:
                eventos.append(Evento.DADO_INFORMADO.value)
            setattr(dados, campo, str(estado.get(campo)))
            pergunta = ""

    # Esclarecimento sobre promo do plano em foco — não relistar catálogo
    if aguardando_plano and eh_esclarecimento_promo_plano(msg):
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.CONFIRMACAO.value,
                Evento.PEDIU_TROCAR_PLANO.value,
                Evento.PLANO_INFORMADO.value,
                Evento.NEGACAO.value,
            }
        ]
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        if not pergunta:
            pergunta = msg_bruto.strip()
        dados.plano = ""

    # Pedido de promo/desconto ≠ confirmação do plano apresentado
    elif aguardando_plano and (
        eh_pedido_plano_promocional(msg) or eh_pedido_planos_com_desconto(msg)
    ):
        eventos = [e for e in eventos if e != Evento.CONFIRMACAO.value]
        if Evento.PEDIU_TROCAR_PLANO.value not in eventos:
            eventos.append(Evento.PEDIU_TROCAR_PLANO.value)
        if eh_pedido_plano_promocional(msg):
            eventos = [
                e
                for e in eventos
                if e not in {Evento.NEGACAO.value, Evento.OUTRO.value}
            ]
            if Evento.PLANO_INFORMADO.value not in eventos:
                eventos.append(Evento.PLANO_INFORMADO.value)
            if not dados.plano:
                dados.plano = msg_bruto[:160]
        else:
            dados.plano = ""
        pergunta = ""

    if (
        aguardando_plano
        and (msg_confirma or msg == "quero")
        and not eh_pedido_contratacao(msg, msg_bruto)
        and not escolha_por_posicao
    ):
        eventos = [e for e in eventos if e not in {Evento.PLANO_INFORMADO.value, Evento.PEDIU_TROCAR_PLANO.value, Evento.NEGACAO.value}]
        if Evento.CONFIRMACAO.value not in eventos:
            eventos.append(Evento.CONFIRMACAO.value)
        dados.plano = ""
        pergunta = ""

    if aguardando_plano and eh_recusa(msg):
        eventos = [e for e in eventos if e not in {Evento.CONFIRMACAO.value, Evento.PLANO_INFORMADO.value}]
        if Evento.NEGACAO.value not in eventos:
            eventos.append(Evento.NEGACAO.value)
        dados.plano = ""
        pergunta = ""

    if (
        fase != "agendamento"
        and pode_trocar_plano
        and (
            msg in PEDIDOS_ALTERNATIVA
            or any(p in msg for p in PEDIDOS_ALTERNATIVA if len(p) >= 8)
        )
    ):
        eventos = [e for e in eventos if e not in {Evento.PERGUNTA.value, Evento.PLANO_INFORMADO.value}]
        if Evento.PEDIU_TROCAR_PLANO.value not in eventos:
            eventos.append(Evento.PEDIU_TROCAR_PLANO.value)
        dados.plano = ""
        pergunta = ""

    if fase in {"vendas", "cadastro"} and (
        any(p in msg for p in PEDIDOS_LISTAR_PLANOS) or eh_pedido_lista_completa_planos(msg)
    ):
        eventos = [e for e in eventos if e not in {Evento.PLANO_INFORMADO.value, Evento.OUTRO.value, Evento.PERGUNTA.value}]
        if Evento.PEDIU_TROCAR_PLANO.value not in eventos:
            eventos.append(Evento.PEDIU_TROCAR_PLANO.value)
        # lista completa → marca PERGUNTA para a SM disparar LISTAR_TODOS
        if eh_pedido_lista_completa_planos(msg):
            if Evento.PERGUNTA.value not in eventos:
                eventos.append(Evento.PERGUNTA.value)
        elif Evento.PERGUNTA.value not in eventos and any(
            p in msg for p in ("quais", "lista", "opcoes", "disponiveis", "so tem esse")
        ):
            eventos.append(Evento.PERGUNTA.value)
        dados.plano = ""
        pergunta = ""

    # "com dois roteadores" / "mais barato" → resolve plano (não trata só como chat)
    if (
        (
            aguardando_plano
            or (fase == "vendas" and estado.get("tem_cobertura") is True)
            or (fase == "cadastro" and estado.get("tem_cobertura") is True)
        )
        and any(k in msg for k in INTENCAO_PLANO_KEYWORDS)
        and not duvida_no_cadastro
        and msg not in CONFIRMACOES_GENERICAS
        and not msg_confirma
        and not any(p in msg for p in PERGUNTAS_PRECO)
        and not eh_pergunta_detalhe_plano(msg, msg_bruto)
        and not eh_pergunta_plano_por_preco(msg, msg_bruto)
        and not eh_pergunta_instalacao(msg, msg_bruto)
        and not any(p in msg for p in PEDIDOS_ALTERNATIVA if len(p) >= 8)
        and not any(p in msg for p in PEDIDOS_LISTAR_PLANOS)
    ):
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.PERGUNTA.value,
                Evento.OUTRO.value,
                Evento.PEDIU_TROCAR_PLANO.value,
                Evento.NEGACAO.value,
            }
        ]
        if Evento.PLANO_INFORMADO.value not in eventos:
            eventos.append(Evento.PLANO_INFORMADO.value)
        if not dados.plano:
            dados.plano = msg_bruto[:160]
        pergunta = ""

    # Correções rotuladas no resumo cadastral
    if fase == "cadastro" and aguardando == "confirmacao_dados" and not msg_confirma:
        correcoes_msg = _extrair_correcoes_rotuladas(msg_bruto)
        if correcoes_msg:
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.CONFIRMACAO.value,
                    Evento.NEGACAO.value,
                    Evento.PERGUNTA.value,
                    Evento.OUTRO.value,
                }
            ]
            for campo, valor in correcoes_msg.items():
                if hasattr(dados, campo):
                    setattr(dados, campo, valor)
                if campo not in campos_corrigidos:
                    campos_corrigidos.append(campo)
            if Evento.CORRECAO_DADO.value not in eventos:
                eventos.append(Evento.CORRECAO_DADO.value)
            if Evento.DADO_INFORMADO.value not in eventos:
                eventos.append(Evento.DADO_INFORMADO.value)
            pergunta = ""
        else:
            campo_errado = detectar_campo_incorreto_resumo(msg_bruto)
            if campo_errado:
                eventos = [
                    e
                    for e in eventos
                    if e
                    not in {
                        Evento.CONFIRMACAO.value,
                        Evento.PERGUNTA.value,
                        Evento.OUTRO.value,
                    }
                ]
                setattr(dados, campo_errado, "")
                if campo_errado not in campos_corrigidos:
                    campos_corrigidos.append(campo_errado)
                if Evento.CORRECAO_DADO.value not in eventos:
                    eventos.append(Evento.CORRECAO_DADO.value)
                if Evento.NEGACAO.value not in eventos:
                    eventos.append(Evento.NEGACAO.value)
                pergunta = ""

    # Confirmação do resumo cadastral (+ dúvida opcional na mesma mensagem)
    if fase == "cadastro" and aguardando == "confirmacao_dados" and msg_confirma:
        eventos = [e for e in eventos if e not in {Evento.NEGACAO.value, Evento.PEDIU_TROCAR_PLANO.value}]
        if Evento.CONFIRMACAO.value not in eventos:
            eventos.append(Evento.CONFIRMACAO.value)
        duvida_no_resumo = (
            tem_duvida_informativa(msg, msg_bruto)
            and len(normalizar_texto(msg).split()) > 4
        )
        if duvida_no_resumo:
            if Evento.PERGUNTA.value not in eventos:
                eventos.append(Evento.PERGUNTA.value)
            if not pergunta:
                pergunta = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()
        else:
            # "Tá" / "Sim" — confirma resumo; não regrava cadastro nem abre RAG de planos
            pergunta = ""
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.PERGUNTA.value,
                    Evento.DADO_INFORMADO.value,
                    Evento.CORRECAO_DADO.value,
                    Evento.PLANO_INFORMADO.value,
                    Evento.PEDIU_TROCAR_PLANO.value,
                }
            ]
            if Evento.CONFIRMACAO.value not in eventos:
                eventos.append(Evento.CONFIRMACAO.value)
            for campo in CAMPOS_DADOS:
                if hasattr(dados, campo):
                    setattr(dados, campo, "")

    # Proteção: citação explícita de plano (não CPF, não campos cadastrais pendentes)
    skip_plano = _parece_cpf_cnpj(msg, msg_bruto) or aguardando in {"cpf", "email", "telefone"}
    plano_detectado = _detectar_plano_na_mensagem(msg) if (pode_trocar_plano and not skip_plano) else ""
    # "qual a diferença pro infinity?" no cadastro é dúvida sobre o plano, não troca
    pergunta_sobre_plano = bool(plano_detectado) and (
        eh_pergunta_informativa_sobre_plano(msg, msg_bruto) or duvida_no_cadastro
    )
    if plano_detectado and not pergunta_sobre_plano:
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.DADO_INFORMADO.value,
                Evento.CORRECAO_DADO.value,
                Evento.PERGUNTA.value,
                Evento.CONFIRMACAO.value,
                Evento.OUTRO.value,
            }
        ]
        if Evento.PLANO_INFORMADO.value not in eventos:
            eventos.append(Evento.PLANO_INFORMADO.value)
        dados.plano = plano_detectado
        # Limpa campos cadastrais acidentais nessa mensagem de troca
        dados.nome = ""
        dados.cpf = ""
        dados.email = ""
        dados.telefone = ""
        campos_corrigidos = []
        pergunta = ""
    elif plano_detectado and pergunta_sobre_plano:
        dados.plano = plano_detectado
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        if not pergunta:
            pergunta = texto(msg_bruto) or msg

    # "O que tem no SUPER+?" / "Qual o de 69,50?" — PERGUNTA (não escolha de plano)
    pode_perguntar_plano = aguardando_plano or fase == "vendas" or (
        fase == "cadastro" and bool(estado.get("plano_confirmado"))
    )
    if pode_perguntar_plano and (
        eh_pergunta_detalhe_plano(msg, msg_bruto)
        or eh_pergunta_plano_por_preco(msg, msg_bruto)
    ):
        eventos = [
            e
            for e in eventos
            if e not in {Evento.PLANO_INFORMADO.value, Evento.CONFIRMACAO.value, Evento.OUTRO.value}
        ]
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        if not pergunta:
            pergunta = texto(msg_bruto) or msg
        if eh_pergunta_plano_por_preco(msg, msg_bruto):
            dados.plano = ""
        # Mantém dados.plano se já detectou o nome (contexto); não força escolha

    # E-mail antecipado ou em mensagem partida ("meu email" + "x@gmail.com")
    if fase == "cadastro" and not pedido_encerrar:
        email_detectado = _extrair_email(msg_bruto)
        if email_detectado and not _parece_cpf_cnpj(msg, msg_bruto):
            dados.email = email_detectado
            if Evento.DADO_INFORMADO.value not in eventos:
                eventos.append(Evento.DADO_INFORMADO.value)
            if aguardando != "cpf" or "email" in msg or "e-mail" in msg or "@" in msg_bruto:
                eventos = [e for e in eventos if e != Evento.LOCALIZACAO_INFORMADA.value]

    # Endereço de instalação no cadastro ≠ localização de cobertura
    if fase == "cadastro" and estado.get("plano_confirmado"):
        campos_inst = [dados.rua, dados.numero, dados.cep, dados.complemento, dados.data_nascimento, dados.rg]
        tem_inst = any(texto(c) for c in campos_inst)
        cidade_mudou = bool(dados.cidade) and normalizar_texto(dados.cidade) != normalizar_texto(
            texto(estado.get("cidade"))
        )
        bairro_mudou = bool(dados.bairro) and normalizar_texto(dados.bairro) != normalizar_texto(
            texto(estado.get("bairro"))
        )
        mudou_cobertura = cidade_mudou or bairro_mudou
        if tem_inst and not mudou_cobertura:
            eventos = [e for e in eventos if e != Evento.LOCALIZACAO_INFORMADA.value]
            dados.cidade = ""
            dados.bairro = ""

    # Cidade vs bairro (Diamantino é bairro; "X é o bairro")
    from app.localizacao_heuristica import aplicar_heuristica_localizacao

    loc_flags = aplicar_heuristica_localizacao(
        mensagem=msg_bruto,
        dados=dados,
        estado=estado,
        aguardando=aguardando,
        fase=fase,
    )
    if loc_flags.get("ajustou"):
        if dados.cidade or dados.bairro:
            eventos = [e for e in eventos if e not in {Evento.SAUDACAO.value, Evento.OUTRO.value}]
            if Evento.LOCALIZACAO_INFORMADA.value not in eventos:
                eventos.append(Evento.LOCALIZACAO_INFORMADA.value)
        if loc_flags.get("limpar_cidade"):
            # sinal para o resolver/state via campos_corrigidos / dado vazio na cidade
            if "cidade" not in campos_corrigidos:
                campos_corrigidos.append("cidade")

    # Cadastro — rua/CEP/número são endereço de instalação, não cobertura
    if fase == "cadastro" and estado.get("plano_confirmado"):
        tem_endereco = any(
            texto(getattr(dados, c, "")) for c in ("rua", "numero", "cep", "complemento")
        ) or _mensagem_tem_sinal_endereco(msg_bruto, aguardando=aguardando) or bool(
            _extrair_rua_rotulo(msg_bruto)
        )
        if tem_endereco:
            eventos = [e for e in eventos if e != Evento.LOCALIZACAO_INFORMADA.value]
            dados.cidade = ""
            dados.bairro = ""

    # Encerrar atendimento — qualquer fase (cadastro, vendas, termos, agendamento)
    if pedido_encerrar and fase != "pos_venda":
        if Evento.NEGACAO.value not in eventos:
            eventos.append(Evento.NEGACAO.value)
        pergunta = ""

    # Pós-venda — "não", "obrigado", "pode encerrar" ≠ dúvida
    if fase == "pos_venda" and aguardando == "duvidas":
        from app.pos_venda_mensagens import eh_pedido_encerrar, mensagem_sem_duvidas

        if eh_pedido_encerrar(msg) or mensagem_sem_duvidas(msg) or eh_recusa(msg):
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.PERGUNTA.value,
                    Evento.CONFIRMACAO.value,
                    Evento.OUTRO.value,
                    Evento.CONVERSA_SOCIAL.value,
                }
            ]
            if Evento.NEGACAO.value not in eventos:
                eventos.append(Evento.NEGACAO.value)
            pergunta = ""

    # Termos — aceite do contrato (sim/ok/aceito ≠ pergunta sobre planos)
    if fase == "termos" and aguardando == "aceite_termos":
        if eh_aceite_termos_explicito(msg) or msg_confirma:
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.NEGACAO.value,
                    Evento.PERGUNTA.value,
                    Evento.OUTRO.value,
                    Evento.PLANO_INFORMADO.value,
                    Evento.PEDIU_TROCAR_PLANO.value,
                    Evento.CONVERSA_SOCIAL.value,
                }
            ]
            if Evento.CONFIRMACAO.value not in eventos:
                eventos.append(Evento.CONFIRMACAO.value)
            pergunta = ""
        elif eh_recusa(msg):
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.CONFIRMACAO.value,
                    Evento.PERGUNTA.value,
                    Evento.OUTRO.value,
                }
            ]
            if Evento.NEGACAO.value not in eventos:
                eventos.append(Evento.NEGACAO.value)
            pergunta = ""

    # Agendamento — escolha e confirmação de horário
    if fase == "agendamento":
        from app.agenda_slots import match_horario, pediu_outro_horario

        if aguardando == "confirmacao_horario":
            if msg_confirma:
                eventos = [e for e in eventos if e not in {Evento.NEGACAO.value, Evento.OUTRO.value}]
                if Evento.CONFIRMACAO.value not in eventos:
                    eventos.append(Evento.CONFIRMACAO.value)
                pergunta = ""
            elif eh_recusa(msg):
                eventos = [e for e in eventos if e not in {Evento.CONFIRMACAO.value, Evento.OUTRO.value}]
                if Evento.NEGACAO.value not in eventos:
                    eventos.append(Evento.NEGACAO.value)
                pergunta = ""
            else:
                resultado = match_horario(msg_bruto, estado)
                if resultado.slot:
                    eventos = [e for e in eventos if e != Evento.OUTRO.value]
                    if Evento.DADO_INFORMADO.value not in eventos:
                        eventos.append(Evento.DADO_INFORMADO.value)
                    dados.turno_escolhido = resultado.slot
                    pergunta = ""

        elif aguardando == "escolha_horario":
            resultado = match_horario(msg_bruto, estado)
            # O texto não bateu com nenhum horário, mas o LLM apontou um da lista
            # ("o do meio da manhã", "aquele depois do almoço") — vale o do LLM.
            if not resultado.slot:
                from app.agenda_slots import ResultadoMatch, slot_valido

                slot_llm = texto(dados_dict.get("turno_escolhido"))
                if slot_llm and slot_valido(slot_llm, estado) and not pediu_outro_horario(msg):
                    resultado = ResultadoMatch(slot=slot_llm)
            if resultado.slot:
                eventos = [e for e in eventos if e != Evento.OUTRO.value]
                if Evento.DADO_INFORMADO.value not in eventos:
                    eventos.append(Evento.DADO_INFORMADO.value)
                dados.turno_escolhido = resultado.slot
                pergunta = ""
            elif resultado.ambiguo:
                eventos = [e for e in eventos if e != Evento.OUTRO.value]
                if Evento.DADO_INFORMADO.value not in eventos:
                    eventos.append(Evento.DADO_INFORMADO.value)
                dados.turno_escolhido = f"__AMBIGUO__:{resultado.turno or 'geral'}"
                pergunta = ""
            elif pediu_outro_horario(msg):
                eventos = [e for e in eventos if e not in {Evento.CONFIRMACAO.value, Evento.OUTRO.value}]
                if Evento.NEGACAO.value not in eventos:
                    eventos.append(Evento.NEGACAO.value)
                dados.complemento = msg_bruto[:300]
                pergunta = ""
            elif re.search(r"\d+\s*h", msg) or "manha" in msg or "tarde" in msg:
                eventos = [e for e in eventos if e != Evento.OUTRO.value]
                if Evento.DADO_INFORMADO.value not in eventos:
                    eventos.append(Evento.DADO_INFORMADO.value)
                dados.turno_escolhido = "__INVALIDO__"
                pergunta = ""
            elif msg_confirma:
                eventos = [
                    e for e in eventos if e != Evento.CONFIRMACAO.value
                ]

    if not eventos:
        eventos = [Evento.OUTRO.value]

    # Pergunta hipotética / informativa ≠ pedido de trocar cobertura agora
    if eh_pergunta_mudanca_endereco(msg_bruto) or eh_pergunta_cobertura_informativa(msg_bruto):
        eventos = _suprimir_troca_localizacao_informativa(eventos, dados, msg_bruto, msg)
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        dados.cidade = ""
        dados.bairro = ""
        if not pergunta:
            pergunta = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()

    if eh_pergunta_instalacao(msg, msg_bruto):
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.PLANO_INFORMADO.value,
                Evento.PEDIU_TROCAR_PLANO.value,
                Evento.CONFIRMACAO.value,
            }
        ]
        dados.plano = ""
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        if not pergunta:
            pergunta = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()

    # Cadastro pausado — cliente quer trocar/ver plano (prioridade sobre coleta de dados)
    pausa_cadastro_plano = False
    if fase == "cadastro" and estado.get("tem_cobertura") is True:
        if (
            not eh_pergunta_informativa_sobre_plano(msg, msg_bruto)
            and not eh_pergunta_cancelamento(msg, msg_bruto)
            and not eh_pergunta_mudanca_endereco(msg_bruto)
            and not eh_pergunta_instalacao(msg, msg_bruto)
            and (
                eh_mensagem_sobre_planos(msg, msg_bruto)
                or Evento.PEDIU_TROCAR_PLANO.value in eventos
                or (
                    Evento.PLANO_INFORMADO.value in eventos
                    and bool(str(dados.plano or "").strip())
                    and not tem_duvida_informativa(msg, msg_bruto)
                )
                or any(k in msg for k in INTENCAO_PLANO_KEYWORDS)
            )
            and not duvida_no_cadastro
            and not eh_mensagem_correcao_cadastro(msg, msg_bruto)
        ):
            from app.plans import normalizar_referencia_plano

            pausa_cadastro_plano = True
            ref = normalizar_referencia_plano(dados.plano or msg_bruto)
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.DADO_INFORMADO.value,
                    Evento.PERGUNTA.value,
                    Evento.OUTRO.value,
                    Evento.CONFIRMACAO.value,
                }
            ]
            if Evento.PLANO_INFORMADO.value not in eventos:
                eventos.append(Evento.PLANO_INFORMADO.value)
            dados.plano = ref or msg_bruto[:160]
            for campo in (
                "rua", "numero", "cep", "nome", "cpf", "email", "telefone", "data_nascimento",
            ):
                setattr(dados, campo, "")
            pergunta = ""

    if (
        fase == "cadastro"
        and not eh_pergunta_instalacao(msg, msg_bruto)
        and not eh_pergunta_cancelamento(msg, msg_bruto)
        and (
            eh_mensagem_sobre_planos(msg, msg_bruto)
            or Evento.PEDIU_TROCAR_PLANO.value in eventos
            or (
                Evento.PLANO_INFORMADO.value in eventos
                and bool(str(dados.plano or "").strip())
                and not tem_duvida_informativa(msg, msg_bruto)
            )
        )
    ):
        for campo in ("rua", "numero", "cep", "nome", "cpf", "email", "telefone", "data_nascimento"):
            if campo != aguardando:
                setattr(dados, campo, "")

    # Nome e rua são texto livre: se o LLM leu a mensagem como conversa ("tá bom",
    # "pera aí", "não entendi") e não extraiu nada, não gravar a frase como dado.
    llm_leu_como_conversa = (
        aguardando in {"nome", "rua", "numero"}
        and bool(eventos_llm)
        and not llm_extraiu_dado
        and not (
            eventos_llm
            & {
                Evento.DADO_INFORMADO.value,
                Evento.CORRECAO_DADO.value,
                Evento.LOCALIZACAO_INFORMADA.value,
                Evento.PLANO_INFORMADO.value,
            }
        )
        and not _texto_livre_parece_dado(msg_bruto, aguardando, eventos_llm)
    )

    # Extração determinística do campo pendente (LLM falhou ou veio dado+pergunta)
    if (
        not pedido_encerrar
        and fase == "cadastro"
        and aguardando_cadastro
        and not pausa_cadastro_plano
        and not llm_leu_como_conversa
        and not eh_pergunta_informativa_sobre_plano(msg, msg_bruto)
    ):
        _aplicar_extracao_campo_pendente(
            aguardando,
            msg_bruto,
            msg,
            dados,
            eventos,
            nome_estado=str(estado.get("nome") or ""),
        )
        _limpar_ecos_estado(dados, estado, msg_bruto, aguardando)
        _sanitizar_ecos_cadastro(dados, msg_bruto, str(estado.get("nome") or ""))

    # Confirmação + dúvida na mesma mensagem — planos
    if aguardando_plano and tem_duvida_informativa(msg, msg_bruto):
        if msg_confirma or msg == "quero":
            pergunta_parte = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()
            pergunta_n = normalizar_texto(pergunta_parte)
            impede_confirmacao = (
                eh_pergunta_informativa_sobre_plano(pergunta_n, pergunta_parte)
                or eh_mensagem_sobre_planos(pergunta_n, pergunta_parte)
                or any(k in pergunta_n for k in INTENCAO_PLANO_KEYWORDS)
                or any(
                    k in pergunta_n
                    for k in (
                        "disney",
                        "mesh",
                        "roteador",
                        "inclui",
                        "tem ",
                        "tem?",
                        "mais barato",
                        "outro plano",
                        "outra opcao",
                    )
                )
                or (
                    tem_duvida_informativa(pergunta_n, pergunta_parte)
                    and not eh_pergunta_instalacao(pergunta_n, pergunta_parte)
                )
            )
            if impede_confirmacao:
                eventos = [e for e in eventos if e != Evento.CONFIRMACAO.value]
            elif Evento.CONFIRMACAO.value not in eventos:
                eventos.append(Evento.CONFIRMACAO.value)
            if Evento.PERGUNTA.value not in eventos:
                eventos.append(Evento.PERGUNTA.value)
            if not pergunta:
                pergunta = pergunta_parte
            dados.plano = ""

    # Confirmação + dúvida — agendamento
    if fase == "agendamento" and aguardando_agenda and tem_duvida_informativa(msg, msg_bruto):
        if msg_confirma:
            if Evento.CONFIRMACAO.value not in eventos:
                eventos.append(Evento.CONFIRMACAO.value)
            if Evento.PERGUNTA.value not in eventos:
                eventos.append(Evento.PERGUNTA.value)
            if not pergunta:
                pergunta = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()

    # Dado + pergunta — cadastro, agendamento, confirmação de dados
    tem_duvida = tem_duvida_informativa(
        msg,
        msg_bruto,
        aguardando=aguardando if fase == "cadastro" else None,
    )
    # "quero o primeiro horário" escolhe um horário — sem "?", não é dúvida
    if (
        fase == "agendamento"
        and texto(dados.turno_escolhido)
        and not dados.turno_escolhido.startswith("__")
        and "?" not in msg_bruto
    ):
        tem_duvida = False
        eventos = [e for e in eventos if e != Evento.PERGUNTA.value]
        pergunta = ""
    if tem_duvida and (
        (fase == "cadastro" and aguardando_cadastro)
        or (fase == "agendamento" and aguardando_agenda)
        or (fase == "cadastro" and aguardando == "confirmacao_dados")
    ):
        linhas = [ln.strip() for ln in msg_bruto.splitlines() if ln.strip()]
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        if not pergunta:
            pergunta = extrair_parte_pergunta(msg_bruto, msg)
            if not pergunta and len(linhas) >= 2:
                duvidas = [
                    ln for ln in linhas if tem_duvida_informativa(normalizar_texto(ln), ln)
                ]
                if duvidas:
                    pergunta = " ".join(duvidas)
        eventos = _suprimir_troca_localizacao_informativa(eventos, dados, msg_bruto, msg)

    # Fases avançadas: dúvida sem endereço novo ≠ troca de cobertura
    if fase in FASES_PROTEGIDAS_LOC and tem_duvida:
        eventos = _suprimir_troca_localizacao_informativa(eventos, dados, msg_bruto, msg)

    # Confirmação curta de horário — "certo", "ok", "si"
    if fase == "agendamento" and aguardando == "confirmacao_horario":
        if eh_ack_curto(msg_bruto) and Evento.DADO_INFORMADO.value not in eventos:
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.CONVERSA_SOCIAL.value,
                    Evento.OUTRO.value,
                    Evento.PERGUNTA.value,
                }
            ]
            if Evento.CONFIRMACAO.value not in eventos:
                eventos.append(Evento.CONFIRMACAO.value)
            pergunta = ""

    # "Entendi" / ack curto — retoma fluxo, não desvia (exceto confirmação de horário)
    elif (
        fase in {"cadastro", "agendamento", "pos_venda"}
        and msg in {"entendi", "ok entendi", "ta entendi", "certo", "ok", "blz", "beleza"}
        and Evento.DADO_INFORMADO.value not in eventos
        and not tem_duvida
        and not (fase == "agendamento" and aguardando == "confirmacao_horario")
    ):
        eventos = [e for e in eventos if e not in {Evento.PEDIU_TROCAR_LOCALIZACAO.value, Evento.OUTRO.value}]
        if Evento.CONVERSA_SOCIAL.value not in eventos:
            eventos.append(Evento.CONVERSA_SOCIAL.value)
        pergunta = ""

    # Dado puro anotado — remove PERGUNTA fantasma do LLM (ex.: nome classificado errado)
    if (
        not tem_duvida
        and not eh_pergunta_informativa_sobre_plano(msg, msg_bruto)
        and aguardando
        in {
            "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero"
        }
    ):
        valor_pendente = texto(getattr(dados, aguardando, ""))
        if valor_pendente and Evento.DADO_INFORMADO.value in eventos:
            eventos = [e for e in eventos if e not in {Evento.PERGUNTA.value, Evento.OUTRO.value}]
            pergunta = ""

    if Evento.CORRECAO_DADO.value in eventos or eh_mensagem_correcao_cadastro(msg, msg_bruto):
        eventos = [e for e in eventos if e not in {Evento.PERGUNTA.value, Evento.OUTRO.value}]
        pergunta = ""

    # Pergunta com "?" — LLM não deve marcar CONFIRMACAO ("pode instalar amanhã?")
    if (
        Evento.CONFIRMACAO.value in eventos
        and not msg_confirma
        and (tem_duvida or "?" in msg_bruto)
    ):
        eventos = [e for e in eventos if e != Evento.CONFIRMACAO.value]

    # LLM pode marcar CONFIRMACAO em pedido de promo/desconto ("quero um na promoção")
    if (
        Evento.CONFIRMACAO.value in eventos
        and aguardando_plano
        and (eh_pedido_plano_promocional(msg) or eh_pedido_planos_com_desconto(msg))
    ):
        eventos = [e for e in eventos if e != Evento.CONFIRMACAO.value]

    if dados.plano:
        from app.plans import normalizar_referencia_plano

        dados.plano = normalizar_referencia_plano(dados.plano) or dados.plano

    # Confirmação pura do plano — não deixar PLANO_INFORMADO/PERGUNTA fantasma do LLM
    if (
        aguardando_plano
        and msg_confirma
        and not eh_pedido_contratacao(msg, msg_bruto)
        and not tem_duvida_informativa(msg, msg_bruto)
        and not escolha_por_posicao
    ):
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.PERGUNTA.value,
                Evento.PLANO_INFORMADO.value,
                Evento.PEDIU_TROCAR_PLANO.value,
                Evento.OUTRO.value,
            }
        ]
        if Evento.CONFIRMACAO.value not in eventos:
            eventos.append(Evento.CONFIRMACAO.value)
        dados.plano = ""
        pergunta = ""

    from app.interpretacao_campo import aplicar_guards_interpretacao

    pergunta = aplicar_guards_interpretacao(
        dados=dados,
        eventos=eventos,
        pergunta=pergunta,
        estado=estado,
        msg=msg,
        msg_bruto=msg_bruto,
        aguardando=aguardando,
        fase=fase,
        campos_corrigidos=campos_corrigidos,
        confianca=confianca,
    )

    if (
        aguardando_plano
        and msg_confirma
        and not eh_pedido_contratacao(msg, msg_bruto)
        and not tem_duvida_informativa(msg, msg_bruto)
        and not escolha_por_posicao
    ):
        eventos = [
            e
            for e in eventos
            if e
            not in {
                Evento.PERGUNTA.value,
                Evento.PLANO_INFORMADO.value,
                Evento.PEDIU_TROCAR_PLANO.value,
                Evento.OUTRO.value,
            }
        ]
        if Evento.CONFIRMACAO.value not in eventos:
            eventos.append(Evento.CONFIRMACAO.value)
        dados.plano = ""
        pergunta = ""

    if (
        aguardando == "confirmacao_plano"
        and msg_confirma
        and not dados.nome
    ):
        nome_conf = _extrair_nome_apos_confirmacao(msg_bruto)
        if nome_conf:
            dados.nome = nome_conf
            if Evento.DADO_INFORMADO.value not in eventos:
                eventos.append(Evento.DADO_INFORMADO.value)

    if fase == "cadastro" and not pedido_encerrar and not pausa_cadastro_plano:
        _reconciliar_com_llm(
            dados=dados,
            dados_llm=dados_dict,
            eventos=eventos,
            campos_corrigidos=campos_corrigidos,
            corrigidos_llm=corrigidos_llm,
            estado=estado,
            aguardando=aguardando,
            msg_bruto=msg_bruto,
        )

    return Interpretacao(
        eventos=eventos,
        dados=dados,
        campos_corrigidos=campos_corrigidos,
        pergunta=pergunta,
        confianca=confianca,
    )
