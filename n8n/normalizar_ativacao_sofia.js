/**
 * n8n Code — entrada subfluxo ATIVAÇÃO SOFIA v4
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
      cpf: String(body.cpf || body.cpf_cnpj || ''),
      telefone: String(body.telefone || ''),
    },
  },
];
