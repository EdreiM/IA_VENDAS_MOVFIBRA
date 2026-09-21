# Guia n8n — mapeamento dos webhooks Sofia (sem Postgres)

A Sofia envia **todos** os dados no body do webhook.
No Execute Workflow, use sempre:

```
={{ $json.body.CAMPO || $json.CAMPO }}
```

(Webhook n8n coloca o JSON em `body`; testes manuais às vezes vêm no root.)

---

## 1) `verifica_tecnicos` → TECNICOS HORARIOS

**Sofia envia (principais):**

| Campo | Exemplo | Uso |
|-------|---------|-----|
| `id_cliente` | ID IXC (preferencial) | input do subfluxo |
| `id_cliente_sessao` | JID WhatsApp | referência |
| `ixc_id_cliente` | mesmo ID IXC | alias |
| `cidade` | Santarem | filtro agenda |
| `bairro` | Diamantino | filtro agenda |
| `nome`, `cpf`, `telefone`… | extras | opcional |

**Execute Workflow — inputs:**

```
id_cliente = {{ $json.body.id_cliente || $json.id_cliente }}
cidade     = {{ $json.body.cidade || $json.cidade }}
bairro     = {{ $json.body.bairro || $json.bairro }}
```

Remova qualquer Postgres que busque cidade/bairro.

---

## 2) `cadastrar_cliente_sofia` → CADASTRO COMPLETO IXC

**Quando:** cliente confirma o resumo cadastral (`sim` na fase `confirmacao_dados`).

**Sofia envia** (`snapshot_cliente` + extras):

| Campo | Exemplo | Uso no n8n |
|-------|---------|------------|
| `id_cliente` | JID WhatsApp / sessão | referência |
| `conversation_id`, `contact_id` | Chatwoot | opcional |
| `nome`, `cpf`, `email`, `telefone` | cadastro | incluir cliente IXC |
| `data_nascimento`, `rg` | cadastro | IXC |
| `cep`, `rua`, `numero`, `bairro`, `cidade` | endereço | IXC + OS |
| `plano_confirmado`, `plano_confirmado_id` | `MOV ONE+`, `1180` | contrato (`id_vd_contrato`) |
| `plano_id`, `id_vd_contrato` | `1180` | alias do plano |
| `tem_cobertura`, `caixa_fibra` | viabilidade | mensagem OS |
| `ixc_cliente_id` | vazio antes | preenchido na resposta |

**Respond to Webhook — JSON de saída (obrigatório):**

```json
{
  "resultado": "ok",
  "ixc_cliente_id": "83450",
  "id_contrato_ixc": "92405",
  "os_id": "1634556",
  "motivo": "Cadastro concluído"
}
```

**Erros:**

```json
{ "resultado": "erro", "motivo": "descrição do erro" }
```

```json
{ "resultado": "ja_cadastrado", "motivo": "CPF já existe no IXC" }
```

**O subfluxo n8n deve fazer (o que a MOV já fazia manualmente):**

1. Incluir/atualizar **cliente** no IXC  
2. Criar **contrato** (`cliente_contrato`) com o plano escolhido  
3. Criar **login** PPPoE (`radusuarios`)  
4. Abrir **ticket/OS** (`su_ticket`, processo 106) — necessário para `insere_agenda`  
5. Devolver os IDs para a Sofia persistir  

**Arquivos prontos no repo:**

| Arquivo | Uso |
|---------|-----|
| `n8n/cadastro_sofia_v4.json` | Subfluxo refatorado (importar no n8n) |
| `n8n/cadastro_webhook_entrada.json` | Webhook fino → Execute Workflow → Respond |
| `n8n/normalizar_cadastro_sofia.js` | Code node entrada (substitui Postgres) |
| `n8n/resposta_cadastro_sofia.js` | Code node saída JSON Sofia |
| `n8n/CADASTRO_SOFIA_V4.md` | Guia passo a passo |

**`.env` Sofia:**

```env
CADASTRO_PROVIDER=webhook
CADASTRO_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/cadastrar_cliente_sofia
```

Com `CADASTRO_PROVIDER=webhook`, a Sofia **não** chama mais a API IXC de cadastro direto.

---

## 3) `insere_agenda` → INSERE AGENDA TÉCNICOS NA OS

**Sofia envia:**

| Campo | Exemplo |
|-------|---------|
| `ixc_id_cliente` | `12345` |
| `data_hora_agendamento` | `2026-08-28 08:00:00` |
| `id_tecnico` | `466` |
| + snapshot completo (nome, cidade, plano…) | |

