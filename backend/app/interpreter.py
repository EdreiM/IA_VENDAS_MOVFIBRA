"""Interpreter semântico — LLM só extrai fatos, não decide fluxo."""

from __future__ import annotations

import json
import re
from typing import Any

from openai import BadRequestError

from app.conversa import SITUACOES_LLM
from app.llm import chat, modelo_ativo
from app.models import CAMPOS_DADOS, Evento

SYSTEM = """Você é o interpretador semântico das mensagens recebidas pela Eva, atendente comercial da MOV FIBRA.

Sua função é compreender o que o cliente comunicou e transformar isso em fatos estruturados.

Você NÃO controla o atendimento.
Você NÃO escolhe fase, ferramenta ou ação.
Você NÃO responde ao cliente.
Você NÃO inventa dados.

Uma mensagem pode gerar vários eventos simultaneamente.
Extraia SOMENTE valores explicitamente informados na mensagem atual.
Nunca copie do estado atual para os dados extraídos — se o cliente não repetiu na mensagem, deixe o campo vazio.

O HISTÓRICO RECENTE serve só para você entender a mensagem atual: a que pergunta da Eva o cliente está respondendo e a que plano ou assunto ele se refere.
Nunca extraia para dados.* um valor que aparece apenas no histórico.
Única exceção — dados.plano: se a Eva listou vários planos e a mensagem atual aponta um deles pela posição ("o primeiro", "o segundo", "o último"), preencha dados.plano com o nome exato desse plano como está no histórico e marque PLANO_INFORMADO.
Se a mensagem atual é uma pergunta incompleta que depende do histórico ("e a multa?", "quanto fica?", "e nesse?"), escreva em "pergunta" a pergunta completa, com o assunto explícito.
Referências genéricas como "esse", "pode ser", "sim" NÃO preenchem dados.plano.
Se aguardando for um campo cadastral (nome, cpf, email, etc.), preencha SOMENTE esse campo e os que o cliente citar explicitamente na mensagem — não reenvie dados já salvos no estado.
Resposta curta ao que foi pedido (ex.: "João Silva", "68020000") → DADO_INFORMADO, não PERGUNTA.
"João Silva?" com interrogação no final ainda é o dado pedido, não PERGUNTA.

Correções são importantes:
- "o nome é João Silva" / "errei, o email é x@y.com" / "na verdade meu telefone é..." → CORRECAO_DADO + campos_corrigidos
- Se corrigir um dado, preencha o valor novo em dados.* e liste o campo em campos_corrigidos

Retorne SOMENTE JSON válido, sem markdown.
"""


# Campos do estado que interpretador e parser consultam — gravados por turno para avaliação
CAMPOS_ESTADO_AVALIACAO = (
    "fase", "aguardando", "cidade", "bairro", "tem_cobertura",
    "plano_apresentado", "plano_apresentado_id",
    "plano_em_negociacao", "plano_em_negociacao_id",
    "plano_confirmado", "plano_confirmado_id",
    "nome", "cpf", "email", "telefone", "data_nascimento",
    "cep", "rua", "numero", "cadastro_completo", "termos_enviados", "ultimo_topico",
    "horarios_manha", "horarios_tarde", "data_agendamento",
)


