"""State Machine única — decide ação. Não interpreta NL. Não conversa.

Sequência do funil (ordem fixa):
  localização → planos → cadastro → aceite termos → ativação → agendamento → encerramento
Ver FLUXO_SOFIA.md
"""

from __future__ import annotations

import re
from typing import Any

from app.models import Decisao
from app.validation import rua_parece_eco_nome, validar_campo

TENTATIVAS_MAX = 3

ORDEM_CADASTRO = [
    "nome",
    "cpf",
    "email",
    "telefone",
    "data_nascimento",
    "cep",
    "rua",
    "numero",
]


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _detectar_beneficio_pergunta(texto_q: str) -> str | None:
    """Retorna rótulo do benefício se a pergunta for sobre ele."""
    mapa = [
        (("disney", "disney+"), "Disney+"),
        (("mesh", "repetidor", "roteador"), "Mesh"),
        (("telemedicina",), "telemedicina"),
        (("exitlag", "jogo", "game"), "ExitLag"),
        (("kaspersky", "antivirus", "antivírus"), "Kaspersky"),
        (("ubook",), "Ubook"),
        (("imagina",), "Imagina Só"),
    ]
    for keys, rotulo in mapa:
        if any(k in texto_q for k in keys):
            return rotulo
    return None


def _campo_ok(estado: dict[str, Any], dados: dict[str, Any], campo: str) -> bool:
    if campo == "cpf":
        cpf_val = _texto(dados.get("cpf") or estado.get("cpf"))
        validado = dados.get("documento_cpf_validado")
        if validado is None:
            validado = estado.get("documento_cpf_validado")
        return bool(cpf_val) and bool(validado)
    if campo in {"cep", "telefone"}:
        val = re.sub(r"\D", "", _texto(dados.get(campo) or estado.get(campo)))
        if campo == "cep":
            return len(val) == 8
        return len(val) >= 10
    if campo == "rua":
        val = _texto(dados.get("rua") or estado.get("rua"))
        if not val or len(val) < 3:
            return False
        nome_ref = _texto(dados.get("nome") or estado.get("nome"))
        if rua_parece_eco_nome(val, nome_ref):
            return False
        return True
    return bool(_texto(dados.get(campo) or estado.get(campo)))


def _proximo_cadastro(estado: dict[str, Any], dados: dict[str, Any]) -> str | None:
    for campo in ORDEM_CADASTRO:
        if not _campo_ok(estado, dados, campo):
            return campo
    return None


def _imagens_enviadas_ids(estado: dict[str, Any]) -> set[int]:
    raw = estado.get("imagens_plano_enviadas")
    out: set[int] = set()
    if isinstance(raw, str) and raw.strip():
        try:
            import json

            raw = json.loads(raw)
        except Exception:
            raw = []
    if isinstance(raw, (list, tuple, set)):
        for x in raw:
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
    # Compat: flag antiga + id do plano em negociação
    if estado.get("imagem_plano_enviada"):
        for key in (
            "plano_confirmado_id",
            "plano_em_negociacao_id",
            "plano_apresentado_id",
        ):
            try:
                if estado.get(key) is not None:
                    out.add(int(estado[key]))
            except (TypeError, ValueError):
                pass
    return out


def _plano_tem_imagem_painel(plano_id: Any) -> bool:
    try:
        from app.planos_admin import obter_plano

        p = obter_plano(int(plano_id))
        return bool(p and str(p.get("imagem_url") or "").strip())
    except Exception:
        return False


def _pode_disparar_imagem_plano(estado: dict[str, Any], plano_id: Any = None) -> bool:
    """Há imagem no painel, ou provider webhook/mock configurado."""
    from app.config import get_settings
    from app.ferramentas_catalog import resolver_url_ferramenta

    if plano_id is not None and _plano_tem_imagem_painel(plano_id):
        # Chat local ou produção: dá para ofertar a imagem do painel
        return True

    settings = get_settings()
    provider = (settings.imagem_plano_provider or "mock").lower()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "enviar_imagem_plano",
        unidade_id=uid,
        fallback_env=settings.imagem_plano_webhook_url,
    )
    tem_conv = bool(_texto(estado.get("conversation_id")))
    if provider == "mock":
        return True
    return provider == "webhook" and bool(url) and tem_conv


def _imagem_pendente_para_plano(estado: dict[str, Any], plano_id: Any) -> bool:
    """
    Imagem só para plano único — e só se ainda não enviou deste id.
    Lista completa nunca chama isto; pergunta de detalhes não reenvia.
    """
    if plano_id is None or str(plano_id).strip() == "":
        return False
    try:
        pid = int(plano_id)
    except (TypeError, ValueError):
        return False
    if pid in _imagens_enviadas_ids(estado):
        return False
    # Imagem cadastrada no painel → envia (Chatwoot / webhook / chat local)
    if _plano_tem_imagem_painel(pid):
        return True
    # Fallback legado n8n (mapa por id) só com conversation + webhook
    from app.config import get_settings
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    if (settings.imagem_plano_provider or "").lower() != "webhook":
        return False
    if not _texto(estado.get("conversation_id")):
        return False
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "enviar_imagem_plano",
        unidade_id=uid,
        fallback_env=settings.imagem_plano_webhook_url,
    )
    return bool(url)


def _dec_apresentar_plano_unico(
    *,
    estado: dict[str, Any],
    plano: dict[str, Any],
    dados: dict[str, Any],
    objetivo: str,
    aguardando: str,
    motivo: str,
    contexto_extra: dict[str, Any] | None = None,
) -> Decisao:
    """Apresenta um plano; envia imagem antes (se pendente). Nunca usar para lista completa."""
    extra = dict(contexto_extra or {})
    if _imagem_pendente_para_plano(estado, plano.get("id")):
        return Decisao(
            acao="ENVIAR_IMAGEM_PLANO",
            objetivo_resposta=None,
            fase="vendas",
            aguardando="resultado_imagem_plano",
            atualizar_dados=dados,
            contexto_resposta={
                "pos_imagem": {
                    "objetivo": objetivo,
                    "fase": "vendas",
                    "aguardando": aguardando,
                    "pergunta": "",
                },
                "plano": plano,
                **extra,
            },
            motivo=f"{motivo} — enviar imagem do plano",
            prioridade="PLANO",
        )
    return Decisao(
        acao="RESPONDER",
        objetivo_resposta=objetivo,
        fase="vendas",
        aguardando=aguardando,
        atualizar_dados=dados,
        contexto_resposta={"plano": plano, **extra},
        motivo=motivo,
        prioridade="PLANO",
    )


def _campos_cadastro_permitidos(
    aguardando: str,
    correcoes: list[str] | None = None,
) -> set[str]:
    """Campo pendente, pares seguintes e correções explícitas."""
    if aguardando not in ORDEM_CADASTRO:
        return set()
    idx = ORDEM_CADASTRO.index(aguardando)
    permitidos = set(ORDEM_CADASTRO[idx:])
    for c in correcoes or []:
        if c in ORDEM_CADASTRO:
            permitidos.add(c)
    return permitidos


def _filtrar_campos_cadastro_pendente(
    aguardando: str | None,
    campos_info: list[str],
    correcoes: list[str],
) -> tuple[list[str], bool]:
    """
    Aceita o campo pendente e campos seguintes na ordem do cadastro.
    Eco do LLM em campos anteriores (ex.: nome quando pedimos rua) é ignorado.
    """
    if not aguardando or aguardando == "confirmacao_dados":
        return campos_info, False
    if aguardando not in ORDEM_CADASTRO:
        return campos_info, False

    cadastro_campos = [c for c in campos_info if c in ORDEM_CADASTRO]
    if not cadastro_campos:
        return campos_info, False

    permitidos = _campos_cadastro_permitidos(aguardando, correcoes)
    aceitos = [c for c in cadastro_campos if c in permitidos]
    rejeitados = [c for c in cadastro_campos if c not in permitidos]
    if rejeitados and not aceitos:
        return [], True
    return aceitos, False


def _correcoes_no_par(
    aguardando: str | None,
    correcoes: list[str],
) -> list[str]:
    """Correções só em campos permitidos (pendente + seguintes)."""
    if not aguardando or aguardando not in ORDEM_CADASTRO:
        return list(correcoes)

    permitidos = {c.lower() for c in _campos_cadastro_permitidos(aguardando, correcoes)}
    return [c for c in correcoes if c.lower() in permitidos]


def _dados_sem_campos_rejeitados(
    dados: dict[str, Any],
    campos_ok: list[str],
) -> dict[str, Any]:
    rejeitados = set(ORDEM_CADASTRO) - set(campos_ok)
    if not rejeitados:
        return dict(dados)
    return {k: v for k, v in dados.items() if k not in rejeitados}


def _pendente_cadastro_apos_anotacao(
    estado: dict[str, Any],
    dados: dict[str, Any],
    aguardando: str | None,
    campos_anotados: list[str] | None,
) -> str | None:
    """Após anotar dado(s) no cadastro, retorna o próximo campo faltante."""
    if not campos_anotados:
        return aguardando
    anotados = {c for c in campos_anotados if c in ORDEM_CADASTRO}
    if not anotados:
        return aguardando
    merged = {**estado, **dados}
    return _proximo_cadastro(estado, merged) or aguardando


def _objetivo_pedir(campo: str) -> str:
    return f"PEDIR_{campo.upper()}"


def _cadastro_travado(estado: dict[str, Any]) -> bool:
    """Depois que o cliente confirma o resumo, plano não pode mais mudar."""
    return bool(estado.get("cadastro_completo")) or _texto(estado.get("fase")) in {
        "finalizado",
        "pos_venda",
    }


def _decidir_pos_venda(
    estado: dict[str, Any],
    resolucao: dict[str, Any],
    dados_base: dict[str, Any],
    flags: dict[str, Any],
    dec,
) -> Decisao:
    from app.pos_venda_mensagens import mensagem_sem_duvidas

    pergunta = _texto(resolucao.get("pergunta") or "")
    mensagem = _texto(resolucao.get("mensagem") or "")

    if flags.get("negacao") or mensagem_sem_duvidas(mensagem):
        return dec(
            "ENCERRAR_ATENDIMENTO",
            None,
            "pos_venda",
            "resultado_encerrar",
            dados_base,
            "Cliente sem mais dúvidas — encerrar",
            "POS_VENDA",
        )

    if flags.get("tem_pergunta") or pergunta:
        return dec(
            "RESPONDER",
            "RESPONDER_DUVIDA_E_RETOMAR",
            "pos_venda",
            "duvidas",
            dados_base,
            "Responder dúvida pós-agendamento",
            "POS_VENDA",
            contexto={"pendente": "duvidas"},
            pergunta=pergunta or mensagem,
        )

    if flags.get("confirmacao"):
        return dec(
            "RESPONDER",
            "PEDIR_FALAR_DUVIDA",
            "pos_venda",
            "duvidas",
            dados_base,
            "Cliente disse sim — pedir a dúvida",
            "POS_VENDA",
        )

    # Qualquer outro texto na fase de dúvidas trata como pergunta
    if mensagem:
        return dec(
            "RESPONDER",
            "RESPONDER_DUVIDA_E_RETOMAR",
            "pos_venda",
            "duvidas",
            dados_base,
            "Texto livre como dúvida pós-venda",
            "POS_VENDA",
            contexto={"pendente": "duvidas"},
            pergunta=mensagem,
        )

    return dec(
        "RESPONDER",
        "PEDIR_DUVIDAS",
        "pos_venda",
        "duvidas",
        dados_base,
        "Retomar pedido de dúvidas",
        "POS_VENDA",
    )


