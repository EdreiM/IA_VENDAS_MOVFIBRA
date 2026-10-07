"""Conversa no meio do funil — quando o cliente não responde ao passo que a Eva pediu.

A máquina de estados decide o funil (o que falta, o que avança). Este módulo cuida do
que uma atendente faria quando a resposta do cliente não é o dado pedido:

- pediu um tempo, quer pensar, não tem o dado, achou caro, não entendeu, mandou áudio:
  a resposta é escrita pelo modelo em cima do que o cliente disse (`response._conversar`),
  em vez de repetir a mesma frase de pedido;
- depois de algumas tentativas sem avançar, chama uma pessoa da equipe;
- quem já é cliente e veio por suporte ou boleto é encaminhado, não entra no roteiro de venda;
- quem volta depois do atendimento encerrado continua de onde parou.

Nada aqui guarda regra comercial: os fatos continuam vindo do catálogo de planos e da RAG.
"""

from __future__ import annotations

import re
from typing import Any

from app.models import Decisao, Evento

ESPERA = "ESPERA"
ADIAMENTO = "ADIAMENTO"
IMPEDIMENTO = "IMPEDIMENTO"
OBJECAO_PRECO = "OBJECAO_PRECO"
NAO_ENTENDEU = "NAO_ENTENDEU"
SUPORTE = "SUPORTE"
MIDIA = "MIDIA"
REPETICAO = "REPETICAO"  # não avançou e nenhuma das situações acima explica

# O que o interpretador pode devolver em "situacao" (MIDIA e REPETICAO são só do código)
SITUACOES_LLM = ("", ESPERA, ADIAMENTO, IMPEDIMENTO, OBJECAO_PRECO, NAO_ENTENDEU, SUPORTE)

# Soma das tentativas sem avanço no mesmo passo que faz a Eva chamar uma pessoa
LIMITE_TRAVADO = 4
_PESO = {ESPERA: 0, ADIAMENTO: 0, IMPEDIMENTO: 2}

_FASES_TERMINAIS = {"transferido", "finalizado"}
_FASES_DE_COMPRA_ADIANTADA = {"cadastro", "termos", "agendamento"}

# Respostas em que a Eva fica no mesmo passo pedindo a mesma coisa
_OBJETIVOS_DE_REPETICAO = {
    "CONVERSAR_E_RETOMAR",
    "CONTINUAR_CONVERSA",
    "CLARIFICAR_INTENCAO",
    "PEDIR_ACEITE_TERMOS",
    "CONFIRMAR_HORARIO_ESCOLHIDO",
    "CONFIRMAR_DADOS_CADASTRO",
    "RETOMAR_ESCOLHA_PLANO",
    "RETOMAR_ESCOLHA_HORARIO",
    "RETOMAR_LOCALIZACAO",
    "PEDIR_LOCALIZACAO",
    "PEDIR_HORARIO_ESPECIFICO",
    "EXPLICAR_HORARIOS_UNICOS",
    "APRESENTAR_PLANO_ESCOLHIDO_E_CONFIRMAR",
    "PEDIR_NOME",
    "PEDIR_CPF",
    "PEDIR_EMAIL",
    "PEDIR_TELEFONE",
    "PEDIR_DATA_NASCIMENTO",
    "PEDIR_CEP",
    "PEDIR_RUA",
    "PEDIR_NUMERO",
    "PEDIR_CPF_NOVAMENTE",
}

_CAMPOS_PEDIDOS = {
    "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero", "localizacao",
}

_CAMPOS_DE_AVANCO = (
    "cidade", "bairro", "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua",
    "numero", "complemento", "plano_em_negociacao", "plano_confirmado", "horario_escolhido",
    "localizacao_fixa",
)

# O buffer junta mensagens rápidas: dois áudios seguidos chegam numa mensagem só, um por linha
_RE_MIDIA = re.compile(
    r"^\s*\[(audio|image|video|file)\](?:\s*\[(?:audio|image|video|file)\])*\s*$", re.I
)

