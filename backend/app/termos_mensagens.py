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


def _corpo_cancelamento_multa(*, pergunta_valor: bool = False) -> str:
    intro = (
        "Sobre o valor da multa: ela é *proporcional* ao tempo que ainda faltava da fidelidade "
        "de 12 meses — não é o valor cheio do plano. O *valor exato* consta no contrato; "
        "a Eva não calcula esse valor aqui no chat."
        if pergunta_valor
        else (
            "Se você cancelar *antes dos 12 meses* de fidelidade, pode haver *multa proporcional* "
            "ao tempo que ainda faltava — não é o valor cheio do plano."
        )
    )
    return (
        f"{intro}\n\n"
        "Também é preciso *devolver os equipamentos* (roteador/repetidor) em bom estado.\n\n"
        "Para o valor preciso, nossa equipe detalha no contrato ou quando você solicitar."
    )


def explicar_cancelamento_termos() -> str:
    return (
        f"{_corpo_cancelamento_multa()}\n\n"
        "Para seguir com a contratação, confira o *áudio* e o *PDF* que enviei e me responda "
        "*aceito* ou *sim, aceito* que agendamos a instalação."
    )


def informar_cancelamento_e_retomar(
    *,
    pendente: str = "",
    campos_anotados: list[str] | None = None,
    pergunta_valor: bool = False,
) -> str:
    """Resposta fixa sobre cancelamento/multa — sem pedir dados irrelevantes para 'calcular'."""
    from app.vendas_mensagens import rotulo_pendente_cadastro

    partes: list[str] = []
    anotados = [c for c in (campos_anotados or []) if c and c != "cpf"]
    if anotados:
        rotulos = {
            "nome": "nome",
            "email": "e-mail",
            "telefone": "telefone",
            "data_nascimento": "data de nascimento",
            "cep": "CEP",
            "rua": "rua",
            "numero": "número",
        }
        itens = [rotulos.get(c, c) for c in anotados]
        if len(itens) == 1:
            partes.append(f"Anotei {itens[0]}.")
        elif len(itens) == 2:
            partes.append(f"Anotei {itens[0]} e {itens[1]}.")
        else:
            partes.append(f"Anotei {', '.join(itens[:-1])} e {itens[-1]}.")

    partes.append(_corpo_cancelamento_multa(pergunta_valor=pergunta_valor))

    retomada = rotulo_pendente_cadastro(pendente)
    if retomada:
        partes.append(retomada)
    else:
        partes.append("Se quiser, seguimos no passo em que paramos.")

    return "\n\n".join(partes)


def recusou_termos() -> str:
    return (
        "Entendo. Sem a aceitação do termo de fidelidade não consigo seguir com a "
        "contratação por aqui.\n\n"
        "Vou encaminhar para nossa equipe te ajudar, tudo bem?"
    )
