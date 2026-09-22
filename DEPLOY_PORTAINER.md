# Deploy Eva — Portainer / Docker

Guia oficial para subir **API + Painel + PostgreSQL** no Portainer.

Repositório: [EdreiM/IA_VENDAS_MOVFIBRA](https://github.com/EdreiM/IA_VENDAS_MOVFIBRA)

---

## 1. Arquitetura

```
Internet / WhatsApp
       ↓
   Chatwoot (n8n)
       ↓
┌──────────────────────────────────────────────┐
│  Servidor Portainer (ex.: 200.6.142.5)       │
│                                              │
│  iavendas-frontend :5180  (nginx + React)    │
│       │ proxy /admin /webhooks …             │
│       ↓                                      │
│  iavendas-api :8001       (FastAPI Eva)      │
│       ↓                                      │
│  iavendas-postgres :5433  (PostgreSQL)       │
└──────────────────────────────────────────────┘
```

| Serviço | Container | Imagem Docker Hub | Porta HOST |
|---------|-----------|-------------------|------------|
| Painel | `iavendas-frontend` | `edreimp/iavendas-frontend` | **5180** |
| API Eva | `iavendas-api` | `edreimp/iavendas-backend` | **8001** |
| PostgreSQL | `iavendas-postgres` | `postgres:16-alpine` | **5433** |

Portas escolhidas para **não conflitar** com stacks comuns (8000, 5173, 5432).

---

## 2. Duas formas de deploy

| Método | Quando usar | Arquivo compose |
|--------|-------------|-----------------|
| **A — Docker Hub (recomendado)** | CI já publica imagens; deploy rápido | `docker-compose.hub.yml` |
| **B — Build no Portainer (Git)** | Sem Hub / primeiro teste | `docker-compose.yml` |

### Método A — Docker Hub + CI (recomendado)

Cada **push na `main`** publica automaticamente:

| Imagem Hub | Tag |
|------------|-----|
| `edreimp/iavendas-backend` | `latest` + SHA do commit |
| `edreimp/iavendas-frontend` | `latest` + SHA do commit |

No Portainer: use `docker-compose.hub.yml` + variáveis mínimas (§5).

Atualizar produção: **Pull and redeploy** na stack.

### Método B — Build local no servidor

O Portainer clona o GitHub e faz `docker build`. Não precisa Docker Hub.

Compose path: `docker-compose.yml`

---

## 3. O que vai no Portainer vs no painel Eva

| Onde | O quê |
|------|-------|
| **Portainer** (infra) | `POSTGRES_PASSWORD`, `DOCKERHUB_USER`, portas |
| **Painel Eva** (operacional) | OpenAI, Chatwoot, n8n, planos, allowlist |

### Obrigatório no Portainer

```env
POSTGRES_PASSWORD=senha-forte-aqui
DOCKERHUB_USER=edreimp
```

### Opcional no Portainer

| Variável | Uso |
|----------|-----|
| `ADMIN_API_TOKEN` | Trava endpoints `/admin`. Vazio = painel aberto (ok para primeiro deploy) |
| `SOFIA_API_PORT` / `SOFIA_DASH_PORT` / `POSTGRES_PORT` | Só se houver conflito de porta |
| `IMAGE_TAG` | Fixar versão (`latest` ou SHA do commit) |

### Configure depois no painel (não precisa no Portainer)

- **Config IA** → `OPENAI_API_KEY`, modelo
- **Chatwoot** → `PUBLIC_BASE_URL`, inbox, allowlist
- **Ferramentas** → webhooks n8n

---

## 4. URLs (sem domínio)

Descubra o IP: `nslookup portainer.mov.pro.br` (ex.: `200.6.142.5`)

| Recurso | URL |
|---------|-----|
| Painel | `http://200.6.142.5:5180` |
| API health | `http://200.6.142.5:8001/health` |
| Webhook Chatwoot | `http://200.6.142.5:8001/webhooks/chatwoot` |

No painel → aba **Chatwoot** → **URL pública**: `http://200.6.142.5:8001`

**Firewall:** libere **5180** (painel) e **8001** (API/webhooks).

O nginx do painel faz proxy interno — **não precisa** `CORS_ORIGINS` no Portainer.

---

## 5. Passo a passo no Portainer (Docker Hub)

### 5.1 Criar stack

1. Portainer → **Stacks** → **Add stack**
2. Nome: `iavendas`
3. **Web editor**: cole o conteúdo de [`docker-compose.hub.yml`](docker-compose.hub.yml)
4. **Environment variables** — cole:

```env
POSTGRES_PASSWORD=sua-senha-forte
DOCKERHUB_USER=edreimp
```

Template completo (opcionais comentados): [`portainer/stack.env.example`](portainer/stack.env.example)

5. **Deploy the stack**

### 5.2 Validar containers

Aguarde os 3 containers ficarem **healthy/running**:

- `iavendas-postgres`
- `iavendas-api`
- `iavendas-frontend`

### 5.3 Configurar no painel

1. Abra `http://SEU-IP:5180`
2. Se definiu `ADMIN_API_TOKEN`, salve o token no topo do painel
3. **Config IA** → OpenAI key
4. **Chatwoot** → URL pública + inbox
5. **Ferramentas** → sync catálogo + URLs n8n

### 5.4 Testar

```bash
curl http://200.6.142.5:8001/health
# {"ok":true,"database":"postgresql",...}
```

---

## 6. Com domínio (produção)

| Serviço | Domínio sugerido |
|---------|------------------|
| Painel | `https://eva.mov.pro.br` |
| API | `https://api-eva.mov.pro.br` |

Configure no painel → **Chatwoot** → URL pública: `https://api-eva.mov.pro.br`

---

## 7. Atualizar stack

### Via CI (código novo)

1. `git push origin main` → GitHub Actions publica no Hub
2. Portainer → stack `iavendas` → **Pull and redeploy**

### Via build local

```powershell
docker compose up -d --build
```

---

## 8. Volumes (dados persistentes)

| Volume | Conteúdo |
|--------|----------|
| `iavendas_pg_data` | Banco PostgreSQL |
| `iavendas_uploads` | Imagens de planos |

**Não apague** esses volumes em produção sem backup.

---

## 9. Troubleshooting

| Sintoma | Causa provável | Ação |
|---------|----------------|------|
| Stack não sobe | `POSTGRES_PASSWORD` vazio | Defina no env |
| Erro ao puxar imagem | `DOCKERHUB_USER` errado ou imagem inexistente | Use `edreimp` + confira Hub |
| API unhealthy | Postgres ainda iniciando | Aguarde ou veja logs |
| Painel "Failed to fetch" | API down | `docker logs iavendas-api` |
| Chatwoot não recebe webhook | Porta 8001 fechada / URL errada | Teste `curl` externo |
| n8n não baixa imagem plano | URL pública errada no painel | Aba Chatwoot → URL pública |
| Porta em uso | Conflito com outro serviço | Mude `SOFIA_*_PORT` |

Logs:

```bash
docker logs iavendas-api -f
docker logs iavendas-frontend -f
docker logs iavendas-postgres -f
```

---

## 10. Referências

- [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml) — CI Docker Hub
- [`README.md`](README.md) — visão geral
- [`REGRAS_NEGOCIO.md`](REGRAS_NEGOCIO.md) — funil comercial
- [`FLUXO_SOFIA.md`](FLUXO_SOFIA.md) — fases técnicas
