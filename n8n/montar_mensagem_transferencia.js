/**
 * n8n Code node — monta texto WhatsApp interno da transferência.
 * Entrada: campos do webhook Eva (flat) ou do Execute Workflow Trigger.
 * Saída: { mensagem_transferencia }
 */
const trigger = $('When Executed by Another Workflow').first().json;
const src = { ...trigger, ...$input.first().json };

function parseJsonField(value, fallback) {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return fallback;
  }
}

const contexto = parseJsonField(src.contexto, {});

const motivo =
  (src.motivo || contexto.objetivo || '').trim() || 'não especificado';

const wa = String(src.id_cliente || '')
  .replace('@s.whatsapp.net', '')
  .replace('@c.us', '');

const fase = src.fase || contexto.fase || 'desconhecida';
const aguardando = src.aguardando || contexto.aguardando || '—';
const cadOk = Boolean(src.cadastro_completo ?? contexto.cadastro_completo);
const ixc = src.ixc_cliente_id || src.ixc_id_cliente || contexto.ixc_cliente_id || '';
const ativ = Boolean(src.ativado_ixc ?? contexto.ativado_ixc);

const linhas = [
  '🔔 Transferência de Atendimento',
  '─────────────────────',
  `👤 Cliente: ${src.nome || 'Não informado'}`,
  `📱 WhatsApp: ${wa || src.telefone || '?'}`,
];

if (src.cpf) {
  linhas.push(`📋 CPF: ${src.cpf}`);
}

linhas.push(
  `📍 Localização: ${src.bairro || '?'}, ${src.cidade || '?'}`,
  '─────────────────────',
  `📌 Fase quando transferido: ${fase}`,
  `⏳ Aguardando: ${aguardando}`,
  `🎯 Motivo da transferência: ${motivo}`,
  '─────────────────────',
);

if (src.plano_confirmado) {
  linhas.push(`📦 Plano: ${src.plano_confirmado}`);
}

linhas.push(
  `✅ Cadastro completo: ${cadOk ? 'sim' : 'não'}`,
  `🏢 IXC cliente: ${ixc || 'pendente'}`,
  `⚡ Ativado IXC: ${ativ ? 'sim' : 'não'}`,
);

return [{ json: { mensagem_transferencia: linhas.join('\n') } }];
