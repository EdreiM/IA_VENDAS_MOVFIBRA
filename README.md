# Eva — IA de vendas MOV FIBRA

Monorepo pronto para **GitHub + Portainer**.

```
IA VENDAS/
  backend/           API FastAPI + PostgreSQL
  frontend/          Painel operacional (Vite/React)
  n8n/               Workflows auxiliares
  docker-compose.yml Stack produção/homolog
  REGRAS_NEGOCIO.md  Regras comerciais
  FLUXO_SOFIA.md     Funil técnico
```

## Pré-requisitos

- Docker / Portainer **ou** Python 3.12 + PostgreSQL 16
- Node 20+ (só para desenvolver o painel)

## Subir com Docker (recomendado / Portainer)

Portas padrão **diferentes** de outros projetos (evita conflito com 8000/5173):

| Serviço | Porta host |
|---------|------------|
| API Eva | **8001** |
| Painel | **5180** |
| PostgreSQL | **5433** |

1. Copie `.env.example` → `.env` e preencha segredos.  
2. No Portainer: **Stacks → Add stack** → cole o `docker-compose.yml` + env.  
   Ou local:

```powershell
docker compose up -d --build
```

3. Health: http://127.0.0.1:8001/health  
4. Painel: http://127.0.0.1:5180 (informe `ADMIN_API_TOKEN` no topo)

No n8n, aponte webhooks para `http://HOST:8001/...` (ou URL pública do reverse proxy).

## Painel operacional

Abas: **Métricas**, **Conversas**, **Planos**, **Promoções**, **Config IA** (RAG), **Ferramentas** (webhooks dinâmicos), **Unidades**.

APIs admin (todas com `X-Admin-Token`):

- `GET/POST/PUT/DELETE /admin/unidades`
- `GET/POST/PUT/DELETE /admin/planos`
- `GET/POST/DELETE /admin/promocoes`
- `GET/PUT /admin/config` (`rag_webhook_url`, etc.)
- `GET/POST/PUT/DELETE /admin/ferramentas`
- `GET /metrics/resumo|funil|conversas`

A transferência automática prioriza a ferramenta `transferir_atendimento` cadastrada no painel.

## Desenvolvimento local

```powershell
# 1) Postgres (stack iavendas)
docker compose up -d postgres
# container: iavendas-postgres · porta 5433

# 2) .env na raiz
DATABASE_URL=postgresql://sofia:sofia@127.0.0.1:5433/sofia

# 3) API
.\run_backend.ps1

# 4) Painel
cd frontend
npm install
npm run dev
```

## GitHub

Não versionar:

- `.env`, `.venv`, `sofia_local.db`, `node_modules`, `dist`

Checklist antes do push:

1. `.env.example` atualizado (sem senhas reais)  
2. `docker compose config` válido  
3. `/health` retorna `"database": "postgresql"`  

## Escalabilidade

- Estado e histórico no **PostgreSQL** com pool.  
- Réplicas da API compartilham o mesmo banco.  
- Buffer WhatsApp é por processo → 1 worker/réplica (já no Dockerfile).  
- Planos/RAG/cadastro via webhooks n8n continuam escalando fora da API.

## Documentos

- [`REGRAS_NEGOCIO.md`](REGRAS_NEGOCIO.md) — comportamento comercial  
- [`FLUXO_SOFIA.md`](FLUXO_SOFIA.md) — fases e webhooks  
- [`n8n/CHATWOOT_HANDOFF.md`](n8n/CHATWOOT_HANDOFF.md) — transferência Chatwoot  
