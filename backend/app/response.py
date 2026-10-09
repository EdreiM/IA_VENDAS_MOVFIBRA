"""Geração da mensagem final — LLM só escreve texto."""

from __future__ import annotations

import json
import re
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
    pedir_aceite_termos,
    recusou_termos,
)
from app.pos_venda_mensagens import (
    despedida_encerramento,
    pedir_duvidas_apos_agendamento,
    pedir_falar_duvida,
    retomar_duvidas,
)
from app.conversacao_mensagens import clarificar_intencao
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
    confirmar_troca_plano_e_retomar_cadastro,
    informar_alteracao_bloqueada_pos_cadastro,
    informar_plano_bloqueado_pos_cadastro,
    informar_plano_nao_encontrado,
    informar_planos_por_beneficio,
    informar_preco_plano,
    informar_precos_planos,
    frase_voltar_ao_cadastro,
    informar_sem_cobertura,
    insistencia_sem_cobertura,
    planos_citados_no_texto,
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
- Não repita uma explicação que você já deu na conversa; se o assunto voltar, responda só o ponto novo, com outras palavras
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


_CAMPOS_CADASTRO_RETOMADA = (
    "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero",
)

# O que precisa aparecer no fim da mensagem para a retomada contar como feita
_SINAIS_DE_RETOMADA: dict[str, tuple[str, ...]] = {
    "nome": ("nome",),
    "cpf": ("cpf",),
    "email": ("e-mail", "email"),
    "telefone": ("telefone", "número", "numero", "whats"),
    "data_nascimento": ("nascimento",),
    "cep": ("cep",),
    "rua": ("rua", "endereço", "endereco"),
    "numero": ("número", "numero"),
    "confirmacao_dados": ("dados", "corret", "confirm"),
    "confirmacao_plano": ("confirm", "fechar", "seguir", "fecho"),
    "escolha_plano": ("plano", "prefere"),
    "lista_planos": ("plano", "prefere"),
    "aceite_termos": ("aceit",),
    "escolha_horario": ("horário", "horario"),
    "confirmacao_horario": ("confirm", "agendamento"),
    "duvidas": ("dúvida", "duvida"),
    "localizacao": ("cidade", "bairro"),
    "confirmar_local": ("cidade", "bairro"),
}

# Só aparece se o LLM estiver fora do ar — sem regra comercial nenhuma
_SEM_LLM = "Sobre isso eu prefiro confirmar com a equipe antes de te responder, pra não te passar nada errado."


def _retomada_apos_duvida(pendente: str, estado: dict[str, Any], *, plano_nome: str = "") -> str:
    """O próximo passo do atendimento, dito de forma direta (o LLM reescreve com as palavras dele)."""
    from app.cadastro_mensagens import pedir_campos

    if pendente in _CAMPOS_CADASTRO_RETOMADA:
        return pedir_campos([pendente])
    if pendente == "confirmacao_dados":
        return "Os dados estão corretos? Me confirma com *sim* para seguir."
    if pendente == "confirmacao_plano":
        nome = plano_nome or str(estado.get("plano_em_negociacao") or "")
        ref = f"o *{nome}*" if nome else "esse plano"
        return f"Quer confirmar {ref} pra gente seguir com o cadastro?"
    if pendente in {"escolha_plano", "lista_planos"}:
        return "Qual plano você prefere?"
    if pendente == "aceite_termos":
        return (
            "Quando estiver de acordo com o termo, me responda *aceito* que seguimos para o "
            "*agendamento da instalação*."
        )
    if pendente == "escolha_horario":
        return "Qual horário da lista fica melhor pra você?"
    if pendente == "confirmacao_horario":
        return "Posso confirmar esse agendamento?"
    if pendente == "duvidas":
        return "Mais alguma dúvida antes de encerrar?"
    if pendente in {"localizacao", "confirmar_local"}:
        return "Me passa sua *cidade* e *bairro* pra eu verificar a cobertura?"
    return ""


_RE_CONFIRMAR_COM_EQUIPE = re.compile(
    r"confirm\w*(\s+\w+){0,3}\s+com\s+(a\s+|o\s+|nossa\s+|nosso\s+|minha\s+|meu\s+)?"
    r"(equipe|time|pessoal|setor|supervis\w+|atendente)"
)


def _marcar(decisao: Decisao, sinal: str, **extra: Any) -> None:
    """Sinal do turno gerado na hora de escrever a resposta (o pipeline lê depois)."""
    ctx = dict(decisao.contexto_resposta or {})
    ctx["sinais"] = [*ctx.get("sinais", []), sinal]
    ctx.update(extra)
    decisao.contexto_resposta = ctx


def _chat_conferido(
    system: str, user: str, *, temperature: float, decisao: Decisao, fatos: str | None = None
) -> str:
    """Resposta do modelo, conferida contra os fatos do próprio prompt (app/verificacao.py).

    Se o texto cita valor, percentual, prazo ou velocidade que não está nos fatos, o modelo
    reescreve uma vez sabendo o que errou. Se insistir, devolve "" e quem chamou usa a
    resposta segura — a Eva nunca envia número que ninguém lhe deu.
    """
    from app.verificacao import afirmacoes_sem_base

    # O interpretador já falhou neste turno: não espera outro timeout para escrever a resposta
    if (decisao.contexto_resposta or {}).get("llm_fora"):
        raise RuntimeError("modelo indisponível neste turno")
    fatos = user if fatos is None else fatos
    texto = (chat(system, user, temperature=temperature) or "").strip()
    sem_base = afirmacoes_sem_base(texto, fatos) if texto else []
    if not sem_base:
        return texto
    aviso = (
        f"\n\nATENÇÃO: sua resposta anterior citou {', '.join(sem_base)}, que não aparece em "
        "nenhum fato acima. Reescreva a mensagem sem citar valor, percentual, prazo ou velocidade "
        "que não esteja escrito nos fatos. Se o cliente perguntou justamente isso, diga que "
        "prefere confirmar com a equipe."
    )
    texto = (chat(system, user + aviso, temperature=0.2) or "").strip()
    if texto and not afirmacoes_sem_base(texto, fatos):
        _marcar(decisao, "resposta_reescrita")
        return texto
    _marcar(decisao, "resposta_barrada", resposta_barrada=True)
    return ""


def _garantir_retomada(texto: str, pendente: str, retomada: str) -> str:
    """Se o LLM esqueceu de retomar o atendimento, acrescenta o próximo passo."""
    if not retomada:
        return texto
    # "prefiro confirmar com a equipe" não é pedir a confirmação do cliente
    fim = _RE_CONFIRMAR_COM_EQUIPE.sub(" ", texto[-200:].casefold())
    sinais = _SINAIS_DE_RETOMADA.get(pendente) or ()
    if sinais and any(s in fim for s in sinais):
        return texto
    return f"{texto.rstrip()}\n\n{retomada}"


