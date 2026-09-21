/**
 * n8n Code — resposta final para a Sofia (Respond to Webhook / retorno subfluxo)
 * Conecte após OS OK + labels Chatwoot (opcional).
 */
const cliente = $('Normalizar Sofia').first().json;
const unificado = $('Cliente IXC ID').first()?.json || {};
const ixcId =
  String(unificado.ixc_id_cliente || '').trim() ||
  String(cliente.ixc_id_cliente || '').trim() ||
  String($('cadastro_cliente').first()?.json?.id || '').trim();

const contrato = $('retorno_contrato').first()?.json || {};
const osNode = $('OS').first()?.json || {};
const loginNode = $('cadastro_login').first()?.json || $('cadastro_login1').first()?.json || {};

const idContrato = String(contrato.id_contrato || '').trim();
const osId = String(osNode.id || osNode.os_id || '').trim();
const idLogin = String(loginNode.id || '').trim();

const ok = Boolean(ixcId && idContrato && osId);

return [
  {
    json: {
      resultado: ok ? 'ok' : 'erro',
      ixc_cliente_id: ixcId,
      id_contrato_ixc: idContrato,
      os_id: osId,
      id_login: idLogin,
      motivo: ok
        ? 'Cadastro concluído (cliente + contrato + login + OS)'
        : `Incompleto: ixc=${ixcId || '-'} contrato=${idContrato || '-'} os=${osId || '-'}`,
      erro: !ok,
    },
  },
];
