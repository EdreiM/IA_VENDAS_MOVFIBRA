"""Mensagens fixas — cobertura, planos e RAG vazia."""

from __future__ import annotations

import re
from typing import Any


def informar_sem_cobertura(cidade: str = "", bairro: str = "") -> str:
    from app.geo_coords import parece_coordenada

    if parece_coordenada(cidade) or parece_coordenada(bairro):
        cidade, bairro = "", ""
    loc = ""
    if cidade and bairro:
        loc = f" em *{bairro}, {cidade}*"
    elif cidade:
        loc = f" em *{cidade}*"
    return (
        f"Verifiquei aqui e, infelizmente, ainda não temos cobertura{loc}.\n\n"
        "Se quiser, me informe *outra cidade e bairro* que eu consulto na hora."
    )


def insistencia_sem_cobertura(tentativa: int, max_tentativas: int = 3) -> str:
    restante = max_tentativas - tentativa
    if restante <= 0:
        return informar_sem_cobertura()
    extra = (
        f"\n\nPosso consultar outro endereço — me passe *cidade e bairro* diferentes."
        if restante > 1
        else "\n\nSe não tiver outro endereço, posso encaminhar você para nossa equipe."
    )
    return (
        "Entendo! Consultei de novo e realmente não temos viabilidade técnica nesse endereço "
        "no momento." + extra
    )


def informar_plano_nao_encontrado(referencia: str = "") -> str:
    ref = f" (*{referencia}*)" if referencia else ""
    return (
        f"Não encontrei um plano{ref} disponível para a sua região.\n\n"
        "Pode me dizer o *nome* ou o *valor* do plano que você viu? "
        "Ou, se preferir, te indico o que a galera mais contrata por aqui."
    )


def _fmt_preco(valor: Any) -> str:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return ""
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _preco_exibicao(plano: dict[str, Any]) -> str:
    """Prefere preço com pontualidade quando existir (é o que o cliente costuma ver)."""
    pont = plano.get("valor_pontualidade")
    if pont is not None and str(pont).strip() != "":
        preco = _fmt_preco(pont)
        if preco:
            return f"{preco} (com desconto de pontualidade)"
    return _fmt_preco(plano.get("valor"))


def _linha_plano(plano: dict[str, Any]) -> str:
    """Nome + velocidade + preço — sem lista de apps/benefícios (parece robô)."""
    nome = str(plano.get("nome") or "").strip() or "nosso plano destaque"
    preco = _preco_exibicao(plano)
    vel = str(plano.get("velocidade") or "").strip()

    partes = [f"*{nome}*"]
    if vel:
        partes.append(vel)
    if preco:
        partes.append(f"por {preco}")
    return " — ".join(partes) if len(partes) > 1 else partes[0]


def apresentar_plano_inicial(
    plano: dict[str, Any] | None = None,
    *,
    cidade: str = "",
    bairro: str = "",
) -> str:
    """Oferta após cobertura: plano destaque com benefícios."""
    plano = plano or {}
    if not plano.get("nome"):
        return (
            "Tenho uma ótima opção pra você — o plano que a maioria dos clientes "
            "escolhe por aqui. Posso te apresentar?"
        )
    intro = ""
    if bairro:
        intro = f"Boa, temos cobertura no bairro {bairro}!"
    elif cidade:
        intro = f"Boa, temos cobertura em {cidade}!"
    else:
        intro = "O plano mais escolhido pelos clientes na sua região é este:"
    return formatar_oferta_plano(
        plano,
        intro=intro,
        cta="Esse plano te atende? Quer fechar com ele ou tem outra preferência?",
    )


