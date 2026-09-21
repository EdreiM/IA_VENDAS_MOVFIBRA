#!/usr/bin/env python3
"""Gera n8n/cadastro_sofia_v4.json — subfluxo refatorado (sem Postgres)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
N8N = ROOT / "n8n"
OUT = N8N / "cadastro_sofia_v4.json"

CRED_IXC = {
    "httpBasicAuth": {"id": "oTcpUfNTfpW9r72r", "name": "c0002_ixc_Agente_de_IA_api"}
}

REF = "$('Normalizar Sofia')"
SET_IXC = "$('Set IXC após cliente')"


def nid() -> str:
    return str(uuid.uuid4())


def code_node(name: str, pos: list, js_path: Path) -> dict:
    return {
        "parameters": {"jsCode": js_path.read_text(encoding="utf-8")},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": pos,
        "id": nid(),
        "name": name,
    }


def if_node(name: str, pos: list, left: str, right: str = "sim") -> dict:
    return {
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "strict",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": nid(),
                        "leftValue": left,
                        "rightValue": right,
                        "operator": {
                            "type": "string",
                            "operation": "equals",
                            "name": "filter.operator.equals",
                        },
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
        "position": pos,
        "id": nid(),
        "name": name,
    }


def set_node(name: str, pos: list, assignments: list[dict]) -> dict:
    return {
        "parameters": {"assignments": {"assignments": assignments}, "options": {}},
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "position": pos,
        "id": nid(),
        "name": name,
    }


def sticky(content: str, pos: list, w: int, h: int, color: int = 1) -> dict:
    return {
        "parameters": {"content": content, "height": h, "width": w, "color": color},
        "type": "n8n-nodes-base.stickyNote",
        "position": pos,
        "typeVersion": 1,
        "id": nid(),
        "name": f"Note {content[:20]}",
    }


def main() -> None:
    normalizar = code_node("Normalizar Sofia", [-3400, 0], N8N / "normalizar_cadastro_sofia.js")
    resposta_ok = code_node("Resposta Sofia", [2100, -64], N8N / "resposta_cadastro_sofia.js")

    trigger = {
        "parameters": {
            "workflowInputs": {
                "values": [
                    {"name": "id_cliente"},
                    {"name": "nome"},
                    {"name": "cpf"},
                    {"name": "email"},
                    {"name": "telefone"},
                    {"name": "data_nascimento"},
                    {"name": "rg"},
                    {"name": "cep"},
                    {"name": "rua"},
                    {"name": "numero"},
                    {"name": "bairro"},
                    {"name": "cidade"},
                    {"name": "complemento"},
                    {"name": "plano_confirmado"},
                    {"name": "plano_confirmado_id"},
                    {"name": "conversation_id"},
                    {"name": "contact_id"},
                    {"name": "ixc_cliente_id"},
                    {"name": "caixa_fibra"},
                    {"name": "localizacao_fixa"},
                    {"name": "data_vencimento_pref"},
                    {"name": "data_hora_agendamento"},
                ]
            }
        },
        "type": "n8n-nodes-base.executeWorkflowTrigger",
        "typeVersion": 1.1,
        "position": [-3648, 0],
        "id": nid(),
        "name": "Trigger Sofia",
    }

    if_cadastrado = if_node(
        "If cadastrado?",
        [-3040, 0],
        f"={{{{ {REF}.item.json.cadastrado }}}}",
    )

    set_ixc = set_node(
        "Set IXC após cliente",
        [-1408, 528],
        [
            {
                "id": nid(),
                "name": "ixc_id_cliente",
                "value": "={{ $('cadastro_cliente').item.json.id }}",
                "type": "string",
            },
            {"id": nid(), "name": "cadastrado", "value": "sim", "type": "string"},
        ],
    )

    resposta_erro_cliente = set_node(
        "Resposta Erro Cliente",
        [-1168, 944],
        [
            {
                "id": nid(),
                "name": "resultado",
                "value": "erro",
                "type": "string",
            },
            {
                "id": nid(),
                "name": "motivo",
                "value": "={{ 'Erro cadastro cliente: ' + ($('cadastro_cliente').item.json.message || 'desconhecido') }}",
                "type": "string",
            },
            {"id": nid(), "name": "erro", "value": True, "type": "boolean"},
        ],
    )

    resposta_erro_contrato = set_node(
        "Resposta Erro Contrato",
        [-1248, 208],
        [
            {"id": nid(), "name": "resultado", "value": "erro", "type": "string"},
            {
                "id": nid(),
                "name": "motivo",
                "value": "={{ 'Erro cadastro contrato: ' + ($json.message || 'desconhecido') }}",
                "type": "string",
            },
            {"id": nid(), "name": "erro", "value": True, "type": "boolean"},
        ],
    )

    resposta_erro_login = set_node(
        "Resposta Erro Login",
        [416, 416],
        [
            {"id": nid(), "name": "resultado", "value": "erro", "type": "string"},
            {
                "id": nid(),
                "name": "motivo",
                "value": "={{ 'Erro cadastro login: ' + ($json.message || 'desconhecido') }}",
                "type": "string",
            },
            {"id": nid(), "name": "erro", "value": True, "type": "boolean"},
        ],
    )

    resposta_erro_os = set_node(
        "Resposta Erro OS",
        [1184, 144],
        [
            {"id": nid(), "name": "resultado", "value": "erro", "type": "string"},
            {
                "id": nid(),
                "name": "motivo",
                "value": "={{ 'Erro abertura OS: ' + ($json.message || 'desconhecido') }}",
                "type": "string",
            },
            {"id": nid(), "name": "erro", "value": True, "type": "boolean"},
        ],
    )

    # IXC nodes — referências apontam para Normalizar Sofia
    C = REF + ".item.json"

    coleta_cidade_cli = {
        "parameters": {
            "url": "https://ixc.mov.pro.br/webservice/v1/cidade",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "ixcsoft", "value": "listar"}]},
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "qtype", "value": "nome"},
                    {"name": "query", "value": f"={{{{ {C}.cidade }}}}"},
                    {"name": "oper", "value": "=="},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [-2336, 544],
        "id": nid(),
        "name": "Coleta_id_cidade",
        "credentials": CRED_IXC,
    }

    id_cidade = set_node(
        "Id_cidade",
        [-2096, 544],
        [
            {
                "id": nid(),
                "name": "id_cidade",
                "value": "={{ $json.registros[0].id }}",
                "type": "string",
            }
        ],
    )

    cadastro_cliente = {
        "parameters": {
            "method": "POST",
            "url": "https://ixc.mov.pro.br/webservice/v1/cliente",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "ativo", "value": "S"},
                    {"name": "id_tipo_cliente", "value": "19"},
                    {"name": "tipo_cliente_scm", "value": "03"},
                    {"name": "tipo_pessoa", "value": "F"},
                    {"name": "razao", "value": f"={{{{ {C}.nome }}}}"},
                    {
                        "name": "cnpj_cpf",
                        "value": f"={{{{ \n  (() => {{\n    const valor = {C}.cpf_cnpj?.toString().replace(/\\\\D/g, '');\n    if (!valor) return '';\n    if (valor.length === 11) return valor.replace(/(\\\\d{{3}})(\\\\d{{3}})(\\\\d{{3}})(\\\\d{{2}})/, '$1.$2.$3-$4');\n    if (valor.length === 14) return valor.replace(/(\\\\d{{2}})(\\\\d{{3}})(\\\\d{{3}})(\\\\d{{4}})(\\\\d{{2}})/, '$1.$2.$3/$4-$5');\n    return valor;\n  }})() \n}}}}",
                    },
                    {"name": "contribuinte_icms", "value": "N"},
                    {"name": "data_nascimento", "value": f"={{{{ {C}.data_nascimento }}}}"},
                    {"name": "tipo_assinante", "value": "3"},
                    {"name": "filial_id", "value": "3"},
                    {
                        "name": "cep",
                        "value": f"={{{{ ({C}.cep || '').replace(/\\\\D/g, '').replace(/^(\\\\d{{5}})(\\\\d{{3}})$/, '$1-$2') || '01010-100' }}}}",
                    },
                    {
                        "name": "endereco",
                        "value": f"={{{{ ({C}.rua || '').trim() || 'rua projetada' }}}}",
                    },
                    {
                        "name": "numero",
                        "value": f"={{{{ ({C}.numero_endereco || '').trim() || '555' }}}}",
                    },
                    {"name": "bairro", "value": f"={{{{ {C}.bairro }}}}"},
                    {"name": "cidade", "value": "={{ $('Id_cidade').item.json.id_cidade }}"},
                    {"name": "complemento", "value": f"={{{{ {C}.complemento || 'Sem complemento' }}}}"},
                    {"name": "tipo_localidade", "value": "U"},
                    {
                        "name": "telefone_celular",
                        "value": f"={{{{ {C}.telefone }}}}",
                    },
                    {"name": "whatsapp", "value": f"={{{{ {C}.telefone }}}}"},
                    {"name": "email", "value": f"={{{{ {C}.email }}}}"},
                    {"name": "senha", "value": "movbrasil"},
                    {"name": "hotsite_acesso", "value": "2"},
                    {"name": "crm", "value": "N"},
                    {"name": "id_vendedor", "value": "308"},
                    {"name": "iss_classificacao_padrao", "value": "99"},
                    {"name": "desconto_irrf_valor_inferior", "value": "S"},
                    {
                        "name": "hotsite_email",
                        "value": f"={{{{ {C}.cpf_cnpj.replace(/\\\\D/g, '') }}}}",
                    },
                    {"name": "fantasia", "value": f"={{{{ {C}.nome }}}}"},
                    {"name": "cob_envia_email", "value": "S"},
                    {"name": "cob_envia_sms", "value": "N"},
                    {"name": "ie_identidade", "value": f"={{{{ {C}.rg_cliente }}}}"},
                    {"name": "id_conta", "value": "70302"},
                    {"name": "id_candato_tipo", "value": "53"},
                    {"name": "id_campanha", "value": "15"},
                    {"name": "responsavel", "value": "486"},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [-1872, 544],
        "id": nid(),
        "name": "cadastro_cliente",
        "credentials": CRED_IXC,
    }

    if3 = if_node(
        "If3 cliente OK",
        [-1680, 544],
        "={{ $('cadastro_cliente').item.json.type }}",
        "success",
    )

    coleta_cidade_con = {
        "parameters": {
            "url": "https://ixc.mov.pro.br/webservice/v1/cidade",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "ixcsoft", "value": "listar"}]},
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "qtype", "value": "nome"},
                    {"name": "query", "value": f"={{{{ {C}.cidade }}}}"},
                    {"name": "oper", "value": "=="},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [-2336, -16],
        "id": nid(),
        "name": "Coleta_id_cidade_cadastra",
        "credentials": CRED_IXC,
    }

    buscar_plano = {
        "parameters": {
            "url": "https://ixc.mov.pro.br/webservice/v1/vd_contratos",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "ixcsoft", "value": "listar"}]},
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "qtype", "value": "vd_contratos.id"},
                    {"name": "query", "value": f"={{{{ {C}.plano_id }}}}"},
                    {"name": "oper", "value": "=="},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [-2096, -16],
        "id": nid(),
        "name": "bucar plano venda",
        "credentials": CRED_IXC,
    }

    cadastro_contrato = {
        "parameters": {
            "method": "POST",
            "url": "https://ixc.mov.pro.br/webservice/v1/cliente_contrato",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "tipo", "value": "={{ $json.registros[0].tipo }}"},
                    {
                        "name": "id_cliente",
                        "value": f"={{{{ {SET_IXC}.item.json.ixc_id_cliente || {REF}.item.json.ixc_id_cliente }}}}",
                    },
                    {"name": "id_vd_contrato", "value": f"={{{{ {C}.plano_id }}}}"},
                    {"name": "descricao_aux_plano_venda", "value": "={{ $json.registros[0].nome }}"},
                    {"name": "contrato", "value": "={{ $json.registros[0].nome }}"},
                    {
                        "name": "id_tipo_contrato",
                        "value": f"={{{{ \n  (() => {{\n    const v = Number({C}.data_vencimento);\n    const mapa = {{ 5: 5, 10: 75, 15: 15, 20: 20 }};\n    return mapa[v] ?? 75;\n  }})() \n}}}}",
                    },
                    {"name": "id_modelo", "value": "23"},
                    {"name": "id_filial", "value": "3"},
                    {"name": "data", "value": "={{ $now.format('dd/MM/yyyy') }}"},
                    {"name": "motivo_inclusao", "value": "I"},
                    {"name": "id_tipo_documento", "value": "501"},
                    {"name": "id_carteira_cobranca", "value": "33"},
                    {"name": "id_vendedor", "value": "308"},
                    {"name": "cc_previsao", "value": "P"},
                    {"name": "tipo_cobranca", "value": "P"},
                    {"name": "renovacao_automatica", "value": "S"},
                    {"name": "base_geracao_tipo_doc", "value": "P"},
                    {"name": "id_tipo_doc_ativ", "value": "501"},
                    {"name": "fidelidade", "value": "12"},
                    {"name": "bloqueio_automatico", "value": "S"},
                    {"name": "aviso_atraso", "value": "S"},
                    {"name": "endereco_padrao_cliente", "value": "N"},
                    {
                        "name": "cep",
                        "value": f"={{{{ {C}.cep.replace(/\\\\D/g, '').replace(/^(\\\\d{{5}})(\\\\d{{3}})$/, '$1-$2') }}}}",
                    },
                    {"name": "endereco", "value": f"={{{{ {C}.rua }}}}"},
                    {"name": "numero", "value": f"={{{{ {C}.numero_endereco }}}}"},
                    {"name": "bairro", "value": f"={{{{ {C}.bairro }}}}"},
                    {
                        "name": "cidade",
                        "value": "={{ $('Coleta_id_cidade_cadastra').item.json.registros[0].id }}",
                    },
                    {"name": "complemento", "value": f"={{{{ {C}.complemento || 'Sem complemento' }}}}"},
                    {
                        "name": "latitude",
                        "value": f"={{{{ String({C}.localizacao || '').split(',')[0].trim() }}}}",
                    },
                    {
                        "name": "longitude",
                        "value": f"={{{{ (String({C}.localizacao || '').split(',')[1] || '').trim() }}}}",
                    },
                    {"name": "status_internet", "value": "AA"},
                    {"name": "id_motivo_inclusao", "value": "1"},
                    {
                        "name": "data_renovacao",
                        "value": "={{ $now.setZone('America/Santarem').plus({ years: 1 }).toFormat('dd/MM/yyyy') }}",
                    },
                    {"name": "taxa_instalacao", "value": "0.00"},
                    {"name": "id_indexador_reajuste", "value": "5"},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [-1856, -16],
        "id": nid(),
        "name": "cadastro_contrato",
        "credentials": CRED_IXC,
    }

    if6 = if_node("If6 contrato OK", [-1648, -16], "={{ $json.type }}", "success")

    retorno_contrato = set_node(
        "retorno_contrato",
        [-1408, -32],
        [
            {"id": nid(), "name": "id_contrato", "value": "={{ $json.id }}", "type": "string"},
            {"id": nid(), "name": "contrato_cadastrado", "value": "Sim", "type": "string"},
            {
                "id": nid(),
                "name": "cidade",
                "value": "={{ $('Coleta_id_cidade_cadastra').item.json.registros[0].nome }}",
                "type": "string",
            },
            {
                "id": nid(),
                "name": "cpf",
                "value": f"={{{{ String({C}.cpf_cnpj || '').replace(/\\\\D/g,'').padStart(11,'0').slice(-11).replace(/(\\\\d{{3}})(\\\\d{{3}})(\\\\d{{3}})(\\\\d{{2}})/,'$1.$2.$3-$4') }}}}",
                "type": "string",
            },
            {
                "id": nid(),
                "name": "id_cliente",
                "value": "={{ $json.atualiza_campos[2].valor }}",
                "type": "string",
            },
        ],
    )

    criacao_ppoe = {
        "parameters": {
            "jsCode": """const cidade = String($json.cidade || "");
