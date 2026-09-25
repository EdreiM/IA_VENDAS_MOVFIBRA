# Endpoints Chatwoot (Sofia backend)

Todas as rotas abaixo exigem `X-Admin-Token` se `ADMIN_API_TOKEN` estiver definido.

## Catálogo

- `GET /chatwoot/agents`
- `GET /chatwoot/teams`
- `GET /chatwoot/labels`
- `GET /chatwoot/inboxes`

## Ações

### Assign
`POST /chatwoot/assign`
```json
{ "conversation_id": "2969", "assignee_id": 12, "team_id": 3 }
```

### Labels (substitui a lista)
`POST /chatwoot/labels`
```json
{ "conversation_id": "2969", "labels": ["sofia_transferido", "humano"] }
```

### Status
`POST /chatwoot/status`
```json
{ "conversation_id": "2969", "status": "open" }
```

### Handoff (tudo junto)
`POST /chatwoot/handoff`
```json
{
  "conversation_id": "2969",
  "assignee_id": 12,
  "team_id": 3,
  "labels": ["sofia_transferido"],
  "status": "open",
  "motivo": "Cliente pediu humano"
}
```

## Automático na Eva

**Prioridade:**

1. Ferramenta **transferir_atendimento** (painel ou `TRANSFER_WEBHOOK_URL`) → webhook n8n
2. Se URL vazia: handoff nativo Chatwoot via ferramenta (fallback)
3. Se ferramenta não existe: `CHATWOOT_TRANSFER_ENABLED=true` + `CHATWOOT_TRANSFER_*` do `.env`

Com webhook n8n configurado, mantenha `CHATWOOT_TRANSFER_ENABLED=false` — o n8n faz assign/labels.

Ver `n8n/TRANSFERIR_ATENDIMENTO.md`.