def _responder_duvida(
    decisao: Decisao,
    estado: dict[str, Any],
    *,
    historico: list[dict[str, str]] | None,
    mensagem_cliente: str,
    pendente: str,
    plano_nome: str = "",
    anotados: list[str] | None = None,
    retomada: str | None = None,
) -> str:
    """Resposta a uma dúvida do cliente + retomada do atendimento, numa mensagem só.

    Escrita pelo LLM a cada pergunta, tendo como fonte a RAG (onde ficam cancelamento,
    instalação e as informações da empresa) e os dados do plano. Com o histórico, não
    repete o que já foi explicado. Não há texto pronto de regra comercial: se a base
    não trouxer a resposta, a Eva diz isso com naturalidade.

    O código só confere se a mensagem terminou retomando o atendimento (pedir o
    próximo dado, o aceite etc.) e acrescenta esse passo se o LLM esqueceu.
    """
    ctx = decisao.contexto_resposta or {}
    original = str(ctx.get("pergunta_original") or mensagem_cliente or "").strip()
    pergunta = str(decisao.pergunta or original).strip()
    if retomada is None:
        retomada = _retomada_apos_duvida(pendente, estado, plano_nome=plano_nome)

    rag_txt = formatar_contexto_rag(ctx.get("rag") or {})
    if rag_txt and _rag_parece_catalogo_planos(rag_txt):
        rag_txt = ""
    plano = _plano_do_estado(estado, ctx)
    plano_txt = ""
    if plano.get("nome"):
        plano_txt = f"{plano.get('nome')} — {_fmt_money(plano.get('valor'))}/mês"
        if plano.get("valor_pontualidade"):
            plano_txt += f" (pagando até o vencimento: {_fmt_money(plano.get('valor_pontualidade'))})"
        plano_txt = f"{plano_txt}. {plano.get('beneficios') or plano.get('descricao') or ''}".strip()
    outros_txt = ""
    for p in ctx.get("planos") or []:
        if p.get("nome") and p.get("nome") != plano.get("nome"):
            outros_txt += (
                f"- {p.get('nome')} — {_fmt_money(p.get('valor'))}/mês. "
                f"{p.get('beneficios') or p.get('descricao') or ''}\n"
            )

    # O que já está acertado com este cliente (para dúvidas como "que horas o técnico vem?")
    dados = {**estado, **(decisao.atualizar_dados or {})}
    situacao: list[str] = []
    if dados.get("cidade") or dados.get("bairro"):
        local = ", ".join(str(x) for x in (dados.get("bairro"), dados.get("cidade")) if x)
        cobertura = {True: "com cobertura confirmada", False: "sem cobertura"}.get(dados.get("tem_cobertura"), "")
        situacao.append(f"Endereço de instalação: {local} {cobertura}".strip())
    if dados.get("horario_escolhido") and dados.get("data_agendamento"):
        estado_agenda = "confirmada" if dados.get("agendamento_confirmado") else "escolhida, ainda não confirmada"
        situacao.append(
            f"Instalação {estado_agenda}: {dados.get('data_agendamento')}, {dados.get('horario_escolhido')}"
        )
    situacao_txt = "\n".join(f"- {s}" for s in situacao)

    hist_txt = ""
    for h in historico or []:
        quem = "Cliente" if h.get("remetente") == "cliente" else "Eva"
        hist_txt += f"{quem}: {h.get('mensagem')}\n"

    rotulos = {"nome": "nome", "cpf": "CPF", "email": "e-mail", "telefone": "telefone",
               "data_nascimento": "data de nascimento", "cep": "CEP", "rua": "rua", "numero": "número"}
    anotou = ", ".join(rotulos.get(c, c) for c in (anotados or []) if c)

    user = f"""O cliente fez uma dúvida no meio do atendimento. Responda e retome o atendimento, numa mensagem só.

DÚVIDA: {pergunta}
MENSAGEM COMO O CLIENTE ESCREVEU: {original or pergunta}

BASE DE CONHECIMENTO DA EMPRESA (sua fonte):
{rag_txt or '(nenhum trecho encontrado para esta pergunta)'}

PLANO DO CLIENTE: {plano_txt or '(ainda não escolhido)'}
OUTROS PLANOS DO CATÁLOGO:
{outros_txt or '(não listados para esta pergunta)'}
O QUE JÁ ESTÁ ACERTADO COM O CLIENTE:
{situacao_txt or '(nada ainda)'}

O QUE VOCÊ JÁ SABE DESTE CLIENTE:
{_notas_txt(estado) or '(nada anotado)'}

CONVERSA ATÉ AQUI:
{hist_txt or '(sem histórico)'}

DADOS QUE O CLIENTE INFORMOU NESTA MENSAGEM: {anotou or '(nenhum)'}
PRÓXIMO PASSO DO ATENDIMENTO: {retomada or '(nenhum)'}

Como escrever:
- Fale como uma atendente de verdade no WhatsApp: natural, direta, em primeira pessoa. Nada de frase de sistema ("a Eva não calcula", "não tenho essa informação na base").
- Responda exatamente o que foi perguntado, em 1 a 3 frases. Se for pergunta de sim ou não, comece pelo "sim" ou "não".
- Use somente a base de conhecimento e os dados acima. A base pode trazer mais do que foi perguntado: use só o trecho que responde a esta dúvida. Se nenhum trecho tratar do assunto perguntado, a resposta não está ali — não adapte um trecho de outro assunto.
- Se a mensagem trouxer mais de uma pergunta, responda cada uma; a que não tiver resposta na base, diga que confirma com a equipe.
- Se a resposta não estiver ali, comece a mensagem com a marca [SEM_BASE] (ela é apagada antes do envio e avisa a equipe) e diga com naturalidade que esse detalhe você prefere confirmar com a equipe, sem inventar. Nunca informe valor de multa, taxa, prazo ou data que não esteja escrito acima.
- Olhe a conversa: não repita o que você já explicou. Se o cliente voltou ao mesmo assunto, responda só o ponto que ele perguntou agora, com outras palavras; se ele pareceu não entender, explique de um jeito mais simples.
- Se o cliente informou dados nesta mensagem, diga em poucas palavras que anotou.
- Termine retomando o atendimento com as suas palavras: peça o que está em PRÓXIMO PASSO, e só isso — não peça nenhum outro dado.

Escreva somente a mensagem.
"""
    try:
        texto = (
            _chat_conferido(_system_prompt(), user, temperature=0.4, decisao=decisao)
            if pergunta else ""
        )
    except Exception:  # noqa: BLE001 — LLM fora do ar
        texto = ""
    if not texto:
        if (decisao.contexto_resposta or {}).get("resposta_barrada"):
            # A Eva vai dizer que confirma com a equipe: a pergunta fica registrada
            decisao.contexto_resposta = {**(decisao.contexto_resposta or {}), "sem_base": True}
        return f"{_SEM_LLM}\n\n{retomada}".strip() if pergunta else retomada
    if _RE_SEM_BASE.search(texto):
        # A base não respondeu: a pergunta fica registrada para a equipe completar a RAG
        texto = _RE_SEM_BASE.sub("", texto).strip()
        decisao.contexto_resposta = {**(decisao.contexto_resposta or {}), "sem_base": True}
    return _garantir_retomada(texto, pendente, retomada)


