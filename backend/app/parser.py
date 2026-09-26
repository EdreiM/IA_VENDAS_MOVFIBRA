"""Parser determinístico — normaliza JSON e protege confirmações genéricas."""

from __future__ import annotations

import json
import re
from typing import Any

from app.models import CAMPOS_DADOS, Evento, Interpretacao, DadosExtraidos

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
)


# Palavras que identificam plano mesmo se o LLM errar (ordem: + antes do nome base)
PLANOS_MENCAO = [
    (r"\bsuper\s*\+", "SUPER+"),
    (r"\bup\s*\+", "UP+"),
    (r"\bone\s*\+|one\s+plus\b", "ONE+"),
    (r"\binfinity\b", "INFINITY"),
    (r"\bessencial\b", "ESSENCIAL"),
    (r"\bcombo.*12\s*gb|12\s*gb", "COMBO TOTAL 12GB"),
    (r"\bcombo.*22\s*gb|22\s*gb", "COMBO TOTAL 22GB"),
    (r"\bcombo\b", "COMBO"),
    (r"\b(?:mov\s+)?super\b", "SUPER"),
]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _extrair_email(bruto: str) -> str:
    s = (bruto or "").strip()
    # Remove prefixos comuns em mensagens partidas ("é erei teste @gmail.com")
    s = re.sub(r"^(?:meu\s+)?(?:e-?mail|email)\s*(?:é|e|eh|:|-)?\s*", "", s, flags=re.I)
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
    return len(n) in {11, 14}


def _extrair_cpf(msg: str, bruto: str = "") -> str:
    n = _somente_digitos(bruto or msg)
    if len(n) in {11, 14}:
        return n
    return ""


def _detectar_plano_na_mensagem(msg: str) -> str:
    """Retorna referência de plano se a mensagem citar um plano conhecido."""
    for padrao, rotulo in PLANOS_MENCAO:
        if re.search(padrao, msg):
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


def cliente_confirmou_ver_planos_desconto(msg: str, ultima_eva: str) -> bool:
    """'Sim' após Eva oferecer mostrar planos com desconto."""
    if not eh_confirmacao(msg):
        return False
    u = normalizar_texto(ultima_eva)
    if not u:
        return False
    return any(
        p in u
        for p in (
            "planos com desconto",
            "planos com esse beneficio",
            "mostrar os planos com",
            "te mostro os planos",
            "mostro os planos com",
            "desconto de pontualidade",
            "beneficio de pontualidade",
        )
    )


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
    if t in CONFIRMACOES_GENERICAS:
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
    # "pode instalar amanhã?" / "isso inclui wifi?" — pergunta, não confirmação
    if "?" in bruto:
        return False
    primeira = t.split()[0] if t.split() else ""
    return primeira in {"sim", "ta", "confirmo", "ok", "blz", "beleza", "fechado", "fechou"}


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
    primeira = t.split()[0] if t.split() else ""
    return primeira in {"nao", "não", "negativo"}


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
    digitos = re.sub(r"\D", "", principal)
    return digitos if len(digitos) == 8 else ""


def _extrair_data_nascimento(bruto: str) -> str:
    principal = _parte_principal_dado(bruto)
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", principal)
    if not m:
        return ""
    d, mes, ano = m.group(1), m.group(2), m.group(3)
    if len(ano) == 2:
        ano = f"19{ano}" if int(ano) > 30 else f"20{ano}"
    return f"{int(d):02d}/{int(mes):02d}/{ano}"


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
    return "".join(m.groups())


def _extrair_nome_livre(bruto: str) -> str:
    t = _strip_trailing_question_mark(_parte_principal_dado(bruto))
    t = re.sub(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)", " ", t)
    t = re.sub(r"(?i)\b(?:cpf|cnpj|nome)\b[:\s]*", " ", t)
    t = re.sub(r"[,;]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    if not t or "@" in t:
        return ""
    partes = [p for p in t.split() if re.search(r"[A-Za-zÀ-ÿ]", p) and not re.search(r"\d", p)]
    if len(partes) >= 2:
        return " ".join(partes)[:120]
    if len(partes) == 1:
        unico = partes[0]
        bloqueio = {
            "sim", "nao", "ok", "quero", "certo", "blz", "beleza", "obrigado",
            "obrigada", "valeu", "entendi", "pode", "isso", "esse", "essa",
        }
        if len(unico) >= 2 and normalizar_texto(unico) not in bloqueio:
            return unico[:120]
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
    "taxa",
)


