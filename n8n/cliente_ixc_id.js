/**
 * n8n Code — ID IXC unificado (cliente novo ou já existente).
 * Conecte ANTES de Coleta_id_cidade_cadastra nos dois ramos do If cadastrado.
 */
const norm = $('Normalizar Sofia').first().json;
let ixcId = String(norm.ixc_id_cliente || '').trim();

const criados = $('cadastro_cliente').all();
if (criados.length > 0 && criados[0].json?.id) {
  ixcId = String(criados[0].json.id).trim();
}

if (!ixcId) {
  throw new Error('ixc_id_cliente vazio — cadastro_cliente falhou ou ixc_cliente_id não veio no payload');
}

return [{ json: { ixc_id_cliente: ixcId, cadastrado: 'sim' } }];