_RE_SEM_BASE = re.compile(r"\[\s*SEM[_ ]BASE\s*\]", re.I)

# Como reagir a cada situação (orientação de conversa — os fatos vêm do catálogo e da RAG)
_GUIA_SITUACAO: dict[str, str] = {
    "ESPERA": (
        "O cliente pediu um tempo para pegar ou procurar o que você pediu. Diga que tudo bem e que "
        "você fica aguardando. Em poucas palavras, lembre o que fica faltando. Não repita o pedido "
        "inteiro nem faça outra pergunta."
    ),
    "ADIAMENTO": (
        "O cliente quer pensar ou deixar para depois. Acolha sem pressionar. Pergunte se ficou "
        "alguma dúvida que você possa esclarecer agora e diga que é só chamar quando quiser "
        "continuar. Não repita o pedido."
    ),
    "IMPEDIMENTO": (
        "O cliente disse que não tem, não sabe ou não conseguiu o que você pediu. Reconheça isso e "
        "ajude com um caminho prático (onde essa informação costuma estar, tentar de outro jeito). "
        "Se a base de conhecimento trouxer uma alternativa, use. Não diga que dá para seguir sem "
        "isso se não estiver escrito nos fatos. Termine perguntando se assim ele consegue."
    ),
    "OBJECAO_PRECO": (
        "O cliente achou caro ou comparou com outra empresa. Reconheça a preocupação, sem discutir "
        "e sem falar mal de concorrente. Use só os fatos abaixo (valor com pontualidade, "
        "benefícios, base de conhecimento). Se houver plano mais em conta na lista, ofereça pelo "
        "nome e preço. Não invente desconto nem condição. Termine perguntando como ele prefere seguir."
    ),
    "NAO_ENTENDEU": (
        "O cliente não entendeu o que você pediu. Explique de um jeito mais simples o que você "
        "precisa e para quê, com um exemplo do formato se ajudar."
    ),
    "MIDIA": (
        "O cliente mandou {midia} e você não conseguiu {acao_midia}. Diga isso com "
        "naturalidade, sem pedir desculpas longas, e peça para ele escrever."
    ),
    "REPETICAO": (
        "O cliente respondeu outra coisa no lugar do que você pediu. Responda em uma frase ao que "
        "ele disse (comentário, brincadeira, desabafo, um 'ok' solto) e retome o pedido com outras "
        "palavras."
    ),
    "TRANSFERENCIA_SUPORTE": (
        "A pessoa já é cliente e precisa de suporte ou do financeiro, que não é com você. Diga em "
        "1 ou 2 frases que entendeu e que já está encaminhando para a equipe que resolve isso, que "
        "continua o atendimento por aqui mesmo. Não peça nenhum dado e não tente resolver."
    ),
    "TRANSFERENCIA_ALTERACAO": (
        "O cadastro do cliente já foi registrado no sistema e você não consegue alterar por aqui. "
        "Diga isso em 1 ou 2 frases e que já está chamando uma pessoa da equipe para ajustar com "
        "ele por aqui mesmo. Não pergunte se pode encaminhar: já está encaminhando."
    ),
    "TRANSFERENCIA_TRAVADO": (
        "Vocês não conseguiram avançar neste passo. Diga em 1 ou 2 frases, sem culpar o cliente, "
        "que para facilitar você vai chamar uma pessoa da equipe para ajudar com isso e que ela "
        "continua por aqui mesmo. Não peça mais nada."
    ),
}

# Dicas práticas de onde achar o dado (não são regra da empresa)
_DICA_CAMPO: dict[str, str] = {
    "cep": "O CEP costuma estar em conta de luz, de água ou em correspondências; também aparece pesquisando o nome da rua na internet.",
    "cpf": "O CPF aparece no RG novo, na CNH e no aplicativo gov.br.",
    "email": "Serve qualquer e-mail que o cliente consiga acessar.",
    "telefone": "Serve o número do próprio WhatsApp, com DDD.",
    "numero": "Se a casa não tiver número, o cliente pode dizer que é sem número.",
}

_SEM_LLM_CONVERSA: dict[str, str] = {
    "TRANSFERENCIA_SUPORTE": (
        "Entendi! Isso é com a nossa equipe de atendimento. Já estou te encaminhando para um "
        "atendente continuar com você por aqui."
    ),
    "TRANSFERENCIA_ALTERACAO": (
        "Seus dados já foram registrados no sistema e por aqui eu não consigo alterar. Já estou "
        "chamando um atendente da equipe para ajustar isso com você."
    ),
    "TRANSFERENCIA_TRAVADO": (
        "Para facilitar, vou chamar um atendente da nossa equipe para te ajudar com isso. "
        "Em instantes alguém continua com você por aqui."
    ),
    "TRANSFERENCIA_INSTABILIDADE": (
        "Estou com uma instabilidade aqui no sistema. Para você não ficar esperando, vou chamar "
        "um atendente da nossa equipe para continuar com você por aqui."
    ),
}

# Modelo fora do ar e as regras não entenderam a mensagem: melhor pedir de novo do que chutar
_INSTABILIDADE_REENVIO = (
    "Tive uma instabilidade aqui do meu lado e não consegui ler sua mensagem. "
    "Pode me mandar de novo, por favor?"
)


def _notas_txt(estado: dict[str, Any]) -> str:
    notas = [ln.strip() for ln in str(estado.get("notas_conversa") or "").split("\n") if ln.strip()]
    return "\n".join(f"- {n}" for n in notas)


