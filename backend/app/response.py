"""Geração da mensagem final — LLM só escreve texto."""

from __future__ import annotations

from typing import Any

from app.agenda_mensagens import (
    agendamento_confirmado,
    confirmar_horario_escolhido,
    explicar_horarios_unicos,
    horario_ambiguo,
    horario_nao_disponivel,
    pedir_horario_especifico,
    retomar_escolha_horario,
)
from app.agenda_resumo import montar_mensagem_horarios
from app.cadastro_resumo import montar_resumo_cadastro
from app.cadastro_mensagens import anotar_e_pedir_proximo, confirmar_plano_e_avancar, pedir_campo
from app.termos_mensagens import (
    explicar_cancelamento_termos,
    pedir_aceite_termos,
    recusou_termos,
)
from app.pos_venda_mensagens import (
    despedida_encerramento,
    pedir_duvidas_apos_agendamento,
    pedir_falar_duvida,
    retomar_duvidas,
)
from app.saudacao import (
    mensagem_abertura,
    mensagem_cumprimento_retomar,
    mensagem_pedir_local_para_planos,
)
from app.vendas_mensagens import (
    apresentar_lista_completa_planos,
    apresentar_plano_inicial,
    apresentar_planos_como_sugestao,
    confirmar_plano_escolhido,
    esclarecer_plano_ambiguo,
    esclarecer_promocao_plano,
    identificar_plano_por_preco,
    informar_detalhes_plano,
    informar_plano_nao_encontrado,
    informar_planos_por_beneficio,
    informar_preco_plano,
    informar_precos_planos,
    informar_sem_cobertura,
    insistencia_sem_cobertura,
    planos_citados_no_texto,
    responder_sem_base_rag,
    transferir_apos_insistencia,
)
from app.llm import chat
from app.models import Decisao
from app.parser import normalizar_texto
from app.rag import formatar_contexto_rag

SYSTEM = """Você é {nome_ia}, atendente comercial da MOV FIBRA no WhatsApp.

Seu nome é {nome_ia}. Se perguntarem quem você é, diga que é a {nome_ia}, atendente virtual da MOV FIBRA.
Tom de voz: {tom_voz}.
{emoji_rule}
Você só escreve a mensagem ao cliente. A lógica do atendimento já foi decidida.
Não invente preço, plano, benefício ou cobertura.
Não mencione fase, JSON, sistema interno, mock, IXC ou "objetivo".
Nunca repita textos técnicos na mensagem.
Estilo:
- Português do Brasil, natural e humano — como uma pessoa educada e objetiva
- Frases curtas, como WhatsApp (1 a 3 frases na maioria das vezes)
- Confirme o que o cliente acabou de dizer antes de pedir o próximo passo
- Não pareça menu, formulário, FAQ ou robô (evite "Opção 1", "Digite sim ou não", listas numeradas longas)
- Varie um pouco as aberturas; não use sempre a mesma frase-clichê
- Não se apresente de novo se cumprimento_feito=true
- Se houver correção, diga que atualizou sem drama
- Gere SOMENTE a mensagem ao cliente
"""


def _system_prompt() -> str:
    from app import ia_config

    nome = ia_config.resolver_nome_ia()
    tom = ia_config._cfg("tom_voz", "Calorosa, simpática, objetiva")
    pode = ia_config._cfg("pode_emoji", "1") in ("1", "true", "True", "sim")
    emoji_rule = (
        "Pode usar no máximo 1 emoji, só se encaixar de leve."
        if pode
        else "Não use emojis nas respostas."
    )
    return SYSTEM.format(nome_ia=nome, tom_voz=tom or "profissional e acolhedora", emoji_rule=emoji_rule)


