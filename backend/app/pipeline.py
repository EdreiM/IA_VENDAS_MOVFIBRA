"""Pipeline completo de um turno de conversa."""

from __future__ import annotations

import json
import logging
import threading
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

logger = logging.getLogger(__name__)


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
        # Cliente já contou o que precisa antes de ver plano ("somos 8 em casa"): o primeiro
        # plano mostrado é o indicado para ele, não o destaque genérico.
        if str(estado.get("notas_conversa") or "").strip():
            rec = _consultar_consultor(estado, "(o cliente ainda não viu nenhum plano)")
            if rec and rec.get("plano"):
                dec = decidir_plano_inicial(rec["plano"], estado)
                return _com_contexto(dec, abertura_plano=rec.get("abertura") or "", sinais=["plano_recomendado"])
        return decidir_plano_inicial(plano, estado)

    if acao == "RECOMENDAR_PLANO":
        return _recomendar_plano(estado, decisao)

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


def _com_contexto(decisao: Decisao, *, sinais: list[str] | None = None, **extra: Any) -> Decisao:
    ctx = dict(decisao.contexto_resposta or {})
    ctx.update({k: v for k, v in extra.items() if v})
    if sinais:
        ctx["sinais"] = [*ctx.get("sinais", []), *sinais]
    decisao.contexto_resposta = ctx
    return decisao


_KIT_DE_VENDA: dict[str, Any] = {"quando": 0.0, "rag": None}
_KIT_TTL_SEGUNDOS = 600
_PERGUNTA_DO_KIT = "conexão fibra ilimitada, instalação, fidelidade, equipamentos, formas de pagamento, suporte"


def base_de_venda(estado: dict[str, Any], mensagem: str) -> dict[str, Any]:
    """Trechos da base para vender: o que responde à mensagem + os fatos gerais da oferta.

    Para "já tenho internet" ou "tá caro" a busca pela própria mensagem costuma voltar
    vazia; a segunda busca traz o que a empresa tem a dizer sobre a oferta (fibra,
    instalação, fidelidade, suporte). Ela é guardada por alguns minutos.
    """
    agora = time.time()
    if _KIT_DE_VENDA["rag"] is None or agora - float(_KIT_DE_VENDA["quando"]) > _KIT_TTL_SEGUNDOS:
        kit = consultar_rag(pergunta=_PERGUNTA_DO_KIT, mensagem=_PERGUNTA_DO_KIT, estado=estado, plano=None)
        if not kit.get("erro"):
            _KIT_DE_VENDA.update(quando=agora, rag=kit)
    else:
        kit = _KIT_DE_VENDA["rag"]
    direto = consultar_rag(pergunta=mensagem, mensagem=mensagem, estado=estado, plano=None) if mensagem.strip() else {}
    junto: dict[str, Any] = {"encontrado": False, "resposta": "", "chunks": [], "fontes": []}
    vistos: set[str] = set()
    for r in (direto, kit or {}):
        if not (r.get("encontrado") or r.get("chunks") or r.get("resposta")):
            continue
        junto["encontrado"] = True
        if r is direto and r.get("resposta"):
            junto["resposta"] = r["resposta"]
        for c in r.get("chunks") or []:
            chave = str(c.get("conteudo") or "")
            if chave and chave not in vistos:
                vistos.add(chave)
                junto["chunks"].append(c)
    return junto


def _consultar_consultor(estado: dict[str, Any], mensagem: str) -> dict[str, Any] | None:
    from app import consultor
    from app.rag import formatar_sem_catalogo

    try:
        id_cliente = str(estado.get("id_cliente") or "")
        historico = db.historico_recente(id_cliente, limite=10) if id_cliente else []
        base = formatar_sem_catalogo(base_de_venda(estado, mensagem if not mensagem.startswith("(") else ""))
        return consultor.recomendar(estado, mensagem, listar_planos(estado), historico=historico, base=base)
    except Exception:  # noqa: BLE001 — sem consultor, o fluxo de sempre continua valendo
        logger.exception("Falha no consultor de planos")
        return None