_RE_SUPORTE = re.compile(
    r"\b(ja sou cliente|sou cliente (de voces|da mov|mov)|"
    r"minha (internet|conexao|net) (caiu|parou|nao funciona|nao ta funcionando|nao esta funcionando|"
    r"ta lenta|esta lenta|ta caindo|vive caindo|ta ruim|esta ruim|ta oscilando)|"
    r"(estou|to|tou|fiquei|estamos|ficamos) sem (internet|sinal|conexao)|"
    r"segunda via|2a via|2 via|boleto (atrasado|vencido)|"
    r"tecnico nao (veio|apareceu|chegou))\b"
)
_RE_ESPERA = re.compile(
    r"\b(pera|perai|espera|espere|aguarda|aguarde|calma|um momento|um minuto|um instante|"
    r"so um (minuto|momento|instante|pouco|segundo)|"
    r"ja (mando|envio|te mando|te envio|volto|passo|te passo|vejo)|"
    r"vou (procurar|pegar|buscar|olhar aqui|ver aqui)|deixa eu (ver|pegar|procurar|olhar)|"
    r"(to|tou|estou) procurando|nao tenho agora|agora nao tenho|nao (to|estou) com (ele|ela|isso) agora)\b"
)
_RE_ADIAMENTO = re.compile(
    r"\b(vou pensar|vou ver com|vou falar com|vou conversar com|"
    r"depois (eu )?(vejo|te falo|falo|mando|envio|te chamo|chamo|volto|decido|te aviso|aviso)|"
    r"mais tarde|outra hora|amanha eu|agora nao (posso|da|consigo)|(to|tou|estou) ocupad[oa])\b"
)
_RE_OBJECAO_PRECO = re.compile(
    r"\b(caro|(ta|esta|muito|achei|bem|meio|ficou|fica) cara|salgado|puxado|mais barato|"
    r"mais em conta|nao cabe|"
    r"sem condic\w+|fora do (meu )?orcamento|concorr\w+|"
    r"outra (operadora|empresa) (faz|cobra|oferece|ta|tem))\b"
)
_RE_NAO_ENTENDEU = re.compile(
    r"\b(nao entendi|nao compreendi|como assim|nao (to|tou|estou) entendendo|"
    r"pode explicar|explica melhor|que isso|confus[oa])\b"
)
_RE_IMPEDIMENTO = re.compile(
    r"\b(nao (tenho|sei|lembro|consegui|consigo|recebi|abriu|abre|chegou|achei|acho|encontrei|"
    r"possuo|uso|tem como|da pra|posso)|esqueci|perdi|sem (email|e mail|cpf|cep)|"
    r"nao (ta|esta) (abrindo|chegando|carregando)|manda de novo|reenvia\w*|envia de novo)\b"
)
_RE_PEDE_ALTERAR_CADASTRO = re.compile(
    r"\b(mudar|trocar|alterar|corrigir|arrumar|atualizar|errei|errado|errada)\b.{0,40}"
    r"\b(endereco|rua|numero|cep|bairro|cidade|nome|cpf|e mail|email|telefone|nascimento|dados|cadastro)\b"
)
_RE_NAO_RECEBEU_TERMOS = re.compile(
    r"\b(nao (recebi|chegou|abriu|abre|consegui abrir|consigo abrir|consegui ouvir|consigo ouvir|"
    r"apareceu|veio)|manda de novo|reenvia\w*|envia de novo|pode (mandar|enviar) de novo)\b"
)


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _norm(mensagem: str) -> str:
    from app.parser import normalizar_texto

    return re.sub(r"[^\w\s?]", " ", normalizar_texto(mensagem or "")).strip()


def tipo_de_midia(mensagem: str) -> str:
    """'audio' / 'image' / 'video' / 'file' quando a mensagem é só o marcador de mídia do Chatwoot."""
    m = _RE_MIDIA.match(mensagem or "")
    return m.group(1).lower() if m else ""