def confirmar_plano_escolhido(
    plano: dict[str, Any] | None = None,
    *,
    troca: bool = False,
) -> str:
    """Apresenta o plano escolhido com benefícios e pede confirmação."""
    plano = plano or {}
    if not plano.get("nome"):
        return "Esse é o plano que eu te indiquei. Posso confirmar ele pra gente seguir?"

    if troca:
        intro = "Perfeito, anotei a troca — ficou este:"
        cta = "Pode confirmar esse pra gente seguir? Depois a gente volta nos seus dados."
    else:
        intro = "Ficou este:"
        cta = "Pode confirmar esse pra gente seguir?"
    return formatar_oferta_plano(plano, intro=intro, cta=cta)


def informar_preco_plano(plano: dict[str, Any] | None = None) -> str:
    """Resposta fixa para 'quanto é?' — sempre com valor."""
    plano = plano or {}
    if not plano.get("nome"):
        return (
            "Te passo o valor certinho do plano em seguida. "
            "Enquanto isso, quer seguir com a opção que te indiquei?"
        )
    preco = _preco_exibicao(plano)
    if not preco:
        return (
            f"O *{plano.get('nome')}* é a opção que estamos vendo. "
            "Vou confirmar o valor atualizado com você — quer que eu te apresente de novo com o preço?"
        )
    vel = str(plano.get("velocidade") or "").strip()
    extra = f" ({vel})" if vel else ""
    return (
        f"O *{plano.get('nome')}*{extra} fica *{preco}* por mês.\n\n"
        "Quer confirmar esse pra gente seguir?"
    )


def informar_instalacao_e_retomar(
    *,
    pendente: str = "confirmacao_plano",
    plano_nome: str = "",
    pergunta_custo: bool = False,
) -> str:
    """
    Resposta fixa sobre instalação — sem inventar 'hoje' nem fidelidade/taxa.
    Agenda só depois do cadastro.
    """
    if pergunta_custo:
        corpo = (
            "Sim! A *instalação é gratuita* — visita do técnico e configuração "
            "já estão inclusas no plano, sem taxa extra de instalação."
        )
    else:
        corpo = (
            "Sim, a gente instala! A visita do técnico é *agendada depois do cadastro* — "
            "aí você escolhe um horário disponível na agenda da região.\n\n"
            "Sobre *hoje*: não consigo confirmar agora. A disponibilidade depende da equipe "
            "e só aparece na hora de agendar."
        )
    nome = str(plano_nome or "").strip()
    if pendente in {"confirmacao_plano", "escolha_plano", "lista_planos"}:
        ref = f" o *{nome}*" if nome else " esse plano"
        return (
            f"{corpo}\n\n"
            f"Quer confirmar{ref} pra gente seguir com o cadastro e depois marcar a instalação?"
        )
    if pendente in {"escolha_horario", "confirmacao_horario"}:
        return (
            f"{corpo}\n\n"
            "Quando quiser, me diga o horário que prefere na lista."
        )
    if pendente in {
        "nome", "cpf", "email", "telefone", "data_nascimento", "cep", "rua", "numero", "confirmacao_dados",
    }:
        mapa = {
            "nome": "seu *nome completo*",
            "cpf": "seu *CPF*",
            "email": "seu *e-mail*",
            "telefone": "seu *telefone*",
            "data_nascimento": "sua *data de nascimento*",
            "cep": "o *CEP*",
            "rua": "o nome da *rua*",
            "numero": "o *número* do endereço",
            "confirmacao_dados": "a confirmação dos dados",
        }
        rotulo = mapa.get(pendente, "o próximo passo")
        return f"{corpo}\n\nQuando quiser, seguimos com {rotulo}."
    return (
        f"{corpo}\n\n"
        "Se quiser, seguimos no passo em que paramos."
    )