def _recomendar_plano(estado: dict[str, Any], decisao: Decisao) -> Decisao:
    """Cliente contou o que procura: indica o plano certo, reforça o atual ou pergunta o que falta."""
    ctx = decisao.contexto_resposta or {}
    mensagem = str(ctx.get("mensagem") or "")
    aguardando_antes = str(ctx.get("aguardando_antes") or "confirmacao_plano")
    estado_antes = {**estado, "aguardando": aguardando_antes}
    sinais = list(ctx.get("sinais") or [])

    rec = _consultar_consultor(estado_antes, mensagem)
    if rec is None:
        # Sem o consultor (modelo fora do ar, resposta inválida): o caminho de sempre
        resolucao = dict(ctx.get("resolucao") or {})
        resolucao["_sem_consultor"] = True
        resolucao["_era_do_consultor"] = True
        return _com_contexto(decidir(estado_antes, resolucao), sinais=sinais)

    plano, abertura = rec.get("plano"), str(rec.get("abertura") or "")
    atual_id = estado.get("plano_em_negociacao_id") or estado.get("plano_apresentado_id")
    if plano is None:
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="PERGUNTAR_NECESSIDADE",
            fase="vendas",
            aguardando=aguardando_antes,
            atualizar_dados={},
            motivo="Consultor precisa saber o que o cliente procura",
            prioridade="PLANO",
            contexto_resposta={"texto_do_consultor": abertura, "sinais": [*sinais, "descoberta"]},
        )
    try:
        mesmo = atual_id is not None and int(plano["id"]) == int(atual_id)
    except (TypeError, ValueError, KeyError):
        mesmo = False
    if mesmo:
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="REFORCAR_PLANO",
            fase="vendas",
            aguardando="confirmacao_plano",
            atualizar_dados={
                "plano_em_negociacao": plano["nome"], "plano_em_negociacao_id": int(plano["id"]),
            },
            motivo="Plano em conversa já atende ao que o cliente contou",
            prioridade="PLANO",
            contexto_resposta={"texto_do_consultor": abertura, "plano": plano, "sinais": [*sinais, "plano_reforcado"]},
        )
    planos = listar_planos(estado)
    try:
        atual = int(atual_id) if atual_id is not None else None
    except (TypeError, ValueError):
        atual = None
    resultado = resolver_plano(str(plano["nome"]), planos, plano_atual_id=atual)
    resultado["referencia"] = str(plano["nome"])
    return _com_contexto(
        decidir_plano_resolvido(resultado, estado_antes),
        abertura_plano=abertura, sinais=[*sinais, "plano_recomendado"],
    )


def _enriquecer_com_rag(
    decisao: Decisao,
    estado: dict[str, Any],
    mensagem: str,
) -> Decisao:
    """Consulta a RAG quando o cliente faz pergunta — é a fonte das respostas a dúvidas."""
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
    # Cancelamento e instalação também saem da RAG (é lá que fica a informação da empresa).
    # Sem conteúdo na RAG, estes dois mantêm o objetivo e caem no texto de reserva.
    objetivos_com_texto_reserva = {
        "INFORMAR_CANCELAMENTO_E_RETOMAR",
        "INFORMAR_INSTALACAO_E_RETOMAR",
    }
    ctx_dec = decisao.contexto_resposta or {}
    # Objeção de preço ou "não tenho esse dado": a base pode trazer o argumento ou a alternativa
    situacao = str((ctx_dec.get("conversa") or {}).get("situacao") or "")
    if situacao in {"OBJECAO_PRECO", "OBJECAO"} or decisao.objetivo_resposta == "RESPONDER_DUVIDA_NA_VENDA":
        rag = base_de_venda(estado, pergunta or mensagem)
        if rag.get("encontrado"):
            decisao.contexto_resposta = {**ctx_dec, "rag": rag}
        return decisao
    if situacao == "IMPEDIMENTO":
        rag = consultar_rag(pergunta=mensagem, mensagem=mensagem, estado=estado, plano=None)
        if rag.get("encontrado") or rag.get("chunks") or rag.get("resposta"):
            decisao.contexto_resposta = {**ctx_dec, "rag": rag}
        return decisao
    if situacao:
        return decisao

    if not pergunta and decisao.objetivo_resposta not in (
        objetivos_com_rag | objetivos_com_texto_reserva
    ):
        return decisao

    if decisao.objetivo_resposta == "PEDIR_ACEITE_TERMOS":
        return decisao
    plano = ctx_dec.get("plano") or {}
    rag = _consultar_rag_por_pergunta(
        _perguntas_da_mensagem(pergunta or mensagem, mensagem),
        mensagem=mensagem,
        estado=estado,
        plano=plano if isinstance(plano, dict) else None,
    )
    tem_conteudo = bool(
        rag.get("encontrado") or rag.get("chunks") or rag.get("resposta")
    )
    if not tem_conteudo:
        if rag.get("erro"):
            # Webhook da base caiu ou demorou: não é falta de conteúdo
            ctx_dec = {**ctx_dec, "rag_fora": True}
            decisao.contexto_resposta = ctx_dec
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


