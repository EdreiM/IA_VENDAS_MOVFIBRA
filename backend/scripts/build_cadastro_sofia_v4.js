const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');

const ROOT = path.join(__dirname, '..');
const N8N = path.join(ROOT, 'n8n');
const OUT = path.join(N8N, 'cadastro_sofia_v4.json');

const CRED_IXC = { httpBasicAuth: { id: 'oTcpUfNTfpW9r72r', name: 'c0002_ixc_Agente_de_IA_api' } };
const REF = "$('Normalizar Sofia')";
const C = REF + '.item.json';

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

function ifNode(name, pos, left, right = 'sim') {
  return {
    parameters: {
      conditions: {
        options: { caseSensitive: true, leftValue: '', typeValidation: 'strict', version: 2 },
        conditions: [{
          id: nid(),
          leftValue: left,
          rightValue: right,
          operator: { type: 'string', operation: 'equals', name: 'filter.operator.equals' },
        }],
        combinator: 'and',
      },
      options: {},
    },
    type: 'n8n-nodes-base.if',
    typeVersion: 2.2,
    position: pos,
    id: nid(),
    name,
  };
}

function setNode(name, pos, assignments) {
  return {
    parameters: { assignments: { assignments }, options: {} },
    type: 'n8n-nodes-base.set',
    typeVersion: 3.4,
    position: pos,
    id: nid(),
    name,
  };
}

function sticky(content, pos, w, h, color = 1) {
  return {
    parameters: { content, height: h, width: w, color },
    type: 'n8n-nodes-base.stickyNote',
    position: pos,
    typeVersion: 1,
    id: nid(),
    name: 'Note',
  };
}

const trigger = {
  parameters: {
    workflowInputs: {
      values: [
        'id_cliente', 'nome', 'cpf', 'email', 'telefone', 'data_nascimento', 'rg',
        'cep', 'rua', 'numero', 'bairro', 'cidade', 'complemento', 'plano_confirmado',
        'plano_confirmado_id', 'conversation_id', 'contact_id', 'ixc_cliente_id',
        'caixa_fibra', 'localizacao_fixa', 'data_vencimento_pref', 'data_hora_agendamento',
      ].map((name) => ({ name })),
    },
  },
  type: 'n8n-nodes-base.executeWorkflowTrigger',
  typeVersion: 1.1,
  position: [-3648, 0],
  id: nid(),
  name: 'Trigger Sofia',
};

const normalizar = codeNode('Normalizar Sofia', [-3400, 0], 'normalizar_cadastro_sofia.js');
const respostaOk = codeNode('Resposta Sofia', [2100, -64], 'resposta_cadastro_sofia.js');
const ifCadastrado = ifNode('If cadastrado?', [-3040, 0], `={{ ${REF}.item.json.cadastrado }}`);

const clienteIxcId = codeNode('Cliente IXC ID', [-1408, 0], 'cliente_ixc_id.js');

const respostaErroCliente = setNode('Resposta Erro Cliente', [-1168, 944], [
  { id: nid(), name: 'resultado', value: 'erro', type: 'string' },
  { id: nid(), name: 'motivo', value: "={{ 'Erro cadastro cliente: ' + ($('cadastro_cliente').item.json.message || 'desconhecido') }}", type: 'string' },
  { id: nid(), name: 'erro', value: true, type: 'boolean' },
]);

const respostaErroContrato = setNode('Resposta Erro Contrato', [-1248, 208], [
  { id: nid(), name: 'resultado', value: 'erro', type: 'string' },
  { id: nid(), name: 'motivo', value: "={{ 'Erro cadastro contrato: ' + ($json.message || 'desconhecido') }}", type: 'string' },
  { id: nid(), name: 'erro', value: true, type: 'boolean' },
]);

const respostaErroLogin = setNode('Resposta Erro Login', [416, 416], [
  { id: nid(), name: 'resultado', value: 'erro', type: 'string' },
  { id: nid(), name: 'motivo', value: "={{ 'Erro cadastro login: ' + ($json.message || 'desconhecido') }}", type: 'string' },
  { id: nid(), name: 'erro', value: true, type: 'boolean' },
]);