def _fatos_da_etapa(decisao: Decisao, estado: dict[str, Any], conversa: dict[str, Any]) -> str:
    """O que a Eva pode afirmar neste turno: plano, planos mais em conta, horários, RAG."""
    ctx = decisao.contexto_resposta or {}
    dados = {**estado, **(decisao.atualizar_dados or {})}
    partes: list[str] = []

    fala_de_plano = conversa.get("situacao") in {"OBJECAO_PRECO", "ADIAMENTO"} or str(
        conversa.get("pendente") or ""
    ) in {"confirmacao_plano", "escolha_plano", "lista_planos"}
    plano = _plano_do_estado(estado, ctx) if fala_de_plano else {}
    if plano.get("nome"):
        linha = f"Plano em conversa: {plano.get('nome')} — {_fmt_money(plano.get('valor'))}/mês"
        if plano.get("valor_pontualidade"):
            linha += f" (pagando até o vencimento: {_fmt_money(plano.get('valor_pontualidade'))})"
        beneficios = str(plano.get("beneficios") or plano.get("descricao") or "").strip()
        partes.append(f"{linha}. {beneficios}".strip())

    for p in conversa.get("planos_mais_em_conta") or []:
        linha = f"Plano mais em conta: {p.get('nome')} — {_fmt_money(p.get('valor'))}/mês"
        if p.get("valor_pontualidade"):
            linha += f" (pagando até o vencimento: {_fmt_money(p.get('valor_pontualidade'))})"
        partes.append(f"{linha}. {str(p.get('beneficios') or '').strip()}".strip())
    if conversa.get("situacao") == "OBJECAO_PRECO" and not conversa.get("planos_mais_em_conta"):
        partes.append("Não há plano mais barato que este no catálogo.")

    if str(dados.get("fase") or "") == "agendamento" or str(conversa.get("pendente") or "") in {
        "escolha_horario", "confirmacao_horario",
    }:
        def _lista(v: Any) -> str:
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except json.JSONDecodeError:
                    v = [v]
            return ", ".join(str(x) for x in (v or []))

        manha, tarde = _lista(dados.get("horarios_manha")), _lista(dados.get("horarios_tarde"))
        if manha or tarde:
            partes.append(
                f"Horários com técnico disponível em {dados.get('data_agendamento') or 'data a confirmar'}: "
                f"manhã: {manha or 'nenhum'}; tarde: {tarde or 'nenhum'}. São os únicos dessa data."
            )
        if dados.get("horario_escolhido"):
            partes.append(f"Horário que o cliente escolheu: {dados.get('horario_escolhido')}.")
        if dados.get("preferencia_horario"):
            partes.append(
                f"Preferência que o cliente disse e você anotou: {dados.get('preferencia_horario')}. "
                "Se nenhum horário da lista servir, você pode chamar a equipe para combinar outro dia."
            )

    if conversa.get("motivo_validacao"):
        partes.append(f"O dado que o cliente mandou veio com problema: {conversa['motivo_validacao']}.")
    dica = _DICA_CAMPO.get(str(conversa.get("pendente") or ""))
    if dica and conversa.get("situacao") in {"IMPEDIMENTO", "NAO_ENTENDEU"}:
        partes.append(dica)

    rag_txt = formatar_contexto_rag(ctx.get("rag") or {})
    if rag_txt and not _rag_parece_catalogo_planos(rag_txt):
        partes.append(f"Base de conhecimento da empresa:\n{rag_txt}")
    return "\n".join(f"- {p}" for p in partes)


def _conversar(
    decisao: Decisao,
    estado: dict[str, Any],
    *,
    historico: list[dict[str, str]] | None,
    mensagem_cliente: str,
) -> str:
    """Resposta escrita pelo LLM quando o cliente não respondeu ao passo pedido.

    Em vez de repetir a mesma frase ("Qual o CEP?"), a Eva responde ao que o cliente
    disse — pediu um tempo, não tem o dado, achou caro, mandou áudio — e conduz de volta.
    Devolve "" quando o LLM não respondeu: quem chama usa o texto de sempre.
    """
    ctx = decisao.contexto_resposta or {}
    conversa = dict(ctx.get("conversa") or {})
    situacao = str(conversa.get("situacao") or "REPETICAO")
    pendente = str(conversa.get("pendente") or ctx.get("pendente") or decisao.aguardando or "")
    transferindo = situacao.startswith("TRANSFERENCIA_")
    plano_nome = str(estado.get("plano_em_negociacao") or estado.get("plano_confirmado") or "")
    retomada = "" if transferindo else _retomada_apos_duvida(pendente, estado, plano_nome=plano_nome)

    guia = _GUIA_SITUACAO.get(situacao) or _GUIA_SITUACAO["REPETICAO"]
    if situacao == "MIDIA":
        midia = str(conversa.get("midia") or "audio")
        guia = guia.format(
            midia={"audio": "um áudio", "image": "uma imagem", "video": "um vídeo"}.get(midia, "um arquivo"),
            acao_midia="ouvir esse áudio" if midia == "audio" else "abrir esse tipo de arquivo",
        )
    if conversa.get("objetivo_original") == "CLARIFICAR_INTENCAO" and situacao == "REPETICAO":
        guia = (
            "Você não teve certeza do que o cliente quis dizer. Diga isso com naturalidade, em uma "
            "frase, pergunte o que ele quis dizer e lembre o que você estava pedindo."
        )
    if conversa.get("objetivo_original") == "EXPLICAR_HORARIOS_UNICOS":
        guia = (
            "O cliente não pode nos horários oferecidos ou pediu outro dia ou horário. Diga que "
            "anotou a preferência dele, explique que os horários da lista são os que têm técnico "
            "disponível nessa data e pergunte se algum deles serve. Diga que, se nenhum servir, "
            "você chama a equipe para combinar outro dia."
        )
    if conversa.get("repetido") and not transferindo:
        guia += " Você já pediu isso antes nesta conversa: não use a mesma frase de novo."

    hist_txt = ""
    for h in historico or []:
        quem = "Cliente" if h.get("remetente") == "cliente" else "Eva"
        hist_txt += f"{quem}: {h.get('mensagem')}\n"

    if situacao in {"ESPERA", "ADIAMENTO"} or transferindo:
        fecho = "Não termine com pedido de dado nem com pergunta de confirmação."
    else:
        fecho = (
            "Termine retomando o atendimento com as suas palavras: peça o que está em O QUE VOCÊ "
            "TINHA PEDIDO, e só isso — não peça nenhum outro dado."
        )

    user = f"""O cliente respondeu ao seu último pedido com outra coisa. Escreva a próxima mensagem.

O QUE VOCÊ TINHA PEDIDO: {retomada or _rotulo_pendente(pendente) or '(nada pendente)'}
MENSAGEM DO CLIENTE: {mensagem_cliente or '(sem texto)'}

O QUE ACONTECEU E COMO REAGIR:
{guia}

FATOS QUE VOCÊ PODE USAR (não afirme nada além disso):
{_fatos_da_etapa(decisao, estado, conversa) or '(nenhum fato específico para este momento)'}

O QUE VOCÊ JÁ SABE DESTE CLIENTE:
{_notas_txt(estado) or '(nada anotado)'}

CONVERSA ATÉ AQUI:
{hist_txt or '(sem histórico)'}

Como escrever:
- Fale como uma atendente de verdade no WhatsApp: natural, direta, em primeira pessoa, 1 a 3 frases.
- Comece respondendo ao que o cliente disse. Nada de frase de sistema ("não entendi sua mensagem", "opção inválida").
- Não invente preço, desconto, prazo, regra ou promessa. O que não estiver nos fatos, você prefere confirmar com a equipe.
- Não repita frases que você já usou na conversa acima.
- {fecho}

Escreva somente a mensagem.
"""
    try:
        texto = _chat_conferido(_system_prompt(), user, temperature=0.5, decisao=decisao)
    except Exception:  # noqa: BLE001 — LLM fora do ar
        texto = ""
    if not texto:
        return ""
    if situacao in {"ESPERA", "ADIAMENTO"} or transferindo:
        return texto
    return _garantir_retomada(texto, pendente, retomada)


