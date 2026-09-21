/**
 * n8n Code — escolhe o registro de termo/contrato (PDF), não RG/selfie.
 * Entrada: resposta de cliente_contrato_assinatura_termo
 */
const ctx = $('Normalizar Sofia').first().json;
const rows = Array.isArray($json.registros) ? $json.registros : [];

if (!rows.length) {
  throw new Error(
    `Nenhum registro em cliente_contrato_assinatura_termo para contrato ${ctx.id_contrato_ixc || '?'}`,
  );
}

const norm = (v) => String(v ?? '').toLowerCase();

const textoRegistro = (r) =>
  [
    r.tipo,
    r.tipo_documento,
    r.tipo_doc,
    r.descricao,
    r.nome,
    r.documento,
    r.modelo_termo,
    r.termo,
    r.obs,
    r.arquivo,
    r.extensao,
    r.mime_type,
  ]
    .map(norm)
    .join(' ');

const isIdentity = (r) =>
  /identidade|documento pessoal|\brg\b|\bcnh\b|selfie|rosto|facial|comprovante|foto/.test(
    textoRegistro(r),
  );

const isTermo = (r) =>
  /termo|fidelidade|contrato|ades[aã]o|assinatura digital/.test(textoRegistro(r)) &&
  !isIdentity(r);

const isPdf = (r) => {
  const t = textoRegistro(r);
  return t.includes('pdf') || t.includes('application/pdf');
};

const byIdAsc = (a, b) => Number(a.id || 0) - Number(b.id || 0);

let chosen =
  rows.find((r) => isTermo(r) && isPdf(r)) ||
  rows.find((r) => isTermo(r)) ||
  rows.find((r) => isPdf(r) && !isIdentity(r)) ||
  rows.filter((r) => !isIdentity(r)).sort(byIdAsc)[0] ||
  rows.slice().sort(byIdAsc)[0];

if (!chosen?.id) {
  throw new Error('Registro de termo sem id válido');
}

return [
  {
    json: {
      ...ctx,
      id_termo_ixc: String(chosen.id),
      termo_debug: {
        total: rows.length,
        escolhido_id: chosen.id,
        escolhido_tipo: chosen.tipo || chosen.tipo_documento || '',
        escolhido_nome: chosen.nome || chosen.descricao || '',
      },
    },
  },
];
