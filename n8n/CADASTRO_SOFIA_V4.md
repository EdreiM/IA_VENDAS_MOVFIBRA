# Cadastro Sofia v4 — fluxo n8n refatorado (sem Postgres)

## Arquitetura

```
Sofia (Python)  POST /webhook/cadastrar_cliente_sofia
       │
       ▼
┌──────────────────────────────────────┐
│  Webhook entrada (opcional, fino)     │
│  → Execute Workflow: CADASTRO IXC v4  │
│  → Respond to Webhook                 │
└──────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│  Subfluxo CADASTRO IXC v4             │
│  1. Normalizar Sofia (Code)           │
│  2. If já tem ixc_id?                 │
│     NÃO → cadastro_cliente IXC        │
│     SIM → pula cliente                │
│  3. contrato → login → OS (ticket)   │
│  4. Resposta Sofia (Code)             │
│  5. Chatwoot labels (opcional)        │
└──────────────────────────────────────┘
       │
       ▼
{ resultado, ixc_cliente_id, id_contrato_ixc, os_id, motivo }
```

A Sofia **não usa Postgres**. Tudo vem no JSON do webhook e o estado fica no SQLite local.

---

## O que REMOVER do fluxo antigo

| Nó | Motivo |
|----|--------|
| `Buscando cliente` (Postgres SELECT) | Sofia envia os dados no body |
| `atualiza_cadastro` | Sofia persiste `ixc_cliente_id` |
| `guarda id contrato` | Sofia persiste `id_contrato_ixc` |
| `atuaiza_status` | Sofia controla fase/aguardando |
| `Erro`, `Erro1`, `Erro2`, `Erro3` | Postgres de erro — use `Resposta Sofia` com `resultado: erro` |
| `Retorno_cad_cliente` → loop no `If` | Substituído por `Set IXC após cliente` → vai direto pro contrato |
| `saida` (Set "Cadastro realizado") | Substituído por `Resposta Sofia` |

**Manter (opcional):** alertas Evolution (`evo go erro*`) — só operação, não bloqueiam a Sofia.

---

## Trigger do subfluxo

### Execute Workflow Trigger — inputs (copie todos):

| Input | Origem Sofia |
|-------|----------------|
| `id_cliente` | sessão WhatsApp |
| `nome`, `cpf`, `email`, `telefone` | cadastro |
| `data_nascimento`, `rg` | cadastro |
| `cep`, `rua`, `numero`, `bairro`, `cidade`, `complemento` | endereço |
| `plano_confirmado_id`, `plano_confirmado` | vendas |
| `conversation_id`, `contact_id` | Chatwoot |
| `ixc_cliente_id` | vazio na 1ª vez; preenchido se reprocessar |
| `caixa_fibra`, `localizacao_fixa` | cobertura |
| `data_vencimento_pref` | default `5` |

Ou um único campo JSON `payload` — mas o Code `normalizar_cadastro_sofia.js` aceita **body flat** direto.

---

## Passo 1 — Colar no início do subfluxo

**Nó Code: `Normalizar Sofia`**  
Arquivo: `n8n/normalizar_cadastro_sofia.js`

Substitui `exec prod` + `Buscando cliente`.

---

## Passo 2 — Trocar referências nos nós IXC

Em **todos** os nós HTTP/Code, substituir:

| Antes | Depois |
|-------|--------|
| `$('Buscando cliente')` | `$('Normalizar Sofia')` |
| `$('exec prod')` | `$('Normalizar Sofia')` |
| `$('If').item.json.ixc_id_cliente` | `$('Set IXC após cliente').item.json.ixc_id_cliente` **ou** `$('Normalizar Sofia').item.json.ixc_id_cliente` |

---

## Passo 3 — Ramificação cliente novo vs existente