def _rag_parece_catalogo_planos(texto: str) -> bool:
    """RAG às vezes devolve catálogo inteiro — não usar como resposta."""
    low = str(texto or "").casefold()
    if not low:
        return False
    if "linha internet" in low or "beneficios:" in low:
        return True
    nomes = sum(
        1 for m in ("mov essencial", "mov one", "mov super", "mov up", "mov infinity")
        if m in low
    )
    return nomes >= 2


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
    from app.plans_catalog import listar_planos

    planos = listar_planos(estado)
    pid = (
        (plano.get("id") if isinstance(plano, dict) else None)
        or estado.get("plano_em_negociacao_id")
        or estado.get("plano_apresentado_id")
        or estado.get("plano_confirmado_id")
    )
    if isinstance(plano, dict) and plano.get("id") is not None:
        for p in planos:
            if int(p.get("id") or -1) == int(plano["id"]):
                return p
    if (
        isinstance(plano, dict)
        and plano.get("nome")
        and (plano.get("valor") or plano.get("valor_pontualidade"))
        and (plano.get("beneficios") or plano.get("descricao") or plano.get("dispositivos_max"))
    ):
        return plano
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
        "confirmar_local": "confirmar se o lugar informado é o bairro, e qual a cidade",
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


_CAMPOS_CADASTRO = frozenset({
    "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero", "confirmacao_dados",
})


def _preco_com_retomada_cadastro(
    base: str,
    ctx: dict[str, Any],
    decisao: Decisao,
    estado: dict[str, Any],
) -> str:
    """Durante cadastro, responde preço e retoma o pendente — sem pedir confirmação de plano."""
    pendente = str(ctx.get("pendente") or decisao.aguardando or "")
    fase_ef = str(estado.get("fase") or decisao.fase or "")
    if fase_ef != "cadastro" or pendente not in _CAMPOS_CADASTRO:
        return base
    linhas = base.strip().splitlines()
    while linhas:
        ult = linhas[-1].casefold()
        if any(x in ult for x in ("quer ", "qual desses", "prefere", "seguir com")):
            linhas.pop()
            while linhas and not linhas[-1].strip():
                linhas.pop()
            continue
        break
    preco = "\n".join(linhas).strip()
    if "\n\n" in preco and "quer confirmar" in preco.casefold():
        preco = preco.split("\n\n", 1)[0].strip()
    return f"{preco}\n\n{frase_voltar_ao_cadastro(pendente)}"


def gerar_resposta(
    decisao: Decisao,
    estado: dict[str, Any],
    *,
    origem: str = "cliente",
    historico: list[dict[str, str]] | None = None,
    mensagem_cliente: str = "",
) -> str:
    conversa = (decisao.contexto_resposta or {}).get("conversa") or {}
    if conversa:
        texto = _resposta_de_conversa(
            decisao, estado, origem=origem, historico=historico, mensagem_cliente=mensagem_cliente
        )
        if texto:
            return texto
    texto = _gerar_resposta(
        decisao, estado, origem=origem, historico=historico, mensagem_cliente=mensagem_cliente
    )
    # Último dado do cadastro veio junto com uma dúvida: responde e já mostra o resumo
    if (decisao.contexto_resposta or {}).get("anexar_resumo"):
        from app.vendas_mensagens import rotulo_pendente_cadastro

        base = (texto or "").replace(rotulo_pendente_cadastro("confirmacao_dados"), "").rstrip()
        resumo = montar_resumo_cadastro({**estado, **(decisao.atualizar_dados or {})})
        texto = f"{base}\n\n{resumo}" if base else resumo
    return texto


def _resposta_de_conversa(
    decisao: Decisao,
    estado: dict[str, Any],
    *,
    origem: str,
    historico: list[dict[str, str]] | None,
    mensagem_cliente: str,
) -> str:
    """Turno em que o cliente não avançou: o LLM conversa; sem LLM, cai no texto de sempre."""
    conversa = (decisao.contexto_resposta or {}).get("conversa") or {}
    situacao = str(conversa.get("situacao") or "")

    def _com_aviso_de_midia() -> str:
        base = _gerar_resposta(
            decisao, estado, origem=origem, historico=historico, mensagem_cliente=""
        )
        return f"{_aviso_midia(str(conversa.get('midia') or 'audio'))}\n\n{base}".strip()

    # Primeiro contato já em áudio: a abertura normal, avisando que não deu para ouvir
    if situacao == "MIDIA" and not int(conversa.get("tentativas") or 0):
        return _com_aviso_de_midia()

    if situacao == "TRANSFERENCIA_INSTABILIDADE":
        return _SEM_LLM_CONVERSA[situacao]  # o modelo é justamente o que está fora do ar
    texto = _conversar(decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente)
    if texto:
        return texto
    if situacao in _SEM_LLM_CONVERSA:
        return _SEM_LLM_CONVERSA[situacao]
    if situacao == "MIDIA":
        return _com_aviso_de_midia()
    return ""


def _aviso_midia(midia: str) -> str:
    if midia == "audio":
        return "Não consegui ouvir esse áudio por aqui. Pode me escrever, por favor?"
    return "Não consegui abrir o que você mandou por aqui. Pode me escrever, por favor?"


