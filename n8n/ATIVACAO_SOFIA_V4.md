# Ativação IXC Sofia v4

## Sequência

```
Aceite termos (sim)
    → ATIVAR_CLIENTE (webhook)
    → IXC cliente_contrato_ativar_cliente
    → BUSCAR_HORARIOS → agendamento
```

## Removido do legado

| Nó | Motivo |
|----|--------|
| `dados_cliente` (Postgres SELECT) | Sofia manda `id_contrato_ixc` |
| `Registra` (Postgres UPDATE) | Sofia persiste `ativado_ixc` no SQLite |
| Alertas Evolution | Opcional — operação |

## Mantido

| Nó | Função |
|----|--------|
| `ativa` | `POST .../cliente_contrato_ativar_cliente` |

## Payload Sofia → webhook

```json
{
  "id_cliente": "559392219098@s.whatsapp.net",
  "conversation_id": "2969",
  "ixc_id_cliente": "83458",
  "id_contrato_ixc": "92405",
  "nome": "Edrei teste",
  "cpf": "60421079096",
  "telefone": "93999990001"
}
```

## Resposta n8n → Sofia

```json
{
  "resultado": "ok",
  "ativado": true,
  "id_contrato_ixc": "92405",
  "motivo": "Contrato ativado com sucesso"
}
```

## Arquivos

| Arquivo | Uso |
|---------|-----|
| `n8n/ativacao_sofia_v4.json` | Subfluxo |
| `n8n/ativacao_webhook_entrada.json` | Webhook `ativar_cliente_sofia` |
| `n8n/normalizar_ativacao_sofia.js` | Entrada |
| `n8n/resposta_ativacao_sofia.js` | Saída |

## .env

```env
ATIVACAO_PROVIDER=webhook
ATIVACAO_WEBHOOK_URL=https://n8n2.mov.pro.br/webhook/ativar_cliente_sofia
ATIVACAO_TIMEOUT_SECONDS=45
```