def _salvar_desvio_cadastro(estado: dict[str, Any], dados: dict[str, Any]) -> dict[str, Any]:
    """Guarda posição do cadastro antes de ir para troca de plano."""
    d = dict(dados)
    if _texto(estado.get("fase")) == "cadastro" or _texto(estado.get("fase_anterior")) == "cadastro":
        d["fase_anterior"] = "cadastro"
        d["aguardando_anterior"] = (
            _texto(estado.get("aguardando_anterior"))
            or _texto(estado.get("aguardando"))
            or "nome"
        )
    return d


def _decisao_retomar_cadastro(
    estado: dict[str, Any],
    dados: dict[str, Any],
    *,
    campos_anotados: list[str] | None = None,
    campos_corrigidos: list[str] | None = None,
    motivo: str = "",
) -> Decisao:
    d = dict(dados)
    d["limpar_desvio"] = True
    nome_ref = _texto(d.get("nome") or estado.get("nome"))
    if rua_parece_eco_nome(_texto(d.get("rua") or estado.get("rua")), nome_ref):
        d["rua"] = ""
    faltando = _proximo_cadastro(estado, d)
    ctx = {
        "campos_anotados": campos_anotados or [],
        "campos_corrigidos": campos_corrigidos or [],
        "pendente": faltando or "confirmacao_dados",
    }
    if faltando:
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="ANOTAR_E_PEDIR_PROXIMO" if (campos_anotados or campos_corrigidos) else _objetivo_pedir(faltando),
            fase="cadastro",
            aguardando=faltando,
            atualizar_dados=d,
            contexto_resposta=ctx,
            motivo=motivo or f"Retomar cadastro — pedir {faltando}",
            prioridade="CADASTRO",
        )
    return Decisao(
        acao="RESPONDER",
        objetivo_resposta="CONFIRMAR_DADOS_CADASTRO",
        fase="cadastro",
        aguardando="confirmacao_dados",
        atualizar_dados=d,
        contexto_resposta=ctx,
        motivo=motivo or "Dados básicos completos — confirmar",
        prioridade="CADASTRO",
    )


def _eh_contexto_cancelamento(texto: str, topico: str) -> bool:
    from app.parser import normalizar_texto

    t = normalizar_texto(texto)
    if topico == "cancelamento":
        return True
    return any(
        p in t
        for p in (
            "cancelar",
            "cancelamento",
            "multa",
            "fidelidade",
            "pagar se eu cancelar",
            "tenho que pagar",
            "opcoes de que",
            "opções de que",
        )
    )


def _decidir_termos(
    estado: dict[str, Any],
    resolucao: dict[str, Any],
    dados_base: dict[str, Any],
    flags: dict[str, Any],
    dec,
    aguardando: str | None,
) -> Decisao:
    from app.parser import eh_aceite_termos_explicito, normalizar_texto

    pergunta = _texto(resolucao.get("pergunta") or "")
    msg = _texto(resolucao.get("mensagem") or "")
    topico = _texto(resolucao.get("topico_contexto") or estado.get("ultimo_topico") or "")

    if flags.get("tem_pergunta") or pergunta:
        texto_q = pergunta or msg
        if _eh_contexto_cancelamento(texto_q, topico):
            return dec(
                "RESPONDER",
                "RESPONDER_DUVIDA_E_RETOMAR_TERMOS",
                "termos",
                "aceite_termos",
                dados_base,
                "Dúvida sobre cancelamento/multa — explicar e retomar aceite",
                "TERMOS",
                contexto={
                    "pendente": "aceite_termos",
                    "topico_contexto": "cancelamento",
                },
                pergunta=texto_q,
            )
        if not flags.get("confirmacao"):
            return dec(
                "RESPONDER",
                "RESPONDER_DUVIDA_E_RETOMAR_TERMOS",
                "termos",
                "aceite_termos",
                dados_base,
                "Dúvida sobre termos — responder e retomar aceite",
                "TERMOS",
                contexto={"pendente": "aceite_termos"},
                pergunta=texto_q,
            )

    if aguardando == "aceite_termos":
        if flags.get("confirmacao"):
            msg_n = normalizar_texto(msg)
            em_duvida_cancelamento = (
                topico == "cancelamento"
                or _texto(estado.get("ultimo_topico")) == "cancelamento"
            )
            aceite_claro = eh_aceite_termos_explicito(msg)
            sim_aceite = msg_n == "sim" and not em_duvida_cancelamento
            if not aceite_claro and not sim_aceite:
                ctx = {
                    "pendente": "aceite_termos",
                    "topico_contexto": "cancelamento",
                    "esclarecer_aceite": True,
                }
                if em_duvida_cancelamento or msg_n == "sim":
                    return dec(
                        "RESPONDER",
                        "RESPONDER_DUVIDA_E_RETOMAR_TERMOS",
                        "termos",
                        "aceite_termos",
                        dados_base,
                        "Sim ambíguo após dúvida de cancelamento",
                        "TERMOS",
                        pergunta=(
                            "Como funciona a multa se eu cancelar antes dos 12 meses?"
                        ),
                        contexto=ctx,
                    )
                return dec(
                    "RESPONDER",
                    "PEDIR_ACEITE_TERMOS",
                    "termos",
                    "aceite_termos",
                    dados_base,
                    "Confirmação ambígua — pedir aceite explícito do termo",
                    "TERMOS",
                    contexto={"pendente": "aceite_termos", "pedir_aceite_explicito": True},
                )
            d = dict(dados_base)
            d["fidelidade_aceita"] = True
            return dec(
                "ATIVAR_CLIENTE",
                None,
                "agendamento",
                "resultado_ativacao",
                d,
                "Termos aceitos — ativar contrato IXC",
                "ATIVACAO",
            )
        if flags.get("negacao"):
            d = dict(dados_base)
            d["transferido_humano"] = True
            d["motivo_transferencia"] = "Cliente não aceitou termos de fidelidade"
            return dec(
                "TRANSFERIR_HUMANO",
                "INFORMAR_RECUSA_TERMOS",
                "transferido",
                None,
                d,
                "Recusa dos termos",
                "TERMOS",
            )

    return dec(
        "RESPONDER",
        "PEDIR_ACEITE_TERMOS",
        "termos",
        "aceite_termos",
        dados_base,
        "Aguardando aceite dos termos",
        "TERMOS",
    )


def _decidir_agendamento(
    estado: dict[str, Any],
    resolucao: dict[str, Any],
    dados_base: dict[str, Any],
    flags: dict[str, Any],
    dec,
    aguardando: str | None,
) -> Decisao:
    from app.agenda_slots import slot_valido

    cadastro = resolucao.get("cadastro") or {}
    campos_info = list(cadastro.get("campos_informados") or [])
    turno = _texto(dados_base.get("turno_escolhido") or estado.get("horario_escolhido"))
    data = _texto(estado.get("data_agendamento") or dados_base.get("data_agendamento"))
    preferencia = _texto(dados_base.get("complemento") or estado.get("preferencia_horario"))

    # Confirmação do horário escolhido
    if aguardando == "confirmacao_horario":
        if flags.get("confirmacao"):
            d = dict(dados_base)
            horario = _texto(estado.get("horario_escolhido") or turno)
            d["horario_escolhido"] = horario
            d["agendamento_confirmado"] = True
            return dec(
                "INSERIR_AGENDAMENTO",
                None,
                "agendamento",
                "resultado_inserir_agenda",
                d,
                "Cliente confirmou horário — gravar na OS",
                "AGENDAMENTO",
                contexto={"horario": horario, "data": data},
            )
        if flags.get("negacao"):
            d = {k: v for k, v in dados_base.items() if k != "turno_escolhido"}
            d["horario_escolhido"] = ""
            return dec(
                "RESPONDER",
                "RETOMAR_ESCOLHA_HORARIO",
                "agendamento",
                "escolha_horario",
                d,
                "Cliente quer outro horário",
                "AGENDAMENTO",
            )
        if turno and turno not in {"__INVALIDO__"} and not turno.startswith("__AMBIGUO__"):
            if slot_valido(turno, estado):
                d = dict(dados_base)
                d["horario_escolhido"] = turno
                return dec(
                    "RESPONDER",
                    "CONFIRMAR_HORARIO_ESCOLHIDO",
                    "agendamento",
                    "confirmacao_horario",
                    d,
                    "Novo horário para confirmar",
                    "AGENDAMENTO",
                    contexto={"horario": turno, "data": data},
                )

    # Escolha do horário
    if aguardando == "escolha_horario":
        from app.parser import normalizar_texto

        msg_ag = normalizar_texto(str(resolucao.get("mensagem") or ""))
        if msg_ag in {"sim", "ok", "pode", "blz", "beleza", "certo", "isso"} and not turno:
            return dec(
                "RESPONDER",
                "PEDIR_HORARIO_ESPECIFICO",
                "agendamento",
                "escolha_horario",
                dados_base,
                "Resposta genérica — pedir horário da lista",
                "AGENDAMENTO",
            )
        if flags.get("negacao"):
            d = dict(dados_base)
            if preferencia:
                d["preferencia_horario"] = preferencia
            return dec(
                "RESPONDER",
                "EXPLICAR_HORARIOS_UNICOS",
                "agendamento",
                "escolha_horario",
                d,
                "Cliente pediu horário fora da lista",
                "AGENDAMENTO",
                contexto={"preferencia": preferencia, "data": data},
            )

        if "turno_escolhido" in campos_info or turno:
            if turno == "__INVALIDO__":
                return dec(
                    "RESPONDER",
                    "HORARIO_NAO_DISPONIVEL",
                    "agendamento",
                    "escolha_horario",
                    {k: v for k, v in dados_base.items() if k != "turno_escolhido"},
                    "Horário não está na lista",
                    "AGENDAMENTO",
                )
            if turno.startswith("__AMBIGUO__:"):
                turno_ref = turno.split(":", 1)[-1]
                return dec(
                    "RESPONDER",
                    "HORARIO_AMBIGUO",
                    "agendamento",
                    "escolha_horario",
                    {k: v for k, v in dados_base.items() if k != "turno_escolhido"},
                    "Turno ambíguo — pedir horário exato",
                    "AGENDAMENTO",
                    contexto={"turno": turno_ref},
                )
            if turno and slot_valido(turno, {**estado, **dados_base}):
                d = dict(dados_base)
                d["horario_escolhido"] = turno
                return dec(
                    "RESPONDER",
                    "CONFIRMAR_HORARIO_ESCOLHIDO",
                    "agendamento",
                    "confirmacao_horario",
                    d,
                    "Horário escolhido — pedir confirmação",
                    "AGENDAMENTO",
                    contexto={"horario": turno, "data": data},
                )
            if turno:
                return dec(
                    "RESPONDER",
                    "HORARIO_NAO_DISPONIVEL",
                    "agendamento",
                    "escolha_horario",
                    {k: v for k, v in dados_base.items() if k != "turno_escolhido"},
                    "Horário inválido",
                    "AGENDAMENTO",
                )

        if flags.get("pediu_humano"):
            pass  # tratado globalmente antes
        elif flags.get("confirmacao") and _texto(estado.get("horario_escolhido")):
            d = dict(dados_base)
            d["agendamento_confirmado"] = True
            horario = _texto(estado.get("horario_escolhido"))
            return dec(
                "INSERIR_AGENDAMENTO",
                None,
                "agendamento",
                "resultado_inserir_agenda",
                d,
                "Confirmação direta do horário — gravar na OS",
                "AGENDAMENTO",
                contexto={
                    "horario": horario,
                    "data": data,
                },
            )

    return dec(
        "RESPONDER",
        "RETOMAR_ESCOLHA_HORARIO",
        "agendamento",
        aguardando or "escolha_horario",
        dados_base,
        "Retomar escolha de horário",
        "AGENDAMENTO",
        contexto={"pendente": aguardando or "escolha_horario"},
    )