def _gerar_resposta(
    decisao: Decisao,
    estado: dict[str, Any],
    *,
    origem: str = "cliente",
    historico: list[dict[str, str]] | None = None,
    mensagem_cliente: str = "",
) -> str:
    _ = origem

    if decisao.objetivo_resposta == "INSTABILIDADE_PEDIR_REENVIO":
        return _INSTABILIDADE_REENVIO

    if decisao.objetivo_resposta == "INFORMAR_TRANSFERENCIA_AJUDA":
        situacao = str(((decisao.contexto_resposta or {}).get("conversa") or {}).get("situacao") or "")
        return _SEM_LLM_CONVERSA.get(situacao) or _SEM_LLM_CONVERSA["TRANSFERENCIA_TRAVADO"]

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

    if decisao.objetivo_resposta == "CONFIRMAR_BAIRRO_OU_CIDADE":
        from app.utils.formatters import titulo_palavras

        ctx = decisao.contexto_resposta or {}
        local = titulo_palavras(str(ctx.get("local") or estado.get("bairro") or "").strip())
        return f"*{local}* é o seu bairro? Se for, me conta também qual é a *cidade*."

    if decisao.objetivo_resposta == "INFORMAR_CIDADE_NAO_ATENDIDA":
        from app.localizacao_heuristica import cidades_atendidas
        from app.utils.formatters import titulo_palavras

        ctx = decisao.contexto_resposta or {}
        cidade = titulo_palavras(str(ctx.get("cidade") or estado.get("cidade") or "").strip())
        lista = cidades_atendidas()
        atendidas = ", ".join(lista[:-1]) + f" e {lista[-1]}" if len(lista) > 1 else "".join(lista)
        return (
            f"Entendi, *{cidade}* é a cidade. Por enquanto a MOV FIBRA ainda não atende aí.\n\n"
            f"Hoje atendemos em {atendidas}. Se a instalação for em uma dessas cidades, "
            "me diz a *cidade* e o *bairro* que eu verifico pra você."
        )

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
        from app.saudacao import texto_pedir_localizacao_instalacao

        return texto_pedir_localizacao_instalacao(compacto=True)

    if decisao.objetivo_resposta == "CUMPRIMENTAR_E_RETOMAR":
        ctx = decisao.contexto_resposta or {}
        pendente = str(ctx.get("pendente") or decisao.aguardando or "")
        return mensagem_cumprimento_retomar(
            mensagem_cliente, pendente, {**estado, **(decisao.atualizar_dados or {})}
        )

    if decisao.objetivo_resposta == "CLARIFICAR_INTENCAO":
        return clarificar_intencao(decisao.contexto_resposta or {})

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
            termos_mock=bool(ctx.get("termos_mock")),
        )

    if decisao.objetivo_resposta == "CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA":
        return _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente="confirmacao_dados",
        )

    if decisao.objetivo_resposta == "INFORMAR_RECUSA_TERMOS":
        return recusou_termos()

    if decisao.objetivo_resposta == "INFORMAR_ERRO_TERMOS_E_TRANSFERENCIA":
        return (
            "Não consegui enviar o contrato e o áudio de fidelidade agora. "
            "Vou te encaminhar para nossa equipe continuar o atendimento, tudo bem?"
        )

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
        pergunta_bruta = str(decisao.pergunta or ctx.get("pergunta_original") or "")
        # "sim" solto logo depois de uma dúvida de cancelamento: a explicação já foi dada —
        # pede o aceite de forma direta em vez de repetir o texto inteiro.
        if ctx.get("esclarecer_aceite"):
            return pedir_aceite_termos(pedir_aceite_explicito=True)
        if normalizar_texto(pergunta_bruta) in {"aceito", "aceita", "concordo"}:
            return pedir_aceite_termos(
                termos_enviados=bool(estado.get("termos_enviados")),
            )
        return _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente="aceite_termos",
        )

    if decisao.objetivo_resposta == "PEDIR_HORARIO_ESPECIFICO":
        return pedir_horario_especifico({**estado, **(decisao.atualizar_dados or {})})

    if decisao.objetivo_resposta == "PEDIR_DUVIDAS":
        return "Antes de encerrar, *tem mais alguma dúvida?*"

    if decisao.objetivo_resposta == "PEDIR_FALAR_DUVIDA":
        return pedir_falar_duvida()

    if decisao.objetivo_resposta == "CORTESIA_POS_ENCERRAMENTO":
        from app.pos_venda_mensagens import cortesia_pos_encerramento

        return cortesia_pos_encerramento(str(estado.get("nome") or ""))

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

    if decisao.objetivo_resposta == "ESCLARECER_BAIRRO":
        from app.vendas_mensagens import esclarecer_bairro

        ctx = decisao.contexto_resposta or {}
        return esclarecer_bairro(
            str(ctx.get("bairro_informado") or ""),
            list(ctx.get("bairros_sugeridos") or []),
        )

    if decisao.objetivo_resposta == "INFORMAR_PLANO_NAO_ENCONTRADO":
        ctx = decisao.contexto_resposta or {}
        return informar_plano_nao_encontrado(str(ctx.get("referencia") or ""))

    if decisao.objetivo_resposta == "INFORMAR_PLANO_BLOQUEADO_POS_CADASTRO":
        ctx = decisao.contexto_resposta or {}
        plano_n = str(
            ctx.get("plano_atual")
            or estado.get("plano_confirmado")
            or ""
        )
        return informar_plano_bloqueado_pos_cadastro(plano_n)

    if decisao.objetivo_resposta == "INFORMAR_ALTERACAO_BLOQUEADA_POS_CADASTRO":
        return informar_alteracao_bloqueada_pos_cadastro()

    if decisao.objetivo_resposta == "CONFIRMAR_TROCA_PLANO_E_RETOMAR_CADASTRO":
        ctx = decisao.contexto_resposta or {}
        plano = _plano_do_estado(estado, ctx)
        pendente = str(ctx.get("pendente") or decisao.aguardando or "nome")
        return confirmar_troca_plano_e_retomar_cadastro(plano, pendente=pendente)

    if decisao.objetivo_resposta == "PRIORIZAR_PLANO_ANTES_CADASTRO":
        from app.vendas_mensagens import prioritizar_plano_antes_cadastro

        ctx = decisao.contexto_resposta or {}
        return prioritizar_plano_antes_cadastro(
            aguardando_cadastro=str(ctx.get("aguardando_cadastro") or ""),
        )

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
            from app.parser import extrair_referencia_plano_na_mensagem
            from app.plans import resolver_plano
            from app.plans_catalog import listar_planos

            ref_resolve = extrair_referencia_plano_na_mensagem(ref, ref) or ref
            plano_atual_id = None
            try:
                if estado.get("plano_em_negociacao_id") is not None:
                    plano_atual_id = int(estado["plano_em_negociacao_id"])
            except (TypeError, ValueError):
                plano_atual_id = None
            resolvido = resolver_plano(
                ref_resolve, listar_planos(estado), plano_atual_id=plano_atual_id
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
        from app.plans_catalog import listar_planos

        catalogo = listar_planos(estado)
        plano_atual = _plano_do_estado(estado, ctx)
        if not plano_atual.get("nome"):
            msg_cli = str(ctx.get("mensagem_cliente") or ctx.get("referencia_plano") or "")
            if msg_cli:
                from app.plans import resolver_plano_citado_na_mensagem

                citado = resolver_plano_citado_na_mensagem(msg_cli, msg_cli, catalogo)
                if citado:
                    plano_atual = citado
        ultima = str(estado.get("ultima_mensagem_sofia") or "")
        msg_cli = str(ctx.get("mensagem_cliente") or "")
        citados = planos_citados_no_texto(msg_cli, catalogo) if msg_cli else []
        if not citados:
            citados = planos_citados_no_texto(ultima, catalogo)
        # Se a Eva citou outros planos (ex.: ONE+ / UP+ com Disney), preço deles
        if len(citados) >= 1:
            ids_citados = {int(p.get("id") or -1) for p in citados}
            id_atual = int(plano_atual.get("id") or -1) if plano_atual else -1
            # Citou alternativas além do atual, ou só as alternativas
            if len(citados) > 1 or (citados and id_atual not in ids_citados):
                base = informar_precos_planos(
                    citados,
                    plano_atual=plano_atual,
                    contexto="Sobre os planos que comentei:",
                )
                return _preco_com_retomada_cadastro(base, ctx, decisao, estado)
        base = informar_preco_plano(plano_atual)
        return _preco_com_retomada_cadastro(base, ctx, decisao, estado)

    if decisao.objetivo_resposta == "INFORMAR_CANCELAMENTO_E_RETOMAR":
        ctx = decisao.contexto_resposta or {}
        return _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente=str(ctx.get("pendente") or decisao.aguardando or ""),
            anotados=list(ctx.get("campos_anotados") or []),
        )

    if decisao.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR":
        ctx = decisao.contexto_resposta or {}
        plano = _plano_do_estado(estado, ctx)
        nome = str(
            ctx.get("plano_nome")
            or (plano or {}).get("nome")
            or estado.get("plano_em_negociacao")
            or estado.get("plano_confirmado")
            or ""
        )
        return _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente=str(ctx.get("pendente") or decisao.aguardando or "confirmacao_plano"),
            plano_nome=nome,
            anotados=list(ctx.get("campos_anotados") or []),
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
        return confirmar_plano_e_avancar(nome, valor, estado)

    if decisao.objetivo_resposta == "CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA":
        from app.parser import (
            eh_pergunta_cancelamento,
            eh_pergunta_instalacao,
            eh_pergunta_preco_plano_nomeado,
        )
        from app.state_machine import _detectar_beneficio_pergunta

        ctx = decisao.contexto_resposta or {}
        plano = _plano_do_estado(estado, ctx)
        nome = str(plano.get("nome") or estado.get("plano_confirmado") or "")
        valor = _fmt_money(plano.get("valor") or plano.get("valor_pontualidade"))
        preco = f" — *{valor}*" if valor else ""
        pergunta_bruta = str(ctx.get("pergunta_original") or decisao.pergunta or "")
        pergunta_txt = normalizar_texto(pergunta_bruta)
        topico = str(ctx.get("topico_contexto") or "")
        beneficio = _detectar_beneficio_pergunta(pergunta_txt)
        from app.cadastro_mensagens import campos_para_pedir, pedir_campos

        prox_cad = campos_para_pedir(estado, str(decisao.aguardando or "")) or ["nome", "cpf"]
        retomada = pedir_campos(prox_cad)
        prefixo = f"Perfeito! Vamos seguir com o *{nome}*{preco}.\n\n"

        if topico == "cancelamento" or eh_pergunta_cancelamento(
            pergunta_bruta, pergunta_bruta, topico=topico
        ):
            return prefixo + _responder_duvida(
                decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
                pendente=prox_cad[0] if prox_cad else "nome", retomada=retomada,
            )
        if topico == "preco_plano" or eh_pergunta_preco_plano_nomeado(
            pergunta_txt, pergunta_bruta
        ):
            return prefixo + informar_preco_plano(plano if isinstance(plano, dict) else {}) + f"\n\n{retomada}"
        if beneficio or topico == "beneficio_plano":
            from app.plans_catalog import listar_planos

            catalogo = listar_planos(estado)
            chave = (beneficio or "benefício").casefold().replace("+", "")
            com = [
                p
                for p in catalogo
                if chave in " ".join(str(t) for t in (p.get("tags") or [])).casefold()
                or chave in str(p.get("beneficios") or p.get("descricao") or "").casefold()
                or chave in str(p.get("nome") or "").casefold()
            ]
            return prefixo + informar_planos_por_beneficio(
                beneficio or "benefício", com, plano_atual=plano
            ) + f"\n\n{retomada}"
        from app.parser import eh_pergunta_detalhe_plano

        # "O que vem nele?" → ficha do plano. Qualquer outra dúvida → base de conhecimento.
        if topico == "detalhe_plano" or (
            eh_pergunta_detalhe_plano(pergunta_txt, pergunta_bruta)
            and not eh_pergunta_instalacao(pergunta_txt, pergunta_bruta)
        ):
            detalhe = informar_detalhes_plano(plano if isinstance(plano, dict) else {})
            return prefixo + detalhe + f"\n\n{retomada}"
        return prefixo + _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente=prox_cad[0] if prox_cad else "nome", plano_nome=nome, retomada=retomada,
        )

    if decisao.objetivo_resposta == "CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA":
        ctx = decisao.contexto_resposta or {}
        horario = str(
            ctx.get("horario")
            or estado.get("horario_escolhido")
            or decisao.atualizar_dados.get("horario_escolhido")
            or ""
        )
        data = str(ctx.get("data") or estado.get("data_agendamento") or "")
        pergunta = normalizar_texto(
            str(ctx.get("pergunta_original") or decisao.pergunta or "")
        )
        _ = pergunta
        # Antes saía "Sobre sua dúvida: vou te explicar" sem explicar nada: agora a dúvida
        # é respondida pela base, como em qualquer outra etapa.
        base = f"Perfeito! Anotei *{horario}* no dia *{data}*."
        return base + "\n\n" + _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente="confirmacao_horario",
        )

    if decisao.objetivo_resposta == "ANOTAR_E_PEDIR_PROXIMO":
        ctx = decisao.contexto_resposta or {}
        dados = {**estado, **(decisao.atualizar_dados or {})}
        return anotar_e_pedir_proximo(
            campos_anotados=list(ctx.get("campos_anotados") or []),
            campos_corrigidos=list(ctx.get("campos_corrigidos") or []),
            pendente=str(ctx.get("pendente") or decisao.aguardando or ""),
            estado=dados,
            retomada_cadastro=bool(ctx.get("retomada_cadastro")),
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
                faltam = campos_para_pedir(
                    {**estado, **(decisao.atualizar_dados or {})}, campo
                )
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
        topico = str(ctx.get("topico_contexto") or "")
        plano_ref = str(estado.get("plano_confirmado") or estado.get("plano_em_negociacao") or "")
        if topico == "beneficio_plano":
            # Benefícios vêm do catálogo de planos, não da RAG
            plano = _plano_do_estado(estado, ctx)
            retomada = _retomada_apos_duvida(pendente, estado, plano_nome=plano_ref)
            return informar_detalhes_plano(plano if isinstance(plano, dict) else {}) + (
                f"\n\n{retomada}" if retomada else ""
            )
        return _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente=pendente, plano_nome=plano_ref,
        )

    if str(estado.get("fase") or "") == "cadastro" and decisao.objetivo_resposta in {
        "CONTINUAR_CONVERSA",
        "CONVERSAR_E_RETOMAR",
    }:
        from app.cadastro_mensagens import campos_para_pedir, pedir_campos

        ctx_cad = decisao.contexto_resposta or {}
        merged = {**estado, **(decisao.atualizar_dados or {})}
        pend = str(ctx_cad.get("pendente") or decisao.aguardando or "")
        faltam = campos_para_pedir(merged, pend) or ([pend] if pend else [])
        cadastro_ok = {
            "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero",
        }
        if faltam and all(c in cadastro_ok for c in faltam):
            plano_n = str(merged.get("plano_confirmado") or "").strip()
            intro = f"Beleza! Seguimos com o *{plano_n}*. " if plano_n else "Beleza! "
            return intro + pedir_campos(faltam)

    if decisao.objetivo_resposta == "ANOTAR_DADO_E_RETOMAR_PLANO":
        ctx = decisao.contexto_resposta or {}
        campos = [c for c in (ctx.get("campos_anotados") or []) if c in {"nome", "cpf", "email", "telefone"}]
        plano_n = str(
            estado.get("plano_em_negociacao")
            or estado.get("plano_apresentado")
            or ""
        ).strip()
        rotulos = {"nome": "seu nome", "cpf": "CPF", "email": "e-mail", "telefone": "telefone"}
        if campos:
            itens = [rotulos.get(c, c) for c in campos]
            anot = f"Anotei {itens[0]}." if len(itens) == 1 else f"Anotei {' e '.join(itens)}."
        else:
            anot = ""
        if plano_n:
            pergunta = f"Quer confirmar o *{plano_n}* pra gente seguir com o cadastro?"
            return f"{anot} {pergunta}".strip()
        from app.vendas_mensagens import prioritizar_plano_antes_cadastro

        return prioritizar_plano_antes_cadastro(
            aguardando_cadastro=str(ctx.get("aguardando_cadastro") or "nome"),
        )

    ctx = decisao.contexto_resposta or {}
    topico = str(ctx.get("topico_contexto") or "")
    _ = topico
    # Toda dúvida passa pelo mesmo redator (base de conhecimento + conferência dos fatos).
    # Antes só cancelamento e instalação passavam; o resto ia pelo prompt geral abaixo.
    if decisao.objetivo_resposta in {
        "RESPONDER_PERGUNTA_E_RETOMAR",
        "RESPONDER_DUVIDA_E_RETOMAR",
        "CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA",
        "CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA",
        "CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA",
    } and str(decisao.pergunta or ctx.get("pergunta_original") or "").strip():
        pendente_duvida = str(ctx.get("pendente") or decisao.aguardando or "")
        if decisao.objetivo_resposta == "RESPONDER_DUVIDA_E_RETOMAR":
            pendente_duvida = "duvidas"
        return _responder_duvida(
            decisao, estado, historico=historico, mensagem_cliente=mensagem_cliente,
            pendente=pendente_duvida,
            plano_nome=str(estado.get("plano_em_negociacao") or estado.get("plano_confirmado") or ""),
            anotados=list(ctx.get("campos_anotados") or []),
        )

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

