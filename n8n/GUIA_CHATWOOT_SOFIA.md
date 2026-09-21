# Ponte Chatwoot (Meta / caixa MOV IA) ↔ Sofia

## Arquitetura recomendada (seu caso)

Você **já recebe** o Chatwoot no n8n (`webhook/mov_woot`).  
A melhor arquitetura **agora** é manter isso e só plugar a Sofia no meio — **não** apontar o Chatwoot direto na Sofia ainda.

```
WhatsApp (Meta)
    ↓
Chatwoot caixa MOV IA (inbox_id = 6)
    ↓
n8n Webhook mov_woot          ← você já tem
    ↓
Normalizar Entrada            ← você já tem
    ↓
If (filtros)                  ← você já tem
    · inboxId = 6
    · messageDirection = incoming
    · senderName ≠ EvolutionAPI
    · teamName vazio
    · (+ allowlist telefone em teste: 93992219098)
    ↓
HTTP Request → Sofia POST /chat
    ↓
Envia_msg_chatwoot (outgoing) ← você já tem o node
    ↓
Cliente no WhatsApp
```

### Por que assim (e não Sofia direto no Chatwoot)?

| | n8n na porta + Sofia cérebro | Sofia recebe o webhook sozinha |
|--|--|--|
| Filtros (inbox, time, loop) | Você já sabe no `If` | Precisa reimplementar |
| Mídia / localização | n8n trata e manda texto | Sofia só texto por enquanto |
| Debug | Vê cada passo no n8n | Só log da API |
| Resposta Meta | Seu node outgoing | Precisa token + cuidado com loop |
| Quando mudar depois | Só troca URL do HTTP | Ok no futuro |

**Resumo:** Chatwoot = canal · n8n = porteiro/filtro · Sofia = cérebro de vendas.

Não precisa “conectar” a Sofia no Chatwoot Settings agora.  
Quando for testar: no fluxo n8n, **depois do If true**, chame a Sofia.

---

## O que o seu pinData já mostra

Do webhook real da MOV IA:

| Campo | Exemplo | Uso na Sofia |
|-------|---------|--------------|
| `inbox.id` | `6` | filtro caixa MOV IA |
| `message_type` | `incoming` | só cliente |
| `conversation.id` | `2762` | `conversation_id` |
| `sender.id` | `1227` | `contact_id` |
| `sender.phone_number` | `+559391473978` | `id_cliente` / telefone |
| `content` | texto **ou** `null` | mensagem |
| `attachments[].file_type` | `location` | Sofia recebe `lat,lng` |

Localização sem texto (`content: null`) → normalizar para algo como:

`-2.43239,-54.71986`

(a Sofia já usa isso na viabilidade.)

---

## Node após o If (quando for plugar)

**HTTP Request → Sofia**

```
POST http://SEU-HOST:8000/chat
Content-Type: application/json

{
  "mensagem": "{{ $json.mensagem }}",
  "id_cliente": "{{ $json.telefone }}",
  "conversation_id": "{{ $json.conversationId }}",
  "contact_id": "{{ $json.contact_id || $json.contactId }}",
  "buffer": false
}
```

(Ajuste os nomes aos campos do seu **Normalizar Entrada1**.)

**Envia_msg_chatwoot** (igual ao que você já usa):

```
content = {{ $json.output }}
message_type = outgoing
URL = .../conversations/{{ conversationId }}/messages
```

### Lista completa de planos (várias bolhas)

Quando o cliente pede **todos os planos**, a Sofia devolve `outputs` (array): **1 bolha por plano** + pergunta final.

Se o n8n ainda usa só `$json.output`, as bolhas vão juntas numa mensagem só. Para enviar **separadas**:

1. Depois do HTTP `/chat`, use **Split Out** no campo `outputs` (ou um Code que faça `$json.outputs.map(...)`).
2. Em cada item, `content = {{ $json }}` (ou o campo do texto da bolha).
3. Conecte no **Envia_msg_chatwoot** (loop automático do Split Out).

Com `CHATWOOT_REPLY_ENABLED=true`, a própria Sofia já envia as bolhas uma a uma no Chatwoot.

### Allowlist só em teste (extra no If)

Além dos 4 filtros que você já tem, adicione **temporariamente**:

`telefone` contém / igual (normalizado) `93992219098`

Assim a Meta produção continua no Chatwoot humano e **não** chama a Sofia.

Na Sofia o `.env` já tem o mesmo conceito:

```env
SOFIA_INBOUND_MODE=allowlist
SOFIA_ALLOWLIST_PHONES=93992219098
CHATWOOT_INBOX_ID=6
CHATWOOT_REPLY_ENABLED=false
```

Com `CHATWOOT_REPLY_ENABLED=false`, a Sofia **não** posta outgoing sozinha — quem responde é o n8n (evita loop e fica igual ao fluxo que você conhece).

---

## Alternativa futura (não agora)

Chatwoot → `POST /webhooks/chatwoot` na Sofia + `CHATWOOT_REPLY_ENABLED=true`.

Útil quando o funil estiver estável e você quiser menos um hop.  
Hoje, para você, o caminho n8n é o mais simples e seguro.

---

## Checklist “ainda sem conectar produção”

1. Sofía sobe local (`uvicorn` porta 8000)  
2. Testa funil no chat `/?id_cliente=93992219098`  
3. Cria branch de teste no n8n (clone do mov_woot) com allowlist  
4. HTTP → `/chat` + Envia_msg só no seu número  
5. Validar → aí sim abrir allowlist / `SOFIA_INBOUND_MODE=open`