def snapshot_estado(estado: dict[str, Any]) -> dict[str, Any]:
    return {
        c: estado.get(c)
        for c in CAMPOS_ESTADO_AVALIACAO
        if estado.get(c) not in (None, "")
    }


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
o que o cliente já contou (notas): {'; '.join(ln for ln in str(estado.get('notas_conversa') or '').split(chr(10)) if ln.strip()) or '(nada)'}
ÚLTIMA MENSAGEM DA EVA: {estado.get('ultima_mensagem_sofia') or ''}
"""


LIMITE_HISTORICO = 12
_MAX_CHARS_CLIENTE = 500
# Mensagem da Eva pode trazer o catálogo inteiro — precisa caber para "o segundo" / "o último"
_MAX_CHARS_EVA = 4000
_MAX_CHARS_HISTORICO = 7000


def _historico_bloco(historico: list[dict[str, str]] | None, mensagem: str) -> str:
    itens = list(historico or [])
    # O pipeline grava a mensagem atual antes de ler o histórico — não repetir
    if itens:
        ultimo = itens[-1]
        if (
            str(ultimo.get("remetente") or "") == "cliente"
            and str(ultimo.get("mensagem") or "").strip() == (mensagem or "").strip()
        ):
            itens = itens[:-1]
    linhas: list[str] = []
    usados = 0
    # Da mais recente para a mais antiga: se estourar o limite, perde o que é mais velho
    for h in reversed(itens[-LIMITE_HISTORICO:]):
        txt = str(h.get("mensagem") or "").strip()
        if not txt:
            continue
        if str(h.get("remetente") or "") == "cliente":
            linha = f"Cliente: {txt[:_MAX_CHARS_CLIENTE]}"
        else:
            linha = f"Eva: {txt[:_MAX_CHARS_EVA]}"
        if linhas and usados + len(linha) > _MAX_CHARS_HISTORICO:
            break
        linhas.append(linha)
        usados += len(linha)
    if not linhas:
        return "HISTÓRICO RECENTE: (sem mensagens anteriores)"
    linhas.reverse()
    return "HISTÓRICO RECENTE (da mais antiga para a mais recente):\n" + "\n".join(linhas)


USER_TEMPLATE = """{estado}
{historico}

MENSAGEM ATUAL DO CLIENTE:
{mensagem}

EVENTOS POSSÍVEIS:
SAUDACAO, CONVERSA_SOCIAL, PEDIDO_CONTRATACAO, LOCALIZACAO_INFORMADA,
PEDIU_TROCAR_LOCALIZACAO, PLANO_INFORMADO, PEDIU_TROCAR_PLANO,
DADO_INFORMADO, CORRECAO_DADO, CONFIRMACAO, NEGACAO, PERGUNTA, PEDIU_HUMANO, OUTRO