**Execute Workflow — inputs:**

```
ixc_id_cliente        = {{ $json.body.ixc_id_cliente || $json.ixc_id_cliente }}
data_hora_agendamento = {{ $json.body.data_hora_agendamento || $json.data_hora_agendamento }}
id_tecnico            = {{ $json.body.id_tecnico || $json.id_tecnico }}
```

No subfluxo, o trigger já recebe esses 3 — **não** busque OS por Postgres se já vierem prontos.
(Se o subfluxo ainda lista OS por `id_cliente` no MySQL IXC, isso é IXC/MySQL de produção — ok manter.)

---

## 4) `encerrar_atendimento` → ENCERRAR ATENDIMENTO

**Sofia envia (completo):**

| Campo | Uso no n8n |
|-------|------------|
| `id_cliente` | sessão / WhatsApp (limpar histórico antigo se ainda usar) |
| `conversation_id` | Chatwoot `toggle_status` |
| `contact_id` | opcional |
| `ixc_id_cliente` | PDF / arquivo no IXC |
| `nome` | PDF |
| `cpf`, `email`, `telefone`, `cidade`, `bairro`, `plano_confirmado`… | PDF / metadados |
| `data_agendamento`, `horario_escolhido`, `tecnico_id`, `os_id` | PDF |
| `mensagens` | array `[{remetente, mensagem, created_at, author, text}]` |
| `buffer` | texto pronto `Cliente (10:22): ...` |
| `total_mensagens` | contagem |

**Execute Workflow ENCERRAR — inputs:**

```
id_cliente       = {{ $json.body.id_cliente || $json.id_cliente }}
conversation_id  = {{ $json.body.conversation_id || $json.conversation_id }}
```

**Dentro de ENCERRAR → Execute `INSERE ATENDIMENTO IXC`:**

Passe direto do webhook (sem Postgres):

```
id_cliente       = {{ $('Encerramento').item.json.body.id_cliente || $('Encerramento').item.json.id_cliente }}
ixc_id_cliente   = {{ $('Encerramento').item.json.body.ixc_id_cliente || $('Encerramento').item.json.ixc_id_cliente }}
nome             = {{ $('Encerramento').item.json.body.nome || $('Encerramento').item.json.nome }}
buffer           = {{ $('Encerramento').item.json.body.buffer || $('Encerramento').item.json.buffer }}
mensagens        = {{ $('Encerramento').item.json.body.mensagens || $('Encerramento').item.json.mensagens }}
conversation_id  = {{ $('Encerramento').item.json.body.conversation_id || $('Encerramento').item.json.conversation_id }}
```

(Ajuste o nome do node Webhook se for diferente de `Encerramento`.)

---

## 5) `enviar_termos_sofia` → TERMOS SOFIA v4

**Quando:** Sofia chama automaticamente após `insere_agenda` OK.

**Sofia envia:**

| Campo | Uso no n8n |
|-------|------------|
| `id_cliente` | sessão WhatsApp |
| `conversation_id` | Chatwoot — envio áudio + PDF |
| `ixc_id_cliente` | metadados / validação |
| `id_contrato_ixc` | IXC `cliente_contrato_assinatura_termo` |
| `nome`, `telefone` | opcional |

**Resposta esperada:**

```json
{
  "resultado": "ok",
  "audio_enviado": true,
  "termo_enviado": true,
  "motivo": "Áudio e termo enviados no Chatwoot"
}
```

**Execute Workflow TERMOS v4 — inputs:**

```
id_cliente       = {{ $json.body.id_cliente || $json.id_cliente }}
conversation_id  = {{ $json.body.conversation_id || $json.conversation_id }}
ixc_id_cliente   = {{ $json.body.ixc_id_cliente || $json.ixc_id_cliente }}
id_contrato_ixc  = {{ $json.body.id_contrato_ixc || $json.id_contrato_ixc }}
nome             = {{ $json.body.nome || $json.nome }}
telefone         = {{ $json.body.telefone || $json.telefone }}
```

Sem Postgres de estado — `id_contrato_ixc` vem do cadastro Sofia.

**Importante:** não usar `registros[0]` com sort `desc` — o IXC Assina grava RG/selfie depois do termo. O nó `Selecionar termo PDF` filtra termo/contrato PDF e rejeita identidade.

---