def informar_precos_planos(
    planos: list[dict[str, Any]],
    *,
    plano_atual: dict[str, Any] | None = None,
    contexto: str = "",
) -> str:
    """Lista preços dos planos citados (ex.: após falar de Disney+/alternativas)."""
    if not planos:
        return informar_preco_plano(plano_atual)

    if len(planos) == 1:
        return informar_preco_plano(planos[0])

    linhas = []
    if contexto:
        linhas.append(contexto)
        linhas.append("")
    linhas.append("Os valores ficam assim:")
    for p in planos:
        nome = p.get("nome") or "Plano"
        preco = _preco_exibicao(p) or "consultar"
        vel = str(p.get("velocidade") or "").strip()
        extra = f" ({vel})" if vel else ""
        linhas.append(f"• *{nome}*{extra} — *{preco}*/mês")

    atual_nome = (plano_atual or {}).get("nome") or ""
    linhas.append("")
    if atual_nome:
        linhas.append(
            f"Quer seguir com o *{atual_nome}* ou prefere um desses?"
        )
    else:
        linhas.append("Qual desses você prefere?")
    return "\n".join(linhas)


def informar_planos_por_beneficio(
    beneficio_rotulo: str,
    planos_com: list[dict[str, Any]],
    *,
    plano_atual: dict[str, Any] | None = None,
) -> str:
    """Ex.: 'tem Disney?' → planos com o benefício + preço sempre."""
    atual = plano_atual or {}
    atual_nome = str(atual.get("nome") or "")
    atual_tem = False
    if atual_nome:
        tags = [str(t).casefold() for t in (atual.get("tags") or [])]
        benef = str(atual.get("beneficios") or atual.get("descricao") or "").casefold()
        chave = beneficio_rotulo.casefold()
        atual_tem = chave in tags or chave in benef or chave.replace("+", "") in benef

    if not planos_com:
        return (
            f"No momento não encontrei plano com *{beneficio_rotulo}* listado aqui. "
            "Posso te indicar o plano mais escolhido ou te passar pra equipe — o que prefere?"
        )

    if atual_tem:
        intro = f"Sim — o *{atual_nome}* inclui *{beneficio_rotulo}*."
        return (
            f"{intro} "
            f"Ele fica *{_preco_exibicao(atual) or 'consultar'}*/mês.\n\n"
            "Quer confirmar esse?"
        )

    intro = (
        f"O *{atual_nome}* não inclui *{beneficio_rotulo}*."
        if atual_nome
        else f"Sobre *{beneficio_rotulo}*:"
    )
    linhas = [intro, "", f"Estes planos incluem *{beneficio_rotulo}*:"]
    for p in planos_com:
        nome = p.get("nome") or "Plano"
        preco = _preco_exibicao(p) or "consultar"
        vel = str(p.get("velocidade") or "").strip()
        extra = f" ({vel})" if vel else ""
        linhas.append(f"• *{nome}*{extra} — *{preco}*/mês")
    linhas.append("")
    linhas.append("Quer trocar para um desses, ou seguir com o que te indiquei?")
    return "\n".join(linhas)