def classificar(mensagem: str, estado: dict[str, Any], situacao_llm: str = "") -> str:
    """Como o cliente reagiu ao passo atual. A leitura do modelo vale; as regras cobrem o resto."""
    if tipo_de_midia(mensagem):
        return MIDIA
    t = _norm(mensagem)
    fase = _texto(estado.get("fase")) or "inicio"
    llm = _texto(situacao_llm).upper()
    if llm not in SITUACOES_LLM:
        llm = ""

    suporte_pela_regra = bool(_RE_SUPORTE.search(t))
    if llm == SUPORTE:
        # No meio de uma compra, só encaminha para o suporte se a mensagem for inequívoca
        if fase not in _FASES_DE_COMPRA_ADIANTADA or suporte_pela_regra:
            return SUPORTE
        llm = ""
    if llm:
        return llm
    if suporte_pela_regra and fase not in _FASES_DE_COMPRA_ADIANTADA:
        return SUPORTE

    # Mensagem longa é assunto para o modelo, não para palavra-chave
    if len(t.split()) > 14:
        return ""
    if t in {"?", "??", "???", "ha?", "oi?", "hein?", "hein", "como?"} or _RE_NAO_ENTENDEU.search(t):
        return NAO_ENTENDEU
    if _RE_ESPERA.search(t):
        return ESPERA
    # Na agenda, "mais tarde" é preferência de horário, não adiamento
    if _RE_ADIAMENTO.search(t) and not (fase == "agendamento" and "mais tarde" in t):
        return ADIAMENTO
    if _RE_OBJECAO_PRECO.search(t):
        return OBJECAO_PRECO
    if _RE_IMPEDIMENTO.search(t):
        return IMPEDIMENTO
    return ""


# ── Notas da conversa ────────────────────────────────────────────────────────

_MAX_NOTAS = 8
_MAX_CHARS_NOTA = 160


def juntar_nota(notas_atuais: Any, nota: str) -> str:
    """Acrescenta uma nota (fato que vale lembrar depois) sem repetir; guarda as mais recentes."""
    linhas = [ln.strip() for ln in _texto(notas_atuais).split("\n") if ln.strip()]
    nova = re.sub(r"\s+", " ", _texto(nota))[:_MAX_CHARS_NOTA].strip(" .-")
    if not nova:
        return "\n".join(linhas)
    from app.parser import normalizar_texto

    chave = normalizar_texto(nova)
    if any(chave == normalizar_texto(ln) or chave in normalizar_texto(ln) for ln in linhas):
        return "\n".join(linhas)
    linhas.append(nova)
    return "\n".join(linhas[-_MAX_NOTAS:])


# ── Antes da máquina de estados ──────────────────────────────────────────────


def _transferir(
    estado: dict[str, Any], *, situacao: str, motivo: str, sinais: list[str]
) -> Decisao:
    return Decisao(
        acao="TRANSFERIR_HUMANO",
        objetivo_resposta="INFORMAR_TRANSFERENCIA_AJUDA",
        fase="transferido",
        aguardando=None,
        atualizar_dados={
            "transferido_humano": True,
            "motivo_transferencia": motivo[:300],
            "tentativas_travadas": 0,
        },
        motivo=motivo[:300],
        prioridade="GLOBAL_HUMANO",
        contexto_resposta={
            "conversa": {"situacao": situacao, "pendente": _texto(estado.get("aguardando"))},
            "sinais": sinais,
        },
    )