def decidir(estado: dict[str, Any], resolucao: dict[str, Any]) -> Decisao:
    fase = _texto(estado.get("fase")) or "inicio"
    aguardando = estado.get("aguardando")
    flags = resolucao.get("flags") or {}
    loc = resolucao.get("localizacao") or {}
    plano = resolucao.get("plano") or {}
    cpf = resolucao.get("cpf") or {}
    cadastro = resolucao.get("cadastro") or {}
    invalidar = resolucao.get("invalidar") or {}
    correcoes = list(resolucao.get("correcao_efetiva") or [])
    campos_alterados = list(resolucao.get("campos_alterados") or [])
    dados_base = dict((resolucao.get("dados") or {}).get("para_salvar") or {})
    dados_base.pop("plano", None)

    # Correção implícita só em campos permitidos (pendente + seguintes).
    # Não transformar a rua ("sergio henn") em troca de nome.
    cadastro_permitidos = (
        _campos_cadastro_permitidos(str(aguardando), correcoes)
        if aguardando in ORDEM_CADASTRO
        else set()
    )
    correcoes = _correcoes_no_par(aguardando if isinstance(aguardando, str) else None, correcoes)
    for c in campos_alterados:
        if c in {"nome", "email", "telefone", "cpf"} and c not in correcoes:
            if cadastro_permitidos and c not in cadastro_permitidos:
                continue
            if aguardando in ORDEM_CADASTRO and c != aguardando and c not in cadastro_permitidos:
                continue
            correcoes.append(c)

    if invalidar.get("cobertura"):
        dados_base["resetar_cobertura"] = True
    # Só invalida plano se mudou endereço ANTES de confirmar — não no meio do cadastro
    if (
        invalidar.get("plano")
        and not _cadastro_travado(estado)
        and loc.get("alterada")
        and not estado.get("plano_confirmado")
        and fase not in {"cadastro", "sem_cobertura"}
    ):
        dados_base["invalidar_plano"] = True
    if loc.get("limpar_bairro_anterior"):
        dados_base["limpar_bairro"] = True

    def dec(
        acao: str,
        objetivo: str | None,
        fase_n: str = fase,
        aguardando_n: str | None = aguardando,
        dados: dict | None = None,
        motivo: str = "",
        prioridade: str = "NORMAL",
        contexto: dict | None = None,
        pergunta: str = "",
    ) -> Decisao:
        return Decisao(
            acao=acao,
            objetivo_resposta=objetivo,
            fase=fase_n,
            aguardando=aguardando_n,
            atualizar_dados=dados if dados is not None else dict(dados_base),
            pergunta=pergunta,
            motivo=motivo,
            contexto_resposta=contexto or {},
            prioridade=prioridade,
        )

    # Pin GPS do WhatsApp → viabilidade direta (lat,lng normalizado)
    from app.geo_coords import extrair_gps_mensagem, parece_coordenada

    msg_gps = str(resolucao.get("mensagem") or "")
    gps_fixa = extrair_gps_mensagem(msg_gps)
    if gps_fixa and fase in {"inicio", "viabilidade", "sem_cobertura"}:
        d = dict(dados_base)
        d["localizacao_fixa"] = gps_fixa
        if parece_coordenada(str(d.get("cidade") or "")):
            d.pop("cidade", None)
        if parece_coordenada(str(d.get("bairro") or "")):
            d.pop("bairro", None)
        d["tentativas_sem_cobertura"] = 0
        return dec(
            "CHECAR_COBERTURA",
            None,
            "viabilidade",
            "resultado_cobertura",
            d,
            "Localização GPS — checar cobertura",
            "GLOBAL_LOCALIZACAO",
        )

    # Terminais
    if fase == "transferido":
        return dec("AGUARDAR", None, "transferido", None, {}, "Já transferido", "TERMINAL")
    if fase == "finalizado":
        return dec("AGUARDAR", None, "finalizado", None, {}, "Já finalizado", "TERMINAL")

    # Pós-venda (após agendamento confirmado)
    if fase == "pos_venda":
        if flags.get("pediu_humano"):
            d = dict(dados_base)
            d["transferido_humano"] = True
            return dec(
                "TRANSFERIR_HUMANO",
                "INFORMAR_TRANSFERENCIA",
                "transferido",
                None,
                d,
                "Cliente pediu humano no pós-venda",
                "GLOBAL_HUMANO",
            )
        return _decidir_pos_venda(estado, resolucao, dados_base, flags, dec)

    # Humano
    if flags.get("pediu_humano"):
        d = dict(dados_base)
        d["transferido_humano"] = True
        return dec(
            "TRANSFERIR_HUMANO",
            "INFORMAR_TRANSFERENCIA",
            "transferido",
            None,
            d,
            "Cliente pediu humano",
            "GLOBAL_HUMANO",
        )

    # ── Plano bloqueado após cadastro fechado ──
    quer_mudar_plano = plano.get("pediu_troca_declarada") or (
        plano.get("informado") and not plano.get("repetido")
    )
    if quer_mudar_plano and _cadastro_travado(estado):
        return dec(
            "RESPONDER",
            "INFORMAR_PLANO_BLOQUEADO_POS_CADASTRO",
            fase,
            aguardando,
            {},
            "Cadastro já fechado — plano não muda mais",
            "GLOBAL_PLANO",
            contexto={"plano_atual": estado.get("plano_confirmado") or ""},
        )

    # Localização
    from app.parser import eh_pergunta_mudanca_endereco, tem_duvida_informativa

    msg_cliente = str(resolucao.get("mensagem") or "")

    pergunta_sobre_endereco = eh_pergunta_mudanca_endereco(msg_cliente) or (
        flags.get("tem_pergunta")
        and str(resolucao.get("topico_contexto") or "") == "mudanca_endereco"
    )
    fase_protegida_loc = fase in {"cadastro", "termos", "agendamento", "pos_venda", "vendas"}
    duvida_sem_endereco = (
        flags.get("tem_pergunta")
        and fase_protegida_loc
        and tem_duvida_informativa(msg_cliente, msg_cliente)
        and not loc.get("informada")
    )

    if loc.get("solicitou_troca_sem_novos_dados") and not (
        (fase == "cadastro" and pergunta_sobre_endereco)
        or duvida_sem_endereco
    ):
        return dec(
            "RESPONDER",
            "PEDIR_NOVA_LOCALIZACAO",
            "viabilidade",
            "localizacao",
            dados_base,
            "Quer trocar endereço sem informar novo",
            "GLOBAL_LOCALIZACAO",
        )

    if loc.get("precisa_revalidar_cobertura"):
        # Durante cadastro, rua/CEP/número não revalidam cobertura
        campos_info = list((resolucao.get("dados") or {}).get("campos_informados") or [])
        campos_endereco_inst = {"rua", "numero", "cep", "complemento", "data_nascimento", "rg"}
        skip_cobertura_cadastro = (
            fase == "cadastro"
            and estado.get("plano_confirmado")
            and any(c in campos_info for c in campos_endereco_inst)
            and not loc.get("alterada")
        )
        if not skip_cobertura_cadastro:
            d = dict(dados_base)
            d["tentativas_sem_cobertura"] = 0
            if loc.get("cidade"):
                d["cidade"] = loc["cidade"]
            if loc.get("bairro"):
                d["bairro"] = loc["bairro"]
            if loc.get("alterada"):
                d["resetar_cobertura"] = True
            # Preserva cadastro se cliente corrigir endereço no meio do fluxo
            if fase == "cadastro" or estado.get("plano_confirmado"):
                d["fase_anterior"] = "cadastro"
                d["aguardando_anterior"] = (
                    _texto(estado.get("aguardando_anterior"))
                    or _texto(aguardando)
                    or _proximo_cadastro(estado, d)
                    or "nome"
                )
            return dec(
                "CHECAR_COBERTURA",
                None,
                "viabilidade",
                "resultado_cobertura",
                d,
                "Localização completa — checar cobertura",
                "GLOBAL_LOCALIZACAO",
            )

    if loc.get("informada") and loc.get("precisa_coletar_localizacao"):
        d = dict(dados_base)
        if loc.get("cidade"):
            d["cidade"] = loc["cidade"]
        if loc.get("bairro"):
            d["bairro"] = loc["bairro"]
        if loc.get("limpar_bairro_anterior"):
            d["limpar_bairro"] = True
        if loc.get("limpar_cidade_anterior"):
            d["limpar_cidade"] = True
            d.pop("cidade", None)
        if loc.get("alterada"):
            d["resetar_cobertura"] = True
            if fase not in {"cadastro", "sem_cobertura"} and not estado.get("plano_confirmado"):
                d["invalidar_plano"] = True
        return dec(
            "RESPONDER",
            "COMPLETAR_LOCALIZACAO",
            "viabilidade",
            "localizacao",
            d,
            "Localização incompleta",
            "GLOBAL_LOCALIZACAO",
        )

    # Confirmação do resumo cadastral (+ dúvida na mesma mensagem)
    if (
        fase == "cadastro"
        and aguardando == "confirmacao_dados"
        and flags.get("confirmacao")
        and flags.get("tem_pergunta")
        and not quer_mudar_plano
    ):
        campos_info = list((resolucao.get("dados") or {}).get("campos_informados") or [])
        d = dict(dados_base)
        return dec(
            "RESPONDER",
            "CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA",
            "cadastro",
            "confirmacao_dados",
            d,
            "Confirmou resumo e perguntou algo",
            "FASE_CADASTRO",
            pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
            contexto={
                "pendente": "confirmacao_dados",
                "topico_contexto": resolucao.get("topico_contexto"),
                "pergunta_original": resolucao.get("pergunta_original") or "",
            },
        )

    # Confirmação do resumo cadastral → cadastrar no IXC
    # Eco de campos já salvos não bloqueia o cadastro
    campos_cadastro = list(cadastro.get("campos_informados") or [])
    novos_turno = set(resolucao.get("campos_novos") or [])
    alterados_turno = set(resolucao.get("campos_alterados") or [])
    tem_dado_novo = bool(correcoes) or any(
        c in novos_turno or c in alterados_turno for c in campos_cadastro
    )
    if (
        fase == "cadastro"
        and aguardando == "confirmacao_dados"
        and flags.get("confirmacao")
        and not quer_mudar_plano
        and not tem_dado_novo
        and not flags.get("tem_pergunta")
    ):
        d = dict(dados_base)
        return dec(
            "CADASTRAR_IXC",
            None,
            "cadastro",
            "resultado_cadastro_ixc",
            d,
            "Cliente confirmou — cadastrar no IXC",
            "FASE_CADASTRO",
        )

    # Cliente disse que algo está errado no resumo
    if (
        fase == "cadastro"
        and aguardando == "confirmacao_dados"
        and flags.get("negacao")
        and not cadastro.get("campos_informados")
    ):
        return dec(
            "RESPONDER",
            "PEDIR_QUAL_DADO_CORRIGIR",
            "cadastro",
            "confirmacao_dados",
            dados_base,
            "Cliente quer corrigir dados do resumo",
            "FASE_CADASTRO",
        )

    # Confirmação de plano (vendas) — com retorno ao cadastro se houver desvio
    if (
        fase == "vendas"
        and aguardando == "confirmacao_plano"
        and flags.get("confirmacao")
        and (not plano.get("informado") or plano.get("repetido"))
        and not plano.get("pediu_troca_declarada")
    ):
        nome = _texto(estado.get("plano_em_negociacao") or estado.get("plano_apresentado"))
        pid = estado.get("plano_em_negociacao_id") or estado.get("plano_apresentado_id")
        if nome and pid is not None:
            d = dict(dados_base)
            d["plano_confirmado"] = nome
            d["plano_confirmado_id"] = int(pid)
            vinha_cadastro = _texto(estado.get("fase_anterior")) == "cadastro"

            # Imagem: preferir na apresentação do plano único; na confirmação só se ainda não enviou
            disparar_imagem = _imagem_pendente_para_plano(estado, pid)
            if disparar_imagem:
                if vinha_cadastro:
                    d["limpar_desvio"] = True
                    faltando = _proximo_cadastro(estado, d)
                    retomada = faltando or "confirmacao_dados"
                    return dec(
                        "ENVIAR_IMAGEM_PLANO",
                        None,
                        "vendas",
                        "resultado_imagem_plano",
                        d,
                        "Plano confirmado — enviar imagem e retomar cadastro",
                        "FASE_VENDAS",
                        contexto={
                            "pos_imagem": {
                                "objetivo": "CONFIRMAR_TROCA_PLANO_E_RETOMAR_CADASTRO",
                                "fase": "cadastro",
                                "aguardando": retomada,
                                "pergunta": "",
                            },
                            "plano": {"nome": nome},
                            "pendente": retomada,
                        },
                    )
                if flags.get("tem_pergunta"):
                    return dec(
                        "ENVIAR_IMAGEM_PLANO",
                        None,
                        "vendas",
                        "resultado_imagem_plano",
                        d,
                        "Plano confirmado — enviar imagem e responder pergunta",
                        "FASE_VENDAS",
                        contexto={
                            "pos_imagem": {
                                "objetivo": "CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA",
                                "fase": "cadastro",
                                "aguardando": "nome",
                                "pergunta": resolucao.get("pergunta")
                                or resolucao.get("mensagem")
                                or "",
                            },
                            "plano": {"nome": nome},
                            "pendente": "nome",
                            "topico_contexto": resolucao.get("topico_contexto"),
                            "pergunta_original": resolucao.get("pergunta_original") or "",
                        },
                    )
                return dec(
                    "ENVIAR_IMAGEM_PLANO",
                    None,
                    "vendas",
                    "resultado_imagem_plano",
                    d,
                    "Plano confirmado — enviar imagem e avançar cadastro",
                    "FASE_VENDAS",
                    contexto={
                        "pos_imagem": {
                            "objetivo": "CONFIRMAR_PLANO_E_AVANCAR",
                            "fase": "cadastro",
                            "aguardando": "nome",
                            "pergunta": "",
                        },
                        "plano": {"nome": nome},
                        "pendente": "nome",
                    },
                )

            if vinha_cadastro:
                d["limpar_desvio"] = True
                faltando = _proximo_cadastro(estado, d)
                retomada = faltando or "confirmacao_dados"
                return dec(
                    "RESPONDER",
                    "CONFIRMAR_TROCA_PLANO_E_RETOMAR_CADASTRO",
                    "cadastro",
                    retomada,
                    d,
                    "Troca de plano confirmada — voltar ao cadastro",
                    "FASE_VENDAS",
                    contexto={
                        "plano": {"nome": nome},
                        "pendente": retomada,
                    },
                )
            if flags.get("tem_pergunta"):
                return dec(
                    "RESPONDER",
                    "CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA",
                    "cadastro",
                    "nome",
                    d,
                    "Cliente confirmou plano e fez pergunta",
                    "FASE_VENDAS",
                    pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
                    contexto={
                        "pendente": "nome",
                        "plano": {"nome": nome},
                        "topico_contexto": resolucao.get("topico_contexto"),
                        "pergunta_original": resolucao.get("pergunta_original") or "",
                    },
                )
            return dec(
                "RESPONDER",
                "CONFIRMAR_PLANO_E_AVANCAR",
                "cadastro",
                "nome",
                d,
                "Cliente confirmou o plano",
                "FASE_VENDAS",
            )
        return dec(
            "TRANSFERIR_HUMANO",
            "INFORMAR_ERRO_E_TRANSFERENCIA",
            "transferido",
            None,
            {"transferido_humano": True},
            "Confirmação sem plano válido",
            "FASE_VENDAS",
        )

    # Recusa de plano
    if (
        fase == "vendas"
        and aguardando == "confirmacao_plano"
        and flags.get("negacao")
        and not plano.get("informado")
        and not plano.get("pediu_troca_declarada")
    ):
        d = _salvar_desvio_cadastro(estado, dados_base)
        d["limpar_plano_em_negociacao"] = True
        return dec(
            "BUSCAR_PLANOS",
            None,
            "vendas",
            "lista_planos",
            d,
            "Recusou plano — buscar alternativas",
            "FASE_VENDAS",
        )

    # Trocar plano sem citar qual — ou listar TODOS os planos
    from app.parser import eh_pedido_lista_completa_planos, normalizar_texto

    msg_n = normalizar_texto(str(resolucao.get("mensagem") or ""))
    pediu_lista_completa = eh_pedido_lista_completa_planos(msg_n)
    pediu_listar_todos = (
        plano.get("pediu_troca_declarada")
        and (flags.get("tem_pergunta") or pediu_lista_completa)
        and fase == "vendas"
    ) or (pediu_lista_completa and fase == "vendas" and estado.get("tem_cobertura") is True)

    if pediu_listar_todos and estado.get("tem_cobertura") is True:
        return dec(
            "LISTAR_TODOS_PLANOS",
            None,
            "vendas",
            "lista_planos",
            dict(dados_base),
            "Cliente pediu lista completa de planos",
            "GLOBAL_PLANO",
            contexto={"lista_completa": True},
        )

    if plano.get("pediu_troca_declarada") and not plano.get("informado"):
        if estado.get("tem_cobertura") is True:
            d = _salvar_desvio_cadastro(estado, dados_base)
            d.pop("invalidar_plano", None)
            d["limpar_plano_em_negociacao"] = True
            return dec(
                "BUSCAR_PLANOS",
                None,
                "vendas",
                "lista_planos",
                d,
                "Pediu outras opções",
                "GLOBAL_PLANO",
            )
        return dec(
            "RESPONDER",
            "PEDIR_LOCALIZACAO",
            "viabilidade",
            "localizacao",
            dados_base,
            "Quer planos mas falta cobertura",
            "GLOBAL_PLANO",
        )

    # "O que tem nesse plano?" — detalhes/benefícios (antes de tratar como escolha)
    if flags.get("tem_pergunta") and fase == "vendas":
        from app.parser import eh_pergunta_detalhe_plano, normalizar_texto

        texto_det = normalizar_texto(
            str(resolucao.get("mensagem") or resolucao.get("pergunta") or "")
        )
        if eh_pergunta_detalhe_plano(texto_det):
            ref = _texto(plano.get("valor")) or _texto(resolucao.get("pergunta")) or ""
            if not ref:
                ref = _texto(resolucao.get("mensagem") or "")
            d = dict(dados_base)
            plano_ctx: dict[str, Any] = {}
            aguard = aguardando or "confirmacao_plano"
            if ref:
                from app.plans import resolver_plano
                from app.plans_catalog import listar_planos

                plano_atual_id = None
                try:
                    if estado.get("plano_em_negociacao_id") is not None:
                        plano_atual_id = int(estado["plano_em_negociacao_id"])
                    elif estado.get("plano_apresentado_id") is not None:
                        plano_atual_id = int(estado["plano_apresentado_id"])
                except (TypeError, ValueError):
                    plano_atual_id = None
                resolvido = resolver_plano(
                    ref,
                    listar_planos(estado),
                    plano_atual_id=plano_atual_id,
                )
                if resolvido.get("evento") == "PLANO_RESOLVIDO" and resolvido.get("plano"):
                    p = resolvido["plano"]
                    plano_ctx = p
                    d["plano_apresentado"] = p.get("nome")
                    d["plano_apresentado_id"] = int(p["id"]) if p.get("id") is not None else None
                    d["plano_em_negociacao"] = p.get("nome")
                    d["plano_em_negociacao_id"] = int(p["id"]) if p.get("id") is not None else None
                    aguard = "confirmacao_plano"
                elif resolvido.get("evento") == "PLANO_AMBIGUO":
                    return dec(
                        "RESPONDER",
                        "ESCLARECER_PLANO_AMBIGUO",
                        "vendas",
                        "escolha_plano",
                        d,
                        "Detalhe pediu plano ambíguo",
                        "GLOBAL_PERGUNTA",
                        contexto={"candidatos": resolvido.get("candidatos") or []},
                    )
            return dec(
                "RESPONDER",
                "INFORMAR_DETALHES_PLANO",
                "vendas",
                aguard,
                d,
                "Pergunta sobre o que inclui o plano",
                "GLOBAL_PERGUNTA",
                contexto={
                    "pendente": aguard,
                    "referencia_plano": ref,
                    "plano": plano_ctx,
                },
            )

    # Plano informado (nome/referência)
    if plano.get("informado") and not plano.get("repetido"):
        if estado.get("tem_cobertura") is True:
            d = _salvar_desvio_cadastro(estado, dados_base)
            d.pop("invalidar_plano", None)
            d["limpar_plano_em_negociacao"] = True
            return dec(
                "RESOLVER_PLANO",
                None,
                "vendas",
                "resultado_plano",
                d,
                "Resolver referência de plano",
                "GLOBAL_PLANO",
                contexto={"referencia_plano": plano.get("valor") or ""},
            )
        if loc.get("completa") and estado.get("tem_cobertura") is not False:
            return dec(
                "CHECAR_COBERTURA",
                None,
                "viabilidade",
                "resultado_cobertura",
                dados_base,
                "Plano antes da cobertura",
                "GLOBAL_PLANO",
            )
        return dec(
            "RESPONDER",
            "PEDIR_LOCALIZACAO",
            "viabilidade",
            "localizacao",
            dados_base,
            "Precisa localização antes do plano",
            "GLOBAL_PLANO",
        )

    # Quer ver planos mas ainda falta localização/cobertura → não cai na RAG
    from app.parser import PEDIDOS_LISTA_COMPLETA, PEDIDOS_LISTAR_PLANOS, normalizar_texto

    msg_n = normalizar_texto(str(resolucao.get("mensagem") or ""))
    pediu_ver_planos = any(p in msg_n for p in PEDIDOS_LISTA_COMPLETA | PEDIDOS_LISTAR_PLANOS) or (
        "plano" in msg_n and any(v in msg_n for v in ("ver", "mostra", "manda", "lista", "quero", "quais"))
    )
    falta_cobertura = estado.get("tem_cobertura") is not True
    falta_local = not (estado.get("cidade") and estado.get("bairro"))
    if (
        pediu_ver_planos
        and fase in {"inicio", "viabilidade", "sem_cobertura"}
        and (falta_cobertura or falta_local)
    ):
        ja_cumprimentou = bool(estado.get("cumprimento_feito"))
        obj = (
            "PEDIR_LOCALIZACAO_PARA_VER_PLANOS"
            if ja_cumprimentou
            else "APRESENTAR_E_PEDIR_LOCALIZACAO"
        )
        return dec(
            "RESPONDER",
            obj,
            "viabilidade",
            "localizacao",
            dict(dados_base),
            "Quer planos — precisa localização antes",
            "GLOBAL_PLANO",
            contexto={"quer_ver_planos": True},
        )

    # "Quanto é?" do PLANO — não confundir com multa de cancelamento
    if flags.get("tem_pergunta") and fase == "vendas":
        from app.parser import (
            PERGUNTAS_PRECO,
            eh_pergunta_custo_instalacao,
            eh_pergunta_instalacao,
            normalizar_texto,
        )

        texto_q = normalizar_texto(
            str(resolucao.get("mensagem") or resolucao.get("pergunta") or "")
        )
        msg_bruta = str(resolucao.get("mensagem") or resolucao.get("pergunta_original") or "")
        topico = str(resolucao.get("topico_contexto") or "")
        if topico == "cancelamento":
            pass  # cai no RESPONDER_PERGUNTA com pergunta enriquecida (multa)
        elif eh_pergunta_instalacao(texto_q, msg_bruta, topico=topico):
            return dec(
                "RESPONDER",
                "INFORMAR_INSTALACAO_E_RETOMAR",
                "vendas",
                aguardando or "confirmacao_plano",
                dict(dados_base),
                "Pergunta sobre instalação — resposta fixa e retomar plano",
                "GLOBAL_PERGUNTA",
                contexto={
                    "pendente": aguardando or "confirmacao_plano",
                    "topico_contexto": "instalacao",
                    "pergunta_custo_instalacao": eh_pergunta_custo_instalacao(
                        texto_q, msg_bruta
                    ),
                    "plano_nome": _texto(
                        estado.get("plano_em_negociacao") or estado.get("plano_apresentado")
                    ),
                },
            )
        elif any(p in texto_q for p in PERGUNTAS_PRECO):
            return dec(
                "RESPONDER",
                "INFORMAR_PRECO_PLANO_E_RETOMAR",
                "vendas",
                aguardando or "confirmacao_plano",
                dict(dados_base),
                "Pergunta de preço do plano",
                "GLOBAL_PERGUNTA",
                contexto={"pendente": aguardando},
            )

        # "Tem Disney?" / benefício → resposta fixa com planos + preço
        beneficio = _detectar_beneficio_pergunta(texto_q)
        if beneficio and topico != "cancelamento":
            return dec(
                "RESPONDER",
                "INFORMAR_PLANOS_POR_BENEFICIO",
                "vendas",
                aguardando or "confirmacao_plano",
                dict(dados_base),
                f"Pergunta sobre benefício {beneficio}",
                "GLOBAL_PERGUNTA",
                contexto={"pendente": aguardando, "beneficio": beneficio},
            )

    # Em cadastro: "quanto paga?" no tópico cancelamento ≠ preço do plano
    if flags.get("tem_pergunta") and fase == "cadastro":
        topico = str(resolucao.get("topico_contexto") or "")
        from app.parser import (
            PERGUNTAS_PRECO,
            eh_pergunta_custo_instalacao,
            eh_pergunta_instalacao,
            normalizar_texto,
        )

        texto_q = normalizar_texto(
            str(resolucao.get("mensagem") or resolucao.get("pergunta_original") or "")
        )
        msg_bruta = str(resolucao.get("mensagem") or resolucao.get("pergunta_original") or "")
        campos_info = list((resolucao.get("dados") or {}).get("campos_informados") or [])
        anotados = [c for c in campos_info if c != "cpf"]
        pendente_ef = _pendente_cadastro_apos_anotacao(estado, dados_base, aguardando, anotados)
        ctx_perg = {
            "pendente": pendente_ef,
            "topico_contexto": topico,
            "pergunta_original": resolucao.get("pergunta_original") or "",
            "campos_anotados": anotados,
        }
        if topico == "mudanca_endereco" or eh_pergunta_mudanca_endereco(msg_cliente):
            d = dict(dados_base)
            return dec(
                "RESPONDER",
                "RESPONDER_PERGUNTA_E_RETOMAR",
                fase,
                pendente_ef,
                d,
                "Pergunta sobre mudança de endereço pós-contratação",
                "GLOBAL_PERGUNTA",
                pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
                contexto={**ctx_perg, "topico_contexto": "mudanca_endereco"},
            )
        if topico == "instalacao" or eh_pergunta_instalacao(
            texto_q, msg_bruta, topico=topico
        ):
            d = dict(dados_base)
            return dec(
                "RESPONDER",
                "INFORMAR_INSTALACAO_E_RETOMAR",
                fase,
                pendente_ef,
                d,
                "Pergunta sobre instalação/agendamento durante cadastro",
                "GLOBAL_PERGUNTA",
                contexto={
                    **ctx_perg,
                    "topico_contexto": "instalacao",
                    "pendente": pendente_ef,
                    "pergunta_custo_instalacao": eh_pergunta_custo_instalacao(
                        texto_q, msg_bruta
                    ),
                    "plano_nome": _texto(
                        estado.get("plano_confirmado")
                        or estado.get("plano_em_negociacao")
                        or estado.get("plano_apresentado")
                    ),
                },
            )
        if topico == "cancelamento" or (
            any(
                p in texto_q
                for p in ("cancelar", "cancelamento", "multa", "fidelidade")
            )
            or (
                "taxa" in texto_q
                and not eh_pergunta_instalacao(texto_q, msg_bruta, topico=topico)
            )
        ):
            d = dict(dados_base)
            return dec(
                "RESPONDER",
                "RESPONDER_PERGUNTA_E_RETOMAR",
                fase,
                pendente_ef,
                d,
                "Pergunta sobre cancelamento/multa",
                "GLOBAL_PERGUNTA",
                pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
                contexto={**ctx_perg, "topico_contexto": "cancelamento"},
            )
        if topico == "beneficio_plano" or any(
            k in texto_q for k in ("roteador", "direito", "comodato", "disney", "mesh", "inclui")
        ):
            d = dict(dados_base)
            return dec(
                "RESPONDER",
                "RESPONDER_PERGUNTA_E_RETOMAR",
                fase,
                pendente_ef,
                d,
                "Pergunta sobre benefícios/equipamentos",
                "GLOBAL_PERGUNTA",
                pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
                contexto={**ctx_perg, "topico_contexto": "beneficio_plano"},
            )

    # Pergunta durante agendamento (antes de processar horário)
    if flags.get("tem_pergunta") and fase == "agendamento":
        d = dict(dados_base)
        campos_info = list((resolucao.get("dados") or {}).get("campos_informados") or [])
        ctx_agenda = {
            "pendente": aguardando or "escolha_horario",
            "topico_contexto": resolucao.get("topico_contexto") or "instalacao",
            "pergunta_original": resolucao.get("pergunta_original") or "",
            "campos_anotados": campos_info,
        }
        if flags.get("confirmacao") and aguardando == "confirmacao_horario":
            return dec(
                "RESPONDER",
                "CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA",
                "agendamento",
                "confirmacao_horario",
                d,
                "Confirmou horário e perguntou algo",
                "AGENDAMENTO",
                pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
                contexto=ctx_agenda,
            )
        return dec(
            "RESPONDER",
            "RESPONDER_PERGUNTA_E_RETOMAR",
            "agendamento",
            aguardando or "escolha_horario",
            d,
            "Pergunta durante agendamento",
            "AGENDAMENTO",
            pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
            contexto=ctx_agenda,
        )

    # Pergunta (inclui cadastro aguardando CPF — dado + dúvida sem disparar validação IXC)
    if flags.get("tem_pergunta") and fase != "termos":
        d = dict(dados_base)
        # CPF antecipado em vendas: salva mas não valida agora
        if cpf.get("informado") and fase == "vendas":
            d["cpf"] = cpf.get("valor") or d.get("cpf")
        campos_info = list((resolucao.get("dados") or {}).get("campos_informados") or [])
        anotados = [c for c in campos_info if c != "cpf"]
        pendente_ef = (
            _pendente_cadastro_apos_anotacao(estado, d, aguardando, anotados)
            if fase == "cadastro"
            else aguardando
        )
        return dec(
            "RESPONDER",
            "RESPONDER_PERGUNTA_E_RETOMAR",
            fase,
            pendente_ef,
            d,
            "Pergunta do cliente",
            "GLOBAL_PERGUNTA",
            pergunta=resolucao.get("pergunta") or resolucao.get("mensagem") or "",
            contexto={
                "pendente": pendente_ef,
                "cpf_anotado": bool(d.get("cpf")),
                "topico_contexto": resolucao.get("topico_contexto"),
                "pergunta_original": resolucao.get("pergunta_original") or "",
                "campos_anotados": anotados,
            },
        )

    # CPF — só valida na fase cadastro quando CPF é o pendente
    cpf_pendente = (
        fase == "cadastro"
        and aguardando == "cpf"
        and not _campo_ok(estado, dados_base, "cpf")
    )
    if (
        cpf.get("informado")
        and fase == "cadastro"
        and not flags.get("tem_pergunta")
        and (
            cpf.get("alterado")
            or cpf.get("novo")
            or (cpf_pendente and (cpf.get("repetido") or _texto(estado.get("cpf"))))
        )
    ):
        motivo_inv = validar_campo("cpf", cpf.get("valor") or "")
        if motivo_inv:
            return dec(
                "RESPONDER",
                "PEDIR_CPF_NOVAMENTE",
                "cadastro",
                "cpf",
                {**dados_base, "documento_cpf_validado": False},
                motivo_inv,
                "GLOBAL_DADOS",
                contexto={"motivo_validacao": motivo_inv},
            )
        d = dict(dados_base)
        if not d.get("cpf") and _texto(estado.get("cpf")):
            d["cpf"] = _texto(estado.get("cpf"))
        if cpf.get("alterado"):
            d["invalidar_validacao_cpf"] = True
            d["documento_cpf_validado"] = False
        from app.cadastro_mensagens import par_de

        permitir = set(par_de(str(aguardando or "")))
        permitir.add("cpf")
        d = {
            k: v
            for k, v in d.items()
            if k not in ORDEM_CADASTRO or k in permitir
        }
        junto = [c for c in ("nome", "email", "telefone") if _texto(d.get(c))]
        return dec(
            "VALIDAR_CPF",
            None,
            "cadastro",
            "resultado_cpf",
            d,
            "CPF informado — consultar IXC",
            "GLOBAL_DADOS",
            contexto={"cpf": cpf.get("valor") or d.get("cpf") or "", "campos_junto": junto},
        )

    # Termos — aceite antes do agendamento
    if fase == "termos":
        return _decidir_termos(
            estado, resolucao, dados_base, flags, dec, aguardando
        )

    # Agendamento — escolha e confirmação de horário
    if fase == "agendamento":
        return _decidir_agendamento(
            estado, resolucao, dados_base, flags, dec, aguardando
        )

    # Dados cadastrais (novos, fora de ordem ou correções)
    campos_info = list(cadastro.get("campos_informados") or [])
    if campos_info and fase in {"cadastro", "vendas", "inicio"}:
        if fase == "cadastro":
            campos_info, fora_ordem = _filtrar_campos_cadastro_pendente(
                aguardando, campos_info, correcoes
            )
            if fora_ordem:
                return dec(
                    "RESPONDER",
                    _objetivo_pedir(str(aguardando)),
                    "cadastro",
                    aguardando,
                    _dados_sem_campos_rejeitados(dados_base, []),
                    f"Campo fora de ordem — pendente {aguardando}",
                    "GLOBAL_DADOS",
                    contexto={"pendente": aguardando},
                )
            # Pendente + campos seguintes — ignora eco do modelo em campos anteriores
            if aguardando in ORDEM_CADASTRO:
                permitidos = _campos_cadastro_permitidos(str(aguardando), correcoes)
                campos_info = [c for c in campos_info if c in permitidos]
                correcoes = _correcoes_no_par(str(aguardando), correcoes)
            dados_base = _dados_sem_campos_rejeitados(dados_base, campos_info)

        if campos_info:
            from app.parser import sanitizar_dados_cadastro

            msg_sanit = str(resolucao.get("mensagem") or resolucao.get("pergunta_original") or "")
            dados_base = sanitizar_dados_cadastro(dados_base, estado, msg_sanit)
            campos_info = [
                c
                for c in campos_info
                if c not in {"rua", "numero"} or _texto(dados_base.get(c))
            ]
            # Validação leve (exceto CPF — já tratado)
            for campo in campos_info:
                if campo == "cpf":
                    continue
                valor = _texto(dados_base.get(campo))
                nome_cli = _texto(dados_base.get("nome") or estado.get("nome"))
                motivo_inv = (
                    validar_campo(campo, valor, nome_cliente=nome_cli) if valor else None
                )
                if motivo_inv:
                    return dec(
                        "RESPONDER",
                        f"PEDIR_CORRECAO_{campo.upper()}",
                        "cadastro",
                        campo,
                        {k: v for k, v in dados_base.items() if k != campo},
                        motivo_inv,
                        "GLOBAL_DADOS",
                        contexto={
                            "campo_invalido": campo,
                            "motivo_validacao": motivo_inv,
                            "pendente": campo,
                        },
                    )

            # Se ainda não confirmou plano e está em vendas pedindo plano, só salva e retoma
            if fase == "vendas" and aguardando in {
                "confirmacao_plano",
                "lista_planos",
                "escolha_plano",
                "resultado_plano",
            }:
                return dec(
                    "RESPONDER",
                    "ANOTAR_DADO_E_RETOMAR_PLANO",
                    "vendas",
                    aguardando,
                    dados_base,
                    "Dado antecipado — retomar plano",
                    "GLOBAL_DADOS",
                    contexto={
                        "campos_anotados": campos_info,
                        "pendente": "plano",
                        "cidade_ja_informada": bool(estado.get("cidade")),
                        "bairro_ja_informado": bool(estado.get("bairro")),
                    },
                )

            corrigidos = [c for c in correcoes if c in campos_info]
            anotados = [c for c in campos_info if c != "cpf"]
            return _decisao_retomar_cadastro(
                estado,
                dados_base,
                campos_anotados=anotados,
                campos_corrigidos=corrigidos,
                motivo="Dados/correções cadastrais",
            )

    # Pergunta (fallback — cadastro aguardando cpf com pergunta misturada)
    if flags.get("tem_pergunta"):
        return dec(
            "RESPONDER",
            "RESPONDER_PERGUNTA_E_RETOMAR",
            fase,
            aguardando,
            dados_base,
            "Pergunta do cliente",
            "GLOBAL_PERGUNTA",
            pergunta=resolucao.get("pergunta") or "",
            contexto={"pendente": aguardando},
        )

    # Social / saudação
    if flags.get("conversa_social") or flags.get("saudacao"):
        if fase == "inicio":
            obj = (
                "CONVERSAR_E_PEDIR_LOCALIZACAO"
                if flags.get("conversa_social")
                else "APRESENTAR_E_PEDIR_LOCALIZACAO"
            )
            return dec(
                "RESPONDER",
                obj,
                "viabilidade",
                "localizacao",
                dados_base,
                "Abertura",
                "GLOBAL_SOCIAL",
            )
        obj = (
            "CONVERSAR_E_RETOMAR"
            if flags.get("conversa_social")
            else "CUMPRIMENTAR_E_RETOMAR"
        )
        return dec(
            "RESPONDER",
            obj,
            fase,
            aguardando,
            dados_base,
            "Social em andamento",
            "GLOBAL_SOCIAL",
            contexto={"pendente": aguardando},
        )

    # Fluxos por fase
    if fase == "inicio":
        return dec(
            "RESPONDER",
            "PEDIR_LOCALIZACAO" if flags.get("pedido_contratacao") else "APRESENTAR_E_PEDIR_LOCALIZACAO",
            "viabilidade",
            "localizacao",
            dados_base,
            "Início do atendimento",
            "FASE",
        )

    if fase == "viabilidade":
        return dec(
            "RESPONDER",
            "RETOMAR_LOCALIZACAO",
            "viabilidade",
            "localizacao",
            dados_base,
            "Retomar viabilidade",
            "FASE",
        )

    if fase == "sem_cobertura":
        if flags.get("pedido_contratacao") or flags.get("pediu_trocar_localizacao_efetivo"):
            d = dict(dados_base)
            d["tentativas_sem_cobertura"] = 0
            return dec(
                "RESPONDER",
                "PEDIR_NOVA_LOCALIZACAO",
                "viabilidade",
                "localizacao",
                d,
                "Tentar outro endereço",
                "FASE",
            )
        tentativas = int(estado.get("tentativas_sem_cobertura") or 0) + 1
        if tentativas >= TENTATIVAS_MAX:
            return dec(
                "TRANSFERIR_HUMANO",
                "TRANSFERIR_INSISTENCIA_SEM_COBERTURA",
                "transferido",
                None,
                {
                    **dados_base,
                    "tentativas_sem_cobertura": tentativas,
                    "transferido_humano": True,
                    "motivo_transferencia": "Insistência em endereço sem cobertura",
                },
                "Limite de tentativas sem cobertura",
                "FASE",
            )
        d = dict(dados_base)
        d["tentativas_sem_cobertura"] = tentativas
        return dec(
            "RESPONDER",
            "INSISTENCIA_SEM_COBERTURA",
            "sem_cobertura",
            None,
            d,
            "Cliente insistiu no mesmo endereço",
            "FASE",
            contexto={"tentativa": tentativas, "max": TENTATIVAS_MAX},
        )

    if fase == "cadastro":
        return _decisao_retomar_cadastro(estado, dados_base, motivo="Retomar coleta cadastral")

    if fase == "agendamento":
        return _decidir_agendamento(
            estado, resolucao, dados_base, flags, dec, aguardando
        )

    if fase == "vendas" and aguardando in {"escolha_plano", "lista_planos", "confirmacao_plano"}:
        return dec(
            "RESPONDER",
            "RETOMAR_ESCOLHA_PLANO",
            fase,
            aguardando,
            dados_base,
            "Aguardando escolha de plano",
            "FASE",
            contexto={"pendente": "plano"},
        )

    return dec(
        "RESPONDER",
        "CONTINUAR_CONVERSA",
        fase,
        aguardando,
        dados_base,
        "Fallback",
        "FALLBACK",
        contexto={"pendente": aguardando},
    )


