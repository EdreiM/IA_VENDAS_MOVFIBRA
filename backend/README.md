# Backend Eva

## Local

Requer PostgreSQL (`DATABASE_URL` no `.env` da raiz).

```powershell
# da raiz do monorepo
.\run_backend.ps1
# API em http://127.0.0.1:8001
```

## Admin / painel

Rotas sob `/admin/*` e `/metrics/*` exigem `X-Admin-Token` (`ADMIN_API_TOKEN`).

Módulos: `unidades`, `planos_admin`, `ferramentas`, `admin_store` (config/promoções).

No boot, `init_schema()` cria/migra tabelas de unidades, ferramentas e seed de `transferir_atendimento`.

## Docker

Construído pelo `docker-compose.yml` na raiz (serviço `api`).
