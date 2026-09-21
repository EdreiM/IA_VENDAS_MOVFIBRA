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

Com `CHATWOOT_TRANSFER_ENABLED=true`, ao `TRANSFERIR_HUMANO` a Eva chama o handoff
usando `CHATWOOT_TRANSFER_*` do `.env`.
