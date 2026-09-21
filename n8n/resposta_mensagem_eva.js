/**
 * n8n Code — resposta envia_mensagem_eva para Eva
 */
const norm = ($('Normalizar').all() || []).filter((it) => !it.json?.erro);
const total = norm.length;

if (!total) {
  const err = $('Normalizar').first()?.json || {};
  return [
    {
      json: {
        resultado: 'erro',
        ok: false,
        erro: true,
        motivo: err.motivo || 'Payload inválido',
        enviadas: 0,
        total: 0,
      },
    },
  ];
}

const enviadas = ($('Envia_msg_chatwoot').all() || []).filter((it) => {
  const j = it.json || {};
  if (j.error || j.erro) return false;
  return Boolean(j.id || j.payload || j.content || j.status === 'sent');
}).length;

const ok = enviadas >= total;

return [
  {
    json: {
      resultado: ok ? 'ok' : 'erro',
      ok,
      erro: !ok,
      enviadas,
      total,
      motivo: ok ? 'Mensagens enviadas' : `Enviadas ${enviadas}/${total}`,
    },
  },
];
