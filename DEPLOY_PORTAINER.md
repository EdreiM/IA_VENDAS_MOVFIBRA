# Deploy Eva — Portainer / Docker

Guia oficial para subir **API + Painel + PostgreSQL** no Portainer (com ou sem domínio).

Repositório: [EdreiM/IA_VENDAS_MOVFIBRA](https://github.com/EdreiM/IA_VENDAS_MOVFIBRA)

---

## 1. Arquitetura

```
Internet / WhatsApp
       ↓
   Chatwoot (n8n)
       ↓
┌──────────────────────────────────────────────┐
│  Servidor Portainer                          │
│                                              │
│  iavendas-frontend :5180  (nginx + React)    │
│       │ proxy /api /admin /webhooks …        │
│       ↓                                      │
│  iavendas-api :8001       (FastAPI Eva)      │
│       ↓                                      │
│  iavendas-postgres :5433  (PostgreSQL)       │
└──────────────────────────────────────────────┘
```

| Serviço | Container | Porta HOST | Porta interna |
|---------|-----------|------------|---------------|
| Painel | `iavendas-frontend` | **5180** | 80 |
| API Eva | `iavendas-api` | **8001** | 8000 |
| PostgreSQL | `iavendas-postgres` | **5433** | 5432 |

Essas portas foram escolhidas para **não conflitar** com stacks comuns (8000, 5173, 5432).

Se alguma porta já estiver em uso no servidor, altere no `.env`:

```env
SOFIA_API_PORT=8002
SOFIA_DASH_PORT=5181
POSTGRES_PORT=5434
```

---

## 2. Preciso de Docker Hub?

**Não obrigatoriamente.** Duas formas:

| Método | Quando usar | Arquivo |
|--------|-------------|---------|
| **A — Build no Portainer (Git)** | Primeiro deploy, mais simples | `docker-compose.yml` |
| **B — Imagens no Docker Hub** | Deploy mais rápido, CI/CD | `docker-compose.hub.yml` |

### Método A — Recomendado para começar

O Portainer clona o GitHub e faz `docker build` na hora. **Não precisa Docker Hub.**

### Método B — Docker Hub (opcional)

Útil quando quiser atualizar só a tag da imagem, sem rebuild no servidor.

```powershell
# Na sua máquina (substitua SEU_USUARIO)
$USER = "edreim"
docker build -t ${USER}/iavendas-api:latest ./backend
docker build -t ${USER}/iavendas-frontend:latest ./frontend
docker login
docker push ${USER}/iavendas-api:latest
docker push ${USER}/iavendas-frontend:latest
```

No Portainer use `docker-compose.hub.yml` e defina `DOCKERHUB_USER=edreim`.

---

## 3. Sem domínio (teste / homolog)

Enquanto o domínio não chega, use o **IP público + porta**:

| Recurso | URL exemplo |
|---------|-------------|
| Painel | `http://203.0.113.10:5180` |
| API health | `http://203.0.113.10:8001/health` |
| Webhook Chatwoot | `http://203.0.113.10:8001/webhooks/chatwoot` |

No `.env` do stack:

```env
PUBLIC_BASE_URL=http://203.0.113.10:8001
CORS_ORIGINS=http://203.0.113.10:5180,http://localhost:5180
```

No painel Eva → aba **Chatwoot**, a URL do webhook será montada a partir de `PUBLIC_BASE_URL`.

**Firewall:** libere as portas **5180** (painel) e **8001** (API/webhooks) no servidor.

---

## 4. Com domínio (produção)

Exemplo com reverse proxy (Traefik / Nginx Proxy Manager):

| Serviço | Domínio sugerido |
|---------|------------------|
| Painel | `https://eva.movfibra.com.br` |
| API | `https://api-eva.movfibra.com.br` |

```env
PUBLIC_BASE_URL=https://api-eva.movfibra.com.br
CORS_ORIGINS=https://eva.movfibra.com.br
```

Webhook Chatwoot: `https://api-eva.movfibra.com.br/webhooks/chatwoot`

O painel em Docker usa nginx com proxy interno — `VITE_API_BASE` fica vazio (mesma origem via `/admin`, `/webhooks`, etc.).

---

## 5. Passo a passo no Portainer

### 5.1 Preparar variáveis

1. Copie `portainer/stack.env.example` → `.env` (ou cole no editor de env do Portainer).
2. Preencha **obrigatórios**:
   - `POSTGRES_PASSWORD` (senha forte)
   - `OPENAI_API_KEY`
   - `ADMIN_API_TOKEN` (token do painel)
   - `CHATWOOT_API_TOKEN`
   - URLs dos webhooks n8n que for usar
3. Ajuste `PUBLIC_BASE_URL` (IP ou domínio).

### 5.2 Criar stack

1. Portainer → **Stacks** → **Add stack**
2. Nome: `iavendas` ou `eva-movfibra`
3. **Web editor**: cole o conteúdo de `docker-compose.yml`
4. **Environment variables**: cole o `.env` ou use env file
5. **Deploy the stack**

### 5.3 Build via repositório Git (alternativa)

1. Stacks → Add stack → **Repository**
2. URL: `https://github.com/EdreiM/IA_VENDAS_MOVFIBRA`
3. Compose path: `docker-compose.yml`
4. Ative **Authentication** se repo privado
5. Deploy

### 5.4 Validar

```bash
curl http://IP:8001/health
# {"ok":true,"database":"postgresql",...}

# Painel no navegador
http://IP:5180
# Informe ADMIN_API_TOKEN no topo
```

---

## 6. Checklist pós-deploy

- [ ] `/health` → `"database": "postgresql"`
- [ ] Painel abre e token admin funciona
- [ ] Aba **Ferramentas** → sync catálogo → URLs n8n preenchidas
- [ ] Aba **Chatwoot** → inbox + URL webhook correta
- [ ] `PUBLIC_BASE_URL` acessível de fora (n8n e Chatwoot)
- [ ] Teste `/chat` ou webhook com allowlist

---

## 7. Atualizar stack

```powershell
# Local (teste antes)
docker compose pull   # só se usar hub
docker compose up -d --build
```

No Portainer: **Pull and redeploy** ou **Update the stack** com compose novo do GitHub.

---

## 8. Volumes (dados persistentes)

| Volume | Conteúdo |
|--------|----------|
| `iavendas_pg_data` | Banco PostgreSQL |
| `iavendas_uploads` | Imagens de planos enviadas |

**Não apague** esses volumes em produção sem backup.

---

## 9. Troubleshooting

| Sintoma | Causa provável | Ação |
|---------|----------------|------|
| API não sobe | `POSTGRES_PASSWORD` vazio | Defina no env do stack |
| Painel "Failed to fetch" | API down ou token errado | Ver logs `iavendas-api` |
| Chatwoot não recebe webhook | Porta 8001 fechada / URL errada | Teste `curl` externo |
| n8n não baixa imagem plano | `PUBLIC_BASE_URL` = localhost | Use IP/domínio público |
| Porta em uso | Conflito com outro serviço | Mude `SOFIA_*_PORT` no .env |

Logs:

```bash
docker logs iavendas-api -f
docker logs iavendas-frontend -f
docker logs iavendas-postgres -f
```

---

## 10. Referências

- [`README.md`](README.md) — visão geral
- [`REGRAS_NEGOCIO.md`](REGRAS_NEGOCIO.md) — funil comercial
- [`FLUXO_SOFIA.md`](FLUXO_SOFIA.md) — fases técnicas
- [`n8n/GUIA_CHATWOOT_SOFIA.md`](n8n/GUIA_CHATWOOT_SOFIA.md) — integração Chatwoot