def decidir_resultado_cobertura(resultado: dict[str, Any], estado: dict[str, Any] | None = None) -> Decisao:
    """Traduz o retorno do executor (igual ao n8n) em decisão."""
    estado = estado or {}
    tipo = _texto(resultado.get("resultado")) or "erro_cobertura"
    cidade = _texto(resultado.get("cidade_normalizada"))
    bairro = _texto(resultado.get("bairro_normalizado"))
    rua = _texto(resultado.get("rua_normalizada"))

    base_dados = {
        "cidade": cidade,
        "bairro": bairro,
        "rua": rua,
        "localizacao_fixa": _texto(resultado.get("localizacao_fixa")),
        "caixa_fibra": _texto(resultado.get("caixa_fibra")),
    }

    if tipo == "cobertura_confirmada":
        base_dados["tem_cobertura"] = True
        base_dados["tentativas_sem_cobertura"] = 0
        # Já tinha plano confirmado / estava no cadastro → retoma, não reinicia venda
        retomar_cadastro = bool(
            estado.get("plano_confirmado")
            or _texto(estado.get("fase_anterior")) == "cadastro"
            or _texto(estado.get("fase")) == "cadastro"
        )
        if retomar_cadastro:
            base_dados["limpar_desvio"] = True
            aguardando_ret = (
                _texto(estado.get("aguardando_anterior"))
                or _proximo_cadastro(estado, base_dados)
                or "nome"
            )
            return _decisao_retomar_cadastro(
                {**estado, **base_dados},
                base_dados,
                motivo="Cobertura reconfirmada — retomar cadastro",
            )
        return Decisao(
            acao="BUSCAR_PLANO_INICIAL",
            objetivo_resposta=None,
            fase="vendas",
            aguardando="resultado_plano",
            atualizar_dados=base_dados,
            motivo=_texto(resultado.get("motivo")) or "Cobertura confirmada",
            prioridade="COBERTURA",
        )

    if tipo == "sem_cobertura":
        base_dados["tem_cobertura"] = False
        base_dados["tentativas_sem_cobertura"] = 0
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="INFORMAR_SEM_COBERTURA",
            fase="sem_cobertura",
            aguardando=None,
            atualizar_dados=base_dados,
            motivo=_texto(resultado.get("motivo")) or "Sem cobertura",
            prioridade="COBERTURA",
        )

    if tipo == "bairro_ambiguo":
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="ESCLARECER_BAIRRO",
            fase="viabilidade",
            aguardando="confirmar_bairro",
            atualizar_dados=base_dados,
            contexto_resposta={
                "bairro_informado": bairro,
                "bairros_sugeridos": resultado.get("bairros_sugeridos") or [],
            },
            motivo=_texto(resultado.get("motivo")) or "Bairro ambíguo",
            prioridade="COBERTURA",
        )

    return Decisao(
        acao="TRANSFERIR_HUMANO",
        objetivo_resposta="INFORMAR_ERRO_E_TRANSFERENCIA",
        fase="transferido",
        aguardando=None,
        atualizar_dados={**base_dados, "transferido_humano": True},
        motivo=_texto(resultado.get("motivo")) or "Erro na viabilidade",
        prioridade="COBERTURA",
    )


