"""Interpreter semântico — LLM só extrai fatos, não decide fluxo."""

from __future__ import annotations

import json
import re
from typing import Any

from app.llm import chat

SYSTEM = """Você é o interpretador semântico das mensagens recebidas pela Eva, atendente comercial da MOV FIBRA.

Sua função é compreender o que o cliente comunicou e transformar isso em fatos estruturados.

Você NÃO controla o atendimento.
Você NÃO escolhe fase, ferramenta ou ação.
Você NÃO responde ao cliente.
Você NÃO inventa dados.

Uma mensagem pode gerar vários eventos simultaneamente.
Extraia SOMENTE valores explicitamente informados na mensagem atual.
Nunca copie do estado atual para os dados extraídos — se o cliente não repetiu na mensagem, deixe o campo vazio.
Referências genéricas como "esse", "pode ser", "sim" NÃO preenchem dados.plano.
Se aguardando for um campo cadastral (nome, cpf, email, etc.), preencha SOMENTE esse campo e os que o cliente citar explicitamente na mensagem — não reenvie dados já salvos no estado.
Resposta curta ao que foi pedido (ex.: "João Silva", "68020000") → DADO_INFORMADO, não PERGUNTA.
"João Silva?" com interrogação no final ainda é o dado pedido, não PERGUNTA.

Correções são importantes:
- "o nome é João Silva" / "errei, o email é x@y.com" / "na verdade meu telefone é..." → CORRECAO_DADO + campos_corrigidos
- Se corrigir um dado, preencha o valor novo em dados.* e liste o campo em campos_corrigidos

Retorne SOMENTE JSON válido, sem markdown.
"""


def _estado_bloco(estado: dict[str, Any]) -> str:
    plano = (
        estado.get("plano_confirmado")
        or estado.get("plano_em_negociacao")
        or estado.get("plano_apresentado")
        or ""
    )
    return f"""ESTADO ATUAL DO ATENDIMENTO:
fase: {estado.get('fase') or ''}
aguardando: {estado.get('aguardando') or ''}
cidade atual: {estado.get('cidade') or ''}
bairro atual: {estado.get('bairro') or ''}
plano atual: {plano}
nome atual: {estado.get('nome') or ''}
cpf atual: {estado.get('cpf') or ''}
email atual: {estado.get('email') or ''}
telefone atual: {estado.get('telefone') or ''}
data_nascimento atual: {estado.get('data_nascimento') or ''}
cep atual: {estado.get('cep') or ''}
rua atual: {estado.get('rua') or ''}
numero atual: {estado.get('numero') or ''}
cadastro_completo: {bool(estado.get('cadastro_completo'))}
tópico recente: {estado.get('ultimo_topico') or ''}
ÚLTIMA MENSAGEM DA EVA: {estado.get('ultima_mensagem_sofia') or ''}
"""


USER_TEMPLATE = """{estado}

MENSAGEM ATUAL DO CLIENTE:
{mensagem}

EVENTOS POSSÍVEIS:
SAUDACAO, CONVERSA_SOCIAL, PEDIDO_CONTRATACAO, LOCALIZACAO_INFORMADA,
PEDIU_TROCAR_LOCALIZACAO, PLANO_INFORMADO, PEDIU_TROCAR_PLANO,
DADO_INFORMADO, CORRECAO_DADO, CONFIRMACAO, NEGACAO, PERGUNTA, PEDIU_HUMANO, OUTRO

Regras rápidas:
- "quero o Essencial" / "quero o de 189" → PLANO_INFORMADO + dados.plano
- "pode ser esse" / "sim" / "quero esse" (sem nome de plano) → CONFIRMACAO, dados.plano=""
- "tem outro?" / "quero outro plano" / "muda o plano" → PEDIU_TROCAR_PLANO
- "esse não" → NEGACAO
- cidade/bairro → LOCALIZACAO_INFORMADA
- CPF/nome/email/telefone/data_nascimento/cep/rua/numero → DADO_INFORMADO
- Na fase agendamento, horário escolhido → DADO_INFORMADO + dados.turno_escolhido (ex: "9h às 10h")
- "não posso nesse horário" / "tem outro?" / "outro dia" → NEGACAO (não é PERGUNTA)
- Ordem ideal do cadastro: nome → cpf → email → telefone → data_nascimento → cep → rua → numero → confirmação
- rua, número, CEP, complemento, data de nascimento → DADO_INFORMADO (NÃO é LOCALIZACAO — cidade/bairro de cobertura já foram definidos)
- Na fase cadastro, NÃO use LOCALIZACAO_INFORMADA só porque o cliente deu endereço de instalação (rua, CEP, etc.)
- "e se eu quiser mudar de endereço?" / "depois de contratar posso mudar?" → PERGUNTA (informação), NÃO PEDIU_TROCAR_LOCALIZACAO
- "e se não tiver cobertura?" / "funciona no meu prédio?" → PERGUNTA, NÃO PEDIU_TROCAR_LOCALIZACAO (sem cidade/bairro novos)
- PEDIU_TROCAR_LOCALIZACAO só quando o cliente quer MUDAR AGORA a cidade/bairro de cobertura e informar novos dados
- Durante cadastro, agendamento e pós-venda: rua/CEP/número/data_nascimento → DADO_INFORMADO, nunca LOCALIZACAO
- "sim]" / "sim!" / "confirmo." → CONFIRMACAO (ignore pontuação extra)
- Mensagem com dado + pergunta (ex.: telefone + "quanto tempo demora instalação?") → DADO_INFORMADO + PERGUNTA
- Correção ("errei", "na verdade", "o certo é", "o nome é X" quando já havia nome) → CORRECAO_DADO + campos_corrigidos
- Durante cadastro, "quero o Infinity" ainda é PLANO_INFORMADO (troca de plano)
- NUNCA preencha dados.nome quando aguardando for rua/numero/cep, salvo correção explícita ("o nome é...")
- CPF, telefone ou CEP na mensagem → preencha só o campo correspondente; não invente rua/número a partir do nome já salvo

Formato:
{{
  "eventos": [],
  "dados": {{
    "cidade": "", "bairro": "", "plano": "", "nome": "", "cpf": "",
    "email": "", "telefone": "", "data_nascimento": "", "rg": "",
    "cep": "", "rua": "", "numero": "", "complemento": "",
    "metodo_pagamento": "", "data_vencimento_pref": "", "turno_escolhido": ""
  }},
  "campos_corrigidos": [],
  "pergunta": "",
  "confianca": 0
}}
"""


def _strip_markdown(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _json_valido(raw: str) -> bool:
    try:
        data = json.loads(_strip_markdown(raw))
        return isinstance(data, dict) and isinstance(data.get("eventos"), list)
    except json.JSONDecodeError:
        return False


def interpretar(mensagem: str, estado: dict[str, Any]) -> str:
    user = USER_TEMPLATE.format(estado=_estado_bloco(estado), mensagem=mensagem)
    bruto = chat(SYSTEM, user, temperature=0.0)
    if _json_valido(bruto):
        return bruto
    retry = chat(
        SYSTEM,
        user + "\n\nIMPORTANTE: sua resposta anterior não era JSON válido. "
        "Retorne SOMENTE o objeto JSON, sem markdown nem texto extra.",
        temperature=0.0,
    )
    return retry if _json_valido(retry) else bruto