def eh_mensagem_sobre_planos(msg: str, msg_bruto: str = "") -> bool:
    t = normalizar_texto(msg_bruto or msg)
    if not t:
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

    par = set(par_de(aguardando))
    duvida = tem_duvida_informativa(msg, msg_bruto, aguardando=aguardando)
    bruto = msg_bruto
    segmentos = _segmentos_mensagem(bruto)

    if "nome" in campos_alvo and not dados.nome and not duvida and not _mensagem_e_apenas_cpf(bruto):
        nome = _extrair_nome_livre(bruto)
        if nome:
            dados.nome = nome
    if "cpf" in campos_alvo and not dados.cpf:
        cpf = _extrair_cpf_embutido(bruto)
        if cpf:
            dados.cpf = cpf
    if "email" in campos_alvo and not dados.email:
        for seg in segmentos + [bruto]:
            email = _extrair_email(seg)
            if email:
                dados.email = email
                break
    if "telefone" in campos_alvo and not dados.telefone:
        tel = _extrair_telefone_em_segmentos(bruto)
        if tel:
            dados.telefone = tel
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


def tem_duvida_informativa(
    msg: str,
    msg_bruto: str = "",
    *,
    aguardando: str | None = None,
) -> bool:
    bruto = texto(msg_bruto or msg)
    partes_sep = re.split(
        r"(?i)\s+(?:mas|porem|porém|e se|so que|só que)\s+",
        bruto,
        maxsplit=1,
    )
    if len(partes_sep) >= 2:
        parte_duvida = partes_sep[1]
        t_duvida = normalizar_texto(parte_duvida)
        if "?" in parte_duvida or any(k in t_duvida for k in CHAVES_DUVIDA_INFORMATIVA):
            return True
        bruto = partes_sep[0]
    t = normalizar_texto(bruto)
    if aguardando and bruto.rstrip().endswith("?"):
        if _texto_parece_apenas_dado_cadastro(bruto, aguardando):
            sem_q = _strip_trailing_question_mark(bruto)
            if not any(k in normalizar_texto(sem_q) for k in CHAVES_DUVIDA_INFORMATIVA):
                return False
    if "?" in bruto:
        return True
    return any(k in t for k in CHAVES_DUVIDA_INFORMATIVA)


def eh_pergunta_detalhe_plano(msg: str, msg_bruto: str = "") -> bool:
    t = normalizar_texto(msg_bruto or msg)
    return any(p in t for p in PERGUNTAS_DETALHE_PLANO)


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
    if not t or not _precos_na_mensagem(t):
        return False
    if eh_confirmacao(t):
        return False
    if re.match(r"^(quero|queria|preciso|gostaria|vou de|fecho com|fico com)\b", t):
        return False
    if "?" in bruto or t.startswith("qual ") or t.startswith("quais "):
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
    if eh_pergunta_custo_instalacao(msg, msg_bruto):
        return True
    if (topico or "").strip().casefold() == "instalacao":
        return True
    t = normalizar_texto(msg_bruto or msg)
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


