"""Contrato único da Eva — eventos, fases e campos."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Evento(str, Enum):
    SAUDACAO = "SAUDACAO"
    CONVERSA_SOCIAL = "CONVERSA_SOCIAL"
    PEDIDO_CONTRATACAO = "PEDIDO_CONTRATACAO"
    LOCALIZACAO_INFORMADA = "LOCALIZACAO_INFORMADA"
    PEDIU_TROCAR_LOCALIZACAO = "PEDIU_TROCAR_LOCALIZACAO"
    PLANO_INFORMADO = "PLANO_INFORMADO"
    PEDIU_TROCAR_PLANO = "PEDIU_TROCAR_PLANO"
    DADO_INFORMADO = "DADO_INFORMADO"
    CORRECAO_DADO = "CORRECAO_DADO"
    CONFIRMACAO = "CONFIRMACAO"
    NEGACAO = "NEGACAO"
    PERGUNTA = "PERGUNTA"
    PEDIU_HUMANO = "PEDIU_HUMANO"
    OUTRO = "OUTRO"


class Fase(str, Enum):
    INICIO = "inicio"
    VIABILIDADE = "viabilidade"
    SEM_COBERTURA = "sem_cobertura"
    VENDAS = "vendas"
    CADASTRO = "cadastro"
    TERMOS = "termos"
    AGENDAMENTO = "agendamento"
    POS_VENDA = "pos_venda"
    TRANSFERIDO = "transferido"
    FINALIZADO = "finalizado"


CAMPOS_DADOS = [
    "cidade",
    "bairro",
    "plano",
    "nome",
    "cpf",
    "email",
    "telefone",
    "data_nascimento",
    "rg",
    "cep",
    "rua",
    "numero",
    "complemento",
    "metodo_pagamento",
    "data_vencimento_pref",
    "turno_escolhido",
]

CAMPOS_CADASTRAIS = [
    "nome",
    "cpf",
    "email",
    "telefone",
    "data_nascimento",
    "rg",
    "cep",
    "rua",
    "numero",
    "complemento",
    "metodo_pagamento",
    "data_vencimento_pref",
    "turno_escolhido",
]


class DadosExtraidos(BaseModel):
    cidade: str = ""
    bairro: str = ""
    plano: str = ""
    nome: str = ""
    cpf: str = ""
    email: str = ""
    telefone: str = ""
    data_nascimento: str = ""
    rg: str = ""
    cep: str = ""
    rua: str = ""
    numero: str = ""
    complemento: str = ""
    metodo_pagamento: str = ""
    data_vencimento_pref: str = ""
    turno_escolhido: str = ""


class Interpretacao(BaseModel):
    eventos: list[str] = Field(default_factory=list)
    dados: DadosExtraidos = Field(default_factory=DadosExtraidos)
    campos_corrigidos: list[str] = Field(default_factory=list)
    pergunta: str = ""
    confianca: float = 0.0


class Decisao(BaseModel):
    acao: str
    objetivo_resposta: str | None = None
    fase: str
    aguardando: str | None = None
    atualizar_dados: dict[str, Any] = Field(default_factory=dict)
    pergunta: str = ""
    motivo: str = ""
    contexto_resposta: dict[str, Any] = Field(default_factory=dict)
    prioridade: str = "NORMAL"


class TurnoResultado(BaseModel):
    id_cliente: str
    mensagem_cliente: str
    interpretacao: Interpretacao
    decisao: Decisao
    resposta: str
    output: str = ""  # alias p/ n8n (Envia_msg_chatwoot usa $json.output)
    outputs: list[str] = Field(default_factory=list)  # bolhas separadas (WhatsApp)
    imagens: list[dict[str, Any]] = Field(default_factory=list)  # URLs do painel (chat/teste)
    conversation_id: str | None = None
    contact_id: str | None = None
    chatwoot_handoff: dict[str, Any] | None = None
    estado: dict[str, Any] = Field(default_factory=dict)
