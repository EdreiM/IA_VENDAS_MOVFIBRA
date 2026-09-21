const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');

const ROOT = path.join(__dirname, '..');
const N8N = path.join(ROOT, 'n8n');
const OUT = path.join(N8N, 'termos_sofia_v4.json');

const CRED_IXC = { httpBasicAuth: { id: 'oTcpUfNTfpW9r72r', name: 'c0002_ixc_Agente_de_IA_api' } };
const CRED_PG = { postgres: { id: 'fBJznTgwjZ9E5LEZ', name: 'MOV FIBRA' } };
// Mesmo token dos nós Chatwoot do cadastro_sofia_v4.json
const CHATWOOT_API_TOKEN = 'ugEufRFeoBACNJNcPVGLZaoD';
const T = "$('When Executed by Another Workflow')";
const N = "$('Normalizar Sofia')";
const C = N + '.item.json';

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
          'ixc_id_cliente',
          'id_contrato_ixc',
          'nome',
          'telefone',
        ].map((name) => ({ name })),
      },
    },
    id: nid(),
    typeVersion: 1.1,
    name: 'When Executed by Another Workflow',
    type: 'n8n-nodes-base.executeWorkflowTrigger',
    position: [-1712, 560],
  },
  codeNode('Normalizar Sofia', [-1520, 560], 'normalizar_termos_sofia.js'),
  {
    parameters: {},
    type: 'n8n-nodes-base.wait',
    typeVersion: 1.1,
    position: [-1328, 560],
    id: nid(),
    name: 'Wait',
    webhookId: nid(),
  },
  {
    parameters: {
      operation: 'select',
      schema: { __rl: true, value: 'ia_vendas', mode: 'list', cachedResultName: 'ia_vendas' },
      table: { __rl: true, value: 'audios', mode: 'list', cachedResultName: 'audios' },
      where: { values: [{ column: 'nome_arquivo', value: 'audio_fidelidade_mov' }] },
      options: {},
    },
    type: 'n8n-nodes-base.postgres',
    typeVersion: 2.6,
    position: [-1120, 560],
    id: nid(),
    name: 'audio',
    credentials: CRED_PG,
  },
  {
    parameters: {
      jsCode: fs.readFileSync(path.join(N8N, 'audio_binary_termos.js'), 'utf8'),
    },
    type: 'n8n-nodes-base.code',
    typeVersion: 2,
    position: [-912, 560],
    id: nid(),
    name: 'Code in JavaScript',
  },
  {
    parameters: {
      method: 'POST',
      url: '=https://chatwoot.mov.pro.br/api/v1/accounts/2/conversations/{{ $json.conversation_id }}/messages',
      sendHeaders: true,
      headerParameters: {
        parameters: [
          { name: 'api_access_token', value: CHATWOOT_API_TOKEN },
        ],
      },
      sendBody: true,
      contentType: 'multipart-form-data',
      bodyParameters: {
        parameters: [
          { name: 'content', value: 'Segue o áudio de fidelidade 🎧' },
          {
            parameterType: 'formBinaryData',
            name: 'attachments[]',
            inputDataFieldName: '=audio_fidelidade',
          },
        ],
      },
      options: {},
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-704, 560],
    id: nid(),
    name: 'envia audio',
    executeOnce: true,
    onError: 'continueErrorOutput',
  },
  {
    parameters: {
      url: 'https://ixc.mov.pro.br/webservice/v1/cliente_contrato_assinatura_termo',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpBasicAuth',
      sendHeaders: true,
      headerParameters: { parameters: [{ name: 'ixcsoft', value: 'listar' }] },
      sendBody: true,
      bodyParameters: {
        parameters: [
          { name: 'qtype', value: '=id_contrato' },
          { name: 'query', value: `=${C}.id_contrato_ixc` },
          { name: 'oper', value: '==' },
          { name: 'page', value: '1' },
          { name: 'rp', value: '20' },
          { name: 'sortname', value: 'cliente_contrato_assinatura_termo.id' },
          { name: 'sortorder', value: 'asc' },
        ],
      },
      options: {
        redirect: { redirect: {} },
        response: { response: { responseFormat: 'json' } },
      },
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-480, 560],
    id: nid(),
    name: 'requisição_termos',
    credentials: CRED_IXC,
    onError: 'continueErrorOutput',
  },
  codeNode('Selecionar termo PDF', [-360, 560], 'selecionar_termo_ixc.js'),
  {
    parameters: {
      url: 'https://ixc.mov.pro.br/webservice/v1/botao_rel_28088',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpBasicAuth',
      sendBody: true,
      bodyParameters: {
        parameters: [{ name: 'id', value: '={{ $json.id_termo_ixc }}' }],
      },
      options: {
        redirect: { redirect: { maxRedirects: '=21' } },
        response: {
          response: { responseFormat: 'file', outputPropertyName: 'attachments[]' },
        },
      },
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-256, 560],
    name: 'baixartermo_unico',
    id: nid(),
    credentials: CRED_IXC,
    onError: 'continueErrorOutput',
  },
  codeNode('Validar PDF termo', [-80, 560], 'validar_pdf_termo.js'),
  {
    parameters: {
      method: 'POST',
      url: "=https://chatwoot.mov.pro.br/api/v1/accounts/2/conversations/{{ $('Normalizar Sofia').first().json.conversation_id }}/messages",
      sendHeaders: true,
      headerParameters: {
        parameters: [
          { name: 'api_access_token', value: CHATWOOT_API_TOKEN },
        ],
      },
      sendBody: true,
      contentType: 'multipart-form-data',
      bodyParameters: {
        parameters: [
          { name: 'message_type', value: 'outgoing' },
          { name: 'private', value: 'false' },
          { name: 'content', value: '=Termo de fidelidade' },
          {
            parameterType: 'formBinaryData',
            name: 'attachments[]',
            inputDataFieldName: '=attachments[]',
          },
        ],
      },
      options: {},
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-32, 560],
    id: nid(),
    name: 'Envia_chatwoot',
    onError: 'continueErrorOutput',
  },
  codeNode('Resposta Sofia', [192, 560], 'resposta_termos_sofia.js'),
  {
    parameters: {
      content: '# Termos Sofia v4\n\nSem Postgres estado. Payload Sofia traz id_contrato_ixc.',
      height: 400,
      width: 2100,
      color: 5,
    },
    type: 'n8n-nodes-base.stickyNote',
    position: [-1776, 480],
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
    main: [[{ node: 'Wait', type: 'main', index: 0 }]],
  },
  Wait: { main: [[{ node: 'audio', type: 'main', index: 0 }]] },
  audio: { main: [[{ node: 'Code in JavaScript', type: 'main', index: 0 }]] },
  'Code in JavaScript': {
    main: [[{ node: 'envia audio', type: 'main', index: 0 }]],
  },
  'envia audio': {
    main: [
      [{ node: 'requisição_termos', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
  requisição_termos: {
    main: [
      [{ node: 'Selecionar termo PDF', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
  'Selecionar termo PDF': {
    main: [[{ node: 'baixartermo_unico', type: 'main', index: 0 }]],
  },
  baixartermo_unico: {
    main: [
      [{ node: 'Validar PDF termo', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
  'Validar PDF termo': {
    main: [[{ node: 'Envia_chatwoot', type: 'main', index: 0 }]],
  },
  Envia_chatwoot: {
    main: [
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
};

const workflow = {
  name: 'TERMOS SOFIA v4 — áudio + PDF (subfluxo)',
  nodes,
  connections,
  pinData: {
    'When Executed by Another Workflow': [
      {
        id_cliente: '559392219098@s.whatsapp.net',
        conversation_id: '2969',
        ixc_id_cliente: '83458',
        id_contrato_ixc: '92405',
        nome: 'Edrei teste',
        telefone: '93999990001',
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