Regras rápidas:
- "quero o Essencial" / "quero o de 189" → PLANO_INFORMADO + dados.plano
- "pode ser esse" / "sim" / "quero esse" (sem nome de plano) → CONFIRMACAO, dados.plano=""
- Depois de uma lista de planos da Eva: "o segundo" / "pode ser o último" → PLANO_INFORMADO + dados.plano só com o nome do plano nessa posição da lista (ex.: "MOV SUPER+")
- "pode ser o infinity" / "sim, o one+" / "vou de flex" (nomeia um plano) → PLANO_INFORMADO + dados.plano, NÃO CONFIRMACAO
- Objeção ou adiamento ("tá caro", "vou pensar", "deixa eu ver", "depois eu vejo", "sim mas tá caro") → OUTRO; nunca CONFIRMACAO (e preencha situacao)
- Mensagem "[audio]", "[image]", "[file]" ou "[video]": o cliente mandou mídia sem texto → OUTRO, dados vazios
- "não entendi" / "como assim?" / "não sei" → OUTRO ou PERGUNTA; nunca NEGACAO
- "tem outro?" / "quero outro plano" / "muda o plano" → PEDIU_TROCAR_PLANO
- "esse não" → NEGACAO
- cidade/bairro → LOCALIZACAO_INFORMADA
- CPF/nome/email/telefone/data_nascimento/cep/rua/numero → DADO_INFORMADO
- Na fase agendamento, horário escolhido → DADO_INFORMADO + dados.turno_escolhido (ex: "9h às 10h")
- "não posso nesse horário" / "tem outro?" / "outro dia" → NEGACAO (não é PERGUNTA)
- Ordem ideal do cadastro: nome → cpf → email → telefone → data_nascimento → cep → rua → numero → confirmação
- rua, número, CEP, complemento, data de nascimento → DADO_INFORMADO (NÃO é LOCALIZACAO — cidade/bairro de cobertura já foram definidos)
- Endereço escrito de uma vez segue a ordem rua → número → complemento: o que vem ANTES do número é a rua, o que vem DEPOIS é o complemento. "sérgio henn, 891 residencial plácido" → rua="sérgio henn", numero="891", complemento="residencial plácido" (o nome do residencial/condomínio NUNCA é a rua). "rua 7" → rua="rua 7", numero="" (o 7 é o nome da rua). "sem número" / "s/n" → numero="S/N"
- dados.numero é SÓ o número da casa ("729", "10A", "S/N"). Bloco, apartamento, casa dos fundos, nome de condomínio, lote/quadra e ponto de referência vão em dados.complemento. "nº 729, Bloco 04, Apto 104 (cond. Boulevard)" → numero="729", complemento="Bloco 04, Apto 104 (cond. Boulevard)"
- Endereço mandado em lista com rótulos ("Cidade: …", "Bairro: …", "Rua: …", "Número: …", "CEP: …", "Ponto de referência: …") → preencha TODOS os campos correspondentes; cidade sem a sigla do estado ("Santarém/PA" → "Santarém")
- Na fase cadastro, NÃO use LOCALIZACAO_INFORMADA só porque o cliente deu endereço de instalação (rua, CEP, etc.)
- "e se eu quiser mudar de endereço?" / "depois de contratar posso mudar?" → PERGUNTA (informação), NÃO PEDIU_TROCAR_LOCALIZACAO
- "e se não tiver cobertura?" / "funciona no meu prédio?" → PERGUNTA, NÃO PEDIU_TROCAR_LOCALIZACAO (sem cidade/bairro novos)
- PEDIU_TROCAR_LOCALIZACAO só quando o cliente quer MUDAR AGORA a cidade/bairro de cobertura e informar novos dados
- Durante cadastro, agendamento e pós-venda: rua/CEP/número/data_nascimento → DADO_INFORMADO, nunca LOCALIZACAO
- "sim]" / "sim!" / "confirmo." → CONFIRMACAO (ignore pontuação extra)
- Mensagem com dado + pergunta (ex.: telefone + "quanto tempo demora instalação?") → DADO_INFORMADO + PERGUNTA
- Vários dados na mesma mensagem ("Maria Souza, cpf ..., maria@gmail.com, 9399...") → preencha TODOS os campos citados
- Data de nascimento em qualquer formato ("16 de agosto de 2000", "16-08-2000") → dados.data_nascimento em dd/mm/aaaa
- Número com 11 dígitos: é telefone se a Eva pediu telefone; é CPF se a Eva pediu CPF
- Cidade/bairro junto com um pedido ("quero internet em Santarém no Diamantino") → PEDIDO_CONTRATACAO + LOCALIZACAO_INFORMADA, preenchendo cidade e bairro
- "bairro Aparecida, Santarém" → respeite o rótulo: bairro=Aparecida, cidade=Santarém
- Um nome de lugar sozinho ("no Diamantino", "Maracanã"): preencha o campo que o cliente indicou; na dúvida, bairro — nunca chute cidade
- aguardando=confirmar_local (a Eva perguntou se um lugar é o bairro): "sim" / "é o bairro" → CONFIRMACAO; "não" / "é a cidade" → NEGACAO; se o cliente disser a cidade ("sim, Santarém") → LOCALIZACAO_INFORMADA + dados.cidade
- Conversa sem dado quando a Eva pediu um dado ("pera aí", "já mando", "tá bom", "não tenho agora") → CONVERSA_SOCIAL ou OUTRO, dados vazios
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
  "situacao": "",
  "nota": "",
  "confianca": 0.95
}}