# Falhas seguidas do modelo por cliente (em memória: some se a API reiniciar, e tudo bem)
_FALHAS_LLM: dict[str, int] = {}
LIMITE_FALHAS_LLM = 2

_EVENTOS_QUE_MUDAM_O_FUNIL = {
    "CONFIRMACAO", "NEGACAO", "PLANO_INFORMADO", "PEDIU_TROCAR_PLANO", "PEDIU_HUMANO",
    "LOCALIZACAO_INFORMADA", "PEDIU_TROCAR_LOCALIZACAO",
}


def divergencias_regra_modelo(raw: str, interpretacao: Any) -> list[str]:
    """Onde as regras do parser mudaram o que o modelo leu (para auditar depois).

    As regras por palavra-chave corrigem o modelo, mas também erram com frases novas.
    Guardar a diferença turno a turno mostra, com conversa real, qual regra ajuda e qual atrapalha.
    """
    from app.parser import _strip_markdown
    from app.resolver import normalizar_campo

    try:
        data = json.loads(_strip_markdown(raw))
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    dados_llm = data.get("dados") if isinstance(data.get("dados"), dict) else {}
    finais = interpretacao.dados.model_dump()
    out: list[str] = []
    for campo, final in finais.items():
        lido = str(dados_llm.get(campo) or "").strip()
        final = str(final or "").strip()
        if not lido or normalizar_campo(campo, lido) == normalizar_campo(campo, final):
            continue
        out.append(f"{campo}: modelo leu {lido!r}, " + (f"regras gravaram {final!r}" if final else "regras descartaram"))
    ev_llm = {str(e).upper() for e in (data.get("eventos") or []) if isinstance(e, str)}
    ev_final = set(interpretacao.eventos or [])
    for ev in sorted((ev_llm ^ ev_final) & _EVENTOS_QUE_MUDAM_O_FUNIL):
        out.append(f"{ev}: " + ("regras tiraram" if ev in ev_llm else "regras acrescentaram"))
    return out[:12]


def _decisao_com_modelo_fora(decisao: Decisao, estado: dict[str, Any], id_cliente: str) -> Decisao:
    """Modelo indisponível neste turno: o cliente não pode ficar sem resposta.

    As regras ainda leem dados claros (CPF, e-mail, "sim"); se com isso o atendimento
    avançou, segue normal. Se não, a Eva diz que teve uma instabilidade e pede para
    mandar de novo. Na segunda falha seguida, chama a equipe.
    """
    from app import conversa

    fase = str(estado.get("fase") or "inicio")
    if fase in {"transferido", "finalizado"} or decisao.acao in {"AGUARDAR", "TRANSFERIR_HUMANO"}:
        return decisao
    sinais = ["llm_fora_do_ar"]
    avancou = decisao.acao != "RESPONDER" or conversa._avancou(decisao, estado) or (
        decisao.fase != fase or str(decisao.aguardando or "") != str(estado.get("aguardando") or "")
    )
    ctx = dict(decisao.contexto_resposta or {})
    ctx.pop("conversa", None)
    ctx["llm_fora"] = True
    if avancou:
        # As regras leram o dado (CPF, telefone, "sim"): o atendimento segue sem o modelo
        ctx["sinais"] = [*ctx.get("sinais", []), *sinais]
        decisao.contexto_resposta = ctx
        return decisao
    if _FALHAS_LLM.get(id_cliente, 0) >= LIMITE_FALHAS_LLM:
        _FALHAS_LLM.pop(id_cliente, None)
        return conversa._transferir(
            estado,
            situacao="TRANSFERENCIA_INSTABILIDADE",
            motivo="Modelo de IA indisponível em mensagens seguidas — atendimento passado para a equipe",
            sinais=[*sinais, "transferido_por_instabilidade"],
        )
    ctx["sinais"] = sinais  # o turno não é "cliente travado": quem falhou foi o modelo
    return Decisao(
        acao="RESPONDER",
        objetivo_resposta="INSTABILIDADE_PEDIR_REENVIO",
        fase=fase,
        aguardando=estado.get("aguardando"),
        atualizar_dados={},
        motivo="Modelo de IA indisponível — pedir para o cliente mandar de novo",
        prioridade="GLOBAL",
        contexto_resposta=ctx,
    )