O QUE VOCÊ JÁ SABE DESTE CLIENTE (leve em conta; não pergunte de novo):
{_notas_txt(estado) or '(nada anotado)'}

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
- PEDIR_LOCALIZACAO / RETOMAR_LOCALIZACAO / COMPLETAR_LOCALIZACAO / PEDIR_NOVA_LOCALIZACAO: peça só o que falta.
- APRESENTAR_PLANO_INICIAL / APRESENTAR_PLANO_ESCOLHIDO_E_CONFIRMAR: use 📦 nome, preço e lista ✅ de benefícios; pergunte se quer fechar.
- APRESENTAR_TROCA_PLANO_E_CONFIRMAR: diga que entendeu a troca, apresente o plano com benefícios e peça confirmação; diga que depois volta aos dados.
- APRESENTAR_PLANOS_ALTERNATIVOS: NÃO liste todos os planos. Sugira o plano em foco com benefícios; diga que há outras opções se quiser comparar.
- CONFIRMAR_PLANO_E_AVANCAR: confirme o plano com naturalidade e peça o nome completo.
- CONFIRMAR_PLANO_E_RESPONDER_PERGUNTA: confirme o plano, responda a dúvida com base na RAG e peça o nome completo.
- CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA: confirme que os dados estão corretos, responda a dúvida com RAG e peça confirmação final do cadastro.
- CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA: confirme o horário escolhido, responda a dúvida e peça confirmação do agendamento.
- CONFIRMAR_TROCA_PLANO_E_RETOMAR_CADASTRO: confirme a troca e retome o pendente do cadastro.
- ANOTAR_E_PEDIR_PROXIMO: confirme o que anotou/corrigiu (nome, email, rua, CEP, etc.) e peça SOMENTE o pendente atual. Se pendente=cpf, não peça endereço de novo — só o CPF.
- ANOTAR_DADO_E_RETOMAR_PLANO: anote o dado e retome a escolha/confirmação do plano. Não peça endereço de novo.
- PEDIR_NOME / PEDIR_CPF / PEDIR_EMAIL / PEDIR_TELEFONE / PEDIR_DATA_NASCIMENTO / PEDIR_CEP / PEDIR_RUA / PEDIR_NUMERO: peça só esse campo.
- PEDIR_CORRECAO_* / PEDIR_CPF_NOVAMENTE: peça de novo de forma leve.
- ENCERRAR_CADASTRO_BASICO: confirme que o cadastro foi concluído e diga que a equipe segue com instalação/contrato.
- INFORMAR_SEM_HORARIOS_E_TRANSFERENCIA / INFORMAR_ERRO_AGENDA_E_TRANSFERENCIA: explique que não há horários no momento e encaminhe para a equipe.
- INFORMAR_PLANO_BLOQUEADO_POS_CADASTRO: cadastro fechado — troca de plano com a equipe.
- INFORMAR_SEM_COBERTURA: sem cobertura + oferecer outro endereço.
- INFORMAR_CPF_JA_CADASTRADO / INFORMAR_ERRO_* / INFORMAR_TRANSFERENCIA: explique e diga que vai encaminhar para a equipe humana. NÃO pergunte "posso ajudar com mais alguma coisa" — o atendimento automático encerra aqui.
- RESPONDER_PERGUNTA_E_RETOMAR: responda a pergunta com base na RAG e no TÓPICO DO CONTEXTO. Follow-ups curtos ("quanto paga?", "tem taxa?", "pra cancelar", "e a multa?") referem-se ao tópico anterior — NÃO troque cancelamento/multa por mensalidade do plano, nem o contrário, sem o cliente pedir. Se citou planos, SEMPRE com preço. Se anotou algum campo nesta mensagem, confirme o dado em 1 frase, responda a dúvida, e retome o pendente. Se cpf_anotado=true, ignore o CPF por enquanto. Não peça dado de cadastro para responder uma dúvida. Se a resposta não estiver na base nem nos dados acima, diga com naturalidade que prefere confirmar esse detalhe com a equipe.
- RESPONDER_DUVIDA_E_RETOMAR: agendamento já feito — responda a dúvida com RAG e/ou dados da conversa (plano, horário, endereço). Termine sempre perguntando se tem mais alguma dúvida.
- CONVERSAR_E_RETOMAR / RETOMAR_ESCOLHA_PLANO: responda ao que o cliente disse e volte ao pendente.
- CONTINUAR_CONVERSA: responda natural e retome o pendente se houver.

Escreva somente a mensagem final.
"""
    try:
        texto = _chat_conferido(_system_prompt(), user, temperature=0.55, decisao=decisao)
    except Exception:  # noqa: BLE001 — modelo fora do ar não pode virar silêncio
        texto = ""
        _marcar(decisao, "llm_fora_do_ar")
    if not texto:
        # Sem texto do modelo (fora do ar ou resposta barrada): retoma o passo, sem inventar nada
        retomada = _retomada_apos_duvida(
            str(pendente or ""), estado,
            plano_nome=str(estado.get("plano_em_negociacao") or estado.get("plano_confirmado") or ""),
        )
        return retomada or _INSTABILIDADE_REENVIO
    if decisao.objetivo_resposta == "RESPONDER_DUVIDA_E_RETOMAR":
        low = texto.casefold()
        if "dúvida" not in low and "duvida" not in low:
            texto = texto.rstrip() + retomar_duvidas()
    return texto
