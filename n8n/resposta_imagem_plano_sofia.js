/**
 * n8n Code — resposta IMAGEM PLANO v5 para Eva
 */
function nodeOk(name) {
  try {
    const item = $(name).first();
    if (!item) return false;
    const j = item.json || {};
    if (j.error || j.erro) return false;
    return Boolean(j.id || j.payload || j.content || j.status === 'sent');
  } catch {
    return false;
  }
}

const norm =
  $('Normalizar Sofia1').first()?.json ||
  $('Normalizar Sofia').first()?.json ||
  {};

if (norm.erro) {
  return [
    {
      json: {
        resultado: 'erro',
        imagem_enviada: false,
        id_plano: String(norm.id_plano || ''),
        motivo: norm.motivo || 'Payload inválido',
        erro: true,
      },
    },
  ];
}

const enviada = [
  'Envio da imagem chatwoot1',
  'Envio da imagem chatwoot',
].some((name) => nodeOk(name));

const idPlano = String(norm.id_plano || '');

return [
  {
    json: {
      resultado: enviada ? 'ok' : 'erro',
      imagem_enviada: enviada,
      id_plano: idPlano,
      motivo: enviada ? 'Imagem enviada' : 'Imagem não enviada',
      erro: !enviada,
    },
  },
];