def _anotar_assunto_explicado(id_cliente: str, estado: dict[str, Any], pergunta: str) -> None:
    """Guarda nas notas o que a Eva já explicou, para não repetir quando sair do histórico recente."""
    from app import conversa

    try:
        notas = conversa.juntar_explicado(estado.get("notas_conversa"), pergunta)
        if notas != str(estado.get("notas_conversa") or ""):
            db.salvar_transicao(
                id_cliente, str(estado.get("fase") or "inicio"), estado.get("aguardando"),
                {"notas_conversa": notas},
            )
    except Exception:  # noqa: BLE001 — anotação nunca derruba o atendimento
        logger.exception("Falha ao anotar assunto explicado")


def _perguntas_da_mensagem(pergunta: str, mensagem: str) -> list[str]:
    """Mensagem com mais de uma pergunta ("tem multa? e a instalação demora?") → uma busca por pergunta."""
    import re

    partes = [p.strip(" ,;.-") for p in re.findall(r"[^?]+\?", mensagem or "")]
    partes = [p for p in partes if len(p.split()) >= 2]
    if len(partes) < 2:
        return [pergunta or mensagem]
    return partes[:3]


def _consultar_rag_por_pergunta(
    perguntas: list[str], *, mensagem: str, estado: dict[str, Any], plano: dict[str, Any] | None
) -> dict[str, Any]:
    """Uma consulta por pergunta, com os trechos reunidos sem repetir."""
    if len(perguntas) == 1:
        return consultar_rag(pergunta=perguntas[0], mensagem=mensagem, estado=estado, plano=plano)
    junto: dict[str, Any] = {"encontrado": False, "resposta": "", "chunks": [], "fontes": []}
    vistos: set[str] = set()
    erros = 0
    for p in perguntas:
        r = consultar_rag(pergunta=p, mensagem=mensagem, estado=estado, plano=plano)
        erros += bool(r.get("erro"))
        if not (r.get("encontrado") or r.get("chunks") or r.get("resposta")):
            continue
        junto["encontrado"] = True
        if r.get("resposta") and r["resposta"] not in junto["resposta"]:
            junto["resposta"] = f"{junto['resposta']}\n{r['resposta']}".strip()
        for c in r.get("chunks") or []:
            chave = str(c.get("conteudo") or "")
            if chave and chave not in vistos:
                vistos.add(chave)
                junto["chunks"].append(c)
        junto["fontes"] += [f for f in (r.get("fontes") or []) if f not in junto["fontes"]]
    if erros == len(perguntas):
        junto["erro"] = True
    return junto