def planos_citados_no_texto(
    texto: str, planos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Planos cujo nome aparece na última fala da Eva."""
    t = str(texto or "").casefold()
    if not t:
        return []
    achados: list[dict[str, Any]] = []
    vistos: set[int] = set()
    # Nomes mais longos primeiro (SUPER+ antes de SUPER)
    ordenados = sorted(
        planos,
        key=lambda p: len(str(p.get("nome") or "")),
        reverse=True,
    )
    for p in ordenados:
        nome = str(p.get("nome") or "").strip()
        if not nome:
            continue
        if nome.casefold() in t:
            pid = int(p.get("id") or -1)
            if pid not in vistos:
                vistos.add(pid)
                achados.append(p)
    return achados


def _fmt_preco_bolha(valor: Any) -> str:
    """Preço curto p/ bolha: R$ 129 (sem centavos quando inteiro)."""
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return ""
    if n == int(n):
        return f"R$ {int(n)}"
    return _fmt_preco(n)


def _plano_tem_chip(plano: dict[str, Any]) -> bool:
    """Só planos com linha móvel/chip de verdade (ex.: COMBO TOTAL 12GB/22GB)."""
    tags = {str(t).casefold() for t in (plano.get("tags") or [])}
    if tags.intersection({"chip", "chip_12gb", "chip_22gb"}):
        return True
    blob = " ".join(
        str(plano.get(campo) or "")
        for campo in ("beneficios", "descricao", "nome")
    ).casefold()
    return any(
        p in blob
        for p in (
            "chip incluso",
            "chip com",
            "linha movel",
            "celular incluso",
            "gb de internet movel",
        )
    )


def _titulo_categoria_plano(plano: dict[str, Any]) -> str:
    if _plano_tem_chip(plano):
        return "📶 INTERNET + CHIP"
    return "📶 INTERNET + BENEFÍCIOS"


def _parse_itens_beneficio(raw: str) -> list[str]:
    itens: list[str] = []
    for part in re.split(r"[\n;|]+", raw or ""):
        item = part.strip()
        item = re.sub(r"^[\s✅✔•\-\*]+", "", item).strip()
        if item:
            itens.append(item)
    return itens


def _itens_beneficio_bolha(plano: dict[str, Any]) -> list[str]:
    """Monta checklist ✅ a partir de dispositivos, beneficios e regras do plano."""
    itens: list[str] = []
    vistos: set[str] = set()

    def _add(texto: str) -> None:
        t = (texto or "").strip()
        if not t:
            return
        key = t.casefold()
        if key in vistos:
            return
        # Evita duplicar "até N aparelhos" se já veio em beneficios
        if "aparelho" in key and any("aparelho" in v for v in vistos):
            return
        if ("cartão" in key or "cartao" in key) and any(
            "cartão" in v or "cartao" in v for v in vistos
        ):
            return
        vistos.add(key)
        itens.append(t)

    disp = plano.get("dispositivos_max")
    if disp not in (None, ""):
        try:
            _add(f"Até {int(disp)} aparelhos")
        except (TypeError, ValueError):
            pass

    for item in _parse_itens_beneficio(str(plano.get("beneficios") or "")):
        _add(item)

    vel = str(plano.get("velocidade") or "").strip()
    if vel and "ilimitad" in vel.casefold():
        if not any("ilimitad" in i.casefold() for i in itens):
            _add("Internet ilimitada")

    if not plano.get("requer_cartao"):
        _add("Não exige cartão")

    pont = plano.get("valor_pontualidade")
    if pont is not None and str(pont).strip() != "":
        if not any("pontualidade" in i.casefold() for i in itens):
            _add("Desconto de pontualidade")
        cond = str(plano.get("condicao_valor_pontualidade") or "").strip()
        if cond:
            _add(cond)
        else:
            preco_p = _fmt_preco_bolha(pont)
            if preco_p:
                _add(
                    f"Pagando até o vencimento, a mensalidade fica por {preco_p}/mês"
                )

    return itens


def formatar_bolha_plano(plano: dict[str, Any], *, opcao: int) -> str:
    """Uma bolha WhatsApp no formato comercial (categoria + opção + ✅)."""
    nome = str(plano.get("nome") or "Plano").strip() or "Plano"
    preco = _fmt_preco_bolha(plano.get("valor")) or "consultar"
    linhas = [
        _titulo_categoria_plano(plano),
        "",
        f"📦 Opção {opcao} — {nome} — {preco}/mês",
        "",
    ]
    for item in _itens_beneficio_bolha(plano):
        linhas.append(f"✅ {item}")
    return "\n".join(linhas).rstrip()


def legenda_imagem_plano(plano: dict[str, Any] | None = None) -> str:
    """Legenda da imagem no Chatwoot — benefícios cadastrados no painel."""
    plano = plano or {}
    desc = str(plano.get("descricao") or "").strip()
    if desc:
        return desc
    itens = _itens_beneficio_bolha(plano)
    if itens:
        return "\n".join(f"✅ {item}" for item in itens)
    nome = str(plano.get("nome") or "Plano").strip() or "Plano"
    return f"📦 {nome}"


def formatar_oferta_plano(
    plano: dict[str, Any],
    *,
    intro: str = "",
    cta: str = "Esse plano te atende? Quer fechar com ele ou tem outra preferência?",
    titulo: str | None = None,
) -> str:
    """Oferta de plano único — prioriza descrição cadastrada no painel."""
    plano = plano or {}
    desc = str(plano.get("descricao") or "").strip()
    linhas: list[str] = []
    if intro:
        linhas.append(intro.strip())
        linhas.append("")

    # Texto comercial completo cadastrado no painel
    if desc and ("✅" in desc or "📦" in desc or "📶" in desc or "📱" in desc):
        linhas.append(desc)
        if cta:
            linhas.append("")
            linhas.append(cta)
        return "\n".join(linhas).rstrip()

    nome = str(plano.get("nome") or "Plano").strip() or "Plano"
    preco = _fmt_preco(plano.get("valor")) or _fmt_preco_bolha(plano.get("valor")) or "consultar"
    linhas.append(titulo or f"📦 {nome} – {preco}/mês")
    linhas.append("")
    itens = _itens_beneficio_bolha(plano)
    if itens:
        for item in itens:
            linhas.append(f"✅ {item}")
    else:
        if desc:
            linhas.append(f"✅ {desc}")
        vel = str(plano.get("velocidade") or "").strip()
        if vel:
            linhas.append(f"✅ {vel}")
    if cta:
        linhas.append("")
        linhas.append(cta)
    return "\n".join(linhas).rstrip()


def bolhas_planos_candidatos(
    candidatos: list[dict[str, Any]],
    *,
    intro: str = "Encontrei mais de um plano nesse perfil. Olha o que cada um inclui:",
) -> list[str]:
    """Uma bolha por candidato (ambiguidade / comparação), com benefícios."""
    if not candidatos:
        return ["Não encontrei opções nesse perfil. Quer que eu te indique o mais escolhido?"]
    # Segurança: nunca despejar o catálogo inteiro numa ambiguidade
    lista = list(candidatos)[:3]
    bolhas: list[str] = []
    if intro:
        bolhas.append(intro)
    for i, p in enumerate(lista, start=1):
        nome = str(p.get("nome") or "Plano").strip() or "Plano"
        preco = _fmt_preco(p.get("valor")) or _fmt_preco_bolha(p.get("valor")) or "consultar"
        bolhas.append(
            formatar_oferta_plano(
                p,
                intro="",
                cta="",
                titulo=f"📦 Opção {i} — {nome} – {preco}/mês",
            )
        )
    bolhas.append("Qual você prefere? Pode falar o número ou o nome do plano.")
    return bolhas


def informar_detalhes_plano(plano: dict[str, Any] | None = None) -> str:
    """Resposta a 'o que tem nesse plano?'."""
    plano = plano or {}
    if not plano.get("nome"):
        return (
            "Me diz qual plano você quer que eu detalhe — pelo nome ou pelo valor — "
            "que eu te mostro tudo que inclui."
        )
    return formatar_oferta_plano(
        plano,
        intro=f"Olha o que tem no *{plano.get('nome')}*:",
        cta="Quer seguir com esse ou prefere ver outra opção?",
    )


def planos_com_desconto_especial(planos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Planos com pontualidade ou promo nos primeiros meses (ex.: SUPER+ R$ 69,50)."""
    out: list[dict[str, Any]] = []
    for p in planos:
        tags = {str(t).casefold() for t in (p.get("tags") or [])}
        if p.get("valor_pontualidade") is not None and str(p.get("valor_pontualidade")).strip() != "":
            out.append(p)
            continue
        if tags.intersection({"promo_inicial", "pontualidade"}):
            out.append(p)
            continue
        blob = f"{p.get('beneficios') or ''} {p.get('descricao') or ''}".casefold()
        if any(k in blob for k in ("50%", "primeiros meses", "desconto nos 3", "promocao")):
            out.append(p)
    return out


def intro_lista_planos_desconto() -> str:
    return (
        "Estes planos têm *desconto de pontualidade* ou *promoção especial* "
        "(como 50% nos primeiros meses):"
    )


def bolhas_lista_completa_planos(
    planos: list[dict[str, Any]],
    *,
    plano_destaque: dict[str, Any] | None = None,
) -> list[str]:
    """
    Uma bolha por plano + pergunta final.
    `plano_destaque` reservado p/ ordenação futura; hoje mantém ordem do catálogo.
    """
    _ = plano_destaque
    if not planos:
        return [
            "No momento não consegui carregar a lista de planos. "
            "Posso te indicar o mais escolhido?"
        ]

    bolhas = [
        formatar_bolha_plano(p, opcao=i) for i, p in enumerate(planos, start=1)
    ]
    bolhas.append("Qual desses você prefere? Pode falar o nome ou o valor.")
    return bolhas


def apresentar_lista_completa_planos(
    planos: list[dict[str, Any]],
    *,
    plano_destaque: dict[str, Any] | None = None,
) -> str:
    """Catálogo completo — texto único (fallback); preferir bolhas_lista_completa_planos."""
    return "\n\n".join(
        bolhas_lista_completa_planos(planos, plano_destaque=plano_destaque)
    )


def apresentar_planos_como_sugestao(
    plano_sugerido: dict[str, Any] | None = None,
    *,
    total_planos: int = 0,
) -> str:
    """
    Quando o cliente pede 'outros planos': não despeja lista.
    Sugere o mais popular e oferece aprofundar se quiser.
    """
    plano = plano_sugerido or {}
    if not plano.get("nome"):
        return (
            "Sim! O que mais fecha com a maioria dos clientes é o nosso plano destaque. "
            "Quer que eu te apresente ele primeiro, ou prefere me dizer se busca "
            "algo mais em conta ou com mais velocidade?"
        )

    intro = "Claro! O que mais tem sido escolhido pelos clientes é este:"
    if total_planos > 1:
        intro += " Se quiser, te mostro todas as opções disponíveis."
    return formatar_oferta_plano(
        plano,
        intro=intro,
        cta="Quer esse, ou prefere algo mais em conta / com mais velocidade?",
    )


def esclarecer_plano_ambiguo(candidatos: list[dict[str, Any]]) -> str:
    """Fallback texto único; preferir bolhas_planos_candidatos."""
    return "\n\n".join(bolhas_planos_candidatos(candidatos))


def responder_sem_base_rag(pendente: str = "") -> str:
    retomada = ""
    mapa = {
        "confirmacao_plano": "a confirmação do plano",
        "escolha_plano": "a escolha do plano",
        "lista_planos": "a escolha do plano",
        "escolha_horario": "o horário de instalação",
        "localizacao": "sua cidade e bairro",
        "duvidas": "o encerramento do atendimento",
    }
    if pendente in mapa:
        retomada = f"\n\nQuando quiser, seguimos com {mapa[pendente]}."
    if pendente == "duvidas":
        retomada = "\n\nMais alguma dúvida antes de encerrar?"
    return (
        "Boa pergunta! Não tenho essa informação confirmada aqui agora — "
        "prefiro não te passar algo impreciso."
        f"{retomada}\n\n"
        "Se precisar de detalhe técnico ou comercial específico, posso encaminhar para a equipe."
    )


def transferir_apos_insistencia(motivo: str = "sem_cobertura") -> str:
    if motivo == "plano":
        return (
            "Para te ajudar melhor com a escolha do plano, vou encaminhar "
            "seu atendimento para um consultor da nossa equipe. "
            "Em instantes alguém continua com você!"
        )
    return (
        "Vou encaminhar seu atendimento para a equipe verificar "
        "possibilidades no seu endereço com mais detalhes. "
        "Em instantes alguém continua com você!"
    )