const respostaErroOs = setNode('Resposta Erro OS', [1184, 144], [
  { id: nid(), name: 'resultado', value: 'erro', type: 'string' },
  { id: nid(), name: 'motivo', value: "={{ 'Erro abertura OS: ' + ($json.message || 'desconhecido') }}", type: 'string' },
  { id: nid(), name: 'erro', value: true, type: 'boolean' },
]);

const coletaCidadeCli = {
  parameters: {
    url: 'https://ixc.mov.pro.br/webservice/v1/cidade',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpBasicAuth',
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'ixcsoft', value: 'listar' }] },
    sendBody: true,
    bodyParameters: {
      parameters: [
        { name: 'qtype', value: 'nome' },
        { name: 'query', value: `={{ ${C}.cidade }}` },
        { name: 'oper', value: '==' },
      ],
    },
    options: { response: { response: { responseFormat: 'json' } } },
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [-2336, 544],
  id: nid(),
  name: 'Coleta_id_cidade',
  credentials: CRED_IXC,
};

const idCidade = setNode('Id_cidade', [-2096, 544], [
  { id: nid(), name: 'id_cidade', value: '={{ $json.registros[0].id }}', type: 'string' },
]);

const cadastroCliente = {
  parameters: {
    method: 'POST',
    url: 'https://ixc.mov.pro.br/webservice/v1/cliente',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpBasicAuth',
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'ixcsoft', value: 'incluir' }] },
    sendBody: true,
    bodyParameters: {
      parameters: [
        { name: 'ativo', value: 'S' },
        { name: 'id_tipo_cliente', value: '19' },
        { name: 'tipo_cliente_scm', value: '03' },
        { name: 'tipo_pessoa', value: 'F' },
        { name: 'razao', value: `={{ ${C}.nome }}` },
        { name: 'cnpj_cpf', value: `={{ (() => { const v = ${C}.cpf_cnpj?.toString().replace(/\\D/g,''); if(!v)return''; if(v.length===11)return v.replace(/(\\d{3})(\\d{3})(\\d{3})(\\d{2})/,'$1.$2.$3-$4'); if(v.length===14)return v.replace(/(\\d{2})(\\d{3})(\\d{3})(\\d{4})(\\d{2})/,'$1.$2.$3/$4-$5'); return v; })() }}` },
        { name: 'contribuinte_icms', value: 'N' },
        { name: 'data_nascimento', value: `={{ ${C}.data_nascimento }}` },
        { name: 'tipo_assinante', value: '3' },
        { name: 'filial_id', value: '3' },
        { name: 'cep', value: `={{ (${C}.cep||'').replace(/\\D/g,'').replace(/^(\\d{5})(\\d{3})$/,'$1-$2')||'01010-100' }}` },
        { name: 'endereco', value: `={{ (${C}.rua||'').trim()||'rua projetada' }}` },
        { name: 'numero', value: `={{ (${C}.numero_endereco||'').trim()||'555' }}` },
        { name: 'bairro', value: `={{ ${C}.bairro }}` },
        { name: 'cidade', value: "={{ $('Id_cidade').item.json.id_cidade }}" },
        { name: 'complemento', value: `={{ ${C}.complemento || 'Sem complemento' }}` },
        { name: 'tipo_localidade', value: 'U' },
        { name: 'telefone_celular', value: `={{ ${C}.telefone }}` },
        { name: 'whatsapp', value: `={{ ${C}.telefone }}` },
        { name: 'email', value: `={{ ${C}.email }}` },
        { name: 'senha', value: 'movbrasil' },
        { name: 'hotsite_acesso', value: '2' },
        { name: 'crm', value: 'N' },
        { name: 'id_vendedor', value: '308' },
        { name: 'iss_classificacao_padrao', value: '99' },
        { name: 'desconto_irrf_valor_inferior', value: 'S' },
        { name: 'hotsite_email', value: `={{ ${C}.cpf_cnpj.replace(/\\D/g, '') }}` },
        { name: 'fantasia', value: `={{ ${C}.nome }}` },
        { name: 'cob_envia_email', value: 'S' },
        { name: 'cob_envia_sms', value: 'N' },
        { name: 'ie_identidade', value: `={{ ${C}.rg_cliente }}` },
        { name: 'id_conta', value: '70302' },
        { name: 'id_candato_tipo', value: '53' },
        { name: 'id_campanha', value: '15' },
        { name: 'responsavel', value: '486' },
      ],
    },
    options: { response: { response: { responseFormat: 'json' } } },
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [-1872, 544],
  id: nid(),
  name: 'cadastro_cliente',
  credentials: CRED_IXC,
};

