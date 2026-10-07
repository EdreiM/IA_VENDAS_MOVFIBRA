"""Pipeline completo de um turno de conversa."""

from __future__ import annotations

import time
from typing import Any

from app import db
from app.agenda import consultar_horarios
from app.agenda_inserir import inserir_agendamento
from app.cadastro_ixc import cadastrar_cliente
from app.coverage import checar_cobertura
from app.cpf_validation import validar_cpf
from app.encerrar import encerrar_atendimento
from app.ativacao import ativar_cliente
from app.imagem_plano import enviar_imagem_plano
from app.termos import enviar_termos
from app.interpreter import interpretar, snapshot_estado
from app.models import Decisao, TurnoResultado
from app.parser import parse_interpretacao
from app.plans import alternativas, resolver_plano
from app.plans_catalog import listar_planos, plano_destaque
from app.resolver import resolver
from app.rag import consultar_rag
from app.response import gerar_resposta
from app.state_machine import (
    decidir,
    decidir_lista_planos,
    decidir_plano_inicial,
    decidir_plano_resolvido,
    decidir_resultado_cadastro_ixc,
    decidir_resultado_cobertura,
    decidir_resultado_encerrar,
    decidir_resultado_horarios,
    decidir_resultado_inserir_agenda,
    decidir_resultado_cpf,
    decidir_resultado_termos,
    decidir_resultado_ativacao,
    decidir_resultado_imagem_plano,
    retomar_duvida_apos_cpf,
)


def tem_pergunta(interpretacao: Any) -> bool:
    """A mensagem traz uma pergunta (texto extraído ou evento PERGUNTA)."""
    return bool((interpretacao.pergunta or "").strip()) or "PERGUNTA" in (interpretacao.eventos or [])


