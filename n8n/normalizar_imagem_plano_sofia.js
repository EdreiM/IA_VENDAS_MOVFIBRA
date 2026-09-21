/**
 * n8n Code — entrada IMAGEM PLANO v5 (payload pronto da Eva)
 * Sem switch por id_plano nem base64 — só valida e repassa.
 */
const raw = $input.first().json;
const body = raw.body && typeof raw.body === 'object' ? raw.body : raw;

function txt(v) {
  return v == null ? '' : String(v).trim();
}

const conversation_id = txt(body.conversation_id);
const imagem_url = txt(body.imagem_url);
const id_plano = txt(
  body.id_plano || body.plano_confirmado_id || body.plano_id || body.id_vd_contrato,
);
const content = txt(body.content || body.descricao);
const imagem_file_name = txt(body.imagem_file_name) || 'plano.jpg';
const imagem_mime_type = txt(body.imagem_mime_type) || 'image/jpeg';

const faltando = [];
if (!conversation_id) faltando.push('conversation_id');
if (!imagem_url) faltando.push('imagem_url');

if (faltando.length) {
  return [
    {
      json: {
        erro: true,
        resultado: 'erro',
        imagem_enviada: false,
        motivo: `Campos ausentes: ${faltando.join(', ')}`,
        id_plano,
        conversation_id,
        imagem_url,
      },
    },
  ];
}

return [
  {
    json: {
      id_cliente: txt(body.id_cliente),
      conversation_id,
      id_plano,
      plano_confirmado: txt(body.plano_confirmado || body.plano_nome),
      nome: txt(body.nome),
      telefone: txt(body.telefone),
      imagem_url,
      imagem_file_name,
      imagem_mime_type,
      content,
      descricao: content,
      chatwoot_attachment_field: txt(body.chatwoot_attachment_field) || 'attachments[]',
      erro: false,
    },
  },
];
