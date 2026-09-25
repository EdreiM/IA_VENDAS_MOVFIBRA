# Transferência para humano — Eva + n8n

## Arquitetura

```
Eva (TRANSFERIR_HUMANO)
       │ POST ferramenta transferir_atendimento
       ▼
┌─────────────────────────────────────────────┐
│  Webhook entrada (fino)                      │
│  POST /webhook/transferir_atendimento_eva    │
│  → Execute Workflow: subfluxo transferência  │
│  → Respond to Webhook                        │
└─────────────────────────────────────────────┘
       │
       ├─ Chatwoot: team vendas (1) + label aguardando
       ├─ INSERE ATENDIMENTO IXC (subfluxo existente)
       └─ Evolution: alerta WhatsApp interno
```

A Eva **não** faz handoff Chatwoot nativo quando a URL da ferramenta está configurada — o n8n assume assign, labels e IXC.

---

## Configuração na Eva

### Painel → Ferramentas → **Transferir atendimento**

URL do webhook (exemplo):

```
https://n8n2.mov.pro.br/webhook/transferir_atendimento_eva
```

### `.env` (opcional — fallback se URL vazia no painel)

```env
TRANSFER_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/transferir_atendimento_eva
TRANSFER_WEBHOOK_TIMEOUT_SECONDS=45
```

Com URL configurada, **desligue** o handoff duplicado:

```env
CHATWOOT_TRANSFER_ENABLED=false
```

---

## Payload que a Eva envia

Campos principais (snapshot completo + extras):

| Campo | Exemplo | Uso no n8n |
|-------|---------|------------|
| `conversation_id` | `18422` | assign + labels Chatwoot |
| `id_cliente` | `5593999999999@s.whatsapp.net` | referência / alerta |
| `motivo` | `Cliente pediu humano` | mensagem interna |
| `contexto` | JSON **string** `{ fase, aguardando, ... }` | resumo do estado |
| `mensagens` | JSON **string** (array) | histórico para INSERE IXC |
| `cadastro_completo`, `ativado_ixc` | `"true"` / `"false"` | strings (n8n Execute Workflow) |
| `nome`, `cpf`, `telefone` | cadastro | alerta Evolution |
| `cidade`, `bairro` | localização | alerta |
| `plano_confirmado` | `MOV SUPER` | alerta |
| `cadastro_completo` | `true` | alerta (não `cadastro_confirmado`) |
| `ixc_cliente_id` | `83450` | INSERE ATENDIMENTO |
| `ativado_ixc` | `false` | alerta |
| `os_id`, `id_contrato_ixc` | IDs IXC | opcional |

**Resposta esperada do webhook:**

```json
{ "resultado": "ok", "retorno": "sucesso" }
```

---

## Importar no n8n

1. Importe `n8n/transferir_atendimento_subfluxo.json` — ajuste IDs se necessário:
   - `INSERE ATENDIMENTO IXC MOV FIBRA V4` (`aqY5bfmOqGWhu1nn`)
   - No trigger do subfluxo, declare também `buffer`, `mensagens` e `total_mensagens`
   - `team_id: 1` → time vendas no Chatwoot
2. Importe `n8n/transferir_webhook_entrada.json`
3. No webhook entrada, troque `SUBSTITUA_PELO_ID_DO_SUBFLUXO` pelo ID do subfluxo importado
4. Ative **ambos** os workflows
5. Configure variáveis de ambiente no n8n (não commitar tokens no Git):

| Variável | Uso |
|----------|-----|
| `CHATWOOT_API_TOKEN` | Header `api_access_token` |
| `EVOLUTION_API_KEY` | Alerta interno |
| `EVOLUTION_ALERT_NUMBER` | Número que recebe alerta (default `9392095710`) |

---

## O que mudou em relação ao fluxo antigo

| Antes | Agora |
|-------|-------|
| Postgres `ia_vendas.estado_cliente_ia` | Dados vêm no body da Eva |
| Colunas `cadastro_confirmado`, `cadastro_ixc_status` | `cadastro_completo`, `ixc_cliente_id`, `ativado_ixc` |
| Tokens hardcoded no JSON | `$env.CHATWOOT_API_TOKEN`, `$env.EVOLUTION_API_KEY` |
| Payload Eva com 5 campos | Snapshot completo + `contexto` |
| Fallback Chatwoot após webhook | Eva **não** duplica assign se URL configurada |
| Timeout 20s | 45s (configurável) |

---

## Nó Call INSERE ATENDIMENTO IXC (dentro do subfluxo)

A Eva envia `mensagens` como **JSON string**. O INSERE V4 exige **array**.

No nó **Call INSERE ATENDIMENTO IXC**:

- **convertFieldsToString:** `false` (senão o array vira string de novo)
- **mensagens:**

```
={{ (() => { const m = $('When Executed by Another Workflow').first().json.mensagens; if (Array.isArray(m)) return m; try { return JSON.parse(m || '[]'); } catch { return []; } })() }}
```

Schema do campo `mensagens`: tipo **array** (não string).

---

## Nó Code — mensagem interna

Arquivo: `n8n/montar_mensagem_transferencia.js`

Substitui o SELECT Postgres. Use no nó **Montar mensagem transferencia**.

---

## Teste manual (curl)

```bash
curl -X POST "https://n8n2.mov.pro.br/webhook/transferir_atendimento_eva" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "2969",
    "id_cliente": "5593999999999@s.whatsapp.net",
    "motivo": "Teste manual",
    "nome": "Maria Silva",
    "cidade": "Santarem",
    "bairro": "Diamantino",
    "fase": "cadastro",
    "aguardando": "cpf",
    "cadastro_completo": false,
    "contexto": { "fase": "cadastro", "objetivo": "Teste manual" }
  }'
```

---

## Quando a Eva transfere

- Cliente pede atendente humano
- Falha IXC (cadastro, termos, ativação, agenda)
- Erros repetidos / insistência sem cobertura
- CPF inválido após tentativas

Ver `REGRAS_NEGOCIO.md` e `backend/app/transfer_chatwoot.py`.
