"""Mensagens de follow-up por inatividade — contextualizadas por fase/pendente."""

from __future__ import annotations

from typing import Any


def _nome_curto(estado: dict[str, Any]) -> str:
    nome = str(estado.get("nome") or "").strip()
    if not nome:
        return ""
    return nome.split()[0]


def _plano_label(estado: dict[str, Any]) -> str:
    return str(
        estado.get("plano_confirmado")
        or estado.get("plano_em_negociacao")
        or estado.get("plano_apresentado")
        or "seu plano"
    ).strip()


def _retomada_pendente(estado: dict[str, Any]) -> str:
    from app.saudacao import mensagem_cumprimento_retomar

    pendente = str(estado.get("aguardando") or "").strip()
    if pendente:
        # Reutiliza mapa humano da retomada de cumprimento (sem cumprimento duplo)
        partes = mensagem_cumprimento_retomar("oi", pendente).split("\n\n", 1)
        if len(partes) == 2:
            return partes[1].strip()
    fase = str(estado.get("fase") or "").strip()
    if fase == "vendas":
        return f"Quer seguir com o *{_plano_label(estado)}* ou prefere ver outras opções?"
    if fase == "cadastro":
        return "Posso continuar seu cadastro por aqui — me manda os dados que faltam."
    if fase == "termos":
        return "Quando puder, confira o áudio e o PDF do termo e me responda *aceito* ou *sim*."
    if fase == "agendamento":
        return "Qual horário de instalação fica melhor pra você?"
    if fase == "viabilidade":
        from app.saudacao import texto_pedir_localizacao_instalacao

        return texto_pedir_localizacao_instalacao(compacto=True)
    return "Como posso te ajudar a continuar?"


def mensagem_followup_inatividade(estado: dict[str, Any], tentativa: int) -> str:
    """
    tentativa: 1, 2 ou 3 (número da chamada de follow-up, não followup_count).
    """
    nome = _nome_curto(estado)
    retoma = _retomada_pendente(estado)
    plano = _plano_label(estado)
    fase = str(estado.get("fase") or "").strip()
    pendente = str(estado.get("aguardando") or "").strip()

    saudacao = f"Oi{', ' + nome if nome else ''}!" if tentativa == 1 else ""
    if tentativa == 1:
        corpo = (
            f"Ainda está por aí? Sem pressa — só quero te ajudar a continuar.\n\n"
            f"{retoma}"
        )
    elif tentativa == 2:
        extras = ""
        if fase == "vendas" and pendente in {"confirmacao_plano", "escolha_plano", "lista_planos"}:
            extras = f"\n\nO *{plano}* continua disponível pra você."
        elif fase == "cadastro" and pendente == "confirmacao_dados":
            extras = "\n\nSe estiver tudo certo nos dados, me confirma com *sim* ou *tá*."
        corpo = (
            f"Passando pra retomar nosso papo{(' sobre o ' + plano) if fase == 'vendas' else ''}.\n\n"
            f"{retoma}{extras}"
        )
    else:
        corpo = (
            "Última chamada por aqui 🙂 Se não puder responder agora, vou encerrar o atendimento "
            "automático em breve — mas quando quiser, é só mandar mensagem de novo.\n\n"
            f"{retoma}"
        )

    if saudacao:
        return f"{saudacao}\n\n{corpo}"
    return corpo


def mensagem_encerramento_inatividade(estado: dict[str, Any]) -> str:
    from app.pos_venda_mensagens import despedida_encerramento

    nome = _nome_curto(estado)
    intro = (
        f"Como não tive retorno{(', ' + nome) if nome else ''}, vou encerrar o atendimento por aqui por enquanto."
    )
    return f"{intro}\n\n{despedida_encerramento(str(estado.get('nome') or ''))}"
