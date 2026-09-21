const base64 = $json.audio_base64;

const binaryData = await this.helpers.prepareBinaryData(
  Buffer.from(base64, 'base64'),
  $json.nome_arquivo || 'audio.ogg',
  $json.mime_type || 'application/ogg'
);

return [
  {
    json: $('Normalizar Sofia').first().json,
    binary: {
      audio_fidelidade: binaryData,
    },
  },
];
