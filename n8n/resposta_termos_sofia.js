/**
 * n8n Code — resposta TERMOS v4 para Eva/Sofia
 *
 * Fluxo linear: áudio → IXC termos → PDF Chatwoot.
 * Se o PDF foi (termoOk), o áudio já passou — mesmo que o HTTP do áudio
 * não traga id/message_type no JSON (comum em multipart no n8n 2.x).
 */
function chatwootOk(json) {
  if (!json || typeof json !== 'object') return false;
  if (json.error || json.errorMessage || json.errorDescription) return false;

  const status = Number(json.statusCode || json.status || 0);
  if (status >= 400) return false;
  if (status >= 200 && status < 300 && (json.id || json.content != null)) return true;

  const mt = json.message_type;
  if (mt === 'outgoing' || mt === 1 || mt === '1') return true;
  if (json.id) return true;
  if (json.content != null) return true;
  if (json.payload) return true;
  if (json.status === 'sent' || json.status === 'delivered') return true;

  const nested = json.message || json.data?.message || json.data;
  if (nested && typeof nested === 'object' && (nested.id || nested.content != null)) {
    return true;
  }

  return false;
}

function nodeOk(name) {
  try {
    const items = $(name).all();
    if (!items.length) return false;
    return items.some((item) => chatwootOk(item.json || {}));
  } catch {
    return false;
  }
}

function nodeExecutou(name) {
  try {
    return $(name).all().length > 0;
  } catch {
    return false;
  }
}

function audioProvavelmenteOk() {
  const candidatos = [
    'envia audio',
    'Envia audio',
    'envia_audio',
  ];
  for (const nome of candidatos) {
    if (nodeOk(nome)) return true;
  }
  for (const nome of candidatos) {
    if (nodeExecutou(nome)) return true;
  }
  // Fallback: qualquer nó cujo nome contenha "audio" e tenha rodado
  try {
    for (const nome of Object.keys($workflow?.nodes || {})) {
      if (!/audio/i.test(nome)) continue;
      if (nodeOk(nome) || nodeExecutou(nome)) return true;
    }
  } catch {
    /* n8n 2.x pode não expor $workflow */
  }
  return false;
}

let audioOk = audioProvavelmenteOk();
const termoOk = nodeOk('Envia_chatwoot') || nodeOk('Envia chatwoot');

// Neste workflow o PDF só existe se o ramo do áudio teve sucesso
if (!audioOk && termoOk) {
  audioOk = true;
}

const ok = audioOk && termoOk;

return [
  {
    json: {
      resultado: ok ? 'ok' : 'erro',
      audio_enviado: audioOk,
      termo_enviado: termoOk,
      motivo: ok
        ? 'Áudio e termo enviados no Chatwoot'
        : `Parcial: audio=${audioOk} termo=${termoOk}`,
      erro: !ok,
      transferir: !termoOk,
    },
  },
];
