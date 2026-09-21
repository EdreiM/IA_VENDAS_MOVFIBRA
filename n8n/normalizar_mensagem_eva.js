/**
 * n8n Code — webhook envia_mensagem_eva
 * Expande outputs[] em itens (1 mensagem WhatsApp por bolha).
 */
const raw = $input.first().json;
const body = raw.body && typeof raw.body === 'object' ? raw.body : raw;

function txt(v) {
  return v == null ? '' : String(v).trim();
}

const conversation_id = txt(body.conversation_id);
const id_cliente = txt(body.id_cliente);

const mensagens = [];
const outputs = body.outputs;
if (Array.isArray(outputs)) {
  for (const o of outputs) {
    const m = txt(o);
    if (m) mensagens.push(m);
  }
}
if (!mensagens.length) {
  const unica =
    txt(body.mensagem) ||
    txt(body.content) ||
    txt(body.output) ||
    txt(body.resposta);
  if (unica) mensagens.push(unica);
}

if (!conversation_id) {
  return [
    {
      json: {
        erro: true,
        motivo: 'conversation_id ausente',
        conversation_id: '',
        mensagem: '',
      },
    },
  ];
}

if (!mensagens.length) {
  return [
    {
      json: {
        erro: true,
        motivo: 'mensagem/resposta vazia',
        conversation_id,
        mensagem: '',
      },
    },
  ];
}

return mensagens.map((mensagem, idx) => ({
  json: {
    conversation_id,
    id_cliente,
    mensagem,
    indice: idx + 1,
    total: mensagens.length,
    erro: false,
  },
}));