def antes(estado: dict[str, Any], resolucao: dict[str, Any]) -> Decisao | None:
    """Casos que saem do funil de venda antes de a máquina de estados decidir."""
    fase = _texto(estado.get("fase")) or "inicio"
    if fase in _FASES_TERMINAIS:
        return None
    mensagem = _texto(resolucao.get("mensagem"))
    situacao = _texto(resolucao.get("situacao"))

    if situacao == SUPORTE:
        return _transferir(
            estado,
            situacao="TRANSFERENCIA_SUPORTE",
            motivo=f"Cliente já é cliente — suporte/financeiro: {mensagem[:180]}",
            sinais=["suporte"],
        )

    # Termos: "não recebi" / "não abriu o PDF" — reenvia. Sem isso a Eva repetia o pedido
    # de aceite, e um "não abre" era lido como recusa dos termos.
    if (
        fase == "termos"
        and _texto(estado.get("aguardando")) == "aceite_termos"
        and _RE_NAO_RECEBEU_TERMOS.search(_norm(mensagem))
    ):
        total = int(estado.get("tentativas_travadas") or 0) + _PESO[IMPEDIMENTO]
        if total >= LIMITE_TRAVADO:
            return _transferir(
                estado,
                situacao="TRANSFERENCIA_TRAVADO",
                motivo=f"Cliente não conseguiu receber ou abrir os termos: {mensagem[:160]}",
                sinais=["travado", "impedimento", "transferido_por_travar"],
            )
        return Decisao(
            acao="ENVIAR_TERMOS",
            objetivo_resposta=None,
            fase="termos",
            aguardando="aceite_termos",
            atualizar_dados={"tentativas_travadas": total},
            motivo="Cliente não recebeu ou não abriu os termos — reenviar",
            prioridade="TERMOS",
            contexto_resposta={
                "reenvio_termos": True,
                "sinais": ["travado", "impedimento", "reenvio_termos"],
            },
        )

    # Dados já registrados no sistema: quem altera é a equipe. Antes a Eva perguntava
    # "posso te encaminhar?" e o "sim" do cliente era lido como aceite dos termos.
    eventos = list(resolucao.get("eventos") or [])
    cadastro_fechado = bool(estado.get("cadastro_completo")) and fase in {"termos", "agendamento", "pos_venda"}
    pede_alterar = bool(_RE_PEDE_ALTERAR_CADASTRO.search(_norm(mensagem))) and "?" not in mensagem
    if cadastro_fechado and (
        Evento.CORRECAO_DADO.value in eventos
        or resolucao.get("correcao_efetiva")
        or pede_alterar
    ):
        return _transferir(
            estado,
            situacao="TRANSFERENCIA_ALTERACAO",
            motivo=f"Cliente quer alterar dados depois do cadastro concluído: {mensagem[:180]}",
            sinais=["alteracao_pos_cadastro"],
        )
    if cadastro_fechado and (
        Evento.PEDIU_TROCAR_PLANO.value in eventos
        or (
            Evento.PLANO_INFORMADO.value in eventos
            and (resolucao.get("plano") or {}).get("alterado")
        )
    ):
        return _transferir(
            estado,
            situacao="TRANSFERENCIA_ALTERACAO",
            motivo=f"Cliente quer trocar de plano depois do cadastro concluído: {mensagem[:180]}",
            sinais=["alteracao_pos_cadastro"],
        )
    return None


# ── Depois da máquina de estados ─────────────────────────────────────────────


def _avancou(decisao: Decisao, estado: dict[str, Any]) -> bool:
    dados = decisao.atualizar_dados or {}
    for campo in _CAMPOS_DE_AVANCO:
        novo = _texto(dados.get(campo))
        if novo and novo != _texto(estado.get(campo)):
            return True
    return False


def _planos_mais_em_conta(estado: dict[str, Any]) -> list[dict[str, Any]]:
    """Planos do catálogo mais baratos que o plano em foco (fatos para responder à objeção)."""
    try:
        from app.plans_catalog import listar_planos

        planos = listar_planos(estado)
    except Exception:  # noqa: BLE001 — catálogo fora do ar não derruba a conversa
        return []
    atual_id = estado.get("plano_em_negociacao_id") or estado.get("plano_confirmado_id")
    atual = next((p for p in planos if p.get("id") == atual_id), None)
    if not atual:
        return []
    try:
        teto = float(atual.get("valor") or 0)
    except (TypeError, ValueError):
        return []
    baratos = []
    for p in planos:
        try:
            valor = float(p.get("valor") or 0)
        except (TypeError, ValueError):
            continue
        if p.get("id") != atual_id and 0 < valor < teto:
            baratos.append({
                "nome": p.get("nome"),
                "valor": valor,
                "valor_pontualidade": p.get("valor_pontualidade"),
                "beneficios": p.get("beneficios") or p.get("descricao") or "",
            })
    return sorted(baratos, key=lambda p: p["valor"], reverse=True)[:2]


