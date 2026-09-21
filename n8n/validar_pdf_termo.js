/**
 * n8n Code — garante PDF antes de enviar ao Chatwoot
 * n8n 2.x: binary vem em $input.first().binary (não existe $binary global).
 */
const ctx =
  $('Selecionar termo PDF').first()?.json ||
  $('Normalizar Sofia').first()?.json ||
  {};

const item = $input.first();
const binary = item?.binary || {};
const bin = binary['attachments[]'] || binary.data;

if (!bin) {
  throw new Error('IXC não retornou arquivo do termo');
}

const mime = String(
  bin.mimeType || bin.mimetype || bin.fileType || '',
).toLowerCase();
const name = String(bin.fileName || bin.fileExtension || '').toLowerCase();

if (!mime.includes('pdf') && !name.endsWith('.pdf')) {
  throw new Error(
    `Arquivo errado (esperado PDF, veio ${mime || name || 'desconhecido'}). ` +
      `id_termo=${ctx.id_termo_ixc || '?'}`,
  );
}

return [
  {
    json: ctx,
    binary,
  },
];
