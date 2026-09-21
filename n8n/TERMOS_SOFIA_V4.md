# Termos + Áudio Sofia v4 — arquitetura

## Recomendação: **n8n envia direto no Chatwoot** (não a Sofia)

| Abordagem | Prós | Contras |
|-----------|------|---------|
| **n8n → Chatwoot** (recomendado) | Igual cadastro/agenda; n8n já tem API, binary, IXC PDF | Sofia depende do retorno JSON |
| Sofia recebe PDF/áudio e reenvia | — | Sofia não tem pipeline de mídia; duplicaria lógica |

**Fluxo ideal:**

```
Sofia (Python)  POST /webhook/enviar_termos_sofia
       │  snapshot: conversation_id, ixc_id_cliente, id_contrato_ixc, nome…
       ▼
n8n subfluxo TERMOS v4
       1. Áudio fidelidade → Chatwoot (multipart)
       2. Busca termo IXC → baixa PDF → Chatwoot
       3. Resposta JSON → Sofia
       ▼
Sofia persiste: termos_enviados=true, audio_fidelidade_enviado=true
Sofia manda só TEXTO: "Enviei o áudio e o termo de fidelidade 🎧📄"
```

A Sofia **não** baixa nem reenvia arquivos — só dispara o webhook e registra no log/SQLite.

---

## Quando chamar

**Após cadastro IXC OK** — antes do agendamento.

1. Sofia dispara `enviar_termos_sofia` (áudio + PDF)
2. Cliente responde *sim/aceito* → Sofia busca horários → agendamento
3. Cliente recusa → transferência humana

Não enviar termos após agendamento (ordem antiga removida).

Não misturar com `encerrar_atendimento`:

- **Termos v4** = áudio fidelidade + PDF contrato (IXC `cliente_contrato_assinatura_termo`)
- **Encerrar** = PDF do atendimento (transcript) + resolve conversa Chatwoot

---

## O que REMOVER do fluxo legado

| Nó | Motivo |
|----|--------|
| `Execute a SQL query` (Postgres estado) | Sofia manda `ixc_id_cliente` + `id_contrato_ixc` |
| `envio evo go` / `disparo arquivo de termo` | Desabilitados — canal é Chatwoot |
| `Merge` órfão | Sem uso |
| Alertas Evolution (`erro`, `erro1`) | Opcional — operação |

## O que MANTER

| Nó | Motivo |
|----|--------|
| Postgres `audios` | **Catálogo de conteúdo** (não é estado de sessão) — igual catálogo de planos |
| IXC `requisição_termos` + `Selecionar termo PDF` + `baixartermo_unico` + `Validar PDF` | PDF real do contrato (não RG/selfie) |
| `envia audio` + `Envia_chatwoot` | Entrega no WhatsApp via Chatwoot |

---

## Payload Sofia → webhook

```json
{
  "id_cliente": "559392219098@s.whatsapp.net",
  "conversation_id": "2319",
  "ixc_id_cliente": "83458",
  "id_contrato_ixc": "92405",
  "nome": "Edrei teste",
  "telefone": "93999990001"
}
```

## Resposta n8n → Sofia

```json
{
  "resultado": "ok",
  "audio_enviado": true,
  "termo_enviado": true,
  "motivo": "Áudio e termo enviados no Chatwoot"
}
```

Erro parcial:
```json
{
  "resultado": "erro",
  "audio_enviado": true,
  "termo_enviado": false,
  "motivo": "Erro ao baixar termo IXC"
}
```

---

## Arquivos

| Arquivo | Uso |
|---------|-----|
| `n8n/termos_sofia_v4.json` | Subfluxo importável |
| `n8n/termos_webhook_entrada.json` | Webhook fino |
| `n8n/normalizar_termos_sofia.js` | Entrada |
| `n8n/validar_pdf_termo.js` | Valida PDF baixado do IXC (`$input.first().binary`) |
| `n8n/resposta_termos_sofia.js` | Saída JSON |

## .env Sofia (futuro)

```env
TERMOS_PROVIDER=webhook
TERMOS_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/enviar_termos_sofia
TERMOS_TIMEOUT_SECONDS=60
```