def decidir_resultado_cpf(resultado: dict[str, Any], estado: dict[str, Any]) -> Decisao:
    """Traduz retorno da checagem IXC (sub-workflow n8n) em decisão."""
    cpf_nums = _texto(resultado.get("cpf_numeros") or resultado.get("cpf_formatado"))
    motivo = _texto(resultado.get("motivo"))

    if resultado.get("erro"):
        if "inválido" in motivo.lower() or "invalido" in motivo.lower():
            return Decisao(
                acao="RESPONDER",
                objetivo_resposta="PEDIR_CPF_NOVAMENTE",
                fase="cadastro",
                aguardando="cpf",
                atualizar_dados={"documento_cpf_validado": False},
                motivo=motivo or "CPF inválido",
                prioridade="CPF",
                contexto_resposta={"motivo_validacao": motivo, "pendente": "cpf"},
            )
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_CPF_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "documento_cpf_validado": False,
                "transferido_humano": True,
                "motivo_transferencia": motivo or "Erro na validação de CPF",
            },
            motivo=motivo or "Erro na validação de CPF",
            prioridade="CPF",
        )

    if resultado.get("ja_cadastrado"):
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_CPF_JA_CADASTRADO",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "cpf": cpf_nums or None,
                "documento_cpf_validado": False,
                "transferido_humano": True,
                "motivo_transferencia": motivo or "CPF já cadastrado",
            },
            motivo=motivo or "CPF já cadastrado no IXC",
            prioridade="CPF",
        )

    dados = {"cpf": cpf_nums, "documento_cpf_validado": True}
    junto = [c for c in (resultado.get("campos_junto") or []) if c and c != "cpf"]
    return _decisao_retomar_cadastro(
        estado,
        dados,
        campos_anotados=junto + ["cpf"],
        motivo="CPF validado — prosseguir cadastro",
    )


