# Resposta de erro — ferramentas n8n → Eva

Quando o **Execute Workflow** (ou qualquer nó) falhar com `onError: continueErrorOutput`,
o ramo de erro do **Respond to Webhook** deve devolver este JSON (não o `$json` bruto do n8n).

## JSON canônico (todas as ferramentas)

```json
{
  "resultado": "erro",
  "ok": false,
  "erro": true,
  "transferir": true,
  "motivo": "Falha na ferramenta — detalhe legível para a Eva",
  "ferramenta": "cadastrar_cliente"
}
```

## Expressão no Respond to Webhook (ramo erro)

Em **Respond With = JSON**, use no *Response Body*:

```
={{
  {
    resultado: 'erro',
    ok: false,
    erro: true,
    transferir: true,
    motivo: String($json.errorDescription || $json.errorMessage || $json.motivo || 'Falha na ferramenta'),
    ferramenta: 'cadastrar_cliente'
  }
}}
```

Troque `ferramenta` conforme o fluxo: `inserir_agendamento`, `ativar_cliente`, `enviar_termos`, etc.

## Sucesso (referência)

```json
{
  "resultado": "ok",
  "ok": true,
  "erro": false,
  "ixc_cliente_id": "12345",
  "id_contrato_ixc": "678",
  "os_id": "90",
  "motivo": "Cadastro concluído"
}
```

## CPF já cadastrado

```json
{
  "resultado": "ja_cadastrado",
  "ok": false,
  "erro": true,
  "transferir": true,
  "motivo": "CPF já cadastrado no IXC",
  "ixc_cliente_id": "12345"
}
```

## O que a Eva faz

- `erro: true` / `ok: false` / `transferir: true` / `resultado: "erro"` → mensagem ao cliente + `TRANSFERIR_HUMANO`
- `resultado: "ja_cadastrado"` → mensagem específica + transferência
