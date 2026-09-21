# Fluxo Eva — sequência oficial

Ordem fixa do funil comercial (não pular etapas):

```
1. Localização     → viabilidade / cobertura IXC
2. Planos          → vendas (apresentar, escolher, confirmar) + imagem (plano único)
3. Cadastro        → dados + IXC (cliente, contrato, OS)
4. Aceite termos   → áudio + PDF (n8n) → cliente aceita
5. Ativação        → IXC cliente_contrato_ativar_cliente
6. Agendamento     → horários → confirma → insere na OS
7. Encerramento    → dúvidas pós-venda → PDF atendimento + resolve Chatwoot
```

Persistência: **PostgreSQL** (`DATABASE_URL`).  
Regras detalhadas: [`REGRAS_NEGOCIO.md`](REGRAS_NEGOCIO.md).

---

## Mapa fase → etapa

| # | Etapa (negócio) | `fase` | Ações / webhooks |
|---|-----------------|--------|------------------|
| 1 | **Localização** | `inicio` → `viabilidade` | `CHECAR_COBERTURA` |
| 2 | **Planos** | `vendas` | planos PG/webhook, imagem se plano único |
| 3 | **Cadastro** | `cadastro` | CPF IXC, `cadastrar_cliente_sofia` |
| 4 | **Aceite termos** | `termos` | `enviar_termos_sofia` → `aceite_termos` |
| 5 | **Ativação** | (pós-aceite) | `ativar_cliente_sofia` → `ativado_ixc` |
| 6 | **Agendamento** | `agendamento` | `verifica_tecnicos` → `insere_agenda` |
| 7 | **Encerramento** | `pos_venda` → `finalizado` | `encerrar_atendimento` |

Fases auxiliares: `sem_cobertura`, `transferido` (humano + handoff Chatwoot opcional).

---

## Transições principais

```mermaid
flowchart LR
    A[Localização] --> B[Planos]
    B --> C[Cadastro]
    C --> D[Termos enviados]
    D --> E{Aceita?}
    E -->|sim| V[Ativar IXC]
    E -->|não| T[Transferido]
    V --> F[Agendamento]
    F --> G[Agenda OK]
    G --> H[Pós-venda / dúvidas]
    H --> I[Encerramento]
```

---

## Detalhe por etapa

### 1. Localização
- Cliente informa cidade/bairro (e endereço quando necessário).
- Eva chama cobertura (Google Maps + IXC).
- Sem cobertura → `sem_cobertura` ou transferência.

### 2. Planos
- Plano único: 📦 + benefícios ✅ (+ imagem se configurado).
- Lista completa / ambíguos: uma bolha por plano, **sem spam de imagens**.
- “O que tem no plano X?” → detalha benefícios.
- Confirmação → libera cadastro.

### 3. Cadastro
- Coleta nome, CPF, e-mail, telefone, endereço, etc.
- Resumo + confirmação → webhook cadastro IXC.
- Salva `ixc_cliente_id`, `id_contrato_ixc`, `os_id`.

### 4. Aceite de termos
- **Após cadastro OK** (não após agendamento).
- Webhook `enviar_termos_sofia`: áudio fidelidade + PDF termo no Chatwoot.
- Aceite → ativação; recusa → transferência humana.

### 5. Ativação
- Webhook `ativar_cliente_sofia` → IXC.
- Sucesso → buscar horários; erro → transferência.

### 6. Agendamento
- Webhook `verifica_tecnicos` → mostra horários.
- Confirma → `insere_agenda` → `pos_venda`.

### 7. Encerramento
- Dúvidas → se não houver, `encerrar_atendimento` → `finalizado`.

### Transferência
- Estado `transferido` + silêncio da IA.
- Opcional: `CHATWOOT_TRANSFER_*` assign/labels/status.

---

## `.env` dos webhooks (produção)

```env
DATABASE_URL=postgresql://sofia:SENHA@postgres:5432/sofia
COVERAGE_PROVIDER=ixc
CADASTRO_PROVIDER=webhook
CADASTRO_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/cadastrar_cliente_sofia
TERMOS_PROVIDER=webhook
TERMOS_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/enviar_termos_sofia
ATIVACAO_PROVIDER=webhook
ATIVACAO_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/ativar_cliente_sofia
AGENDA_PROVIDER=webhook
ENCERRAR_PROVIDER=webhook
PLANS_PROVIDER=webhook
CHATWOOT_TRANSFER_ENABLED=true
```

Portainer / Docker: ver [`README.md`](README.md) e `docker-compose.yml` (API **8001**, Dash **5180**, PG **5433**).
