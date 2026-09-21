"""Resolver Global — compara interpretação com o estado real do banco."""

from __future__ import annotations

import re
from typing import Any

from app.models import CAMPOS_CADASTRAIS, CAMPOS_DADOS, Evento, Interpretacao


def texto(valor: Any) -> str:
    if valor is None:
        return ""
    return str(valor).strip()


def somente_numeros(valor: str) -> str:
    return re.sub(r"\D", "", texto(valor))


def normalizar_campo(campo: str, valor: str) -> str:
    bruto = texto(valor)
    if not bruto:
        return ""
    if campo in {"cpf", "telefone", "cep"}:
        return somente_numeros(bruto)
    if campo == "email":
        return bruto.lower().replace(" ", "")
    t = bruto.casefold()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def valor_para_salvar(campo: str, valor: str) -> str:
    bruto = texto(valor)
    if not bruto:
        return ""
    if campo in {"cpf", "telefone", "cep"}:
        return somente_numeros(bruto)
    if campo == "email":
        return bruto.lower().replace(" ", "")
    return bruto


def valor_atual(estado: dict[str, Any], campo: str) -> str:
    if campo == "plano":
        return texto(
            estado.get("plano_confirmado")
            or estado.get("plano_em_negociacao")
            or estado.get("plano_apresentado")
        )
    return texto(estado.get(campo))


