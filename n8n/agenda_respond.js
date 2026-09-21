// Code node n8n — após "Montar Horarios" (ou último node do subfluxo)
// Respond to Webhook deve retornar este JSON

const item = $input.first()?.json || {};

return [{
  json: {
    resultado: item.resultado || 'erro',
    tecnico_id: item.tecnico_id || item.id_tecnico || '',
    data: item.data || item.data_alvo_br || '',
    manha: Array.isArray(item.manha) ? item.manha : [],
    tarde: Array.isArray(item.tarde) ? item.tarde : [],
    motivo: item.motivo || '',
  },
}];