## 6) `ativar_cliente_sofia` → ATIVAÇÃO IXC v4

**Quando:** Sofia chama automaticamente após aceite dos termos (`sim`/`aceito`).

**Sofia envia:**

| Campo | Uso no n8n |
|-------|------------|
| `id_contrato_ixc` | IXC `cliente_contrato_ativar_cliente` |
| `ixc_id_cliente` | metadados |
| `id_cliente`, `conversation_id`, `nome`, `cpf`, `telefone` | opcional / log |

**Resposta esperada:**

```json
{
  "resultado": "ok",
  "ativado": true,
  "id_contrato_ixc": "92405",
  "motivo": "Contrato ativado com sucesso"
}
```

**Execute Workflow ATIVAÇÃO v4 — inputs:**

```
id_cliente       = {{ $json.body.id_cliente || $json.id_cliente }}
conversation_id  = {{ $json.body.conversation_id || $json.conversation_id }}
ixc_id_cliente   = {{ $json.body.ixc_id_cliente || $json.ixc_id_cliente }}
id_contrato_ixc  = {{ $json.body.id_contrato_ixc || $json.id_contrato_ixc }}
nome             = {{ $json.body.nome || $json.nome }}
cpf              = {{ $json.body.cpf || $json.cpf }}
telefone         = {{ $json.body.telefone || $json.telefone }}
```

Sem Postgres — Sofia persiste `ativado_ixc` no SQLite.

---

**Refatore o subfluxo INSERE ATENDIMENTO:**

1. **Apague** nodes Postgres `dados_cliente` / `Log_mensagens`
2. No trigger, declare inputs: `id_cliente`, `ixc_id_cliente`, `nome`, `buffer` (ou `mensagens`)
3. Use `$json.buffer` / `$json.mensagens` no Code que monta o HTML
4. Use `$json.ixc_id_cliente` no upload IXC
5. **Apague** o `DELETE FROM ia_vendas.historico...` — a Sofia limpa o SQLite local

**resolve_conversa Chatwoot:**

```
URL: .../conversations/{{ conversation_id }}/toggle_status
```

`conversation_id` vem do input do ENCERRAR (já mapeado).

---

## 5) `RAG_V3_SOFIA` (RAG)

**Sofia envia:**

```
pergunta, mensagem, contexto{...}, id_cliente, cidade, bairro, plano_confirmado, fase, nome
```

Se o subfluxo RAG só precisa da pergunta:

```
pergunta = {{ $json.body.pergunta || $json.pergunta }}
```

Extras opcionais para personalizar resposta.

---

## 6) `PLANOS_SOFIA` (planos)

**Sofia envia:**

```
acao: "listar"
+ snapshot flatten (cidade, bairro, id_cliente, plano_confirmado…)
contexto: { mesmo snapshot }
```

Se o subfluxo só lista planos do Postgres/Sheets de **planos** (catálogo), pode ignorar o snapshot.
Se filtrava por cidade no estado do cliente, use:

```
cidade = {{ $json.body.cidade || $json.cidade }}
bairro = {{ $json.body.bairro || $json.bairro }}
```

---

## Checklist geral

1. Webhook = **POST** + workflow **ativo**
2. Respond to Webhook = `={{ $json }}`
3. Remover Postgres de **estado/histórico do cliente**
4. Manter MySQL/API **IXC** (sistema de produção real)
5. Manter Chatwoot HTTP
6. Catálogo de planos / RAG knowledge base podem continuar em Postgres **de conteúdo**, não de sessão

---

## Exemplo de body real (`encerrar_atendimento`)

```json
{
  "id_cliente": "5593999999999@s.whatsapp.net",
  "conversation_id": "18422",
  "ixc_id_cliente": "55210",
  "nome": "Maria Silva",
  "cpf": "000.000.000-00",
  "cidade": "Santarem",
  "bairro": "Diamantino",
  "plano_confirmado": "MOV SUPER",
  "data_agendamento": "28/08/2026",
  "horario_escolhido": "8h às 9h",
  "tecnico_id": "466",
  "mensagens": [
    {"remetente": "cliente", "mensagem": "Oi", "author": "Cliente", "text": "Oi", "created_at": "..."},
    {"remetente": "sofia", "mensagem": "Olá!", "author": "Atendente", "text": "Olá!", "created_at": "..."}
  ],
  "buffer": "Cliente (10:01): Oi\nAtendente (10:01): Olá!",
  "total_mensagens": 2
}
```