def _imagens_plano_do_contexto(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrai imagens de plano enviadas no turno (painel + Chatwoot)."""
    img_url = str(ctx.get("imagem_url") or "").strip()
    if not img_url or not (
        bool(ctx.get("imagem_plano_enviada")) or bool(ctx.get("imagem_painel"))
    ):
        return []
    plano_ctx = ctx.get("plano") if isinstance(ctx.get("plano"), dict) else {}
    return [
        {
            "url": img_url,
            "plano_id": plano_ctx.get("id"),
            "plano_nome": plano_ctx.get("nome") or "",
        }
    ]


def _executar_acao(estado: dict[str, Any], decisao: Decisao) -> Decisao:
    acao = decisao.acao

    if acao == "CHECAR_COBERTURA":
        resultado = checar_cobertura(
            cidade=str(decisao.atualizar_dados.get("cidade") or estado.get("cidade") or ""),
            bairro=str(decisao.atualizar_dados.get("bairro") or estado.get("bairro") or ""),
            rua=str(decisao.atualizar_dados.get("rua") or estado.get("rua") or ""),
            numero=str(decisao.atualizar_dados.get("numero") or estado.get("numero") or ""),
            localizacao_fixa=str(
                decisao.atualizar_dados.get("localizacao_fixa")
                or estado.get("localizacao_fixa")
                or ""
            ),
            id_cliente=str(estado.get("id_cliente") or ""),
        )
        return decidir_resultado_cobertura(resultado, estado)

    if acao == "LISTAR_TODOS_PLANOS":
        planos = listar_planos(estado)
        ctx_lista = decisao.contexto_resposta or {}
        if str(ctx_lista.get("filtro") or "").casefold() == "desconto":
            from app.vendas_mensagens import planos_com_desconto_especial

            filtrados = planos_com_desconto_especial(planos)
            if filtrados:
                planos = filtrados
        ref_id = estado.get("plano_em_negociacao_id") or estado.get("plano_confirmado_id")
        ref = next(
            (p for p in planos if ref_id is not None and int(p["id"]) == int(ref_id)),
            None,
        )
        lista_completa = bool(ctx_lista.get("lista_completa"))
        # LISTAR_TODOS sempre mostra o catálogo completo (ou filtrado)
        dec_lista = decidir_lista_planos(planos, ref, estado, lista_completa=lista_completa)
        if str(ctx_lista.get("filtro") or "").casefold() == "desconto":
            ctx_out = dict(dec_lista.contexto_resposta or {})
            ctx_out["filtro"] = "desconto"
            dec_lista.contexto_resposta = ctx_out
        return dec_lista

    if acao == "VALIDAR_CPF":
        ctx = decisao.contexto_resposta or {}
        cpf_valor = str(
            ctx.get("cpf")
            or decisao.atualizar_dados.get("cpf")
            or estado.get("cpf")
            or ""
        )
        resultado = validar_cpf(
            cpf_cnpj=cpf_valor,
            id_cliente=str(estado.get("id_cliente") or ""),
            contact_id=str(estado.get("contact_id") or ""),
        )
        if isinstance(resultado, dict):
            resultado = dict(resultado)
            resultado["campos_junto"] = list((decisao.contexto_resposta or {}).get("campos_junto") or [])
        dec_cpf = decidir_resultado_cpf(resultado, estado)
        # CPF veio junto com uma dúvida: validado, responde a dúvida e pede o próximo campo
        depois = ctx.get("responder_depois")
        if (
            isinstance(depois, dict)
            and dec_cpf.acao == "RESPONDER"
            and dec_cpf.fase == "cadastro"
            and (dec_cpf.atualizar_dados or {}).get("documento_cpf_validado")
        ):
            return retomar_duvida_apos_cpf(depois, dec_cpf)
        return dec_cpf

    if acao == "CADASTRAR_IXC":
        estado_efetivo = {**estado, **(decisao.atualizar_dados or {})}
        resultado = cadastrar_cliente(estado_efetivo)
        return decidir_resultado_cadastro_ixc(resultado, estado_efetivo)

    if acao == "BUSCAR_HORARIOS":
        estado_efetivo = {**estado, **(decisao.atualizar_dados or {})}
        id_ixc = str(estado_efetivo.get("ixc_cliente_id") or "").strip()
        if not id_ixc:
            return Decisao(
                acao="TRANSFERIR_HUMANO",
                objetivo_resposta="INFORMAR_ERRO_CADASTRO_E_TRANSFERENCIA",
                fase="transferido",
                aguardando=None,
                atualizar_dados={
                    "transferido_humano": True,
                    "motivo_transferencia": "Cadastro sem ID IXC — não é possível agendar",
                },
                motivo="ixc_cliente_id ausente após cadastro",
                prioridade="AGENDAMENTO",
            )
        resultado = consultar_horarios(estado_efetivo)
        return decidir_resultado_horarios(resultado, estado_efetivo)

    if acao == "INSERIR_AGENDAMENTO":
        estado_efetivo = {**estado, **(decisao.atualizar_dados or {})}
        resultado = inserir_agendamento(estado_efetivo)
        return decidir_resultado_inserir_agenda(resultado, estado_efetivo)

    if acao == "ENVIAR_TERMOS":
        estado_efetivo = {**estado, **(decisao.atualizar_dados or {})}
        resultado = enviar_termos(estado_efetivo)
        return decidir_resultado_termos(resultado, estado_efetivo)

    if acao == "ATIVAR_CLIENTE":
        estado_efetivo = {**estado, **(decisao.atualizar_dados or {})}
        resultado = ativar_cliente(estado_efetivo)
        return decidir_resultado_ativacao(resultado, estado_efetivo)

    if acao == "ENVIAR_IMAGEM_PLANO":
        estado_efetivo = {**estado, **(decisao.atualizar_dados or {})}
        if (decisao.atualizar_dados or {}).get("_omitir_legenda_imagem"):
            estado_efetivo["_omitir_legenda_imagem"] = True
        ctx_img = decisao.contexto_resposta or {}
        plano_ctx = ctx_img.get("plano") if isinstance(ctx_img.get("plano"), dict) else {}
        if plano_ctx.get("id") is not None:
            estado_efetivo["plano_apresentado_id"] = plano_ctx["id"]
            estado_efetivo["plano_em_negociacao_id"] = plano_ctx["id"]
            if plano_ctx.get("nome"):
                estado_efetivo["plano_apresentado"] = plano_ctx["nome"]
                estado_efetivo["plano_em_negociacao"] = plano_ctx["nome"]
        resultado = enviar_imagem_plano(estado_efetivo)
        return decidir_resultado_imagem_plano(resultado, estado_efetivo, decisao)

    if acao == "ENCERRAR_ATENDIMENTO":
        estado_efetivo = {**estado, **(decisao.atualizar_dados or {})}
        resultado = encerrar_atendimento(estado_efetivo)
        return decidir_resultado_encerrar(resultado, estado_efetivo)

    if acao == "BUSCAR_PLANO_INICIAL":
        plano = plano_destaque(estado)
        return decidir_plano_inicial(plano, estado)

    if acao == "BUSCAR_PLANOS":
        # Persist desvio already applied in salvar_transicao before this call
        estado_efetivo = {
            **estado,
            **{
                k: v
                for k, v in (decisao.atualizar_dados or {}).items()
                if k in {"fase_anterior", "aguardando_anterior"}
            },
        }
        planos = listar_planos(estado)
        ref_id = (
            estado.get("plano_em_negociacao_id")
            or estado.get("plano_confirmado_id")
            or estado.get("plano_apresentado_id")
        )
        alts = alternativas(planos, int(ref_id) if ref_id is not None else None)
        ref = next((p for p in planos if ref_id is not None and int(p["id"]) == int(ref_id)), None)
        return decidir_lista_planos(alts, ref, estado_efetivo)

    if acao == "RESOLVER_PLANO":
        estado_efetivo = {
            **estado,
            **{
                k: v
                for k, v in (decisao.atualizar_dados or {}).items()
                if k in {"fase_anterior", "aguardando_anterior"}
            },
        }
        ref = (
            (decisao.contexto_resposta or {}).get("referencia_plano")
            or (decisao.atualizar_dados or {}).get("plano")
            or ""
        )
        planos = listar_planos(estado)
        plano_atual_id = None
        try:
            if estado_efetivo.get("plano_em_negociacao_id") is not None:
                plano_atual_id = int(estado_efetivo["plano_em_negociacao_id"])
            elif estado_efetivo.get("plano_apresentado_id") is not None:
                plano_atual_id = int(estado_efetivo["plano_apresentado_id"])
        except (TypeError, ValueError):
            plano_atual_id = None
        resultado = resolver_plano(
            str(ref), planos, plano_atual_id=plano_atual_id
        )
        resultado["referencia"] = str(ref)
        return decidir_plano_resolvido(resultado, estado_efetivo)

    return decisao


def _enriquecer_com_rag(
    decisao: Decisao,
    estado: dict[str, Any],
    mensagem: str,
) -> Decisao:
    """Consulta RAG externa quando o cliente faz pergunta (fidelidade, mesh, etc.)."""
    pergunta = (decisao.pergunta or "").strip()
    objetivos_com_rag = {
        "RESPONDER_PERGUNTA_E_RETOMAR",
        "RESPONDER_DUVIDA_E_RETOMAR",
        "RESPONDER_DUVIDA_E_RETOMAR_TERMOS",  # filtrado em response.py se vier catálogo
        "CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA",
        "CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA",
        "CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA",
        "CONVERSAR_E_RETOMAR",
        "CUMPRIMENTAR_E_RETOMAR",
        "RETOMAR_ESCOLHA_PLANO",
        "RETOMAR_ESCOLHA_HORARIO",
        "CONTINUAR_CONVERSA",
    }
    if not pergunta and decisao.objetivo_resposta not in objetivos_com_rag:
        return decisao

    ctx_dec = decisao.contexto_resposta or {}
    topico_rag = str(ctx_dec.get("topico_contexto") or "")
    if topico_rag in {"cancelamento", "instalacao"}:
        return decisao
    if decisao.objetivo_resposta in {
        "INFORMAR_CANCELAMENTO_E_RETOMAR",
        "PEDIR_ACEITE_TERMOS",
    }:
        return decisao
    plano = ctx_dec.get("plano") or {}
    rag = consultar_rag(
        pergunta=pergunta or mensagem,
        mensagem=mensagem,
        estado=estado,
        plano=plano if isinstance(plano, dict) else None,
    )
    tem_conteudo = bool(
        rag.get("encontrado") or rag.get("chunks") or rag.get("resposta")
    )
    if not tem_conteudo:
        if pergunta and decisao.objetivo_resposta in objetivos_com_rag | {"CONTINUAR_CONVERSA"}:
            ctx = dict(ctx_dec)
            ctx["rag_vazia"] = True
            ctx["pendente"] = ctx.get("pendente") or decisao.aguardando
            decisao.objetivo_resposta = "RESPONDER_SEM_BASE_RAG"
            decisao.contexto_resposta = ctx
        return decisao

    ctx = dict(ctx_dec)
    ctx["rag"] = rag
    decisao.contexto_resposta = ctx
    return decisao


def process_message(
    id_cliente: str,
    mensagem: str,
    *,
    conversation_id: str | None = None,
    contact_id: str | None = None,
    message_id: str | None = None,
) -> TurnoResultado:
    t0 = time.perf_counter()
    mensagem = (mensagem or "").strip()
    if not mensagem:
        raise ValueError("Mensagem vazia")

    estado = db.carregar_ou_criar_estado(id_cliente)
    meta: dict[str, Any] = {}
    if conversation_id:
        meta["conversation_id"] = conversation_id
    if contact_id:
        meta["contact_id"] = contact_id
    if meta:
        estado = db.salvar_transicao(
            id_cliente,
            str(estado.get("fase") or "inicio"),
            estado.get("aguardando"),
            meta,
        )

    db.log_mensagem(id_cliente, "cliente", mensagem)

    # +1: a mensagem atual acabou de ser gravada e o interpretador a descarta
    historico_prev = db.historico_recente(id_cliente, limite=9)
    estado_antes = snapshot_estado(estado)

    raw = interpretar(mensagem, estado, historico=historico_prev)
    interpretacao = parse_interpretacao(raw, mensagem, estado)

    from app.contexto_conversa import enriquecer_pergunta

    plano_nome = str(
        estado.get("plano_em_negociacao")
        or estado.get("plano_confirmado")
        or ""
    )
    ctx_perg = enriquecer_pergunta(
        mensagem,
        pergunta=interpretacao.pergunta or mensagem,
        historico=historico_prev,
        plano_nome=plano_nome,
        ultimo_topico=str(estado.get("ultimo_topico") or "") or None,
    )
    # Só há pergunta quando o interpretador viu uma. Antes, o texto de TODA mensagem
    # entrava aqui ("não", "claro", um CEP) e a máquina de estados tratava como dúvida.
    if tem_pergunta(interpretacao) and ctx_perg.get("pergunta"):
        interpretacao.pergunta = str(ctx_perg["pergunta"])

    from app.parser import eh_apenas_dado_cadastro, eh_mensagem_correcao_cadastro

    topico_meta: dict[str, Any] = {}
    if ctx_perg.get("topico"):
        topico_meta["ultimo_topico"] = ctx_perg["topico"]
    elif eh_apenas_dado_cadastro(mensagem, mensagem) or eh_mensagem_correcao_cadastro(
        mensagem, mensagem
    ):
        topico_meta["limpar_topico"] = True
    if interpretacao.pergunta:
        topico_meta["ultima_pergunta_cliente"] = interpretacao.pergunta
    if topico_meta:
        estado = db.salvar_transicao(
            id_cliente,
            str(estado.get("fase") or "inicio"),
            estado.get("aguardando"),
            topico_meta,
        )

    resolucao = resolver(estado, interpretacao)
    resolucao["mensagem"] = mensagem
    resolucao["pergunta"] = interpretacao.pergunta
    resolucao["topico_contexto"] = ctx_perg.get("topico")
    resolucao["pergunta_original"] = ctx_perg.get("mensagem_original") or mensagem
    resolucao["confianca"] = float(interpretacao.confianca or 0)

    decisao = decidir(estado, resolucao)
    if decisao.acao == "RESOLVER_PLANO":
        ctx_rp = dict(decisao.contexto_resposta or {})
        if not str(ctx_rp.get("referencia_plano") or "").strip():
            ctx_rp["referencia_plano"] = (resolucao.get("plano") or {}).get("valor") or ""
        decisao.contexto_resposta = ctx_rp

    # Propaga contexto de follow-up para RAG/resposta
    if ctx_perg.get("topico") or ctx_perg.get("era_followup"):
        ctx = dict(decisao.contexto_resposta or {})
        ctx["topico_contexto"] = ctx_perg.get("topico")
        ctx["pergunta_original"] = ctx_perg.get("mensagem_original")
        ctx["era_followup"] = bool(ctx_perg.get("era_followup"))
        decisao.contexto_resposta = ctx
    if interpretacao.pergunta and not decisao.pergunta:
        decisao.pergunta = interpretacao.pergunta
    elif interpretacao.pergunta and decisao.objetivo_resposta in {
        "RESPONDER_PERGUNTA_E_RETOMAR",
        "RESPONDER_DUVIDA_E_RETOMAR",
        "RESPONDER_DUVIDA_E_RETOMAR_TERMOS",
        "CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA",
        "CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA",
        "CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA",
    }:
        decisao.pergunta = interpretacao.pergunta

    for _ in range(5):
        if decisao.acao in {"RESPONDER", "TRANSFERIR_HUMANO", "AGUARDAR"}:
            break
        estado = db.salvar_transicao(
            id_cliente,
            decisao.fase,
            decisao.aguardando,
            decisao.atualizar_dados,
        )
        decisao = _executar_acao(estado, decisao)

    from app.plano_intencao import contexto_por_objetivo_resposta

    ctx_plano_auto = contexto_por_objetivo_resposta(decisao.objetivo_resposta)
    dados_finais = dict(decisao.atualizar_dados or {})
    if ctx_plano_auto and "contexto_plano" not in dados_finais:
        dados_finais["contexto_plano"] = ctx_plano_auto

    estado = db.salvar_transicao(
        id_cliente,
        decisao.fase,
        decisao.aguardando,
        dados_finais,
    )

    chatwoot_handoff = None
    if decisao.acao == "TRANSFERIR_HUMANO":
        from app.transfer_chatwoot import talvez_handoff_ao_transferir

        chatwoot_handoff = talvez_handoff_ao_transferir(
            estado,
            motivo=str(decisao.motivo or decisao.objetivo_resposta or ""),
        )

    outputs: list[str] = []
    if decisao.acao == "AGUARDAR":
        resposta = ""
    else:
        decisao = _enriquecer_com_rag(decisao, estado, mensagem)
        historico = db.historico_recente(id_cliente, limite=6)
        resposta = gerar_resposta(
            decisao, estado, historico=historico, mensagem_cliente=mensagem
        )
        if decisao.objetivo_resposta == "APRESENTAR_LISTA_COMPLETA_PLANOS":
            from app.vendas_mensagens import (
                bolhas_lista_completa_planos,
                intro_lista_planos_desconto,
            )

            ctx = decisao.contexto_resposta or {}
            sugerido = ctx.get("plano_sugerido") or ctx.get("plano") or {}
            if not isinstance(sugerido, dict):
                sugerido = {}
            planos_ctx = list(ctx.get("planos") or [])
            outputs = bolhas_lista_completa_planos(
                planos_ctx,
                plano_destaque=sugerido,
            )
            if str(ctx.get("filtro") or "").casefold() == "desconto" and planos_ctx:
                outputs = [intro_lista_planos_desconto(), *outputs]
            resposta = "\n\n".join(outputs)
        elif decisao.objetivo_resposta == "ESCLARECER_PLANO_AMBIGUO":
            from app.vendas_mensagens import bolhas_planos_candidatos

            ctx = decisao.contexto_resposta or {}
            outputs = bolhas_planos_candidatos(list(ctx.get("candidatos") or []))
            resposta = "\n\n".join(outputs)
        elif (resposta or "").strip():
            outputs = [resposta]
        if (resposta or "").strip():
            db.salvar_resposta(id_cliente, resposta)

    estado = db.carregar_ou_criar_estado(id_cliente)

    duracao_ms = int((time.perf_counter() - t0) * 1000)
    ctx_final = decisao.contexto_resposta or {}
    rag = ctx_final.get("rag") if isinstance(ctx_final.get("rag"), dict) else {}
    rag_hit = bool(rag.get("encontrado") or rag.get("chunks") or rag.get("resposta"))

    imagens = _imagens_plano_do_contexto(ctx_final)
    # Painel local: registra imagem no histórico; Chatwoot já recebeu via webhook/API
    cid_conv = str(estado.get("conversation_id") or conversation_id or "").strip()
    for img in imagens:
        url = str(img.get("url") or "").strip()
        if not url:
            continue
        if cid_conv:
            continue
        nome = str(img.get("plano_nome") or "").strip()
        legenda = f"📦 {nome}" if nome else "Imagem do plano"
        db.log_mensagem(id_cliente, "eva", legenda, imagem_url=url)

    db.log_turno(
        id_cliente,
        mensagem_cliente=mensagem,
        eventos=list(interpretacao.eventos or []),
        acao=decisao.acao,
        objetivo=decisao.objetivo_resposta or "",
        fase=str(estado.get("fase") or ""),
        aguardando=estado.get("aguardando"),
        topico=str(ctx_perg.get("topico") or estado.get("ultimo_topico") or ""),
        rag_hit=rag_hit,
        duracao_ms=duracao_ms,
        message_id=message_id or "",
        estado_antes=estado_antes,
        interpretacao_llm=raw,
        confianca=float(interpretacao.confianca or 0),
    )

    return TurnoResultado(
        id_cliente=id_cliente,
        mensagem_cliente=mensagem,
        interpretacao=interpretacao,
        decisao=decisao,
        resposta=resposta,
        output=resposta,
        outputs=outputs,
        imagens=imagens,
        conversation_id=str(estado.get("conversation_id") or conversation_id or "") or None,
        contact_id=str(estado.get("contact_id") or contact_id or "") or None,
        chatwoot_handoff=chatwoot_handoff,
        estado={
            "fase": estado.get("fase"),
            "aguardando": estado.get("aguardando"),
            "cidade": estado.get("cidade"),
            "bairro": estado.get("bairro"),
            "tem_cobertura": estado.get("tem_cobertura"),
            "plano_em_negociacao": estado.get("plano_em_negociacao"),
            "plano_confirmado": estado.get("plano_confirmado"),
            "nome": estado.get("nome"),
            "cpf": estado.get("cpf"),
            "email": estado.get("email"),
            "telefone": estado.get("telefone"),
            "cadastro_completo": estado.get("cadastro_completo"),
            "conversation_id": estado.get("conversation_id"),
            "contact_id": estado.get("contact_id"),
        },
    )
