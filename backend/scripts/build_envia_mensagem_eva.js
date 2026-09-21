const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');

const ROOT = path.join(__dirname, '..', '..');
const N8N = path.join(ROOT, 'n8n');
const OUT = path.join(N8N, 'envia_mensagem_eva.json');

const CHATWOOT_API_TOKEN = 'ugEufRFeoBACNJNcPVGLZaoD';
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
      httpMethod: 'POST',
      path: 'envia_mensagem_eva',
      responseMode: 'responseNode',
      options: {},
    },
    type: 'n8n-nodes-base.webhook',
    typeVersion: 2.1,
    position: [0, 0],
    id: nid(),
    name: 'Webhook',
    webhookId: 'b88ca2ab-214e-46cd-b8fc-42c1fc004e21',
  },
  codeNode('Normalizar', [224, 0], 'normalizar_mensagem_eva.js'),
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
    position: [448, 0],
    id: nid(),
    name: 'Payload inválido?',
  },
  {
    parameters: {
      method: 'POST',
      url: '=https://chatwoot.mov.pro.br/api/v1/accounts/2/conversations/{{ $json.conversation_id }}/messages',
      sendHeaders: true,
      headerParameters: {
        parameters: [
          { name: 'api_access_token', value: CHATWOOT_API_TOKEN },
          { name: 'Content-Type', value: 'application/json' },
        ],
      },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: '={{ { content: $json.mensagem, message_type: "outgoing", private: false } }}',
      options: {},
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [672, -80],
    id: nid(),
    name: 'Envia_msg_chatwoot',
    retryOnFail: true,
    onError: 'continueErrorOutput',
  },
  codeNode('Resposta Eva', [896, 0], 'resposta_mensagem_eva.js'),
  {
    parameters: {
      respondWith: 'json',
      responseBody: '={{ $json }}',
      options: {},
    },
    type: 'n8n-nodes-base.respondToWebhook',
    typeVersion: 1.5,
    position: [1120, -80],
    id: nid(),
    name: 'Respond to Webhook OK',
    executeOnce: true,
  },
  {
    parameters: {
      respondWith: 'json',
      responseBody: '={{\n  {\n    resultado: "erro",\n    ok: false,\n    erro: true,\n    motivo: String($json.motivo || $json.errorDescription || $json.errorMessage || "Falha ao enviar mensagem"),\n    ferramenta: "enviar_mensagem"\n  }\n}}',
      options: {},
    },
    type: 'n8n-nodes-base.respondToWebhook',
    typeVersion: 1.5,
    position: [1120, 96],
    id: nid(),
    name: 'Respond to Webhook Erro',
    executeOnce: true,
  },
  {
    parameters: {
      content:
        '# Envia mensagem Eva → Chatwoot\n\nPOST /webhook/envia_mensagem_eva\n\nPayload:\n- conversation_id (obrig.)\n- mensagem OU outputs[] (bolhas)\n\nEva com CHATWOOT_MSG_WEBHOOK_URL chama este fluxo.',
      height: 280,
      width: 520,
      color: 4,
    },
    type: 'n8n-nodes-base.stickyNote',
    position: [-40, -200],
    typeVersion: 1,
    id: nid(),
    name: 'Sticky Note',
  },
];

const connections = {
  Webhook: { main: [[{ node: 'Normalizar', type: 'main', index: 0 }]] },
  Normalizar: { main: [[{ node: 'Payload inválido?', type: 'main', index: 0 }]] },
  'Payload inválido?': {
    main: [
      [{ node: 'Respond to Webhook Erro', type: 'main', index: 0 }],
      [{ node: 'Envia_msg_chatwoot', type: 'main', index: 0 }],
    ],
  },
  Envia_msg_chatwoot: {
    main: [
      [{ node: 'Resposta Eva', type: 'main', index: 0 }],
      [{ node: 'Respond to Webhook Erro', type: 'main', index: 0 }],
    ],
  },
  'Resposta Eva': {
    main: [[{ node: 'Respond to Webhook OK', type: 'main', index: 0 }]],
  },
};

const workflow = {
  name: 'Envia mensagem Eva → Chatwoot',
  nodes,
  connections,
  pinData: {
    Webhook: [
      {
        body: {
          conversation_id: '3075',
          id_cliente: '93992219098',
          outputs: ['Olá! Boa, temos cobertura no Centro.', 'Esse plano te atende?'],
        },
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
