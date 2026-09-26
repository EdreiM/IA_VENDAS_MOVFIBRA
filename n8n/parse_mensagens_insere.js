/**
 * n8n Code — primeiro nó do INSERE ATENDIMENTO V4 (após trigger).
 * Converte mensagens (string JSON ou array) → array para o restante do fluxo.
 */
const raw = $input.first().json;
let mensagens = raw.mensagens;

if (typeof mensagens === 'string' && mensagens.trim()) {
  try {
    mensagens = JSON.parse(mensagens);
  } catch {
    mensagens = [];
  }
}
if (!Array.isArray(mensagens)) {
  mensagens = [];
}

return [
  {
    json: {
      ...raw,
      mensagens,
      buffer: String(raw.buffer || '').trim(),
    },
  },
];