def decidir_resultado_cadastro_ixc(resultado: dict[str, Any], estado: dict[str, Any]) -> Decisao:
    """Traduz retorno do cadastro IXC em decisão."""
    motivo = _texto(resultado.get("motivo"))

    if resultado.get("erro") or not resultado.get("ok") or resultado.get("transferir"):
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_CADASTRO_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "transferido_humano": True,
                "motivo_transferencia": motivo or "Erro ao cadastrar no IXC",
            },
            contexto_resposta={"motivo": motivo or "Erro ao cadastrar no IXC"},
            motivo=motivo or "Erro ao cadastrar no IXC",
            prioridade="CADASTRO",
        )

    if resultado.get("ja_cadastrado"):
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_CPF_JA_CADASTRADO",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "transferido_humano": True,
                "motivo_transferencia": motivo or "CPF já cadastrado",
            },
            motivo=motivo or "CPF já cadastrado no IXC",
            prioridade="CADASTRO",
        )

    id_ixc = _texto(resultado.get("id_cliente_ixc"))
    if not id_ixc:
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_CADASTRO_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "transferido_humano": True,
                "motivo_transferencia": motivo or "IXC não retornou ID do cliente",
            },
            motivo="Cadastro IXC sem ID retornado",
            prioridade="CADASTRO",
        )

    dados: dict[str, Any] = {
        "cadastro_completo": True,
        "ixc_cliente_id": id_ixc,
    }
    os_id = _texto(resultado.get("os_id"))
    id_contrato = _texto(resultado.get("id_contrato_ixc"))
    if os_id:
        dados["os_id"] = os_id
    if id_contrato:
        dados["id_contrato_ixc"] = id_contrato

    # Sempre dispara enviar_termos (webhook n8n ou mock) — nunca pula direto pro texto
    return Decisao(
        acao="ENVIAR_TERMOS",
        objetivo_resposta=None,
        fase="termos",
        aguardando="aceite_termos",
        atualizar_dados=dados,
        motivo=motivo or "Cadastro concluído — enviar termos",
        prioridade="TERMOS",
        contexto_resposta={
            "id_cliente_ixc": id_ixc,
            "os_id": os_id,
            "id_contrato_ixc": id_contrato,
        },
    )


