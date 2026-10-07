"""Mensagens da fase de termos / fidelidade."""

from __future__ import annotations


def pedir_aceite_termos(
    *,
    termos_enviados: bool = False,
    parcial: bool = False,
    pedir_aceite_explicito: bool = False,
    termos_mock: bool = False,
) -> str:
    if pedir_aceite_explicito:
        return (
            "Para seguir, preciso do seu *aceite explícito* ao termo de fidelidade "
            "que enviei (áudio + PDF).\n\n"
            "Me responda *aceito* ou *sim, aceito* quando estiver de acordo."
        )
    if parcial:
        intro = (
            "Tive uma dificuldade para enviar tudo agora, mas segue o que consegui encaminhar.\n\n"
        )
    elif termos_enviados:
        intro = (
            "Acabei de enviar o *áudio* e o *termo de fidelidade* aqui no chat.\n\n"
        )
    elif termos_mock:
        intro = (
            "Cadastro confirmado! Em produção, o *áudio* e o *PDF* do termo chegam "
            "automaticamente aqui no chat.\n\n"
        )
    else:
        intro = (
            "Vou te encaminhar o *áudio* e o *termo de fidelidade* por aqui.\n\n"
        )

    return (
        f"{intro}"
        "Dá uma olhada com calma — são as condições de fidelidade do plano.\n\n"
        "Se estiver de acordo, me responda *sim* ou *aceito* que seguimos para o "
        "*agendamento da instalação*."
    )


def recusou_termos() -> str:
    return (
        "Entendo. Sem a aceitação do termo de fidelidade não consigo seguir com a "
        "contratação por aqui.\n\n"
        "Vou encaminhar para nossa equipe te ajudar, tudo bem?"
    )
