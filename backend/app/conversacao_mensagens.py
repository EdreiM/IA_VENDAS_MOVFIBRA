"""Mensagens de conversa — clarificação e retomada natural."""

from __future__ import annotations

from typing import Any

from app.cadastro_mensagens import ROTULO_CAMPO


def clarificar_intencao(ctx: dict[str, Any]) -> str:
    """Pede esclarecimento quando a interpretação está incerta."""
    motivo = str(ctx.get("motivo") or "outro").casefold()
    pendente = str(ctx.get("pendente") or "").strip()
    rotulo = ROTULO_CAMPO.get(pendente, pendente.replace("_", " "))

    if motivo == "cadastro_incerto" and rotulo:
        return (
            f"Só pra eu não anotar errado 😊 "
            f"Você quis me passar *{rotulo}* ou estava com alguma dúvida?"
        )

    if motivo == "plano_incerto":
        return (
            "Quero te ajudar certinho! "
            "Você está *escolhendo ou trocando de plano*, ou só quer *tirar uma dúvida*?"
        )

    if motivo == "ambiguo" and rotulo:
        return (
            f"Entendi parte da mensagem, mas quero confirmar: "
            f"você quer me informar *{rotulo}* ou prefere *tirar uma dúvida* primeiro?"
        )

    if rotulo:
        return (
            f"Desculpa, não entendi direito 😅 "
            f"Você pode reformular? Se for sobre *{rotulo}*, pode mandar de novo."
        )

    return (
        "Desculpa, não entendi direito 😅 "
        "Pode me explicar de outro jeito? "
        "Se for sobre planos, cadastro ou instalação, eu te ajudo."
    )
