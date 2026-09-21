"""Cumprimentos naturais — espelha o tom do cliente."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from app.parser import normalizar_texto


def _periodo_pelo_relogio() -> str:
    """Fallback quando o cliente não disse bom dia/tarde/noite."""
    try:
        agora = datetime.now(ZoneInfo("America/Manaus"))
    except Exception:  # noqa: BLE001
        agora = datetime.now()
    h = agora.hour
    if 5 <= h < 12:
        return "bom_dia"
    if 12 <= h < 18:
        return "boa_tarde"
    return "boa_noite"


def detectar_saudacao(mensagem: str) -> str:
    """
    Retorna: bom_dia | boa_tarde | boa_noite | oi | padrao
    Prioridade: período explícito > oi/olá > padrão.
    """
    msg = normalizar_texto(mensagem or "")
    if not msg:
        return "padrao"
    if re.search(r"\bboa\s+noite\b", msg):
        return "boa_noite"
    if re.search(r"\bboa\s+tarde\b", msg):
        return "boa_tarde"
    if re.search(r"\bbom\s+dia\b", msg):
        return "bom_dia"
    if re.search(r"\b(oi+|ola|eai|eae|hey|hello|hia?)\b", msg):
        return "oi"
    return "padrao"


def frase_cumprimento(mensagem: str, *, usar_relogio_se_padrao: bool = True) -> str:
    """Uma linha de cumprimento alinhada ao cliente."""
    tipo = detectar_saudacao(mensagem)
    if tipo == "padrao" and usar_relogio_se_padrao:
        tipo = _periodo_pelo_relogio()

    if tipo == "bom_dia":
        return "Bom dia! Tudo bem?"
    if tipo == "boa_tarde":
        return "Boa tarde! Tudo bem?"
    if tipo == "boa_noite":
        return "Boa noite! Tudo bem?"
    # oi / padrao sem relógio
    return "Olá! Tudo bem?"


def mensagem_abertura(mensagem_cliente: str = "", *, quer_planos: bool = False) -> str:
    """Primeira mensagem: cumprimento + apresentação + cidade/bairro."""
    from app import ia_config

    nome = ia_config.resolver_nome_ia()
    cumprimento = frase_cumprimento(mensagem_cliente, usar_relogio_se_padrao=True)
    if quer_planos:
        return (
            f"{cumprimento} Sou a *{nome}*, atendente virtual da *MOV FIBRA*.\n\n"
            "Claro! Pra eu te mostrar os planos da sua região, "
            "me passa sua *cidade* e *bairro*?"
        )
    return (
        f"{cumprimento} Sou a *{nome}*, atendente virtual da *MOV FIBRA*.\n\n"
        "Para eu te atender melhor, me passa sua *cidade* e *bairro*?"
    )


def mensagem_pedir_local_para_planos() -> str:
    return (
        "Claro! Pra te mostrar os planos certos da sua região, "
        "me passa sua *cidade* e *bairro*."
    )


def mensagem_cumprimento_retomar(mensagem_cliente: str, pendente: str = "") -> str:
    """Cliente cumprimenta no meio do fluxo — responde na altura e retoma."""
    # No meio da conversa, "oi" → Olá; se não houver saudação clara, ainda responde leve
    tipo = detectar_saudacao(mensagem_cliente)
    if tipo == "padrao":
        cumprimento = "Olá!"
    else:
        cumprimento = frase_cumprimento(mensagem_cliente, usar_relogio_se_padrao=False)

    retomadas = {
        "localizacao": "Me passa sua *cidade* e *bairro* pra eu seguir?",
        "confirmacao_plano": "Quer confirmar o plano que te indiquei?",
        "escolha_plano": "Qual plano você prefere?",
        "lista_planos": "Qual plano você prefere?",
        "nome": "Me passa seu *nome completo* e o *CPF*? Pode ser na mesma mensagem.",
        "cpf": "Me envia seu *CPF*?",
        "email": "Qual o seu *e-mail*?",
        "telefone": "Qual o seu *telefone com DDD*?",
        "data_nascimento": "Qual a sua *data de nascimento*?",
        "cep": "Qual o *CEP*?",
        "rua": "Qual o nome da *rua*?",
        "numero": "Qual o *número* do endereço?",
        "confirmacao_dados": "Os dados estão corretos?",
        "escolha_horario": "Qual horário de instalação fica melhor pra você?",
        "confirmacao_horario": "Posso confirmar esse horário?",
        "duvidas": "Ficou alguma dúvida?",
    }
    retoma = retomadas.get(pendente or "", "Como posso te ajudar?")
    return f"{cumprimento}\n\n{retoma}"