def resolver(estado: dict[str, Any], interpretacao: Interpretacao) -> dict[str, Any]:
    eventos = list(interpretacao.eventos)
    dados_recv = interpretacao.dados.model_dump()

    def tem(ev: str) -> bool:
        return ev in eventos

    campos_informados: list[str] = []
    campos_novos: list[str] = []
    campos_alterados: list[str] = []
    campos_repetidos: list[str] = []
    para_salvar: dict[str, str] = {}

    for campo in CAMPOS_DADOS:
        recebido = texto(dados_recv.get(campo))
        if not recebido:
            continue
        campos_informados.append(campo)
        atual = valor_atual(estado, campo)
        atual_n = normalizar_campo(campo, atual)
        recv_n = normalizar_campo(campo, recebido)
        para_salvar[campo] = valor_para_salvar(campo, recebido)
        if not atual_n:
            campos_novos.append(campo)
        elif atual_n == recv_n:
            campos_repetidos.append(campo)
        else:
            campos_alterados.append(campo)

    correcao_declarada = [
        c.lower()
        for c in interpretacao.campos_corrigidos
        if c.lower() in CAMPOS_DADOS
    ]
    correcao_efetiva = [c for c in correcao_declarada if c in campos_alterados]

    cidade_atual = texto(estado.get("cidade"))
    bairro_atual = texto(estado.get("bairro"))
    tinha_alguma = bool(cidade_atual or bairro_atual)
    tinha_completa = bool(cidade_atual and bairro_atual)

    informou_cidade = "cidade" in campos_informados
    informou_bairro = "bairro" in campos_informados
    localizacao_informada = informou_cidade or informou_bairro

    cidade_alterada = "cidade" in campos_alterados
    bairro_alterado = "bairro" in campos_alterados
    cidade_nova = "cidade" in campos_novos
    bairro_novo = "bairro" in campos_novos

    cidade_efetiva = cidade_atual
    bairro_efetivo = bairro_atual

    if informou_cidade:
        cidade_efetiva = para_salvar.get("cidade", "")
        if informou_bairro:
            bairro_efetivo = para_salvar.get("bairro", "")
        elif cidade_alterada:
            bairro_efetivo = ""
    elif informou_bairro:
        bairro_efetivo = para_salvar.get("bairro", "")

    limpar_cidade = False
    # "Diamantino é o bairro" depois de ter gravado Diamantino como cidade
    if informou_bairro and bairro_efetivo:
        if cidade_efetiva and normalizar_campo("cidade", cidade_efetiva) == normalizar_campo(
            "bairro", bairro_efetivo
        ):
            cidade_efetiva = ""
            limpar_cidade = True
        elif cidade_atual and normalizar_campo("cidade", cidade_atual) == normalizar_campo(
            "bairro", bairro_efetivo
        ):
            cidade_efetiva = ""
            limpar_cidade = True

    localizacao_nova = localizacao_informada and not tinha_alguma
    localizacao_complementada = (
        localizacao_informada
        and tinha_alguma
        and not tinha_completa
        and (cidade_nova or bairro_novo)
        and not cidade_alterada
        and not bairro_alterado
    )
    localizacao_alterada = cidade_alterada or bairro_alterado or limpar_cidade
    localizacao_completa = bool(cidade_efetiva and bairro_efetivo)

    pediu_troca_loc = tem(Evento.PEDIU_TROCAR_LOCALIZACAO.value)
    fase_atual = texto(estado.get("fase"))
    # Fases avançadas: PERGUNTA sem endereço novo ≠ troca de cobertura
    if (
        pediu_troca_loc
        and not localizacao_informada
        and fase_atual in {"cadastro", "agendamento", "pos_venda", "vendas"}
        and tem(Evento.PERGUNTA.value)
    ):
        pediu_troca_loc = False
    solicitou_troca_sem_dados = pediu_troca_loc and tinha_alguma and not localizacao_informada
    pediu_troca_loc_efetiva = pediu_troca_loc and tinha_alguma and (
        solicitou_troca_sem_dados or localizacao_alterada
    )

    # Endereço de instalação (rua/CEP) no cadastro ≠ trocar cidade/bairro de cobertura
    campos_endereco_inst = {"rua", "numero", "cep", "complemento", "data_nascimento", "rg"}
    tem_endereco_inst = any(c in campos_informados for c in campos_endereco_inst)
    endereco_inst_sem_cobertura = (
        fase_atual == "cadastro"
        and estado.get("plano_confirmado")
        and tem_endereco_inst
        and not localizacao_alterada
    )
    if endereco_inst_sem_cobertura:
        localizacao_informada = False

    cobertura_conhecida = isinstance(estado.get("tem_cobertura"), bool)
    precisa_revalidar = localizacao_informada and localizacao_completa and (
        not cobertura_conhecida or localizacao_nova or localizacao_complementada or localizacao_alterada
    )
    precisa_coletar = solicitou_troca_sem_dados or (localizacao_informada and not localizacao_completa)
    if endereco_inst_sem_cobertura:
        precisa_revalidar = False
        precisa_coletar = False
    limpar_bairro = cidade_alterada and not informou_bairro
    if limpar_cidade:
        limpar_bairro = False

    informou_plano = tem(Evento.PLANO_INFORMADO.value) and "plano" in campos_informados
    plano_alterado = "plano" in campos_alterados
    plano_repetido = "plano" in campos_repetidos
    pediu_troca_plano = tem(Evento.PEDIU_TROCAR_PLANO.value)

    informou_cpf = "cpf" in campos_informados
    cpf_novo = "cpf" in campos_novos
    cpf_alterado = "cpf" in campos_alterados

    # Eco do modelo (campo já salvo e igual) não conta como dado novo
    cadastro_informados = [
        c
        for c in campos_informados
        if c in CAMPOS_CADASTRAIS and c not in campos_repetidos
    ]

    invalidar = {
        "cobertura": localizacao_alterada,
        "plano": localizacao_alterada or plano_alterado,
        "validacao_cpf": cpf_alterado,
        "documentos_cpf": cpf_alterado,
        "termos_comerciais": localizacao_alterada or plano_alterado,
        "agendamento": localizacao_alterada or plano_alterado,
    }

    return {
        "eventos": eventos,
        "flags": {
            "pediu_humano": tem(Evento.PEDIU_HUMANO.value),
            "tem_pergunta": tem(Evento.PERGUNTA.value),
            "conversa_social": tem(Evento.CONVERSA_SOCIAL.value),
            "saudacao": tem(Evento.SAUDACAO.value),
            "pedido_contratacao": tem(Evento.PEDIDO_CONTRATACAO.value),
            "confirmacao": tem(Evento.CONFIRMACAO.value),
            "negacao": tem(Evento.NEGACAO.value),
            "localizacao_informada": localizacao_informada,
            "plano_informado": informou_plano,
            "pediu_trocar_plano_declarado": pediu_troca_plano,
            "pediu_trocar_localizacao_efetivo": pediu_troca_loc_efetiva,
        },
        "dados": {"para_salvar": para_salvar, "campos_informados": campos_informados},
        "localizacao": {
            "informada": localizacao_informada,
            "alterada": localizacao_alterada,
            "completa": localizacao_completa,
            "cidade": cidade_efetiva,
            "bairro": bairro_efetivo,
            "solicitou_troca_sem_novos_dados": solicitou_troca_sem_dados,
            "precisa_coletar_localizacao": precisa_coletar,
            "precisa_revalidar_cobertura": precisa_revalidar,
            "limpar_bairro_anterior": limpar_bairro,
            "limpar_cidade_anterior": limpar_cidade,
            "pediu_troca_efetiva": pediu_troca_loc_efetiva,
            "repetida": localizacao_informada
            and not localizacao_nova
            and not localizacao_complementada
            and not localizacao_alterada,
        },
        "plano": {
            "informado": informou_plano,
            "valor": texto(para_salvar.get("plano")),
            "alterado": plano_alterado,
            "repetido": plano_repetido,
            "pediu_troca_declarada": pediu_troca_plano,
        },
        "cpf": {
            "informado": informou_cpf,
            "valor": texto(para_salvar.get("cpf")),
            "novo": cpf_novo,
            "alterado": cpf_alterado,
            "repetido": "cpf" in campos_repetidos,
        },
        "cadastro": {"campos_informados": cadastro_informados},
        "invalidar": invalidar,
        "pergunta": interpretacao.pergunta,
        "correcao_efetiva": correcao_efetiva,
        "campos_alterados": campos_alterados,
        "campos_novos": campos_novos,
    }
