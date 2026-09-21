const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');

const ROOT = path.join(__dirname, '..');
const N8N = path.join(ROOT, 'n8n');
const OUT = path.join(N8N, 'ativacao_sofia_v4.json');

const CRED_IXC = {
  httpBasicAuth: { id: 'oTcpUfNTfpW9r72r', name: 'c0002_ixc_Agente_de_IA_api' },
};
const C = "$('Normalizar Sofia').item.json";

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
          'cpf',
          'telefone',
        ].map((name) => ({ name })),
      },
    },
    id: nid(),
    typeVersion: 1.1,
    name: 'When Executed by Another Workflow',
    type: 'n8n-nodes-base.executeWorkflowTrigger',
    position: [-1328, 16],
  },
  codeNode('Normalizar Sofia', [-1104, 16], 'normalizar_ativacao_sofia.js'),
  {
    parameters: {
      method: 'POST',
      url: 'https://ixc.mov.pro.br/webservice/v1/cliente_contrato_ativar_cliente',
      authentication: 'genericCredentialType',
      genericAuthType: 'httpBasicAuth',
      sendBody: true,
      specifyBody: 'json',
      jsonBody: `={\n  \"id_contrato\": \"{{ ${C}.id_contrato_ixc }}\"\n}`,
      options: {
        redirect: { redirect: {} },
        response: { response: { responseFormat: 'json' } },
      },
    },
    type: 'n8n-nodes-base.httpRequest',
    typeVersion: 4.2,
    position: [-864, 16],
    id: nid(),
    name: 'ativa',
    credentials: CRED_IXC,
    onError: 'continueErrorOutput',
  },
  codeNode('Resposta Sofia', [-608, 16], 'resposta_ativacao_sofia.js'),
  {
    parameters: {
      content:
        '# Ativação Sofia v4\n\nSem Postgres.\nSofia manda id_contrato_ixc → IXC ativar → JSON.',
      height: 280,
      width: 900,
      color: 4,
    },
    type: 'n8n-nodes-base.stickyNote',
    position: [-1360, -80],
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
    main: [[{ node: 'ativa', type: 'main', index: 0 }]],
  },
  ativa: {
    main: [
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
};

const workflow = {
  name: 'ATIVAÇÃO IXC v4 — Sofia (subfluxo)',
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
        cpf: '60421079096',
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
