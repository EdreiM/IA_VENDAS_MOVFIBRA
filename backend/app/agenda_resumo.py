"""Mensagem formatada com horários de instalação."""

from __future__ import annotations

from typing import Any


def montar_mensagem_horarios(agenda: dict[str, Any]) -> str:
    data = str(agenda.get("data") or "").strip()
    manha = [str(h).strip() for h in (agenda.get("manha") or []) if str(h).strip()]
    tarde = [str(h).strip() for h in (agenda.get("tarde") or []) if str(h).strip()]

    linhas = [
        "✅ Cadastro concluído com sucesso!",
        "",
        f"📅 Horários disponíveis para instalação em *{data}*:",
        "",
    ]

    if manha:
        linhas.append("🌅 *Manhã*")
        for h in manha:
            linhas.append(f"• {h}")
        linhas.append("")

    if tarde:
        linhas.append("🌇 *Tarde*")
        for h in tarde:
            linhas.append(f"• {h}")
        linhas.append("")

    linhas.append("Qual horário você prefere?")
    return "\n".join(linhas)
