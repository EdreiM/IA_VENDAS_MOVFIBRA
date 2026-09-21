# Eva — IA de vendas MOV FIBRA

Monorepo oficial da **Eva**: API FastAPI, painel operacional, integrações n8n/Chatwoot/IXC.

**GitHub:** [EdreiM/IA_VENDAS_MOVFIBRA](https://github.com/EdreiM/IA_VENDAS_MOVFIBRA)

```
IA VENDAS/
├── backend/              API FastAPI (Eva)
├── frontend/             Painel React + nginx
├── n8n/                  Workflows e documentação
├── portainer/            Template de env para Portainer
├── docker-compose.yml    Stack padrão (build local/Git)
├── docker-compose.hub.yml Stack com imagens Docker Hub
├── DEPLOY_PORTAINER.md   Guia de deploy
├── REGRAS_NEGOCIO.md     Regras comerciais
└── FLUXO_SOFIA.md        Funil técnico
```

---

## Stack Docker / Portainer

| Serviço | Container | Porta HOST |
|---------|-----------|------------|
| API Eva | `iavendas-api` | **8001** |
| Painel | `iavendas-frontend` | **5180** |
| PostgreSQL | `iavendas-postgres` | **5433** |

Portas escolhidas para **não conflitar** com 8000/5173/5432 de outros projetos.

### Deploy rápido

1. Copie `portainer/stack.env.example` → `.env` e preencha segredos.
2. Ajuste `PUBLIC_BASE_URL` (`http://IP:8001` sem domínio).
3. No Portainer: **Stacks → Add stack** → cole `docker-compose.yml` + env.

Guia completo: **[DEPLOY_PORTAINER.md](DEPLOY_PORTAINER.md)**

```powershell
docker compose up -d --build
curl http://127.0.0.1:8001/health
# Painel: http://127.0.0.1:5180
```

**Docker Hub:** opcional. O Portainer pode buildar direto do GitHub. Ver [DEPLOY_PORTAINER.md](DEPLOY_PORTAINER.md) §2.

---

## Painel operacional

| Aba | Função |
|-----|--------|
| Chat teste | Simular conversa local |
| Métricas | Funil e totais |
| Conversas | Lista + handoff + histórico de mensagens |
| **Clientes** | Ficha completa (cadastro, plano, IXC) |
| Planos | Catálogo com imagens |
| Promoções | Códigos promocionais |
| Config IA | OpenAI, RAG, tom de voz |
| **Chatwoot** | Webhook inbound, inbox, teste de payload |
| Ferramentas | Webhooks n8n dinâmicos |
| Unidades | Filiais / cidades |

Autenticação admin: header `X-Admin-Token` = `ADMIN_API_TOKEN` do `.env`.

---

## Desenvolvimento local

```powershell
docker compose up -d postgres
# .env: DATABASE_URL=postgresql://sofia:SENHA@127.0.0.1:5433/sofia

.\run_backend.ps1          # API :8001
cd frontend && npm run dev # Painel :5180
```

---

## Integrações

| Canal | Entrada | Saída |
|-------|---------|-------|
| Chatwoot/WhatsApp | `POST /webhooks/chatwoot` | Ferramenta `enviar_mensagem` (n8n) |
| n8n | `POST /chat` | Webhooks configurados no painel |
| IXC | Via n8n | Cadastro, ativação, agenda |

Webhook Chatwoot (produção): `{PUBLIC_BASE_URL}/webhooks/chatwoot`

---

## Git — o que NÃO versionar

- `.env`, `.venv`, `node_modules`, `dist/`, `backend/uploads/`

Antes do push: `docker compose config` válido e `/health` com PostgreSQL.

---

## Documentação

- [DEPLOY_PORTAINER.md](DEPLOY_PORTAINER.md) — Portainer, portas, domínio, Docker Hub
- [REGRAS_NEGOCIO.md](REGRAS_NEGOCIO.md) — comportamento comercial
- [FLUXO_SOFIA.md](FLUXO_SOFIA.md) — fases e webhooks
- [n8n/GUIA_CHATWOOT_SOFIA.md](n8n/GUIA_CHATWOOT_SOFIA.md) — Chatwoot