**If `Cliente já no IXC?`**
- Condição: `{{ $('Normalizar Sofia').item.json.cadastrado }}` equals `sim`
- **True** → `Coleta_id_cidade_cadastra` (fluxo contrato)
- **False** → `Coleta_id_cidade` → `Id_cidade` → `cadastro_cliente`

**Após `cadastro_cliente` OK ou quando cliente já existe**, use o nó Code **`Cliente IXC ID`** (`n8n/cliente_ixc_id.js`) antes de `Coleta_id_cidade_cadastra`:

- Ramo `cadastrado = sim` → **Cliente IXC ID** → contrato
- Ramo cliente novo → `If3` OK → **Cliente IXC ID** → contrato

**No `cadastro_contrato`**, campo `id_cliente`:
```
={{ $('Cliente IXC ID').item.json.ixc_id_cliente }}
```

Esse nó unifica ID novo (`cadastro_cliente.id`) e existente (`ixc_cliente_id` no payload) — evita erro 500 e "Preencha Cliente".

---

## Passo 4 — Fim do fluxo

**Nó Code: `Resposta Sofia`**  
Arquivo: `n8n/resposta_cadastro_sofia.js`

Conectar após `If5` (OS OK) → antes ou depois de `Cadastrou chatwoot`.

Se usar **Webhook externo** chamando o subfluxo, o último nó deve ser **Respond to Webhook** com body = output de `Resposta Sofia`.

---

## Resposta obrigatória (contrato Sofia)

```json
{
  "resultado": "ok",
  "ixc_cliente_id": "83450",
  "id_contrato_ixc": "92405",
  "os_id": "123456",
  "id_login": "789",
  "motivo": "Cadastro concluído (cliente + contrato + login + OS)"
}
```

Erro:
```json
{
  "resultado": "erro",
  "motivo": "cadastro de contrato não realizado: ...",
  "erro": true
}
```

---

## Webhook de entrada (workflow fino)

Arquivo pronto: `n8n/cadastro_webhook_entrada.json`

1. **Webhook** `POST cadastrar_cliente_sofia`
2. **Execute Workflow** → subfluxo CADASTRO IXC v4  
   - Passar: campos do `$json.body`
3. **Respond to Webhook** → `={{ $json }}` (output do subfluxo)

---

## .env Sofia

```env
CADASTRO_PROVIDER=webhook
CADASTRO_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/cadastrar_cliente_sofia
CADASTRO_TIMEOUT_SECONDS=120
```

`CPF_PROVIDER=ixc` continua só para **validar** se CPF já existe **antes** do resumo.

---

## Payload que a Sofia envia (exemplo)

```json
{
  "id_cliente": "5593992219098",
  "conversation_id": "12345",
  "contact_id": "678",
  "nome": "Maria Silva Teste",
  "cpf": "63798637610",
  "email": "maria@test.com",
  "telefone": "93992219098",
  "data_nascimento": "16/08/1995",
  "rg": "",
  "cep": "68010010",
  "rua": "Travessa Tapajós",
  "numero": "100",
  "bairro": "Diamantino",
  "cidade": "Santarém",
  "complemento": "",
  "plano_confirmado": "MOV ONE+",
  "plano_confirmado_id": 1180,
  "caixa_fibra": "MOV_790_RA33_AR03",
  "localizacao_fixa": "-2.43,-54.70",
  "data_vencimento_pref": "5"
}
```

Aliases legados (`cpf_cnpj`, `numero_endereco`, `plano_id`, etc.) já vêm no snapshot Python.

---

## Ordem dos nós (happy path)

1. Normalizar Sofia  
2. If cadastrado?  
3. [novo] Coleta_id_cidade → Id_cidade → cadastro_cliente → If3 → Set IXC após cliente  
4. Coleta_id_cidade_cadastra → buscar plano venda → cadastro_contrato → If6  
5. retorno_contrato → Criação_ppoe → buscar plano velo → cadastro_login → If1  
6. dado_OS → OS → If5 → Resposta Sofia → Cadastrou chatwoot (opcional)
