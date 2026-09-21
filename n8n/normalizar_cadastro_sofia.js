/**
 * n8n Code — entrada do subfluxo CADASTRO SOFIA v4
 * Aceita body do Webhook Sofia OU inputs do Execute Workflow.
 * Saída: mesmo shape do antigo "Buscando cliente" (Postgres), sem DB.
 */
const raw = $input.first().json;
const body = raw.body && typeof raw.body === 'object' ? raw.body : raw;

function digits(v) {
  return String(v ?? '').replace(/\D/g, '');
}

function telBr(v) {
  let n = digits(v);
  if (n.length === 13 && n.startsWith('55')) n = n.slice(2);
  return n;
}

const ixc = String(body.ixc_cliente_id || body.ixc_id_cliente || '').trim();

return [
  {
    json: {
      id_cliente: String(body.id_cliente || ''),
      conversation_id: String(body.conversation_id || ''),
      contact_id: String(body.contact_id || ''),
      nome: String(body.nome || ''),
      cpf_cnpj: digits(body.cpf || body.cpf_cnpj),
      email: String(body.email || ''),
      telefone: telBr(body.telefone),
      whatsapp: telBr(body.telefone),
      cep: String(body.cep || ''),
      rua: String(body.rua || ''),
      numero_endereco: String(body.numero || body.numero_endereco || ''),
      bairro: String(body.bairro || ''),
      cidade: String(body.cidade || ''),
      complemento: String(body.complemento || 'Sem complemento'),
      data_nascimento: String(body.data_nascimento || ''),
      plano_id: String(body.plano_confirmado_id || body.plano_id || body.id_vd_contrato || ''),
      plano_confirmado: String(body.plano_confirmado || ''),
      rg_cliente: digits(body.rg || body.rg_cliente),
      localizacao: String(body.localizacao_fixa || body.localizacao || ''),
      caixa_fibra: String(body.caixa_fibra || ''),
      data_vencimento: String(body.data_vencimento_pref || body.data_vencimento || '5'),
      data_hora_agendamento: String(body.data_hora_agendamento || ''),
      ixc_id_cliente: ixc,
      cadastrado: ixc ? 'sim' : 'nao',
    },
  },
];
