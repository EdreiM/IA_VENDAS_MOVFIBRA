# Imagem do plano — v5 (URL do painel)

## Fluxo

```
Eva → POST enviar_imagem_plano_sofia
    → n8n baixa imagem_url (GET)
    → n8n POST Chatwoot (content + attachments[])
    → texto completo do plano continua vindo da Eva (outputs / reply)
```

**Sem** base64, **sem** switch por `id_plano`, **sem** Sets manuais por plano.

## Payload (Eva monta tudo)

```json
{
  "conversation_id": "3075",
  "id_plano": "1212",
  "plano_confirmado": "MOV SUPER+",
  "imagem_url": "https://api.mov.pro.br/media/planos/plano_1212_abc.jpg",
  "imagem_file_name": "plano_1212_abc.jpg",
  "imagem_mime_type": "image/jpeg",
  "content": "✅ Internet ilimitada 📶\n✅ Imagina Só e Ubook 📚\n✅ Repetidor Mesh…",
  "descricao": "…",
  "chatwoot_attachment_field": "attachments[]"
}
```

| Campo | Uso |
|-------|-----|
| `imagem_url` | URL **pública** da imagem (n8n faz GET) |
| `content` / `descricao` | Legenda no Chatwoot (benefícios do painel) |
| `imagem_file_name` | Nome do arquivo no anexo |
| `imagem_mime_type` | MIME (`image/jpeg`, `image/png`…) |

## Importar no n8n

1. `node backend/scripts/build_imagem_plano_sofia_v4.js` — gera `imagem_plano_sofia_v4.json`
2. Importar subfluxo **IMAGEM PLANO Sofia v5**
3. Importar/atualizar `imagem_plano_webhook_entrada.json`
4. Apontar o Execute Workflow para o ID do subfluxo v5
5. Publicar webhook

## .env

```env
IMAGEM_PLANO_PROVIDER=webhook
IMAGEM_PLANO_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/enviar_imagem_plano_sofia
PUBLIC_BASE_URL=https://URL-PUBLICA-DA-API
```

`PUBLIC_BASE_URL` precisa ser acessível pelo servidor n8n (não use `127.0.0.1` em produção).

## Resposta

```json
{
  "resultado": "ok",
  "imagem_enviada": true,
  "id_plano": "1212",
  "motivo": "Imagem enviada"
}
```
