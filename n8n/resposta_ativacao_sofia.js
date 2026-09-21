/**
 * n8n Code — resposta ATIVAÇÃO v4 para Sofia
 *
 * Conecte após o nó `ativa` (sucesso e erro → Continue On Fail).
 */
const ativa = $('ativa').first()?.json || {};
const msg = String(ativa.message || ativa.mensagem || ativa.motivo || '').trim();
const type = String(ativa.type || '').toLowerCase();

const ok =
  type === 'success' ||
  Boolean(ativa.id) ||
  /sucesso|ativado|ok/i.test(msg) ||
  (!ativa.error && !/erro|error|fail/i.test(msg) && Object.keys(ativa).length > 0);

const contrato = String(
  $('Normalizar Sofia').first()?.json?.id_contrato_ixc || '',
);

return [
  {
    json: {
      resultado: ok ? 'ok' : 'erro',
      ativado: ok,
      id_contrato_ixc: contrato,
      motivo: ok
        ? msg || 'Contrato ativado com sucesso'
        : msg || 'Erro ao ativar contrato no IXC',
      erro: !ok,
    },
  },
];
