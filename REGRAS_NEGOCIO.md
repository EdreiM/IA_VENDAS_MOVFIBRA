# Eva — regras de negócio (fonte da verdade operacional)

## 1. Objetivo

A **Eva** é a IA de vendas da MOV FIBRA no WhatsApp (via Chatwoot/n8n).
Ela conduz o funil até agendamento e encerramento, com transferência humana quando necessário.
Nome público e identidade: **Eva** (não Sofia).

## 2. Sequência oficial (não pular)

1. **Localização** → cobertura IXC  
2. **Planos** → apresentar / escolher / confirmar (+ imagem só de plano único)  
3. **Cadastro** → dados + IXC  
4. **Termos** → áudio + PDF → aceite  
5. **Ativação** → IXC  
6. **Agendamento** → horários + OS  
7. **Encerramento** → dúvidas → PDF + resolve  

Fases auxiliares: `sem_cobertura`, `transferido`.

## 3. Persistência

- **PostgreSQL** é o banco oficial (estado, histórico, logs, planos locais, admin).
- Conexão via `DATABASE_URL` + pool (`DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE`).
- Catálogo de planos: tabela `planos` **ou** webhook n8n (`PLANS_PROVIDER=webhook`).
- Multiunidade: tabela `unidades` (filial/cidade). Planos, promoções, config e ferramentas podem ter `unidade_id`.
- Config IA (ex.: `rag_webhook_url`) em `sofia_config` por unidade ou global.
- Ferramentas webhook em `ferramentas` + `ferramenta_parametros` (seed padrão: `transferir_atendimento`).

## 4. Planos (comportamento comercial)

| Situação | Comportamento |
|----------|----------------|
| Oferta de **1 plano** | Formato 📦 + ✅ benefícios; pode enviar imagem |
| Pedido de **todos os planos** | 1 bolha por plano com benefícios; **sem** imagem |
| Ambiguidade (ex.: mesh) | 1 bolha por candidato com benefícios |
| “O que tem nesse plano?” | Detalha benefícios; não trata como escolha automática |
| Confirmação | Imagem só se ainda não enviou daquele plano |

Imagens de plano no painel: campo `imagem_url` (URL). Escopo por unidade opcional.

## 5. Transferência humana

1. Eva marca `fase=transferido` e para de responder.  
2. Se existir ferramenta ativa `transferir_atendimento`, usa o webhook cadastrado (ou handoff Chatwoot se a URL estiver vazia).  
3. Senão, se `CHATWOOT_TRANSFER_ENABLED=true`, faz handoff no Chatwoot (time/atendente/labels/status).  
4. Endpoints manuais: `/chatwoot/*` (painel ou n8n).

## 6. Integrações (produção)

Providers no `.env`: `mock` (dev) | `webhook` / `ixc` (prod).

| Etapa | Provider típico |
|-------|-----------------|
| Cobertura | `ixc` |
| Planos | `webhook` ou `postgres` |
| Cadastro / termos / ativação / agenda / encerrar | `webhook` n8n |
| RAG | webhook n8n — URL preferencialmente em **Config IA** do painel (`rag_webhook_url`), senão `.env` |

## 7. Painel operacional

Abas: Métricas, Conversas (status `com_ia` / `transferido` / `finalizado`), Planos, Promoções, Config IA, Ferramentas, Unidades.  
Auth: header `X-Admin-Token` = `ADMIN_API_TOKEN`.

## 8. Escalabilidade

- API em container com PostgreSQL compartilhado.  
- Pool de conexões (não abre SQLite por request).  
- Índices em `id_cliente`, `conversation_id`, `fase`, `updated_at`.  
- Buffer de mensagens é **in-memory por processo** → preferir 1 worker por réplica; escalar com mais containers se houver sticky session, ou Redis no futuro.  
- Idempotência de webhook Chatwoot: tabela `mensagens_processadas_ia`.

## 9. Deploy

- Dev local: PostgreSQL (Docker) + `run_backend.ps1` + `frontend npm run dev`.  
- Produção: `docker-compose.yml` no Portainer (API **8001**, Dash **5180**, PG **5433** por padrão — evita conflito com outros projetos na 8000/5173).

## 10. Segurança

- Segredos só no `.env` / variáveis do Portainer (nunca no Git).  
- `ADMIN_API_TOKEN` protege `/metrics`, `/admin`, `/chatwoot`.  
- `SOFIA_INBOUND_MODE=allowlist` em teste; `open` só em produção controlada.
