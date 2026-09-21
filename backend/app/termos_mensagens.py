"""Mensagens da fase de termos / fidelidade."""

from __future__ import annotations


def pedir_aceite_termos(
    *,
    termos_enviados: bool = True,
    parcial: bool = False,
    pedir_aceite_explicito: bool = False,
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
    else:
        intro = ""

    return (
        f"{intro}"
        "Dá uma olhada com calma — são as condições de fidelidade do plano.\n\n"
        "Se estiver de acordo, me responda *sim* ou *aceito* que seguimos para o "
        "*agendamento da instalação*."
    )


def explicar_cancelamento_termos() -> str:
    return (
        "Se você cancelar *antes dos 12 meses* de fidelidade, pode haver *multa proporcional* "
        "ao tempo que ainda faltava — não é o valor cheio do plano.\n\n"
        "Também é preciso *devolver os equipamentos* (roteador/repetidor) em bom estado.\n\n"
        "O valor exato da multa consta no contrato; nossa equipe detalha se você precisar.\n\n"
        "Para seguir com a contratação, confira o *áudio* e o *PDF* que enviei e me responda "
        "*aceito* ou *sim, aceito* que agendamos a instalação."
    )


def recusou_termos() -> str:
    return (
        "Entendo. Sem a aceitação do termo de fidelidade não consigo seguir com a "
        "contratação por aqui.\n\n"
        "Vou encaminhar para nossa equipe te ajudar, tudo bem?"
    )
