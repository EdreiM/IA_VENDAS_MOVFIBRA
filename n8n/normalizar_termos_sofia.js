/**
 * n8n Code — entrada subfluxo TERMOS SOFIA v4
 */
const raw = $input.first().json;
const body = raw.body && typeof raw.body === 'object' ? raw.body : raw;

return [
  {
    json: {
      id_cliente: String(body.id_cliente || ''),
      conversation_id: String(body.conversation_id || ''),
      ixc_id_cliente: String(body.ixc_id_cliente || body.ixc_cliente_id || ''),
      id_contrato_ixc: String(body.id_contrato_ixc || body.id_contrato || ''),
      nome: String(body.nome || ''),
      telefone: String(body.telefone || ''),
    },
  },
];
