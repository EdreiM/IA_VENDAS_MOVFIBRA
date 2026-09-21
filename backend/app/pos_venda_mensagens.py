"""Mensagens da fase pós-venda / encerramento."""

from __future__ import annotations


def mensagem_sem_duvidas(msg: str) -> bool:
    """Cliente não tem mais dúvidas ou quer encerrar."""
    t = " ".join(str(msg or "").strip().casefold().split())
    if not t:
        return False
    frases = (
        "nao",
        "não",
        "nops",
        "nop",
        "negativo",
        "sem duvida",
        "sem dúvida",
        "sem duvidas",
        "sem dúvidas",
        "nao tenho",
        "não tenho",
        "nao preciso",
        "não preciso",
        "tudo certo",
        "tudo ok",
        "tudo bem",
        "por enquanto nao",
        "por enquanto não",
        "e so isso",
        "é só isso",
        "so isso",
        "só isso",
        "pode encerrar",
        "pode finalizar",
        "pode fechar",
        "obrigado",
        "obrigada",
        "valeu",
        "vlw",
        "tchau",
        "ate logo",
        "até logo",
        "ate mais",
        "até mais",
        "encerrar",
        "finalizar",
        "nao mais",
        "não mais",
        "nao obrigado",
        "não obrigado",
        "nao, obrigado",
        "não, obrigado",
    )
    if t in frases:
        return True
    return any(f in t for f in frases if len(f) > 3)


def pedir_duvidas_apos_agendamento(
    horario: str = "",
    data: str = "",
    nome: str = "",
) -> str:
    saudacao = f"{nome.split()[0]}, " if nome.strip() else ""
    bloco = ""
    if data or horario:
        bloco = (
            f"\n📅 Data: *{data or '—'}*\n"
            f"🕐 Horário: *{horario or '—'}*\n"
        )
    return (
        f"✅ {saudacao}agendamento confirmado!{bloco}\n"
        "Nossa equipe segue com os próximos passos da instalação.\n\n"
        "Antes de encerrar, *tem mais alguma dúvida?*"
    )


def pedir_falar_duvida() -> str:
    return "Claro! Pode perguntar — estou aqui pra ajudar."


def retomar_duvidas() -> str:
    return "\n\nMais alguma dúvida antes de encerrar?"


def despedida_encerramento(nome: str = "") -> str:
    primeiro = nome.split()[0] if nome.strip() else ""
    quem = f", {primeiro}" if primeiro else ""
    return (
        f"Perfeito{quem}! Foi um prazer te atender.\n\n"
        "Se precisar de algo depois, é só chamar. "
        "Boa instalação e até breve! 👋"
    )