const cpf = String($json.cpf || "");
const mapaCidades = {
  "santarem": "stm", "alenquer": "alq", "altamira": "atm", "brasil novo": "bn",
  "medicilandia": "med", "uruara": "uru", "ruropolis": "rp", "itaituba": "itb", "mojui dos campos": "mjc"
};
function normalizarTexto(texto) {
  return String(texto).normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase().trim().replace(/\\s+/g, " ");
}
const sigla = mapaCidades[normalizarTexto(cidade)] || "??";
const cpfNumerico = cpf.replace(/\\D/g, "");
return [{ json: { ...$json, pppoe: `${cpfNumerico}_${sigla}` } }];"""
        },
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [-1200, -32],
        "id": nid(),
        "name": "Criação_ppoe",
    }

    buscar_plano_velo = {
        "parameters": {
            "url": "https://ixc.mov.pro.br/webservice/v1/vd_contratos_produtos",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "ixcsoft", "value": "listar"}]},
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "qtype", "value": "id_vd_contrato"},
                    {"name": "query", "value": "={{ $('bucar plano venda').item.json.registros[0].id }}"},
                    {"name": "oper", "value": "=="},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [-976, -32],
        "id": nid(),
        "name": "bucar plano velo",
        "credentials": CRED_IXC,
    }

    cadastro_login = {
        "parameters": {
            "method": "POST",
            "url": "https://ixc.mov.pro.br/webservice/v1/radusuarios",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "ativo", "value": "S"},
                    {"name": "id_contrato", "value": "={{ $('retorno_contrato').item.json.id_contrato }}"},
                    {"name": "id_grupo", "value": "=1080"},
                    {
                        "name": "id_cliente",
                        "value": "={{ $('cadastro_contrato').item.json.atualiza_campos[2].valor }}",
                    },
                    {"name": "login", "value": "={{ $('Criação_ppoe').item.json.pppoe }}"},
                    {
                        "name": "senha",
                        "value": "={{ $('retorno_contrato').item.json.cpf.replace(/\\D/g, '') }}",
                    },
                    {"name": "endereco", "value": f"={{{{ {C}.rua }}}}"},
                    {"name": "numero", "value": f"={{{{ {C}.numero_endereco }}}}"},
                    {"name": "bairro", "value": f"={{{{ {C}.bairro }}}}"},
                    {
                        "name": "cidade",
                        "value": "={{ $('Coleta_id_cidade_cadastra').item.json.registros[0].id }}",
                    },
                    {
                        "name": "cep",
                        "value": f"={{{{ {C}.cep.replace(/\\\\D/g, '').replace(/^(\\\\d{{5}})(\\\\d{{3}})$/, '$1-$2') }}}}",
                    },
                    {
                        "name": "latitude",
                        "value": f"={{{{ String({C}.localizacao || '').split(',')[0].trim() }}}}",
                    },
                    {
                        "name": "longitude",
                        "value": f"={{{{ (String({C}.localizacao || '').split(',')[1] || '').trim() }}}}",
                    },
                    {"name": "autenticacao", "value": "L"},
                    {"name": "id_filial", "value": "3"},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [-672, -32],
        "id": nid(),
        "name": "cadastro_login",
        "credentials": CRED_IXC,
    }

    if1 = if_node("If1 login OK", [-448, -32], "={{ $json.type }}", "success")
    if2 = if_node(
        "If2 login existe?",
        [-224, 64],
        "={{ $json.message }}",
        "Login já existe!",
    )

    dado_os = set_node(
        "dado_OS",
        [496, -48],
        [
            {
                "id": nid(),
                "name": "mensagem",
                "value": f"=Telefone: {{{{ {C}.telefone }}}}\nendereço: {{{{ {C}.rua }}}}, {{{{ {C}.bairro }}}}, {{{{ {C}.numero_endereco }}}}, {{{{ {C}.complemento }}}}\nDisponibilidade: {{{{ {C}.data_hora_agendamento }}}}\nCaixa: {{{{ {C}.caixa_fibra }}}}\nLocalização: {{{{ {C}.localizacao }}}}\nTaxa de Instalação: Gratuita",
                "type": "string",
            },
            {
                "id": nid(),
                "name": "id_login",
                "value": "={{ $('cadastro_login').item.json.id || $json.id}}",
                "type": "string",
            },
            {
                "id": nid(),
                "name": "id_contrato",
                "value": "={{ $('retorno_contrato').item.json.id_contrato }}",
                "type": "string",
            },
            {
                "id": nid(),
                "name": "data_instalacao",
                "value": f"={{{{ {C}.data_hora_agendamento }}}}",
                "type": "string",
            },
            {
                "id": nid(),
                "name": "id_cliente",
                "value": "={{ $('cadastro_login').item.json.atualiza_campos[1].valor }}",
                "type": "string",
            },
        ],
    )

    os_node = {
        "parameters": {
            "method": "POST",
            "url": "https://ixc.mov.pro.br/webservice/v1/su_ticket",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpBasicAuth",
            "sendBody": True,
            "bodyParameters": {
                "parameters": [
                    {"name": "tipo", "value": "C"},
                    {"name": "id_cliente", "value": "={{ $json.id_cliente }}"},
                    {"name": "id_login", "value": "={{ $json.id_login }}"},
                    {"name": "id_contrato", "value": "={{ $json.id_contrato }}"},
                    {"name": "id_filial", "value": "3"},
                    {"name": "id_assunto", "value": "585"},
                    {"name": "titulo", "value": "ATIVAÇÃO DE NOVO CLIENTE"},
                    {"name": "id_wfl_processo", "value": "106"},
                    {"name": "id_ticket_setor", "value": "45"},
                    {"name": "id_responsavel_tecnico", "value": "249"},
                    {"name": "data_criacao", "value": "={{ $now.format('yyyy-MM-dd') }}"},
                    {"name": "id_usuarios", "value": "225"},
                    {"name": "menssagem", "value": "={{ $json.mensagem }}"},
                    {"name": "su_status", "value": "N"},
                    {"name": "prioridade", "value": "A"},
                    {"name": "data_agenda", "value": "={{ $json.data_instalacao }}"},
                ]
            },
            "options": {"response": {"response": {"responseFormat": "json"}}},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [752, -48],
        "id": nid(),
        "name": "OS",
        "retryOnFail": True,
        "credentials": CRED_IXC,
    }

    if5 = if_node("If5 OS OK", [944, -48], "={{ $json.type }}", "success")

    chatwoot = {
        "parameters": {
            "method": "POST",
            "url": f"=https://chatwoot.mov.pro.br/api/v1/accounts/2/conversations/{{{{ {C}.conversation_id.trim() }}}}/labels",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "Content-Type", "value": "application/json"},
                    {"name": "api_access_token", "value": "ugEufRFeoBACNJNcPVGLZaoD"},
                ]
            },
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": '={ "labels": ["contratou", "aguradando_assinatura"] }',
            "options": {},
        },
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.4,
        "position": [1900, -64],
        "id": nid(),
        "name": "Cadastrou chatwoot",
    }

    nodes = [
        trigger,
        normalizar,
        if_cadastrado,
        coleta_cidade_cli,
        id_cidade,
        cadastro_cliente,
        if3,
        set_ixc,
        resposta_erro_cliente,
        coleta_cidade_con,
        buscar_plano,
        cadastro_contrato,
        if6,
        retorno_contrato,
        resposta_erro_contrato,
        criacao_ppoe,
        buscar_plano_velo,
        cadastro_login,
        if1,
        if2,
        resposta_erro_login,
        dado_os,
        os_node,
        if5,
        resposta_erro_os,
        chatwoot,
        resposta_ok,
        sticky("## CADASTRO SOFIA v4\nSem Postgres — dados do webhook", [-3648, -120], 800, 120, 5),
        sticky("## CADASTRA CLIENTE", [-2352, 448], 1268, 240),
        sticky("## CADASTRAR CONTRATO", [-2384, -80], 1320, 240, 3),
        sticky("## LOGIN + OS", [-736, -144], 1424, 464, 4),
    ]

    connections = {
        "Trigger Sofia": {"main": [[{"node": "Normalizar Sofia", "type": "main", "index": 0}]]},
        "Normalizar Sofia": {"main": [[{"node": "If cadastrado?", "type": "main", "index": 0}]]},
        "If cadastrado?": {
            "main": [
                [{"node": "Coleta_id_cidade_cadastra", "type": "main", "index": 0}],
                [{"node": "Coleta_id_cidade", "type": "main", "index": 0}],
            ]
        },
        "Coleta_id_cidade": {"main": [[{"node": "Id_cidade", "type": "main", "index": 0}]]},
        "Id_cidade": {"main": [[{"node": "cadastro_cliente", "type": "main", "index": 0}]]},
        "cadastro_cliente": {"main": [[{"node": "If3 cliente OK", "type": "main", "index": 0}]]},
        "If3 cliente OK": {
            "main": [
                [{"node": "Set IXC após cliente", "type": "main", "index": 0}],
                [{"node": "Resposta Erro Cliente", "type": "main", "index": 0}],
            ]
        },
        "Set IXC após cliente": {
            "main": [[{"node": "Coleta_id_cidade_cadastra", "type": "main", "index": 0}]]
        },
        "Coleta_id_cidade_cadastra": {
            "main": [[{"node": "bucar plano venda", "type": "main", "index": 0}]]
        },
        "bucar plano venda": {"main": [[{"node": "cadastro_contrato", "type": "main", "index": 0}]]},
        "cadastro_contrato": {"main": [[{"node": "If6 contrato OK", "type": "main", "index": 0}]]},
        "If6 contrato OK": {
            "main": [
                [{"node": "retorno_contrato", "type": "main", "index": 0}],
                [{"node": "Resposta Erro Contrato", "type": "main", "index": 0}],
            ]
        },
        "retorno_contrato": {"main": [[{"node": "Criação_ppoe", "type": "main", "index": 0}]]},
        "Criação_ppoe": {"main": [[{"node": "bucar plano velo", "type": "main", "index": 0}]]},
        "bucar plano velo": {"main": [[{"node": "cadastro_login", "type": "main", "index": 0}]]},
        "cadastro_login": {"main": [[{"node": "If1 login OK", "type": "main", "index": 0}]]},
        "If1 login OK": {
            "main": [
                [{"node": "dado_OS", "type": "main", "index": 0}],
                [{"node": "If2 login existe?", "type": "main", "index": 0}],
            ]
        },
        "If2 login existe?": {
            "main": [
                [{"node": "dado_OS", "type": "main", "index": 0}],
                [{"node": "Resposta Erro Login", "type": "main", "index": 0}],
            ]
        },
        "dado_OS": {"main": [[{"node": "OS", "type": "main", "index": 0}]]},
        "OS": {"main": [[{"node": "If5 OS OK", "type": "main", "index": 0}]]},
        "If5 OS OK": {
            "main": [
                [{"node": "Cadastrou chatwoot", "type": "main", "index": 0}],
                [{"node": "Resposta Erro OS", "type": "main", "index": 0}],
            ]
        },
        "Cadastrou chatwoot": {"main": [[{"node": "Resposta Sofia", "type": "main", "index": 0}]]},
    }

    workflow = {
        "name": "CADASTRO IXC v4 — Sofia (subfluxo)",
        "nodes": nodes,
        "connections": connections,
        "meta": {"templateCredsSetupCompleted": True},
    }

    OUT.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gerado: {OUT} ({len(nodes)} nós)")


if __name__ == "__main__":
    main()