def _fmt_money(valor: Any) -> str:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return ""
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _plano_do_estado(estado: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Monta dict do plano em foco com preço (catálogo), para nunca omitir valor."""
    ctx = ctx or {}
    plano = ctx.get("plano") or ctx.get("plano_sugerido") or {}
    if (
        isinstance(plano, dict)
        and (plano.get("valor") or plano.get("valor_pontualidade"))
        and (plano.get("beneficios") or plano.get("descricao") or plano.get("dispositivos_max"))
    ):
        return plano

    from app.plans_catalog import listar_planos

    planos = listar_planos(estado)
    pid = (
        (plano.get("id") if isinstance(plano, dict) else None)
        or estado.get("plano_em_negociacao_id")
        or estado.get("plano_apresentado_id")
        or estado.get("plano_confirmado_id")
    )
    if pid is not None:
        for p in planos:
            if int(p.get("id") or -1) == int(pid):
                return p

    nome = (
        (plano.get("nome") if isinstance(plano, dict) else None)
        or estado.get("plano_em_negociacao")
        or estado.get("plano_apresentado")
        or estado.get("plano_confirmado")
        or ""
    )
    if nome:
        alvo = str(nome).casefold()
        for p in planos:
            if str(p.get("nome") or "").casefold() == alvo:
                return p
    return plano if isinstance(plano, dict) else {}


def _rotulo_pendente(pendente: str | None) -> str:
    mapa = {
        "localizacao": "cidade e bairro",
        "nome": "nome completo",
        "cpf": "CPF",
        "email": "e-mail",
        "telefone": "telefone com DDD",
        "data_nascimento": "data de nascimento (dd/mm/aaaa)",
        "cep": "CEP",
        "rua": "nome da rua",
        "numero": "número da casa ou apartamento",
        "confirmacao_dados": "confirmação dos dados",
        "escolha_horario": "escolha do horário de instalação",
        "confirmacao_plano": "confirmação do plano",
        "escolha_plano": "escolha de plano",
        "lista_planos": "escolha de plano",
        "plano": "confirmação/escolha de plano",
    }
    if not pendente:
        return ""
    return mapa.get(pendente, pendente)


def gerar_resposta(
    decisao: Decisao,
    estado: dict[str, Any],
    *,
    origem: str = "cliente",
    historico: list[dict[str, str]] | None = None,
    mensagem_cliente: str = "",
) -> str:
    _ = origem

    # Última fala do cliente (para espelhar bom dia / oi)
    if not mensagem_cliente and historico:
        for h in reversed(historico):
            if h.get("remetente") == "cliente" and h.get("mensagem"):
                mensagem_cliente = str(h.get("mensagem") or "")
                break
    if not mensagem_cliente and decisao.pergunta:
        mensagem_cliente = decisao.pergunta

    # Resumo cadastral fixo — não deixa a LLM inventar ou omitir campos
    if decisao.objetivo_resposta == "CONFIRMAR_DADOS_CADASTRO":
        dados = {**estado, **(decisao.atualizar_dados or {})}
        return montar_resumo_cadastro(dados)

    if decisao.objetivo_resposta in {
        "APRESENTAR_E_PEDIR_LOCALIZACAO",
        "CONVERSAR_E_PEDIR_LOCALIZACAO",
    }:
        quer_planos = bool((decisao.contexto_resposta or {}).get("quer_ver_planos"))
        return mensagem_abertura(mensagem_cliente, quer_planos=quer_planos)

    if decisao.objetivo_resposta == "PEDIR_LOCALIZACAO_PARA_VER_PLANOS":
        return mensagem_pedir_local_para_planos()

    # Primeiro contato pedindo localização (ex.: "quero internet") — ainda cumprimenta
    if (
        decisao.objetivo_resposta == "PEDIR_LOCALIZACAO"
        and not estado.get("cumprimento_feito")
    ):
        quer_planos = bool((decisao.contexto_resposta or {}).get("quer_ver_planos"))
        return mensagem_abertura(mensagem_cliente, quer_planos=quer_planos)

    if decisao.objetivo_resposta == "COMPLETAR_LOCALIZACAO":
        cidade = str(
            decisao.atualizar_dados.get("cidade")
            or estado.get("cidade")
            or ""
        ).strip()
        bairro = str(
            decisao.atualizar_dados.get("bairro")
            or estado.get("bairro")
            or ""
        ).strip()
        if decisao.atualizar_dados.get("limpar_cidade"):
            cidade = ""
        if cidade and not bairro:
            return (
                f"Anotei a cidade *{cidade}*. "
                "Agora me passa o *bairro*, por favor."
            )
        if bairro and not cidade:
            return (
                f"Anotei o bairro *{bairro}*. "
                "Qual a *cidade*?"
            )
        return "Me passa sua *cidade* e *bairro* pra eu consultar a cobertura."

    if decisao.objetivo_resposta == "CUMPRIMENTAR_E_RETOMAR":
        ctx = decisao.contexto_resposta or {}
        pendente = str(ctx.get("pendente") or decisao.aguardando or "")
        return mensagem_cumprimento_retomar(mensagem_cliente, pendente)

    if decisao.objetivo_resposta == "PEDIR_QUAL_DADO_CORRIGIR":
        return (
            "Sem problemas! Me diga qual dado você quer corrigir "
            "(nome, CPF, e-mail, telefone, data de nascimento ou endereço)."
        )

    if decisao.objetivo_resposta == "APRESENTAR_HORARIOS":
        ctx = decisao.contexto_resposta or {}
        agenda = ctx.get("agenda") or {}
        if not agenda.get("data"):
            agenda = {
                "data": estado.get("data_agendamento") or decisao.atualizar_dados.get("data_agendamento"),
                "manha": decisao.atualizar_dados.get("horarios_manha") or estado.get("horarios_manha") or [],
                "tarde": decisao.atualizar_dados.get("horarios_tarde") or estado.get("horarios_tarde") or [],
            }
        return montar_mensagem_horarios(agenda)

    if decisao.objetivo_resposta == "CONFIRMAR_HORARIO_ESCOLHIDO":
        ctx = decisao.contexto_resposta or {}
        horario = ctx.get("horario") or decisao.atualizar_dados.get("horario_escolhido") or ""
        data = ctx.get("data") or estado.get("data_agendamento") or ""
        return confirmar_horario_escolhido(horario, data)

    if decisao.objetivo_resposta == "HORARIO_NAO_DISPONIVEL":
        return horario_nao_disponivel({**estado, **(decisao.atualizar_dados or {})})

    if decisao.objetivo_resposta == "HORARIO_AMBIGUO":
        ctx = decisao.contexto_resposta or {}
        return horario_ambiguo(
            str(ctx.get("turno") or ""),
            {**estado, **(decisao.atualizar_dados or {})},
        )

    if decisao.objetivo_resposta == "EXPLICAR_HORARIOS_UNICOS":
        ctx = decisao.contexto_resposta or {}
        msg = explicar_horarios_unicos(
            {**estado, **(decisao.atualizar_dados or {})},
            str(ctx.get("preferencia") or ""),
        )
        return msg + "\n\n" + retomar_escolha_horario({**estado, **(decisao.atualizar_dados or {})})

    if decisao.objetivo_resposta == "AGENDAMENTO_CONFIRMADO":
        ctx = decisao.contexto_resposta or {}
        return agendamento_confirmado(
            str(ctx.get("horario") or estado.get("horario_escolhido") or ""),
            str(ctx.get("data") or estado.get("data_agendamento") or ""),
            str(estado.get("nome") or ""),
        )

    if decisao.objetivo_resposta == "AGENDAMENTO_CONFIRMADO_E_PEDIR_DUVIDAS":
        ctx = decisao.contexto_resposta or {}
        return pedir_duvidas_apos_agendamento(
            str(ctx.get("horario") or estado.get("horario_escolhido") or ""),
            str(ctx.get("data") or estado.get("data_agendamento") or ""),
            str(estado.get("nome") or ""),
        )

    if decisao.objetivo_resposta == "PEDIR_ACEITE_TERMOS":
        ctx = decisao.contexto_resposta or {}
        return pedir_aceite_termos(
            termos_enviados=bool(ctx.get("termos_enviados")),
            parcial=bool(ctx.get("termos_parcial")),
            pedir_aceite_explicito=bool(ctx.get("pedir_aceite_explicito")),
        )

    if decisao.objetivo_resposta == "INFORMAR_RECUSA_TERMOS":
        return recusou_termos()

    if decisao.objetivo_resposta == "INFORMAR_ERRO_ATIVACAO_E_TRANSFERENCIA":
        return (
            "Tive um problema ao ativar seu contrato no sistema. "
            "Vou te encaminhar para nossa equipe continuar o atendimento, tudo bem?"
        )

    if decisao.objetivo_resposta == "INFORMAR_ERRO_CADASTRO_E_TRANSFERENCIA":
        return (
            "Tive uma falha ao registrar seu cadastro no sistema. "
            "Vou te transferir agora para um atendente da nossa equipe resolver isso com você."
        )

    if decisao.objetivo_resposta == "INFORMAR_CPF_JA_CADASTRADO":
        return (
            "Vi aqui que este CPF já consta no nosso sistema. "
            "Vou te transferir para um atendente seguir com o seu caso, tudo bem?"
        )

    if decisao.objetivo_resposta == "INFORMAR_ERRO_AGENDA_E_TRANSFERENCIA":
        return (
            "Não consegui consultar/agendar os horários agora. "
            "Vou te encaminhar para a equipe continuar o agendamento."
        )

    if decisao.objetivo_resposta == "INFORMAR_ERRO_E_TRANSFERENCIA":
        return (
            "Tive um problema técnico neste passo. "
            "Vou te transferir para um atendente humano para não te deixar na mão."
        )

    if decisao.objetivo_resposta == "INFORMAR_TRANSFERENCIA":
        return (
            "Vou te transferir para um atendente da nossa equipe. "
            "Em instantes alguém continua com você por aqui."
        )

    if decisao.objetivo_resposta == "RESPONDER_DUVIDA_E_RETOMAR_TERMOS":
        ctx = decisao.contexto_resposta or {}
        topico = str(ctx.get("topico_contexto") or "")
        if topico == "cancelamento" or ctx.get("esclarecer_aceite"):
            return explicar_cancelamento_termos()
        rag = ctx.get("rag") or {}
        pergunta_bruta = normalizar_texto(
            str(decisao.pergunta or ctx.get("pergunta_original") or "")
        )
        if pergunta_bruta in {"aceito", "aceita", "concordo"}:
            return pedir_aceite_termos(
                termos_enviados=bool(estado.get("termos_enviados")),
            )
        if rag.get("resposta") and topico != "cancelamento":
            base = str(rag["resposta"]).strip()
        else:
            base = "Boa pergunta!"
        return base + "\n\n" + pedir_aceite_termos(
            termos_enviados=bool(estado.get("termos_enviados")),
        )

    if decisao.objetivo_resposta == "PEDIR_HORARIO_ESPECIFICO":
        return pedir_horario_especifico({**estado, **(decisao.atualizar_dados or {})})

    if decisao.objetivo_resposta == "PEDIR_DUVIDAS":
        return "Antes de encerrar, *tem mais alguma dúvida?*"

    if decisao.objetivo_resposta == "PEDIR_FALAR_DUVIDA":
        return pedir_falar_duvida()

    if decisao.objetivo_resposta == "DESPEDIDA_ENCERRAMENTO":
        ctx = decisao.contexto_resposta or {}
        return despedida_encerramento(str(ctx.get("nome") or estado.get("nome") or ""))

    if decisao.objetivo_resposta == "RETOMAR_ESCOLHA_HORARIO":
        return retomar_escolha_horario({**estado, **(decisao.atualizar_dados or {})})

    if decisao.objetivo_resposta == "INFORMAR_SEM_COBERTURA":
        cidade = str(estado.get("cidade") or decisao.atualizar_dados.get("cidade") or "")
        bairro = str(estado.get("bairro") or decisao.atualizar_dados.get("bairro") or "")
        return informar_sem_cobertura(cidade, bairro)

    if decisao.objetivo_resposta == "INSISTENCIA_SEM_COBERTURA":
        ctx = decisao.contexto_resposta or {}
        return insistencia_sem_cobertura(
            int(ctx.get("tentativa") or 1),
            int(ctx.get("max") or 3),
        )

    if decisao.objetivo_resposta == "TRANSFERIR_INSISTENCIA_SEM_COBERTURA":
        return transferir_apos_insistencia("cobertura")

    if decisao.objetivo_resposta == "INFORMAR_PLANO_NAO_ENCONTRADO":
        ctx = decisao.contexto_resposta or {}
        return informar_plano_nao_encontrado(str(ctx.get("referencia") or ""))

    if decisao.objetivo_resposta == "ESCLARECER_PLANO_AMBIGUO":
        ctx = decisao.contexto_resposta or {}
        return esclarecer_plano_ambiguo(list(ctx.get("candidatos") or []))

    if decisao.objetivo_resposta == "ESCLARECER_PROMO_PLANO":
        return esclarecer_promocao_plano(_plano_do_estado(estado, decisao.contexto_resposta or {}))

    if decisao.objetivo_resposta == "INFORMAR_DETALHES_PLANO":
        ctx = decisao.contexto_resposta or {}
        plano = _plano_do_estado(estado, ctx)
        ref = str(ctx.get("referencia_plano") or "").strip()
        if ref:
            from app.plans import resolver_plano
            from app.plans_catalog import listar_planos

            plano_atual_id = None
            try:
                if estado.get("plano_em_negociacao_id") is not None:
                    plano_atual_id = int(estado["plano_em_negociacao_id"])
            except (TypeError, ValueError):
                plano_atual_id = None
            resolvido = resolver_plano(
                ref, listar_planos(estado), plano_atual_id=plano_atual_id
            )
            if resolvido.get("evento") == "PLANO_RESOLVIDO" and resolvido.get("plano"):
                plano = resolvido["plano"]
            elif resolvido.get("evento") == "PLANO_AMBIGUO":
                cands = list(resolvido.get("candidatos") or [])
                if cands:
                    return esclarecer_plano_ambiguo(cands)
        if ctx.get("identificacao_por_preco"):
            return identificar_plano_por_preco(plano if isinstance(plano, dict) else {})
        return informar_detalhes_plano(plano if isinstance(plano, dict) else {})

    if decisao.objetivo_resposta == "APRESENTAR_PLANO_INICIAL":
        ctx = decisao.contexto_resposta or {}
        return apresentar_plano_inicial(
            _plano_do_estado(estado, ctx),
            cidade=str(estado.get("cidade") or ""),
            bairro=str(estado.get("bairro") or ""),
        )

    if decisao.objetivo_resposta == "APRESENTAR_PLANO_ESCOLHIDO_E_CONFIRMAR":
        ctx = decisao.contexto_resposta or {}
        return confirmar_plano_escolhido(_plano_do_estado(estado, ctx), troca=False)

    if decisao.objetivo_resposta == "APRESENTAR_TROCA_PLANO_E_CONFIRMAR":
        ctx = decisao.contexto_resposta or {}
        return confirmar_plano_escolhido(_plano_do_estado(estado, ctx), troca=True)

    if decisao.objetivo_resposta == "INFORMAR_PRECO_PLANO_E_RETOMAR":
        ctx = decisao.contexto_resposta or {}
        plano_atual = _plano_do_estado(estado, ctx)
        from app.plans_catalog import listar_planos

        catalogo = listar_planos(estado)
        ultima = str(estado.get("ultima_mensagem_sofia") or "")
        citados = planos_citados_no_texto(ultima, catalogo)
        # Se a Eva citou outros planos (ex.: ONE+ / UP+ com Disney), preço deles
        if len(citados) >= 1:
            ids_citados = {int(p.get("id") or -1) for p in citados}
            id_atual = int(plano_atual.get("id") or -1) if plano_atual else -1
            # Citou alternativas além do atual, ou só as alternativas
            if len(citados) > 1 or (citados and id_atual not in ids_citados):
                return informar_precos_planos(
                    citados,
                    plano_atual=plano_atual,
                    contexto="Sobre os planos que comentei:",
                )
        return informar_preco_plano(plano_atual)

    if decisao.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR":
        from app.vendas_mensagens import informar_instalacao_e_retomar

        ctx = decisao.contexto_resposta or {}
        plano = _plano_do_estado(estado, ctx)
        nome = str(
            ctx.get("plano_nome")
            or (plano or {}).get("nome")
            or estado.get("plano_em_negociacao")
            or estado.get("plano_confirmado")
            or ""
        )
        return informar_instalacao_e_retomar(
            pendente=str(ctx.get("pendente") or decisao.aguardando or "confirmacao_plano"),
            plano_nome=nome,
            pergunta_custo=bool(ctx.get("pergunta_custo_instalacao")),
        )

    if decisao.objetivo_resposta == "INFORMAR_PLANOS_POR_BENEFICIO":
        ctx = decisao.contexto_resposta or {}
        beneficio = str(ctx.get("beneficio") or "").strip() or "esse benefício"
        plano_atual = _plano_do_estado(estado, ctx)
        from app.plans_catalog import listar_planos

        catalogo = listar_planos(estado)
        chave = beneficio.casefold().replace("+", "")
        com: list[dict] = []
        for p in catalogo:
            tags = " ".join(str(t) for t in (p.get("tags") or [])).casefold()
            benef = str(p.get("beneficios") or p.get("descricao") or "").casefold()
            nome = str(p.get("nome") or "").casefold()
            if chave in tags or chave in benef or chave in nome:
                com.append(p)
        return informar_planos_por_beneficio(beneficio, com, plano_atual=plano_atual)

    if decisao.objetivo_resposta == "APRESENTAR_LISTA_COMPLETA_PLANOS":
        ctx = decisao.contexto_resposta or {}
        planos = list(ctx.get("planos") or [])
        sugerido = ctx.get("plano_sugerido") or ctx.get("plano") or {}
        if not isinstance(sugerido, dict):
            sugerido = {}
        return apresentar_lista_completa_planos(planos, plano_destaque=sugerido)

    if decisao.objetivo_resposta == "APRESENTAR_PLANOS_ALTERNATIVOS":
        ctx = decisao.contexto_resposta or {}
        sugerido = _plano_do_estado(estado, ctx)
        return apresentar_planos_como_sugestao(
            sugerido,
            total_planos=int(ctx.get("total_planos") or len(ctx.get("planos") or []) or 0),
        )

    if decisao.objetivo_resposta == "CONFIRMAR_PLANO_E_AVANCAR":
        ctx = decisao.contexto_resposta or {}
        plano = _plano_do_estado(estado, ctx)
        nome = str(plano.get("nome") or estado.get("plano_confirmado") or "")
        valor = _fmt_money(plano.get("valor") or plano.get("valor_pontualidade"))
        return confirmar_plano_e_avancar(nome, valor)

    if decisao.objetivo_resposta == "ANOTAR_E_PEDIR_PROXIMO":
        ctx = decisao.contexto_resposta or {}
        dados = {**estado, **(decisao.atualizar_dados or {})}
        return anotar_e_pedir_proximo(
            campos_anotados=list(ctx.get("campos_anotados") or []),
            campos_corrigidos=list(ctx.get("campos_corrigidos") or []),
            pendente=str(ctx.get("pendente") or decisao.aguardando or ""),
            estado=dados,
        )

    if decisao.objetivo_resposta and decisao.objetivo_resposta.startswith("PEDIR_"):
        alvo = decisao.objetivo_resposta.replace("PEDIR_CORRECAO_", "").replace("PEDIR_", "").lower()
        mapa = {
            "nome": "nome",
            "cpf": "cpf",
            "email": "email",
            "telefone": "telefone",
            "data_nascimento": "data_nascimento",
            "cep": "cep",
            "rua": "rua",
            "numero": "numero",
            "cpf_novamente": "cpf",
        }
        campo = mapa.get(alvo, alvo)
        if campo in {
            "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero",
        }:
            ctx = decisao.contexto_resposta or {}
            from app.cadastro_mensagens import campos_para_pedir, pedir_campos

            if not decisao.objetivo_resposta.startswith("PEDIR_CORRECAO_"):
                faltam = campos_para_pedir({**estado, **(decisao.atualizar_dados or {})})
                if campo in faltam and len(faltam) > 1:
                    return pedir_campos(faltam)
            base = pedir_campo(campo)
            motivo = str(ctx.get("motivo_validacao") or "").strip()
            if motivo and decisao.objetivo_resposta.startswith("PEDIR_CORRECAO_"):
                return f"{motivo.capitalize()}. {base}"
            return base

    if decisao.objetivo_resposta == "RESPONDER_SEM_BASE_RAG":
        ctx = decisao.contexto_resposta or {}
        pendente = str(ctx.get("pendente") or decisao.aguardando or "")
        return responder_sem_base_rag(pendente)

    ctx = decisao.contexto_resposta or {}
    plano = ctx.get("plano") or {}
    planos = ctx.get("planos") or []
    planos_txt = ""
    for i, p in enumerate(planos, 1):
        preco = _fmt_money(p.get("valor"))
        pont = p.get("valor_pontualidade")
        extra_preco = ""
        if pont:
            extra_preco = f" (pontualidade: {_fmt_money(pont)})"
        planos_txt += (
            f"{i}. {p.get('nome')} — {preco}{extra_preco}\n"
            f"   {p.get('beneficios') or p.get('descricao') or ''}\n"
        )

    pendente = ctx.get("pendente") or decisao.aguardando
    anotados = ctx.get("campos_anotados") or []
    corrigidos = ctx.get("campos_corrigidos") or []
    motivo_val = ctx.get("motivo_validacao") or ""
    cpf_anotado = ctx.get("cpf_anotado", False)
    rag_txt = formatar_contexto_rag(ctx.get("rag") or {})
    topico = ctx.get("topico_contexto") or ""
    pergunta_original = ctx.get("pergunta_original") or ""

    from app.contexto_conversa import rotulo_topico

    hist_txt = ""
    for h in historico or []:
        quem = "Cliente" if h.get("remetente") == "cliente" else "Eva"
        hist_txt += f"{quem}: {h.get('mensagem')}\n"

    user = f"""OBJETIVO: {decisao.objetivo_resposta or ''}
PENDENTE AGORA: {_rotulo_pendente(str(pendente) if pendente else None) or '(nenhum)'}
CUMPRIMENTO JÁ FEITO: {bool(estado.get('cumprimento_feito'))}
CAMPOS QUE ACABARAM DE SER ANOTADOS: {', '.join(anotados) or '(nenhum)'}
CAMPOS CORRIGIDOS AGORA: {', '.join(corrigidos) or '(nenhum)'}
MOTIVO DE VALIDAÇÃO (se houver): {motivo_val or '(nenhum)'}
CPF ANOTADO MAS NÃO VALIDAR AGORA: {cpf_anotado}
TÓPICO DO CONTEXTO (siga este assunto nos follow-ups): {rotulo_topico(str(topico) if topico else None)}
PERGUNTA ORIGINAL DO CLIENTE: {pergunta_original or '(igual abaixo)'}
PERGUNTA DO CLIENTE (já contextualizada): {decisao.pergunta or '(nenhuma)'}

BASE DE CONHECIMENTO (RAG — use como fonte; não invente além disso):
{rag_txt or '(nenhum trecho encontrado — responda só com o que souber dos planos acima)'}

ÚLTIMAS MENSAGENS (use para entender follow-ups como "quanto paga?", "pra cancelar", "e a taxa?"):
{hist_txt or '(sem histórico)'}

DADOS DO CLIENTE (já coletados — não peça de novo sem motivo):
cidade={decisao.atualizar_dados.get('cidade') or estado.get('cidade') or ''}
bairro={decisao.atualizar_dados.get('bairro') or estado.get('bairro') or ''}
plano={decisao.atualizar_dados.get('plano_confirmado') or estado.get('plano_confirmado') or estado.get('plano_em_negociacao') or ''}
nome={decisao.atualizar_dados.get('nome') or estado.get('nome') or ''}
cpf={decisao.atualizar_dados.get('cpf') or estado.get('cpf') or ''}
email={decisao.atualizar_dados.get('email') or estado.get('email') or ''}
telefone={decisao.atualizar_dados.get('telefone') or estado.get('telefone') or ''}
data_nascimento={decisao.atualizar_dados.get('data_nascimento') or estado.get('data_nascimento') or ''}
cep={decisao.atualizar_dados.get('cep') or estado.get('cep') or ''}
rua={decisao.atualizar_dados.get('rua') or estado.get('rua') or ''}
numero={decisao.atualizar_dados.get('numero') or estado.get('numero') or ''}

PLANO EM FOCO:
nome={plano.get('nome') or ''}
valor={_fmt_money(plano.get('valor'))}
beneficios={plano.get('beneficios') or plano.get('descricao') or ''}

OUTROS PLANOS:
{planos_txt or '(nenhum)'}

Como cumprir o objetivo:
- APRESENTAR_E_PEDIR_LOCALIZACAO / CONVERSAR_E_PEDIR_LOCALIZACAO: (gerado automaticamente — cumprimento na altura + cidade/bairro)
- CUMPRIMENTAR_E_RETOMAR: (gerado automaticamente — responde bom dia/tarde/noite/oi na altura e retoma)
- PEDIR_LOCALIZACAO / RETOMAR_LOCALIZACAO / COMPLETAR_LOCALIZACAO / PEDIR_NOVA_LOCALIZACAO: peça só o que falta.
- APRESENTAR_PLANO_INICIAL / APRESENTAR_PLANO_ESCOLHIDO_E_CONFIRMAR: use 📦 nome, preço e lista ✅ de benefícios; pergunte se quer fechar.
- APRESENTAR_TROCA_PLANO_E_CONFIRMAR: diga que entendeu a troca, apresente o plano com benefícios e peça confirmação; diga que depois volta aos dados.
- APRESENTAR_PLANOS_ALTERNATIVOS: NÃO liste todos os planos. Sugira o plano em foco com benefícios; diga que há outras opções se quiser comparar.
- INFORMAR_PRECO_PLANO_E_RETOMAR / INFORMAR_PLANOS_POR_BENEFICIO / INFORMAR_INSTALACAO_E_RETOMAR: respostas fixas (não invente).
- INFORMAR_INSTALACAO_E_RETOMAR: instalação só após cadastro; não prometa hoje/amanhã nem invente taxa/fidelidade; retome a confirmação do plano.
- CONFIRMAR_PLANO_E_AVANCAR: confirme o plano com naturalidade e peça o nome completo.
- CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA: confirme o plano, responda a dúvida com base na RAG e peça o nome completo.
- CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA: confirme que os dados estão corretos, responda a dúvida com RAG e peça confirmação final do cadastro.
- CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA: confirme o horário escolhido, responda a dúvida e peça confirmação do agendamento.
- CONFIRMAR_TROCA_PLANO_E_RETOMAR_CADASTRO: confirme a troca e retome o pendente do cadastro.
- ANOTAR_E_PEDIR_PROXIMO: confirme o que anotou/corrigiu (nome, email, rua, CEP, etc.) e peça SOMENTE o pendente atual. Se pendente=cpf, não peça endereço de novo — só o CPF.
- ANOTAR_DADO_E_RETOMAR_PLANO: anote o dado e retome a escolha/confirmação do plano. Não peça endereço de novo.
- PEDIR_NOME / PEDIR_CPF / PEDIR_EMAIL / PEDIR_TELEFONE / PEDIR_DATA_NASCIMENTO / PEDIR_CEP / PEDIR_RUA / PEDIR_NUMERO: peça só esse campo.
- PEDIR_CORRECAO_* / PEDIR_CPF_NOVAMENTE: peça de novo de forma leve.
- CONFIRMAR_DADOS_CADASTRO: (gerado automaticamente — não use este objetivo via LLM)
- APRESENTAR_HORARIOS: (gerado automaticamente — não use este objetivo via LLM)
- ENCERRAR_CADASTRO_BASICO: confirme que o cadastro foi concluído e diga que a equipe segue com instalação/contrato.
- INFORMAR_SEM_HORARIOS_E_TRANSFERENCIA / INFORMAR_ERRO_AGENDA_E_TRANSFERENCIA: explique que não há horários no momento e encaminhe para a equipe.
- INFORMAR_PLANO_BLOQUEADO_POS_CADASTRO: cadastro fechado — troca de plano com a equipe.
- INFORMAR_SEM_COBERTURA: sem cobertura + oferecer outro endereço.
- INFORMAR_CPF_JA_CADASTRADO / INFORMAR_ERRO_* / INFORMAR_TRANSFERENCIA: explique e diga que vai encaminhar para a equipe humana. NÃO pergunte "posso ajudar com mais alguma coisa" — o atendimento automático encerra aqui.
- RESPONDER_PERGUNTA_E_RETOMAR: responda a pergunta com base na RAG e no TÓPICO DO CONTEXTO. Follow-ups curtos ("quanto paga?", "tem taxa?", "pra cancelar", "e a multa?") referem-se ao tópico anterior — NÃO troque cancelamento/multa por mensalidade do plano, nem o contrário, sem o cliente pedir. Se citou planos, SEMPRE com preço. Se anotou algum campo nesta mensagem, confirme o dado em 1 frase, responda a dúvida, e retome o pendente. Se cpf_anotado=true, ignore o CPF por enquanto.
- RESPONDER_DUVIDA_E_RETOMAR: agendamento já feito — responda a dúvida com RAG e/ou dados da conversa (plano, horário, endereço). Termine sempre perguntando se tem mais alguma dúvida.
- CONVERSAR_E_RETOMAR / CUMPRIMENTAR_E_RETOMAR / RETOMAR_ESCOLHA_PLANO: responda e volte ao pendente.
- CONTINUAR_CONVERSA: responda natural e retome o pendente se houver.

Escreva somente a mensagem final.
"""
    texto = chat(_system_prompt(), user, temperature=0.55)
    if decisao.objetivo_resposta == "RESPONDER_DUVIDA_E_RETOMAR":
        low = texto.casefold()
        if "dúvida" not in low and "duvida" not in low:
            texto = texto.rstrip() + retomar_duvidas()
    return texto