const if3 = ifNode('If3 cliente OK', [-1680, 544], "={{ $('cadastro_cliente').item.json.type }}", 'success');

const coletaCidadeCon = { ...coletaCidadeCli, position: [-2336, -16], id: nid(), name: 'Coleta_id_cidade_cadastra' };

const buscarPlano = {
  parameters: {
    url: 'https://ixc.mov.pro.br/webservice/v1/vd_contratos',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpBasicAuth',
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'ixcsoft', value: 'listar' }] },
    sendBody: true,
    bodyParameters: {
      parameters: [
        { name: 'qtype', value: 'vd_contratos.id' },
        { name: 'query', value: `={{ ${C}.plano_id }}` },
        { name: 'oper', value: '==' },
      ],
    },
    options: { response: { response: { responseFormat: 'json' } } },
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [-2096, -16],
  id: nid(),
  name: 'bucar plano venda',
  credentials: CRED_IXC,
};

const cadastroContrato = {
  parameters: {
    method: 'POST',
    url: 'https://ixc.mov.pro.br/webservice/v1/cliente_contrato',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpBasicAuth',
    sendBody: true,
    bodyParameters: {
      parameters: [
        { name: 'tipo', value: '={{ $json.registros[0].tipo }}' },
        { name: 'id_cliente', value: "={{ $('Cliente IXC ID').item.json.ixc_id_cliente }}" },
        { name: 'id_vd_contrato', value: `={{ ${C}.plano_id }}` },
        { name: 'descricao_aux_plano_venda', value: '={{ $json.registros[0].nome }}' },
        { name: 'contrato', value: '={{ $json.registros[0].nome }}' },
        { name: 'id_tipo_contrato', value: `={{ (() => { const v = Number(${C}.data_vencimento); const m = {5:5,10:75,15:15,20:20}; return m[v]??75; })() }}` },
        { name: 'id_modelo', value: '23' },
        { name: 'id_filial', value: '3' },
        { name: 'data', value: "={{ $now.format('dd/MM/yyyy') }}" },
        { name: 'motivo_inclusao', value: 'I' },
        { name: 'id_tipo_documento', value: '501' },
        { name: 'id_carteira_cobranca', value: '33' },
        { name: 'id_vendedor', value: '308' },
        { name: 'cc_previsao', value: 'P' },
        { name: 'tipo_cobranca', value: 'P' },
        { name: 'renovacao_automatica', value: 'S' },
        { name: 'base_geracao_tipo_doc', value: 'P' },
        { name: 'id_tipo_doc_ativ', value: '501' },
        { name: 'fidelidade', value: '12' },
        { name: 'bloqueio_automatico', value: 'S' },
        { name: 'aviso_atraso', value: 'S' },
        { name: 'endereco_padrao_cliente', value: 'N' },
        { name: 'cep', value: `={{ ${C}.cep.replace(/\\D/g,'').replace(/^(\\d{5})(\\d{3})$/,'$1-$2') }}` },
        { name: 'cep_novo', value: `={{ ${C}.cep.replace(/\\D/g,'').replace(/^(\\d{5})(\\d{3})$/,'$1-$2') }}` },
        { name: 'endereco', value: `={{ ${C}.rua }}` },
        { name: 'endereco_novo', value: `={{ ${C}.rua }}` },
        { name: 'numero', value: `={{ ${C}.numero_endereco }}` },
        { name: 'numero_novo', value: `={{ ${C}.numero_endereco }}` },
        { name: 'bairro', value: `={{ ${C}.bairro }}` },
        { name: 'bairro_novo', value: `={{ ${C}.bairro }}` },
        { name: 'cidade', value: "={{ $('Coleta_id_cidade_cadastra').item.json.registros[0].id }}" },
        { name: 'cidade_novo', value: "={{ $('Coleta_id_cidade_cadastra').item.json.registros[0].id }}" },
        { name: 'complemento', value: `={{ ${C}.complemento || 'Sem complemento' }}` },
        { name: 'complemento_novo', value: `={{ ${C}.complemento || 'Sem complemento' }}` },
        { name: 'latitude', value: `={{ String(${C}.localizacao || '').split(',')[0].trim() }}` },
        { name: 'latitude_novo', value: `={{ String(${C}.localizacao || '').split(',')[0].trim() }}` },
        { name: 'longitude', value: `={{ (String(${C}.localizacao || '').split(',')[1] || '').trim() }}` },
        { name: 'longitude_novo', value: `={{ (String(${C}.localizacao || '').split(',')[1] || '').trim() }}` },
        { name: 'status_internet', value: 'AA' },
        { name: 'id_motivo_inclusao', value: '1' },
        { name: 'data_renovacao', value: "={{ $now.setZone('America/Santarem').plus({ years: 1 }).toFormat('dd/MM/yyyy') }}" },
        { name: 'taxa_instalacao', value: '0.00' },
        { name: 'id_indexador_reajuste', value: '5' },
        { name: 'tipo_doc_opc', value: '429' },
        { name: 'tipo_doc_opc2', value: '420' },
        { name: 'tipo_doc_opc3', value: '428' },
      ],
    },
    options: { response: { response: { responseFormat: 'json' } } },
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [-1856, -16],
  id: nid(),
  name: 'cadastro_contrato',
  credentials: CRED_IXC,
};

const if6 = ifNode('If6 contrato OK', [-1648, -16], '={{ $json.type }}', 'success');

const retornoContrato = setNode('retorno_contrato', [-1408, -32], [
  { id: nid(), name: 'id_contrato', value: '={{ $json.id }}', type: 'string' },
  { id: nid(), name: 'cidade', value: "={{ $('Coleta_id_cidade_cadastra').item.json.registros[0].nome }}", type: 'string' },
  { id: nid(), name: 'cpf', value: `={{ String(${C}.cpf_cnpj||'').replace(/\\D/g,'').padStart(11,'0').slice(-11).replace(/(\\d{3})(\\d{3})(\\d{3})(\\d{2})/,'$1.$2.$3-$4') }}`, type: 'string' },
]);

const criacaoPpoe = {
  parameters: {
    jsCode: `const cidade = String($json.cidade || "");
const cpf = String($json.cpf || "");
const mapa = { santarem:"stm", alenquer:"alq", altamira:"atm", "brasil novo":"bn", medicilandia:"med", uruara:"uru", ruropolis:"rp", itaituba:"itb", "mojui dos campos":"mjc" };
const norm = (t) => String(t).normalize("NFD").replace(/[\\u0300-\\u036f]/g,"").toLowerCase().trim();
const sigla = mapa[norm(cidade)] || "??";
return [{ json: { ...$json, pppoe: cpf.replace(/\\D/g,"") + "_" + sigla } }];`,
  },
  type: 'n8n-nodes-base.code',
  typeVersion: 2,
  position: [-1200, -32],
  id: nid(),
  name: 'Criação_ppoe',
};

const buscarPlanoVelo = {
  parameters: {
    url: 'https://ixc.mov.pro.br/webservice/v1/vd_contratos_produtos',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpBasicAuth',
    sendHeaders: true,
    headerParameters: { parameters: [{ name: 'ixcsoft', value: 'listar' }] },
    sendBody: true,
    bodyParameters: {
      parameters: [
        { name: 'qtype', value: 'id_vd_contrato' },
        { name: 'query', value: "={{ $('bucar plano venda').item.json.registros[0].id }}" },
        { name: 'oper', value: '==' },
      ],
    },
    options: { response: { response: { responseFormat: 'json' } } },
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [-976, -32],
  id: nid(),
  name: 'bucar plano velo',
  credentials: CRED_IXC,
};

const cadastroLogin = {
  parameters: {
    method: 'POST',
    url: 'https://ixc.mov.pro.br/webservice/v1/radusuarios',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpBasicAuth',
    sendBody: true,
    bodyParameters: {
      parameters: [
        { name: 'autenticacao_por_mac', value: 'P' },
        { name: 'relacionar_concentrador_ao_login', value: 'H' },
        { name: 'auto_preencher_ipv6', value: 'H' },
        { name: 'fixar_ipv6', value: 'H' },
        { name: 'relacionar_ipv6_ao_login', value: 'H' },
        { name: 'service_tag_vlan', value: 'N' },
        { name: 'mtu', value: '1500' },
        { name: 'onu_compartilhada', value: 'N' },
        { name: 'tipo_acesso', value: 'http' },
        { name: 'ativo', value: 'S' },
        { name: 'tipo_conexao_mapa', value: 'F' },
        { name: 'id_contrato', value: "={{ $('retorno_contrato').item.json.id_contrato }}" },
        { name: 'id_grupo', value: '=1080' },
        { name: 'id_cliente', value: "={{ $('cadastro_contrato').item.json.atualiza_campos[2].valor }}" },
        { name: 'login', value: "={{ $('Criação_ppoe').item.json.pppoe }}" },
        { name: 'senha', value: "={{ $('retorno_contrato').item.json.cpf.replace(/\\D/g, '') }}" },
        { name: 'auto_preencher_ip', value: 'H' },
        { name: 'auto_preencher_mac', value: 'H' },
        { name: 'endereco', value: `={{ ${C}.rua }}` },
        { name: 'numero', value: `={{ ${C}.numero_endereco }}` },
        { name: 'complemento', value: `={{ ${C}.complemento }}` },
        { name: 'relacionar_ip_ao_login', value: 'H' },
        { name: 'bairro', value: `={{ ${C}.bairro }}` },
        { name: 'relacionar_mac_ao_login', value: 'H' },
        { name: 'latitude', value: `={{ String(${C}.localizacao || '').split(',')[0].trim() }}` },
        { name: 'longitude', value: `={{ (String(${C}.localizacao || '').split(',')[1] || '').trim() }}` },
        { name: 'autenticacao', value: 'L' },
        { name: 'login_simultaneo', value: '1' },
        { name: 'senha_md5', value: 'N' },
        { name: 'fixar_ip', value: 'H' },
        { name: 'porta_http', value: '80' },
        { name: 'cliente_tem_a_senha', value: 'N' },
        { name: 'tipo_vinculo_plano', value: 'D' },
        { name: 'cidade', value: "={{ $('Coleta_id_cidade_cadastra').item.json.registros[0].id }}" },
        { name: 'cep', value: `={{ ${C}.cep.replace(/\\D/g, '').replace(/^(\\d{5})(\\d{3})$/,'$1-$2') }}` },
        { name: 'referencia', value: `={{ ${C}.complemento }}` },
        { name: 'endereco_padrao_cliente', value: 'N' },
        { name: 'id_filial', value: '3' },
        { name: 'senha_router1', value: 'movt3l3c0m' },
        { name: 'senha_router2', value: 'movt3l3c0m' },
        { name: 'porta_router2', value: '1978' },
      ],
    },
    options: { response: { response: { responseFormat: 'json' } } },
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [-672, -32],
  id: nid(),
  name: 'cadastro_login',
  credentials: CRED_IXC,
};

const if1 = ifNode('If1 login OK', [-448, -32], '={{ $json.type }}', 'success');
const if2 = ifNode('If2 login existe?', [-224, 64], '={{ $json.message }}', 'Login já existe!');

const dadoOs = setNode('dado_OS', [496, -48], [
  { id: nid(), name: 'mensagem', value: `=Telefone: {{ ${C}.telefone }}\\nendereço: {{ ${C}.rua }}, {{ ${C}.bairro }}\\nCaixa: {{ ${C}.caixa_fibra }}\\nLocalização: {{ ${C}.localizacao }}`, type: 'string' },
  { id: nid(), name: 'id_login', value: "={{ $('cadastro_login').item.json.id || $json.id}}", type: 'string' },
  { id: nid(), name: 'id_contrato', value: "={{ $('retorno_contrato').item.json.id_contrato }}", type: 'string' },
  { id: nid(), name: 'data_instalacao', value: `={{ ${C}.data_hora_agendamento }}`, type: 'string' },
  { id: nid(), name: 'id_cliente', value: "={{ $('cadastro_login').item.json.atualiza_campos[1].valor }}", type: 'string' },
]);

const osNode = {
  parameters: {
    method: 'POST',
    url: 'https://ixc.mov.pro.br/webservice/v1/su_ticket',
    authentication: 'genericCredentialType',
    genericAuthType: 'httpBasicAuth',
    sendBody: true,
    bodyParameters: {
      parameters: [
        { name: 'tipo', value: 'C' },
        { name: 'id_cliente', value: '={{ $json.id_cliente }}' },
        { name: 'id_login', value: '={{ $json.id_login }}' },
        { name: 'id_contrato', value: '={{ $json.id_contrato }}' },
        { name: 'id_filial', value: '3' },
        { name: 'id_assunto', value: '585' },
        { name: 'titulo', value: 'ATIVAÇÃO DE NOVO CLIENTE' },
        { name: 'origem_endereco', value: 'L' },
        { name: 'id_wfl_processo', value: '106' },
        { name: 'id_ticket_setor', value: '45' },
        { name: 'id_responsavel_tecnico', value: '249' },
        { name: 'data_criacao', value: "={{ $now.format('yyyy-MM-dd') }}" },
        { name: 'id_usuarios', value: '225' },
        { name: 'menssagem', value: '={{ $json.mensagem }}' },
        { name: 'su_status', value: 'N' },
        { name: 'prioridade', value: 'A' },
        { name: 'data_agenda', value: '={{ $json.data_instalacao }}' },
      ],
    },
    options: { response: { response: { responseFormat: 'json' } } },
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.2,
  position: [752, -48],
  id: nid(),
  name: 'OS',
  retryOnFail: true,
  credentials: CRED_IXC,
};

const if5 = ifNode('If5 OS OK', [944, -48], '={{ $json.type }}', 'success');

const ifChatwoot = ifNode(
  'Tem conversation_id?',
  [1700, -64],
  `={{ ${REF}.item.json.conversation_id }}`,
  '',
);
// Override operator to notEquals empty - rebuild ifNode doesn't support, use custom
ifChatwoot.parameters.conditions.conditions[0].operator = {
  type: 'string',
  operation: 'notEquals',
  name: 'filter.operator.notEquals',
};

const chatwoot = {
  parameters: {
    method: 'POST',
    url: `=https://chatwoot.mov.pro.br/api/v1/accounts/2/conversations/{{ ${C}.conversation_id.trim() }}/labels`,
    sendHeaders: true,
    headerParameters: {
      parameters: [
        { name: 'Content-Type', value: 'application/json' },
        { name: 'api_access_token', value: 'ugEufRFeoBACNJNcPVGLZaoD' },
      ],
    },
    sendBody: true,
    specifyBody: 'json',
    jsonBody: '={ "labels": ["contratou", "aguradando_assinatura"] }',
    options: {},
  },
  type: 'n8n-nodes-base.httpRequest',
  typeVersion: 4.4,
  position: [1900, -64],
  id: nid(),
  name: 'Cadastrou chatwoot',
  onError: 'continueRegularOutput',
};

const nodes = [
  trigger, normalizar, ifCadastrado, coletaCidadeCli, idCidade, cadastroCliente, if3, clienteIxcId,
  respostaErroCliente, coletaCidadeCon, buscarPlano, cadastroContrato, if6, retornoContrato,
  respostaErroContrato, criacaoPpoe, buscarPlanoVelo, cadastroLogin, if1, if2, respostaErroLogin,
  dadoOs, osNode, if5, respostaErroOs, ifChatwoot, chatwoot, respostaOk,
  sticky('## CADASTRO SOFIA v4\nSem Postgres', [-3648, -120], 800, 120, 5),
];

const connections = {
  'Trigger Sofia': { main: [[{ node: 'Normalizar Sofia', type: 'main', index: 0 }]] },
  'Normalizar Sofia': { main: [[{ node: 'If cadastrado?', type: 'main', index: 0 }]] },
    'If cadastrado?': {
      main: [
        [{ node: 'Cliente IXC ID', type: 'main', index: 0 }],
        [{ node: 'Coleta_id_cidade', type: 'main', index: 0 }],
      ],
    },
  Coleta_id_cidade: { main: [[{ node: 'Id_cidade', type: 'main', index: 0 }]] },
  Id_cidade: { main: [[{ node: 'cadastro_cliente', type: 'main', index: 0 }]] },
  cadastro_cliente: { main: [[{ node: 'If3 cliente OK', type: 'main', index: 0 }]] },
  'If3 cliente OK': {
    main: [
      [{ node: 'Cliente IXC ID', type: 'main', index: 0 }],
      [{ node: 'Resposta Erro Cliente', type: 'main', index: 0 }],
    ],
  },
  'Cliente IXC ID': { main: [[{ node: 'Coleta_id_cidade_cadastra', type: 'main', index: 0 }]] },
  Coleta_id_cidade_cadastra: { main: [[{ node: 'bucar plano venda', type: 'main', index: 0 }]] },
  'bucar plano venda': { main: [[{ node: 'cadastro_contrato', type: 'main', index: 0 }]] },
  cadastro_contrato: { main: [[{ node: 'If6 contrato OK', type: 'main', index: 0 }]] },
  'If6 contrato OK': {
    main: [
      [{ node: 'retorno_contrato', type: 'main', index: 0 }],
      [{ node: 'Resposta Erro Contrato', type: 'main', index: 0 }],
    ],
  },
  retorno_contrato: { main: [[{ node: 'Criação_ppoe', type: 'main', index: 0 }]] },
  'Criação_ppoe': { main: [[{ node: 'bucar plano velo', type: 'main', index: 0 }]] },
  'bucar plano velo': { main: [[{ node: 'cadastro_login', type: 'main', index: 0 }]] },
  cadastro_login: { main: [[{ node: 'If1 login OK', type: 'main', index: 0 }]] },
  'If1 login OK': {
    main: [
      [{ node: 'dado_OS', type: 'main', index: 0 }],
      [{ node: 'If2 login existe?', type: 'main', index: 0 }],
    ],
  },
  'If2 login existe?': {
    main: [
      [{ node: 'dado_OS', type: 'main', index: 0 }],
      [{ node: 'Resposta Erro Login', type: 'main', index: 0 }],
    ],
  },
  dado_OS: { main: [[{ node: 'OS', type: 'main', index: 0 }]] },
  OS: { main: [[{ node: 'If5 OS OK', type: 'main', index: 0 }]] },
  'If5 OS OK': {
    main: [
      [{ node: 'Tem conversation_id?', type: 'main', index: 0 }],
      [{ node: 'Resposta Erro OS', type: 'main', index: 0 }],
    ],
  },
  'Tem conversation_id?': {
    main: [
      [{ node: 'Cadastrou chatwoot', type: 'main', index: 0 }],
      [{ node: 'Resposta Sofia', type: 'main', index: 0 }],
    ],
  },
  'Cadastrou chatwoot': { main: [[{ node: 'Resposta Sofia', type: 'main', index: 0 }]] },
};

const workflow = {
  name: 'CADASTRO IXC v4 — Sofia (subfluxo)',
  nodes,
  connections,
  meta: { templateCredsSetupCompleted: true },
};

fs.writeFileSync(OUT, JSON.stringify(workflow, null, 2), 'utf8');
console.log('Gerado:', OUT, nodes.length, 'nós');
