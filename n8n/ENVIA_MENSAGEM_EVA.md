# Envia mensagem Eva → Chatwoot

Respostas de texto da Eva para o cliente no WhatsApp via n8n.

## Arquitetura

```
Chatwoot (cliente) → n8n mov_woot → POST /chat (Eva)
    → Eva retorna outputs[]
    → Eva POST envia_mensagem_eva (webhook)
    → n8n → Chatwoot outgoing → WhatsApp
```

Ou: `POST /webhooks/chatwoot` na Eva (com `CHATWOOT_MSG_WEBHOOK_URL` no `.env`).

## Webhook

```
POST https://n8n2.mov.pro.br/webhook/envia_mensagem_eva
Content-Type: application/json
```

### Payload

```json
{
  "conversation_id": "3075",
  "id_cliente": "93992219098",
  "mensagem": "Texto único (opcional se usar outputs)",
  "outputs": [
    "Boa, temos cobertura no Centro!",
    "Esse plano te atende?"
  ]
}
```

### Resposta OK

```json
{
  "resultado": "ok",
  "ok": true,
  "enviadas": 2,
  "total": 2,
  "motivo": "Mensagens enviadas"
}
```

## Fluxo n8n (importar)

1. `node backend/scripts/build_envia_mensagem_eva.js`
2. Importar `n8n/envia_mensagem_eva.json`
3. Publicar webhook `envia_mensagem_eva`

Nodes: **Webhook → Normalizar → IF → Envia_msg_chatwoot → Resposta → Respond**

## .env Eva

```env
CHATWOOT_REPLY_ENABLED=false
CHATWOOT_MSG_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/envia_mensagem_eva
```

Painel **Ferramentas → Enviar mensagem (Chatwoot)** — URL prevalece sobre `.env`.

## mov_woot (opcional)

Se o fluxo principal ainda chama `/chat` e envia manualmente, pode **remover** o Envia_msg duplicado — a Eva já dispara o webhook sozinha quando `CHATWOOT_MSG_WEBHOOK_URL` está configurado.