def depois(decisao: Decisao, estado: dict[str, Any], resolucao: dict[str, Any]) -> Decisao:
    """Marca os turnos em que o cliente não avançou, para a resposta ser uma conversa."""
    if decisao.acao != "RESPONDER":
        # Uma ação (checar cobertura, validar CPF, cadastrar...) é avanço: zera a contagem
        if decisao.acao != "AGUARDAR" and int(estado.get("tentativas_travadas") or 0):
            decisao.atualizar_dados = {**(decisao.atualizar_dados or {}), "tentativas_travadas": 0}
        return decisao
    fase = _texto(estado.get("fase")) or "inicio"
    aguardando = _texto(estado.get("aguardando"))
    mensagem = _texto(resolucao.get("mensagem"))
    situacao = _texto(resolucao.get("situacao"))
    antes_n = int(estado.get("tentativas_travadas") or 0)
    objetivo = _texto(decisao.objetivo_resposta)
    ctx = dict(decisao.contexto_resposta or {})
    dados = dict(decisao.atualizar_dados or {})
    tem_pergunta = bool((resolucao.get("flags") or {}).get("tem_pergunta")) or bool(
        _texto(resolucao.get("pergunta"))
    )

    mesmo_passo = (
        bool(aguardando)
        and decisao.fase == fase
        and _texto(decisao.aguardando) == aguardando
        and objetivo in _OBJETIVOS_DE_REPETICAO
        and not _avancou(decisao, estado)
    )
    travado = mesmo_passo and (not tem_pergunta or situacao in {OBJECAO_PRECO, IMPEDIMENTO, MIDIA})

    if not travado:
        if situacao == MIDIA:
            # Primeira mensagem já é áudio: cumprimenta e avisa que não ouviu
            ctx["conversa"] = {"situacao": MIDIA, "midia": tipo_de_midia(mensagem), "tentativas": 0}
            ctx["sinais"] = [*ctx.get("sinais", []), "midia"]
            decisao.contexto_resposta = ctx
        if antes_n and not mesmo_passo:
            dados["tentativas_travadas"] = 0
            decisao.atualizar_dados = dados
        return decisao

    if not situacao and aguardando in _CAMPOS_PEDIDOS:
        from app.parser import eh_ack_curto

        # "ok" / "tá" depois de um pedido de dado: o cliente vai buscar, não está travado
        if eh_ack_curto(mensagem):
            situacao = ESPERA
    situacao = situacao or REPETICAO
    peso = _PESO.get(situacao, 1)
    if objetivo == "EXPLICAR_HORARIOS_UNICOS":
        peso = 2  # nenhum horário da lista serve: na segunda vez é caso para a equipe
    total = antes_n + peso
    # Pedir um tempo ou querer pensar não é travar: fica só o registro da situação
    sinais = ["travado", situacao.lower()] if peso else [situacao.lower()]

    if total >= LIMITE_TRAVADO:
        rotulo = aguardando.replace("_", " ")
        detalhe = _texto(dados.get("preferencia_horario") or estado.get("preferencia_horario"))
        extra = f" (preferência de horário: {detalhe})" if detalhe and fase == "agendamento" else ""
        return _transferir(
            {**estado, "aguardando": aguardando},
            situacao="TRANSFERENCIA_TRAVADO",
            motivo=(
                f"Cliente não avançou em '{rotulo}' — {situacao.lower()}{extra}. "
                f"Última mensagem: {mensagem[:160]}"
            ),
            sinais=[*sinais, "transferido_por_travar"],
        )

    conversa: dict[str, Any] = {
        "situacao": situacao,
        "tentativas": total,
        "repetido": antes_n > 0,
        "pendente": aguardando,
        "objetivo_original": objetivo,
    }
    if situacao == MIDIA:
        conversa["midia"] = tipo_de_midia(mensagem)
    if situacao == OBJECAO_PRECO:
        conversa["planos_mais_em_conta"] = _planos_mais_em_conta(estado)
    motivo_val = _texto(ctx.get("motivo_validacao"))
    if motivo_val:
        conversa["motivo_validacao"] = motivo_val
    ctx["conversa"] = conversa
    ctx["sinais"] = [*ctx.get("sinais", []), *sinais]
    if peso or antes_n != total:
        dados["tentativas_travadas"] = total
    decisao.contexto_resposta = ctx
    decisao.atualizar_dados = dados
    return decisao