def parse_interpretacao(raw: str, mensagem_cliente: str, estado: dict[str, Any]) -> Interpretacao:
    try:
        data = json.loads(_strip_markdown(raw))
    except json.JSONDecodeError:
        return Interpretacao(eventos=[Evento.OUTRO.value], confianca=0)

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

    # CPF/CNPJ — só forçar extração quando estivermos pedindo CPF (evita confundir em vendas/perguntas)
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
        dados.plano = ""
        campos_corrigidos = []
        pergunta = ""

    elif msg in REPETICAO_DADO and aguardando_cadastro:
        # "já disse" — reutiliza dado que já está no estado
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

    if aguardando_plano and (eh_confirmacao(msg) or msg == "quero"):
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

    if pode_trocar_plano and (
        msg in PEDIDOS_ALTERNATIVA or any(p in msg for p in PEDIDOS_ALTERNATIVA if len(p) >= 8)
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
            or (fase == "cadastro" and estado.get("plano_confirmado"))
        )
        and any(k in msg for k in INTENCAO_PLANO_KEYWORDS)
        and msg not in CONFIRMACOES_GENERICAS
        and not eh_confirmacao(msg)
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
    if fase == "cadastro" and aguardando == "confirmacao_dados" and not eh_confirmacao(msg):
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
    if fase == "cadastro" and aguardando == "confirmacao_dados" and eh_confirmacao(msg):
        eventos = [e for e in eventos if e not in {Evento.NEGACAO.value, Evento.PEDIU_TROCAR_PLANO.value}]
        if Evento.CONFIRMACAO.value not in eventos:
            eventos.append(Evento.CONFIRMACAO.value)
        if tem_duvida_informativa(msg, msg_bruto):
            if Evento.PERGUNTA.value not in eventos:
                eventos.append(Evento.PERGUNTA.value)
            if not pergunta:
                pergunta = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()
        else:
            # "Sim" / "tá certo" não regrava o cadastro que o modelo ecoou
            pergunta = ""
            eventos = [
                e
                for e in eventos
                if e
                not in {
                    Evento.PERGUNTA.value,
                    Evento.DADO_INFORMADO.value,
                    Evento.CORRECAO_DADO.value,
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
    if plano_detectado:
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

    # "O que tem no SUPER+?" / "Qual o de 69,50?" — PERGUNTA (não escolha de plano)
    if (aguardando_plano or fase == "vendas") and (
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
    if fase == "cadastro":
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

    # Pós-venda — "não", "obrigado", "pode encerrar" ≠ dúvida
    if fase == "pos_venda" and aguardando == "duvidas":
        from app.pos_venda_mensagens import mensagem_sem_duvidas

        if mensagem_sem_duvidas(msg) or eh_recusa(msg):
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
        if eh_aceite_termos_explicito(msg) or eh_confirmacao(msg):
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
            if eh_confirmacao(msg):
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
            if pediu_outro_horario(msg):
                eventos = [e for e in eventos if e not in {Evento.CONFIRMACAO.value, Evento.OUTRO.value}]
                if Evento.NEGACAO.value not in eventos:
                    eventos.append(Evento.NEGACAO.value)
                dados.complemento = msg_bruto[:300]
                pergunta = ""
            else:
                resultado = match_horario(msg_bruto, estado)
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
                elif re.search(r"\d+\s*h", msg) or "manha" in msg or "tarde" in msg:
                    eventos = [e for e in eventos if e != Evento.OUTRO.value]
                    if Evento.DADO_INFORMADO.value not in eventos:
                        eventos.append(Evento.DADO_INFORMADO.value)
                    dados.turno_escolhido = "__INVALIDO__"
                    pergunta = ""
                elif eh_confirmacao(msg):
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
        if Evento.PERGUNTA.value not in eventos:
            eventos.append(Evento.PERGUNTA.value)
        if not pergunta:
            pergunta = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()

    if fase == "cadastro" and (
        eh_mensagem_sobre_planos(msg, msg_bruto)
        or Evento.PEDIU_TROCAR_PLANO.value in eventos
        or Evento.PLANO_INFORMADO.value in eventos
    ):
        for campo in ("rua", "numero", "cep", "nome", "cpf", "email", "telefone", "data_nascimento"):
            if campo != aguardando:
                setattr(dados, campo, "")

    # Extração determinística do campo pendente (LLM falhou ou veio dado+pergunta)
    if fase == "cadastro" and aguardando_cadastro:
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
        if eh_confirmacao(msg) or msg == "quero":
            if Evento.CONFIRMACAO.value not in eventos:
                eventos.append(Evento.CONFIRMACAO.value)
            if Evento.PERGUNTA.value not in eventos:
                eventos.append(Evento.PERGUNTA.value)
            if not pergunta:
                pergunta = extrair_parte_pergunta(msg_bruto, msg) or msg_bruto.strip()
            dados.plano = ""

    # Confirmação + dúvida — agendamento
    if fase == "agendamento" and aguardando_agenda and tem_duvida_informativa(msg, msg_bruto):
        if eh_confirmacao(msg):
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

    # "Entendi" / ack curto — retoma fluxo, não desvia
    if (
        fase in {"cadastro", "agendamento", "pos_venda"}
        and msg in {"entendi", "ok entendi", "ta entendi", "certo", "ok", "blz", "beleza"}
        and Evento.DADO_INFORMADO.value not in eventos
        and not tem_duvida
    ):
        eventos = [e for e in eventos if e not in {Evento.PEDIU_TROCAR_LOCALIZACAO.value, Evento.OUTRO.value}]
        if Evento.CONVERSA_SOCIAL.value not in eventos:
            eventos.append(Evento.CONVERSA_SOCIAL.value)
        pergunta = ""

    # Dado puro anotado — remove PERGUNTA fantasma do LLM (ex.: nome classificado errado)
    if not tem_duvida and aguardando in {
        "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero"
    }:
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
        and not eh_confirmacao(msg)
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

    return Interpretacao(
        eventos=eventos,
        dados=dados,
        campos_corrigidos=campos_corrigidos,
        pergunta=pergunta,
        confianca=confianca,
    )