def decidir_resultado_horarios(resultado: dict[str, Any], estado: dict[str, Any]) -> Decisao:
    """Traduz retorno do webhook de agenda em decisão."""
    tipo = _texto(resultado.get("resultado")).lower()
    motivo = _texto(resultado.get("motivo"))

    if resultado.get("erro") or tipo == "erro":
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_AGENDA_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "transferido_humano": True,
                "motivo_transferencia": motivo or "Erro ao consultar horários",
            },
            motivo=motivo or "Erro ao consultar horários",
            prioridade="AGENDAMENTO",
        )

    if tipo in {"sem_agenda", "sem_horarios"}:
        data = _texto(resultado.get("data"))
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_SEM_HORARIOS_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "transferido_humano": True,
                "motivo_transferencia": motivo or f"Sem horários ({tipo})",
            },
            motivo=motivo or tipo,
            prioridade="AGENDAMENTO",
            contexto_resposta={"tipo": tipo, "data": data},
        )

    if tipo != "ok":
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_AGENDA_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "transferido_humano": True,
                "motivo_transferencia": motivo or f"Retorno inesperado: {tipo}",
            },
            motivo=motivo or tipo,
            prioridade="AGENDAMENTO",
        )

    agenda = {
        "tecnico_id": _texto(resultado.get("tecnico_id")),
        "data": _texto(resultado.get("data")),
        "manha": list(resultado.get("manha") or []),
        "tarde": list(resultado.get("tarde") or []),
    }

    return Decisao(
        acao="RESPONDER",
        objetivo_resposta="APRESENTAR_HORARIOS",
        fase="agendamento",
        aguardando="escolha_horario",
        atualizar_dados={
            "tecnico_id": agenda["tecnico_id"],
            "data_agendamento": agenda["data"],
            "horarios_manha": agenda["manha"],
            "horarios_tarde": agenda["tarde"],
        },
        motivo="Horários disponíveis — apresentar ao cliente",
        prioridade="AGENDAMENTO",
        contexto_resposta={"agenda": agenda},
    )


def decidir_resultado_inserir_agenda(
    resultado: dict[str, Any], estado: dict[str, Any]
) -> Decisao:
    """Traduz retorno do webhook de gravação de agendamento."""
    tipo = _texto(resultado.get("resultado")).lower()
    motivo = _texto(resultado.get("motivo"))
    horario = _texto(estado.get("horario_escolhido"))
    data = _texto(estado.get("data_agendamento"))

    if tipo == "ok" and not resultado.get("erro"):
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="AGENDAMENTO_CONFIRMADO_E_PEDIR_DUVIDAS",
            fase="pos_venda",
            aguardando="duvidas",
            atualizar_dados={
                "agendamento_confirmado": True,
                "os_id": _texto(resultado.get("os_id")),
            },
            contexto_resposta={"horario": horario, "data": data},
            motivo=motivo or "Agendamento gravado — oferecer dúvidas",
            prioridade="AGENDAMENTO",
        )

    msg = motivo or "Não foi possível gravar o agendamento"
    if tipo == "sem_os":
        msg = "Ordem de serviço não encontrada para este cliente"

    return Decisao(
        acao="TRANSFERIR_HUMANO",
        objetivo_resposta="INFORMAR_ERRO_AGENDA_E_TRANSFERENCIA",
        fase="transferido",
        aguardando=None,
        atualizar_dados={
            "transferido_humano": True,
            "motivo_transferencia": msg,
            "agendamento_confirmado": False,
        },
        motivo=msg,
        prioridade="AGENDAMENTO",
    )


def decidir_resultado_termos(
    resultado: dict[str, Any], estado: dict[str, Any]
) -> Decisao:
    """Após envio de áudio/PDF — pede aceite antes da ativação/agendamento."""
    audio = bool(resultado.get("audio_enviado"))
    termo = bool(resultado.get("termo_enviado"))
    ok = (
        str(resultado.get("resultado") or "").lower() == "ok"
        or (audio and termo)
        or (termo and not resultado.get("transferir"))
    )
    parcial = not ok and (audio or termo)

    return Decisao(
        acao="RESPONDER",
        objetivo_resposta="PEDIR_ACEITE_TERMOS",
        fase="termos",
        aguardando="aceite_termos",
        atualizar_dados={
            "termos_enviados": termo,
            "audio_fidelidade_enviado": audio or ok,
        },
        contexto_resposta={
            "termos_enviados": ok,
            "termos_parcial": parcial,
            "termos_motivo": _texto(resultado.get("motivo")),
        },
        motivo=_texto(resultado.get("motivo")) or "Termos enviados — aguardar aceite",
        prioridade="TERMOS",
    )


def decidir_resultado_ativacao(
    resultado: dict[str, Any], estado: dict[str, Any]
) -> Decisao:
    """Após ativar contrato IXC — segue para horários ou transfere."""
    motivo = _texto(resultado.get("motivo"))
    ok = (
        str(resultado.get("resultado") or "").lower() == "ok"
        and not resultado.get("erro")
    ) or bool(resultado.get("ativado"))

    if not ok:
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_ATIVACAO_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                "ativado_ixc": False,
                "transferido_humano": True,
                "motivo_transferencia": motivo or "Erro ao ativar contrato",
            },
            motivo=motivo or "Erro na ativação IXC",
            prioridade="ATIVACAO",
        )

    return Decisao(
        acao="BUSCAR_HORARIOS",
        objetivo_resposta=None,
        fase="agendamento",
        aguardando="resultado_horarios",
        atualizar_dados={"ativado_ixc": True},
        motivo=motivo or "Contrato ativado — buscar horários",
        prioridade="ATIVACAO",
    )