situacao — como o cliente reagiu ao que a Eva pediu por último. Deixe "" quando ele respondeu o que foi pedido, fez uma pergunta comum ou seguiu o atendimento.
- ESPERA: pediu um tempo para pegar ou procurar ("pera aí", "já mando", "vou procurar")
- ADIAMENTO: quer pensar ou deixar para depois ("vou pensar", "depois eu vejo", "vou falar com minha esposa")
- IMPEDIMENTO: não tem, não sabe ou não conseguiu o que foi pedido ("não tenho e-mail", "não sei meu CEP", "não consegui abrir o PDF", "nenhum desses horários dá pra mim")
- OBJECAO_PRECO: achou caro ou comparou o preço com outra empresa
- OBJECAO: resistência que não é preço — não quer fidelidade/contrato, já tem internet de outra empresa, desconfia da qualidade, acha que demora, "preciso ver se vale a pena"
- NECESSIDADE: contou o que precisa ou o que procura num plano — quantas pessoas ou aparelhos usam, para que usa (trabalho, jogos, streaming), um benefício que quer ("queria com Disney", "tem com chip?"), "só quero internet", "tem um mais em conta?", "preciso de um mais completo". Não é NECESSIDADE quando ele cita um plano pelo nome (isso é PLANO_INFORMADO).
- NAO_ENTENDEU: não entendeu o que a Eva pediu ou explicou
- SUPORTE: a pessoa JÁ É CLIENTE da MOV e quer resolver algo do serviço que já tem (internet caiu ou está lenta, boleto ou 2ª via, técnico que não veio, cancelar ou mudar o serviço atual). Dúvida de quem está contratando ("a internet cai muito?", "como vou pagar a fatura?", "tem suporte 24h?") NÃO é SUPORTE.

nota — um fato que o cliente contou NESTA mensagem e que vale lembrar no resto do atendimento, em uma frase curta na terceira pessoa. Ex.: "só pode receber o técnico à tarde", "a instalação é na casa da mãe dele", "trabalha em home office e precisa de internet estável", "achou o plano caro", "são 8 aparelhos na casa", "quer um plano com Disney+", "já tem internet de outra operadora". Sempre anote o que ele disser sobre quantidade de aparelhos ou pessoas, para que usa a internet e que benefício procura — é o que define o plano certo. Não anote dado de cadastro (nome, CPF, e-mail, telefone, endereço), pergunta, cumprimento nem o que já está nas notas. Na maioria das mensagens fica "".

confianca (0 a 1): quão certo você está da interpretação.
- 0.95+: mensagem clara (dado explícito, confirmação óbvia, pergunta direta).
- 0.7–0.9: razoável, mas com alguma ambiguidade.
- Abaixo de 0.7: incerto — mensagem confusa, múltiplas intenções ou não sabe classificar.
Sempre informe confianca honestamente; nunca use 0.
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


SCHEMA_INTERPRETACAO: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "interpretacao",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "eventos", "dados", "campos_corrigidos", "pergunta", "situacao", "nota", "confianca",
            ],
            "properties": {
                "eventos": {
                    "type": "array",
                    "items": {"type": "string", "enum": [e.value for e in Evento]},
                },
                "dados": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(CAMPOS_DADOS),
                    "properties": {campo: {"type": "string"} for campo in CAMPOS_DADOS},
                },
                "campos_corrigidos": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(CAMPOS_DADOS)},
                },
                "pergunta": {"type": "string"},
                "situacao": {"type": "string", "enum": list(SITUACOES_LLM)},
                "nota": {"type": "string"},
                "confianca": {"type": "number"},
            },
        },
    },
}

# Modelos/servidores que recusaram json_schema — seguem no JSON livre com retry
_SEM_SCHEMA: set[str] = set()


def _erro_de_schema(exc: BadRequestError) -> bool:
    low = str(exc).casefold()
    return "response_format" in low or "json_schema" in low


def interpretar(
    mensagem: str,
    estado: dict[str, Any],
    historico: list[dict[str, str]] | None = None,
) -> str:
    user = USER_TEMPLATE.format(
        estado=_estado_bloco(estado),
        historico=_historico_bloco(historico, mensagem),
        mensagem=mensagem,
    )
    modelo = modelo_ativo()
    if modelo not in _SEM_SCHEMA:
        try:
            estruturado = chat(
                SYSTEM, user, temperature=0.0, response_format=SCHEMA_INTERPRETACAO
            )
            if _json_valido(estruturado):
                return estruturado
        except BadRequestError as exc:
            if _erro_de_schema(exc):
                _SEM_SCHEMA.add(modelo)

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