def _registrar_pergunta_sem_resposta(
    estado: dict[str, Any], decisao: Decisao, mensagem: str, *, motivo: str = "base de conhecimento sem resposta"
) -> None:
    """A Eva disse que vai confirmar com a equipe: a equipe precisa ficar sabendo.

    A pergunta entra na lista do painel (para completar a RAG) e vira nota privada
    na conversa do Chatwoot. Falha aqui nunca derruba o atendimento.
    """
    id_cliente = str(estado.get("id_cliente") or "")
    pergunta = str(decisao.pergunta or mensagem or "").strip()
    if not id_cliente or not pergunta:
        return
    try:
        db.registrar_pergunta_sem_resposta(
            id_cliente,
            pergunta,
            mensagem=mensagem,
            fase=str(estado.get("fase") or ""),
            motivo=motivo,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao registrar pergunta sem resposta")
    cid = str(estado.get("conversation_id") or "").strip()
    if not cid:
        return
    from app.integrations.chatwoot import enviar_mensagem

    nota = (
        f'[Eva] Não encontrei na base de conhecimento a resposta para: "{pergunta[:300]}". '
        "Respondi que vou confirmar com a equipe."
    )
    # Em segundo plano: a nota não pode atrasar a resposta ao cliente
    threading.Thread(
        target=enviar_mensagem, args=(cid, nota), kwargs={"private": True}, daemon=True
    ).start()


def process_message(
    id_cliente: str,
    mensagem: str,
    *,
    conversation_id: str | None = None,
    contact_id: str | None = None,
    message_id: str | None = None,
    sinais_extra: list[str] | None = None,
) -> TurnoResultado:
    t0 = time.perf_counter()
    mensagem = (mensagem or "").strip()
    if not mensagem:
        raise ValueError("Mensagem vazia")

    from app import custos

    custos.definir_cliente(id_cliente)  # o custo das chamadas deste turno é deste cliente
    estado = db.carregar_ou_criar_estado(id_cliente)
    # Dado ditado por áudio ("maria arroba gmail ponto com", "cinco dois nove...") vira o
    # texto que o cliente digitaria — é o que as regras de cadastro sabem conferir.
    from app.fala import normalizar_fala

    mensagem = normalizar_fala(
        mensagem,
        aguardando=str(estado.get("aguardando") or ""),
        audio="audio_transcrito" in (sinais_extra or []),
    ).strip() or mensagem
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
    historico_prev = db.historico_recente(id_cliente, limite=13)
    estado_antes = snapshot_estado(estado)

    from app import conversa

    llm_fora = False
    if conversa.tipo_de_midia(mensagem):
        # Áudio/imagem sem texto: não há o que interpretar (ver conversa.MIDIA)
        raw = json.dumps({"eventos": ["OUTRO"], "dados": {}, "confianca": 0.99})
    else:
        try:
            raw = interpretar(mensagem, estado, historico=historico_prev)
            _FALHAS_LLM.pop(id_cliente, None)
        except Exception:  # noqa: BLE001 — modelo fora do ar não pode virar silêncio
            logger.exception("Interpretador indisponível para %s", id_cliente)
            llm_fora = True
            _FALHAS_LLM[id_cliente] = _FALHAS_LLM.get(id_cliente, 0) + 1
            # Sem o modelo, só as regras leem a mensagem (CPF, e-mail, "sim"...)
            raw = json.dumps({"eventos": ["OUTRO"], "dados": {}, "confianca": 0})
    interpretacao = parse_interpretacao(raw, mensagem, estado)
    divergencias = [] if llm_fora else divergencias_regra_modelo(raw, interpretacao)

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
    if interpretacao.nota:
        notas = conversa.juntar_nota(estado.get("notas_conversa"), interpretacao.nota)
        if notas != str(estado.get("notas_conversa") or ""):
            topico_meta["notas_conversa"] = notas
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
    if llm_fora:
        decisao = _decisao_com_modelo_fora(decisao, estado, id_cliente)
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

    sinais_do_turno: list[str] = list((decisao.contexto_resposta or {}).get("sinais") or [])
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
        sinais_do_turno += list((decisao.contexto_resposta or {}).get("sinais") or [])

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
        historico = db.historico_recente(id_cliente, limite=12)
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

    sinais = [
        str(s)
        for s in [*(sinais_extra or []), *sinais_do_turno, *(ctx_final.get("sinais") or [])]
        if s
    ]
    if decisao.objetivo_resposta == "CLARIFICAR_INTENCAO":
        sinais.append("esclarecimento")
    if decisao.acao == "AGUARDAR":
        sinais.append("silencio")
    sem_base = bool(ctx_final.get("sem_base") or ctx_final.get("rag_vazia"))
    if ctx_final.get("rag_fora"):
        sinais.append("rag_fora_do_ar")
    if sem_base and decisao.acao != "AGUARDAR":
        sinais.append("sem_base")
        _registrar_pergunta_sem_resposta(
            estado, decisao, mensagem,
            motivo=(
                "base de conhecimento fora do ar" if ctx_final.get("rag_fora")
                else "resposta barrada: citava dado que não estava na base" if ctx_final.get("resposta_barrada")
                else "base de conhecimento sem resposta"
            ),
        )
    elif decisao.pergunta and decisao.acao == "RESPONDER" and rag_hit and not ctx_final.get("conversa"):
        # Só dúvida respondida vira "já explicado" (objeção contornada não é pergunta)
        _anotar_assunto_explicado(id_cliente, estado, decisao.pergunta)
    if divergencias:
        sinais.append("regra_mudou_leitura")
    sinais = list(dict.fromkeys(sinais))

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
        sinais=sinais,
        divergencias=divergencias,
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