def decidir_resultado_imagem_plano(
    resultado: dict[str, Any],
    estado: dict[str, Any],
    decisao_prev: Decisao | None = None,
) -> Decisao:
    """Após envio da imagem — segue oferta/confirmação (mesmo se imagem falhar)."""
    ctx = dict((decisao_prev.contexto_resposta if decisao_prev else None) or {})
    pos = ctx.get("pos_imagem") if isinstance(ctx.get("pos_imagem"), dict) else {}
    objetivo = _texto(pos.get("objetivo")) or "CONFIRMAR_PLANO_E_AVANCAR"
    fase_n = _texto(pos.get("fase")) or "cadastro"
    aguardando_n = _texto(pos.get("aguardando")) or "nome"
    pergunta = _texto(pos.get("pergunta"))
    enviada = bool(resultado.get("imagem_enviada")) or str(
        resultado.get("resultado") or ""
    ).lower() == "ok"

    ctx_out = {k: v for k, v in ctx.items() if k != "pos_imagem"}
    ctx_out["imagem_plano_enviada"] = enviada
    ctx_out["imagem_plano_motivo"] = _texto(resultado.get("motivo"))
    if resultado.get("imagem_url"):
        ctx_out["imagem_url"] = resultado.get("imagem_url")
    if resultado.get("imagem_painel"):
        ctx_out["imagem_painel"] = True
    if "plano" not in ctx_out:
        ctx_out["plano"] = {
            "nome": _texto(estado.get("plano_confirmado")),
        }

    enviadas = list(_imagens_enviadas_ids(estado))
    id_raw = resultado.get("id_plano") or (ctx_out.get("plano") or {}).get("id")
    try:
        pid = int(id_raw) if id_raw is not None else None
    except (TypeError, ValueError):
        pid = None
    if enviada and pid is not None and pid not in enviadas:
        enviadas.append(pid)

    return Decisao(
        acao="RESPONDER",
        objetivo_resposta=objetivo,
        fase=fase_n,
        aguardando=aguardando_n,
        atualizar_dados={
            "imagem_plano_enviada": enviada,
            "imagens_plano_enviadas": enviadas,
        },
        pergunta=pergunta,
        contexto_resposta=ctx_out,
        motivo=_texto(resultado.get("motivo")) or "Imagem processada — avançar",
        prioridade="VENDAS",
    )


def decidir_resultado_encerrar(
    resultado: dict[str, Any], estado: dict[str, Any]
) -> Decisao:
    """Após webhook de encerramento — despede e finaliza (mesmo se n8n falhar)."""
    motivo = _texto(resultado.get("motivo"))
    nome = _texto(estado.get("nome"))
    # Cliente já encerrou a conversa do ponto de vista dele; não transferir por falha do n8n
    return Decisao(
        acao="RESPONDER",
        objetivo_resposta="DESPEDIDA_ENCERRAMENTO",
        fase="finalizado",
        aguardando=None,
        atualizar_dados={
            "atendimento_encerrado": True,
            "motivo_encerramento": motivo or "Encerrado",
        },
        contexto_resposta={"nome": nome},
        motivo=motivo or "Atendimento encerrado",
        prioridade="ENCERRAMENTO",
    )


def decidir_pos_cobertura(estado: dict[str, Any], tem_cobertura: bool, cidade: str, bairro: str) -> Decisao:
    """Compatibilidade — preferir decidir_resultado_cobertura."""
    return decidir_resultado_cobertura(
        {
            "resultado": "cobertura_confirmada" if tem_cobertura else "sem_cobertura",
            "tem_cobertura": tem_cobertura,
            "cidade_normalizada": cidade,
            "bairro_normalizado": bairro,
        }
    )


def decidir_plano_inicial(
    plano: dict[str, Any] | None,
    estado: dict[str, Any] | None = None,
) -> Decisao:
    estado = estado or {}
    if not plano:
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={"transferido_humano": True},
            motivo="Sem plano destaque",
            prioridade="PLANO",
        )
    dados = {
        "plano_apresentado": plano["nome"],
        "plano_apresentado_id": int(plano["id"]),
        "plano_em_negociacao": plano["nome"],
        "plano_em_negociacao_id": int(plano["id"]),
    }
    return _dec_apresentar_plano_unico(
        estado=estado,
        plano=plano,
        dados=dados,
        objetivo="APRESENTAR_PLANO_INICIAL",
        aguardando="confirmacao_plano",
        motivo="Apresentar plano inicial",
    )


def decidir_plano_resolvido(resultado: dict[str, Any], estado: dict[str, Any] | None = None) -> Decisao:
    estado = estado or {}
    evento = resultado.get("evento")
    desvio = {
        k: estado.get(k)
        for k in ("fase_anterior", "aguardando_anterior")
        if estado.get(k)
    }
    referencia = _texto(resultado.get("referencia") or "")

    if evento == "PLANO_RESOLVIDO" and resultado.get("plano"):
        p = resultado["plano"]
        dados = {
            "plano_apresentado": p["nome"],
            "plano_apresentado_id": p["id"],
            "plano_em_negociacao": p["nome"],
            "plano_em_negociacao_id": p["id"],
            "tentativas_plano_invalido": 0,
            **desvio,
        }
        objetivo = (
            "APRESENTAR_TROCA_PLANO_E_CONFIRMAR"
            if desvio.get("fase_anterior") == "cadastro"
            else "APRESENTAR_PLANO_ESCOLHIDO_E_CONFIRMAR"
        )
        return _dec_apresentar_plano_unico(
            estado=estado,
            plano=p,
            dados=dados,
            objetivo=objetivo,
            aguardando="confirmacao_plano",
            motivo="Plano resolvido — aguardar confirmação",
            contexto_extra={
                "vindo_do_cadastro": desvio.get("fase_anterior") == "cadastro",
            },
        )
    if evento == "PLANO_AMBIGUO":
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="ESCLARECER_PLANO_AMBIGUO",
            fase="vendas",
            aguardando="escolha_plano",
            atualizar_dados={**desvio, "tentativas_plano_invalido": 0},
            contexto_resposta={"candidatos": resultado.get("candidatos") or []},
            motivo="Referência ambígua",
            prioridade="PLANO",
        )
    if evento == "PLANO_NAO_ENCONTRADO":
        tentativas = int(estado.get("tentativas_plano_invalido") or 0) + 1
        if tentativas >= TENTATIVAS_MAX:
            return Decisao(
                acao="LISTAR_TODOS_PLANOS",
                objetivo_resposta=None,
                fase="vendas",
                aguardando="lista_planos",
                atualizar_dados={**desvio, "tentativas_plano_invalido": 0},
                motivo="Muitas tentativas inválidas — listar todos",
                prioridade="PLANO",
            )
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="INFORMAR_PLANO_NAO_ENCONTRADO",
            fase="vendas",
            aguardando="escolha_plano",
            atualizar_dados={**desvio, "tentativas_plano_invalido": tentativas},
            contexto_resposta={"referencia": referencia, "tentativa": tentativas},
            motivo="Plano não encontrado",
            prioridade="PLANO",
        )
    return Decisao(
        acao="RESPONDER",
        objetivo_resposta="INFORMAR_PLANO_NAO_ENCONTRADO",
        fase="vendas",
        aguardando="escolha_plano",
        atualizar_dados=desvio,
        motivo="Plano não encontrado",
        prioridade="PLANO",
    )


def decidir_lista_planos(
    planos: list[dict[str, Any]],
    ref: dict[str, Any] | None,
    estado: dict[str, Any] | None = None,
    *,
    lista_completa: bool = False,
) -> Decisao:
    estado = estado or {}
    desvio = {
        k: estado.get(k)
        for k in ("fase_anterior", "aguardando_anterior")
        if estado.get(k)
    }
    if not planos:
        return Decisao(
            acao="TRANSFERIR_HUMANO",
            objetivo_resposta="INFORMAR_ERRO_E_TRANSFERENCIA",
            fase="transferido",
            aguardando=None,
            atualizar_dados={
                **desvio,
                "transferido_humano": True,
                "motivo_transferencia": "Catálogo de planos indisponível",
            },
            motivo="Sem planos no catálogo",
            prioridade="PLANO",
        )

    from app.plans_catalog import plano_destaque

    sugerido = plano_destaque(estado) or ref or (planos[0] if planos else {})

    if lista_completa:
        # Sem imagem — várias bolhas de texto; imagem só quando escolher 1 plano
        return Decisao(
            acao="RESPONDER",
            objetivo_resposta="APRESENTAR_LISTA_COMPLETA_PLANOS",
            fase="vendas",
            aguardando="escolha_plano",
            atualizar_dados={
                **desvio,
                "tentativas_plano_invalido": 0,
                "plano_apresentado": sugerido.get("nome"),
                "plano_apresentado_id": int(sugerido["id"]) if sugerido.get("id") is not None else None,
                "plano_em_negociacao": sugerido.get("nome"),
                "plano_em_negociacao_id": int(sugerido["id"]) if sugerido.get("id") is not None else None,
            },
            contexto_resposta={
                "planos": planos,
                "plano": sugerido,
                "plano_sugerido": sugerido,
                "total_planos": len(planos),
                "lista_completa": True,
            },
            motivo="Listar todos os planos com preço (sem imagem)",
            prioridade="PLANO",
        )

    # Sugestão = plano mais escolhido (não dump da lista)
    if (
        ref
        and sugerido
        and ref.get("id") is not None
        and sugerido.get("id") is not None
        and int(ref["id"]) == int(sugerido["id"])
        and len(planos) > 1
    ):
        for p in planos:
            if int(p["id"]) != int(sugerido["id"]):
                sugerido = p
                break

    dados_alt = {
        **desvio,
        "tentativas_plano_invalido": 0,
        "plano_apresentado": sugerido.get("nome"),
        "plano_apresentado_id": int(sugerido["id"]) if sugerido.get("id") is not None else None,
        "plano_em_negociacao": sugerido.get("nome"),
        "plano_em_negociacao_id": int(sugerido["id"]) if sugerido.get("id") is not None else None,
    }
    # Alternativa textual sem imagem (evita spam ao "ver outros"); imagem na escolha/confirmação
    return Decisao(
        acao="RESPONDER",
        objetivo_resposta="APRESENTAR_PLANOS_ALTERNATIVOS",
        fase="vendas",
        aguardando="escolha_plano",
        atualizar_dados=dados_alt,
        contexto_resposta={
            "planos": planos,
            "plano": sugerido,
            "plano_sugerido": sugerido,
            "plano_referencia": ref or {},
            "total_planos": len(planos),
            "vindo_do_cadastro": desvio.get("fase_anterior") == "cadastro",
        },
        motivo="Sugerir plano mais escolhido (sem listar catálogo)",
        prioridade="PLANO",
    )