# ── Cliente que volta depois do atendimento encerrado ────────────────────────

# Colunas do funil zeradas quando o atendimento recomeça (histórico e notas ficam)
CAMPOS_DO_FUNIL = (
    "cidade", "bairro", "tem_cobertura", "localizacao_fixa", "caixa_fibra",
    "plano_apresentado", "plano_apresentado_id", "plano_em_negociacao", "plano_em_negociacao_id",
    "plano_confirmado", "plano_confirmado_id", "nome", "cpf", "email", "telefone",
    "data_nascimento", "rg", "cep", "rua", "numero", "complemento", "metodo_pagamento",
    "ixc_cliente_id", "tecnico_id", "data_agendamento", "horarios_manha", "horarios_tarde",
    "horario_escolhido", "preferencia_horario", "os_id", "id_contrato_ixc", "ultimo_topico",
    "ultima_pergunta_cliente", "contexto_plano", "motivo_transferencia", "fase_anterior",
    "aguardando_anterior", "retorno_estado",
)
FLAGS_DO_FUNIL = (
    "documento_cpf_validado", "transferido_humano", "cadastro_completo", "agendamento_confirmado",
    "termos_enviados", "audio_fidelidade_enviado", "fidelidade_aceita", "ativado_ixc",
    "imagem_plano_enviada", "cumprimento_feito",
)
_FASES_QUE_RETOMAM = {"viabilidade", "sem_cobertura", "vendas", "cadastro", "termos"}


def estado_reiniciado(estado: dict[str, Any]) -> dict[str, Any]:
    """O mesmo cliente começando um atendimento novo: funil limpo, identificação mantida."""
    novo = dict(estado)
    for campo in CAMPOS_DO_FUNIL:
        novo[campo] = None
    for flag in FLAGS_DO_FUNIL:
        novo[flag] = False
    novo.update(
        fase="inicio", aguardando=None, tentativas_sem_cobertura=0, tentativas_plano_invalido=0,
        tentativas_travadas=0, imagens_plano_enviadas="[]",
    )
    return novo


def reabrir_se_encerrado(
    estado: dict[str, Any], resolucao: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Cliente voltou a falar depois de "finalizado": de onde a conversa continua.

    Devolve (estado para decidir, dados a gravar junto com a decisão, sinais do turno).
    Agradecimento solto continua sendo só a cortesia de despedida.
    """
    if _texto(estado.get("fase")) != "finalizado":
        return estado, {}, []
    from app.pos_venda_mensagens import eh_agradecimento_ou_despedida

    if eh_agradecimento_ou_despedida(_texto(resolucao.get("mensagem"))):
        return estado, {}, []

    # Venda concluída: volta para as dúvidas do pós-venda
    if estado.get("agendamento_confirmado"):
        return (
            {**estado, "fase": "pos_venda", "aguardando": "duvidas"},
            {},
            ["voltou_apos_encerrar"],
        )

    # Encerrado por falta de resposta: continua do passo em que estava
    retorno = estado.get("retorno_estado")
    if isinstance(retorno, dict) and _texto(retorno.get("fase")) in _FASES_QUE_RETOMAM:
        aguardando = _texto(retorno.get("aguardando")) or None
        if aguardando and not aguardando.startswith("resultado_"):
            return (
                {**estado, "fase": _texto(retorno.get("fase")), "aguardando": aguardando,
                 "tentativas_travadas": 0},
                {"retorno_estado": "", "tentativas_travadas": 0},
                ["voltou_apos_encerrar", "retomou_de_onde_parou"],
            )

    # Sem venda e sem ponto de retomada: atendimento novo
    return estado_reiniciado(estado), {"reiniciar_atendimento": True}, ["voltou_apos_encerrar"]
