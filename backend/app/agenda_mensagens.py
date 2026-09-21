"""Mensagens fixas da fase de agendamento."""

from __future__ import annotations

from typing import Any

from app.agenda_resumo import montar_mensagem_horarios
from app.agenda_slots import horarios_disponiveis


def confirmar_horario_escolhido(horario: str, data: str) -> str:
    return (
        f"Perfeito! Anotei *{horario}* no dia *{data}*.\n\n"
        "Posso confirmar esse agendamento?"
    )


def horario_nao_disponivel(estado: dict[str, Any]) -> str:
    manha, tarde = horarios_disponiveis(estado)
    linhas = [
        "Esse horário não está entre as opções disponíveis.",
        "",
        "Por favor, escolha um destes:",
        "",
    ]
    if manha:
        linhas.append("🌅 Manhã")
        for h in manha:
            linhas.append(f"• {h}")
        linhas.append("")
    if tarde:
        linhas.append("🌇 Tarde")
        for h in tarde:
            linhas.append(f"• {h}")
        linhas.append("")
    linhas.append("Qual prefere?")
    return "\n".join(linhas)


def horario_ambiguo(turno: str, estado: dict[str, Any]) -> str:
    manha, tarde = horarios_disponiveis(estado)
    slots = manha if turno == "manha" else tarde if turno == "tarde" else manha + tarde
    titulo = "da manhã" if turno == "manha" else "da tarde" if turno == "tarde" else "disponíveis"
    linhas = [f"Temos mais de um horário {titulo}. Qual você prefere?", ""]
    for h in slots:
        linhas.append(f"• {h}")
    linhas.append("")
    linhas.append("Me diga o horário exato, por favor.")
    return "\n".join(linhas)


def explicar_horarios_unicos(estado: dict[str, Any], preferencia: str = "") -> str:
    data = str(estado.get("data_agendamento") or "").strip()
    pref = f"\n\nAnotei sua preferência: *{preferencia}*." if preferencia else ""
    return (
        f"Entendo! Para *{data}*, esses são os únicos horários com técnico disponível "
        f"na sua região.{pref}\n\n"
        "Você será *priorizado* no atendimento — nossa equipe faz o possível "
        "para encaixar o melhor horário.\n\n"
        "Se algum horário abaixo funcionar, me avise. Caso contrário, "
        "posso encaminhar para a equipe te ajudar pessoalmente."
    )


def agendamento_confirmado(horario: str, data: str, nome: str = "") -> str:
    saudacao = f"{nome}, " if nome else ""
    return (
        f"✅ {saudacao}agendamento confirmado!\n\n"
        f"📅 Data: *{data}*\n"
        f"🕐 Horário: *{horario}*\n\n"
        "Nossa equipe segue com os próximos passos da instalação. "
        "Qualquer dúvida, estou por aqui!"
    )


def pedir_horario_especifico(estado: dict[str, Any]) -> str:
    return (
        "Para agendar, escolha um horário *da lista abaixo* — "
        "pode mandar o intervalo (ex.: *16h às 17h*) ou só o início (ex.: *16*).\n\n"
        + retomar_escolha_horario(estado)
    )


def retomar_escolha_horario(estado: dict[str, Any]) -> str:
    agenda = {
        "data": estado.get("data_agendamento"),
        "manha": horarios_disponiveis(estado)[0],
        "tarde": horarios_disponiveis(estado)[1],
    }
    base = montar_mensagem_horarios(agenda)
    return base.replace("✅ Cadastro concluído com sucesso!\n\n", "")
