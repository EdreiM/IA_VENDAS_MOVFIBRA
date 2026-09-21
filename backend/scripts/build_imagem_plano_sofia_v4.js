const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');

const ROOT = path.join(__dirname, '..', '..');
const N8N = path.join(ROOT, 'n8n');
const OUT = path.join(N8N, 'imagem_plano_sofia_v4.json');

const CHATWOOT_API_TOKEN = 'ugEufRFeoBACNJNcPVGLZaoD';
const N = "$('Normalizar Sofia')";

const nid = () => randomUUID();

function codeNode(name, pos, jsFile) {
  return {
    parameters: { jsCode: fs.readFileSync(path.join(N8N, jsFile), 'utf8') },
    type: 'n8n-nodes-base.code',
    typeVersion: 2,
    position: pos,
    id: nid(),
    name,
  };
}

const nodes = [
  {
    parameters: {
      workflowInputs: {
        values: [
          'id_cliente',
          'conversation_id',
          'id_plano',
          'plano_confirmado',
          'nome',
          'telefone',
          'imagem_url',
          'imagem_file_name',
          'imagem_mime_type',
          'content',
          'descricao',
          'chatwoot_attachment_field',
        ].map((name) => ({ name })),
      },
    },
    id: nid(),
    typeVersion: 1.1,
    name: 'When Executed by Another Workflow',
    type: 'n8n-nodes-base.executeWorkflowTrigger',
    position: [-640, 320],
  },
  codeNode('Normalizar Sofia', [-416, 320], 'normalizar_imagem_plano_sofia.js'),
  {
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
        conditions: [
          {
            id: nid(),
            leftValue: '={{ $json.erro }}',
            rightValue: true,
            operator: { type: 'boolean', operation: 'true', singleValue: true },
          },
        ],
        combinator: 'and',
      },
      options: {},
    },
    type: 'n8n-nodes-base.if',
    typeVersion: 2.2,
    position: [-192, 320],
    id: nid(),
    name: 'Payload inválido?',
  },
  {
    parameters: {
      method: 'GET',
      url: '={{ $json.imagem_url }}',
      options: {
        response: {
          response: {
            responseFormat: 'file',
            outputPropertyName: 'attachments[]',
          },
        },
      },
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [48, 240],
    id: nid(),
    name: 'Baixar imagem',
    onError: 'continueErrorOutput',
  },
  {
    parameters: {
      method: 'POST',
      url: `=https://chatwoot.mov.pro.br/api/v1/accounts/2/conversations/{{ ${N}.item.json.conversation_id }}/messages`,
      sendHeaders: true,
      headerParameters: {
        parameters: [{ name: 'api_access_token', value: CHATWOOT_API_TOKEN }],
      },
      sendBody: true,
      contentType: 'multipart-form-data',
      bodyParameters: {
        parameters: [
          { name: 'message_type', value: 'outgoing' },
          { name: 'private', value: 'false' },
          { name: 'content', value: `={{ ${N}.item.json.content || '' }}` },
          {
            parameterType: 'formBinaryData',
            name: 'attachments[]',
            inputDataFieldName: 'attachments[]',
          },
        ],
      },
      options: {},
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [304, 240],
    id: nid(),
    name: 'Envio da imagem chatwoot',
    executeOnce: true,
    onError: 'continueErrorOutput',
  },
  codeNode('Resposta Sofia', [560, 320], 'resposta_imagem_plano_sofia.js'),
  {
    parameters: {
      content:
        '# Imagem Plano v5\n\nEva envia imagem_url + content + metadados.\nSem base64, sem switch por id_plano.\n\n1. Baixar imagem (GET imagem_url)\n2. POST Chatwoot multipart',
      height: 420,
      width: 920,
      color: 6,
    },
    type: 'n8n-nodes-base.stickyNote',
    position: [-672, 80],
    typeVersion: 1,
    id: nid(),
    name: 'Sticky Note',
  },
];

const connections = {
  'When Executed by Another Workflow': {
    main: [[{ node: 'Normalizar Sofia', type: 'main', index: 0 }]],
  },
  'Normalizar Sofia': {
    main: [[{ node: 'Payload inválido?', type: 'main', index: 0 }]],
  },
  'Payload inválido?': {
    main: [
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
      [{ node: 'Baixar imagem', type: 'main', index: 0 }],
    ],
  },
  'Baixar imagem': {
    main: [
      [{ node: 'Envio da imagem chatwoot', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
  'Envio da imagem chatwoot': {
    main: [
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
};

const workflow = {
  name: 'IMAGEM PLANO Sofia v5 — URL painel (subfluxo)',
  nodes,
  connections,
  pinData: {
    'When Executed by Another Workflow': [
      {
        id_cliente: '559392219098@s.whatsapp.net',
        conversation_id: '2969',
        id_plano: '1212',
        plano_confirmado: 'MOV SUPER+',
        imagem_url: 'https://SEU-HOST/media/planos/plano_1212_exemplo.jpg',
        imagem_file_name: 'plano_1212.jpg',
        imagem_mime_type: 'image/jpeg',
        content: '✅ Internet ilimitada 📶\n✅ Imagina Só e Ubook 📚\n✅ Repetidor Mesh',
      },
    ],
  },
  meta: {
    templateCredsSetupCompleted: true,
    instanceId: '79075fb22e5045e1beb3493444de048310c5aee705e7f3d3f6b2ea7d89bc4b09',
  },
};

fs.writeFileSync(OUT, JSON.stringify(workflow, null, 2));
console.log('Gerado:', OUT);
