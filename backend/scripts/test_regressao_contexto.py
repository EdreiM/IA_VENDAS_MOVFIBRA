# -*- coding: utf-8 -*-
"""Regressão — bugs de contexto (dado+pergunta, confirmação, fases protegidas)."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.config import get_settings

get_settings.cache_clear()

from app.contexto_conversa import enriquecer_pergunta
from app.models import Evento
from app.parser import (
    eh_aceite_termos_explicito,
    eh_confirmacao,
    eh_pedido_lista_completa_planos,
    eh_pergunta_cobertura_informativa,
    eh_pergunta_mudanca_endereco,
    parse_interpretacao,
    tem_duvida_informativa,
)
from app.plans import resolver_plano
from app.response import gerar_resposta
from app.resolver import resolver
from app.state_machine import decidir
from app.pipeline import _executar_acao


def _raw(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _turno(estado: dict, msg: str, llm: dict) -> tuple[dict, object]:
    interp = parse_interpretacao(_raw(llm), msg, estado)
    ctx = enriquecer_pergunta(
        msg,
        pergunta=interp.pergunta or msg,
        historico=[],
        plano_nome="MOV ONE+",
        ultimo_topico=str(estado.get("ultimo_topico") or "") or None,
    )
    if ctx.get("pergunta"):
        interp.pergunta = str(ctx["pergunta"])
    res = resolver(estado, interp)
    res["mensagem"] = msg
    res["pergunta"] = interp.pergunta
    res["topico_contexto"] = ctx.get("topico")
    res["pergunta_original"] = msg
    dec = decidir(estado, res)
    for _ in range(5):
        if dec.acao in {"RESPONDER", "TRANSFERIR_HUMANO", "AGUARDAR"}:
            break
        for k, v in (dec.atualizar_dados or {}).items():
            if k not in {"limpar_desvio", "resetar_cobertura"} and v is not None:
                estado[k] = v
        dec = _executar_acao(estado, dec)
    estado["fase"] = dec.fase
    estado["aguardando"] = dec.aguardando
    for k, v in (dec.atualizar_dados or {}).items():
        if k not in {"limpar_desvio", "resetar_cobertura"} and v is not None:
            estado[k] = v
    return estado, dec


def test_confirmacoes_typo() -> None:
    assert eh_confirmacao("sim]")
    assert eh_confirmacao("sim!")
    assert eh_confirmacao("confirmo.")
    raw = _raw({"eventos": [], "dados": {}, "confianca": 0.9})
    i = parse_interpretacao(raw, "sim]", {"fase": "vendas", "aguardando": "confirmacao_plano"})
    _assert(Evento.CONFIRMACAO.value in i.eventos, "sim] → CONFIRMACAO")


def test_cadastro_telefone_mais_pergunta() -> None:
    msg = "93992219098 mas quanto tempo demora a instalacao?"
    raw = _raw({"eventos": ["DADO_INFORMADO"], "dados": {"telefone": "93992219098"}, "confianca": 0.9})
    estado = {
        "fase": "cadastro",
        "aguardando": "telefone",
        "plano_confirmado": "MOV ONE+",
        "nome": "Ana Silva",
        "cpf": "60421079096",
        "documento_cpf_validado": True,
        "email": "ana@test.com",
    }
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PERGUNTA.value in i.eventos, "telefone+instalação → PERGUNTA")
    _assert(i.dados.telefone == "93992219098", "telefone extraído")
    estado, dec = _turno(estado, msg, {"eventos": ["DADO_INFORMADO"], "dados": {"telefone": "93992219098"}})
    _assert(dec.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR", dec.objetivo_resposta)
    _assert(dec.aguardando == "data_nascimento", f"aguardando={dec.aguardando}")


def test_data_nascimento_nao_preenche_rua_nem_numero() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "data_nascimento",
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "email": "edreiteste@gmail.com",
        "telefone": "93992219098",
        "cep": "68020000",
        "plano_confirmado": "MOV ONE+",
        "documento_cpf_validado": True,
    }
    msg = "16/08/2000"
    raw = _raw(
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {
                "data_nascimento": "16/08/2000",
                "rua": "Edrei testes",
                "numero": "16",
            },
            "confianca": 0.8,
        }
    )
    interp = parse_interpretacao(raw, msg, estado)
    _assert(interp.dados.data_nascimento == "16/08/2000", interp.dados)
    _assert(not interp.dados.rua, f"rua indevida={interp.dados.rua}")
    _assert(not interp.dados.numero, f"numero indevido={interp.dados.numero}")

    _, dec = _turno(estado, msg, {"eventos": ["DADO_INFORMADO"], "dados": interp.dados.model_dump()})
    _assert(dec.aguardando == "rua", f"aguardando={dec.aguardando} acao={dec.acao}")


def test_cadastro_instalacao_gratis() -> None:
    from app.response import gerar_resposta

    estado = {
        "fase": "cadastro",
        "aguardando": "data_nascimento",
        "plano_confirmado": "MOV ONE+",
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "email": "edreiteste@gmail.com",
        "telefone": "93992219098",
        "documento_cpf_validado": True,
    }
    msg = "A instalação é grátis?"
    _, dec = _turno(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "pergunta": msg, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR", dec.objetivo_resposta)
    txt = gerar_resposta(dec, estado)
    _assert("grátis" in txt.casefold() or "gratuita" in txt.casefold(), txt)
    _assert("sobre *hoje*" not in txt.casefold() and "sobre hoje" not in txt.casefold(), txt)
    _assert("data de nascimento" in txt.casefold(), txt)


def test_vendas_instalacao_hoje() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao": "MOV SUPER+",
        "plano_em_negociacao_id": 1,
        "ultimo_topico": "instalacao",
    }
    msg = "Mas hoje?"
    estado2, dec = _turno(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "pergunta": msg, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR", dec.objetivo_resposta)
    _assert(dec.aguardando == "confirmacao_plano", f"aguardando={dec.aguardando}")

    msg2 = "Vocês conseguem instalar h?"
    estado3, dec2 = _turno(
        {**estado, "ultimo_topico": None},
        msg2,
        {"eventos": ["PERGUNTA"], "pergunta": msg2, "confianca": 0.9},
    )
    _assert(dec2.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR", dec2.objetivo_resposta)


def test_cadastro_cep_mais_pergunta() -> None:
    msg = "68010-010 e se nao tiver cobertura no predio?"
    raw = _raw({"eventos": ["PEDIU_TROCAR_LOCALIZACAO", "DADO_INFORMADO"], "dados": {"cep": "68010010"}, "confianca": 0.8})
    estado = {"fase": "cadastro", "aguardando": "cep", "plano_confirmado": "MOV ONE+", "cidade": "Santarem", "bairro": "Diamantino"}
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PEDIU_TROCAR_LOCALIZACAO.value not in i.eventos, "cep+cobertura ≠ troca loc")
    _assert(Evento.PERGUNTA.value in i.eventos, "cep+cobertura → PERGUNTA")
    _assert(eh_pergunta_cobertura_informativa(msg), "cobertura informativa")


def test_agendamento_sim_mais_duvida() -> None:
    msg = "sim] mas posso remarcar depois?"
    raw = _raw({"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9})
    estado = {
        "fase": "agendamento",
        "aguardando": "confirmacao_horario",
        "horario_escolhido": "8h às 9h",
        "data_agendamento": "01/09/2026",
    }
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.CONFIRMACAO.value in i.eventos, "sim]+duvida → CONFIRMACAO")
    _assert(Evento.PERGUNTA.value in i.eventos, "sim]+duvida → PERGUNTA")
    estado, dec = _turno(estado, msg, {"eventos": ["CONFIRMACAO"], "dados": {}})
    _assert(dec.objetivo_resposta == "CONFIRMAR_HORARIO_E_RESPONDER_PERGUNTA", dec.objetivo_resposta)


def test_confirmacao_dados_mais_duvida() -> None:
    msg = "sim mas qual a multa de cancelamento?"
    raw = _raw({"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9})
    estado = {"fase": "cadastro", "aguardando": "confirmacao_dados", "nome": "Ana", "plano_confirmado": "MOV ONE+"}
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.CONFIRMACAO.value in i.eventos, "confirma+multa → CONFIRMACAO")
    _assert(Evento.PERGUNTA.value in i.eventos, "confirma+multa → PERGUNTA")
    estado, dec = _turno(estado, msg, {"eventos": ["CONFIRMACAO"], "dados": {}})
    _assert(dec.objetivo_resposta == "CONFIRMAR_DADOS_E_RESPONDER_PERGUNTA", dec.objetivo_resposta)
    _assert(dec.fase == "cadastro", dec.fase)


def test_cadastro_cpf_mais_pergunta() -> None:
    msg = "60421079096 mas qual a multa de cancelamento?"
    raw = _raw({"eventos": ["DADO_INFORMADO"], "dados": {"cpf": "60421079096"}, "confianca": 0.9})
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "plano_confirmado": "MOV ONE+",
        "nome": "Ana Silva",
    }
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PERGUNTA.value in i.eventos, "cpf+multa → PERGUNTA")
    estado, dec = _turno(
        estado,
        msg,
        {"eventos": ["DADO_INFORMADO"], "dados": {"cpf": "60421079096"}},
    )
    _assert(dec.objetivo_resposta == "RESPONDER_PERGUNTA_E_RETOMAR", dec.objetivo_resposta)
    _assert(dec.acao == "RESPONDER", f"acao={dec.acao}")
    _assert(dec.aguardando == "cpf", f"aguardando={dec.aguardando}")


def test_mudanca_endereco_agendamento() -> None:
    msg = "e se eu quiser mudar de endereco depois?"
    raw = _raw({"eventos": ["PEDIU_TROCAR_LOCALIZACAO"], "dados": {}, "confianca": 0.8})
    estado = {"fase": "agendamento", "aguardando": "escolha_horario"}
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PEDIU_TROCAR_LOCALIZACAO.value not in i.eventos, "agendamento ≠ troca loc")
    _assert(eh_pergunta_mudanca_endereco(msg), "mudança endereço detectada")


def test_cadastro_pede_em_pares() -> None:
    from app.cadastro_mensagens import anotar_e_pedir_proximo, confirmar_plano_e_avancar

    abertura = confirmar_plano_e_avancar("MOV SUPER+", "R$ 139,00")
    _assert("nome completo" in abertura and "CPF" in abertura, abertura)

    so_nome = anotar_e_pedir_proximo(
        campos_anotados=["nome"],
        campos_corrigidos=[],
        pendente="cpf",
        estado={"nome": "Edrei Silva"},
    )
    _assert("CPF" in so_nome and "e-mail" not in so_nome.casefold(), so_nome)

    proximo_par = anotar_e_pedir_proximo(
        campos_anotados=["cpf"],
        campos_corrigidos=[],
        pendente="email",
        estado={"nome": "Edrei Silva", "cpf": "60421079096"},
    )
    _assert("e-mail" in proximo_par.casefold() and "telefone" in proximo_par.casefold(), proximo_par)

    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "plano_confirmado": "MOV SUPER+",
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    dec = _decidir_sem_executar(
        estado,
        "Edrei Silva 604.210.790-96",
        {"eventos": ["OUTRO"], "dados": {}, "confianca": 0.4},
    )
    dados = dec.atualizar_dados or {}
    _assert(dec.acao == "VALIDAR_CPF", f"{dec.acao} {dec.objetivo_resposta} {dados}")
    _assert("edrei" in str(dados.get("nome") or "").casefold(), dados.get("nome"))
    cpf = "".join(ch for ch in str(dados.get("cpf") or "") if ch.isdigit())
    _assert(cpf == "60421079096", cpf)
    _assert("rua" not in dados, dados)


def test_imagem_painel_com_conversation_id() -> None:
    from unittest.mock import patch

    from app.imagem_plano import enviar_imagem_plano

    estado = {
        "conversation_id": "3075",
        "plano_em_negociacao_id": "1212",
    }
    plano = {
        "id": 1212,
        "nome": "MOV SUPER+",
        "imagem_url": "/media/planos/plano_1212_test.jpg",
    }

    with patch("app.planos_admin.obter_plano", return_value=plano), patch(
        "app.imagem_plano.enviar_imagem_plano_webhook",
        return_value={
            "resultado": "erro",
            "imagem_enviada": False,
            "motivo": "ECONNREFUSED",
            "erro": True,
        },
    ), patch("app.imagem_plano.get_settings") as mock_settings:
        s = mock_settings.return_value
        s.imagem_plano_provider = "webhook"
        s.chatwoot_api_token = ""
        out = enviar_imagem_plano(estado)

    _assert(out.get("imagem_painel") is True, out)
    _assert(out.get("imagem_url") == "/media/planos/plano_1212_test.jpg", out)


def test_payload_imagem_plano_pronto_chatwoot() -> None:
    from app.imagem_plano_payload import montar_payload_imagem_plano

    estado = {
        "id_cliente": "teste-local",
        "conversation_id": "3075",
        "plano_em_negociacao_id": "1212",
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    plano = {
        "id": 1212,
        "nome": "MOV SUPER+",
        "descricao": "✅ Internet ilimitada 📶\n✅ Repetidor Mesh",
        "imagem_url": "/media/planos/plano_1212_test.jpg",
        "beneficios": "Mesh\nUbook",
    }

    class _Cfg:
        public_base_url = "https://api.teste.mov"

    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.planos_admin.obter_plano", return_value=plano
    ), __import__("unittest.mock", fromlist=["patch"]).patch(
        "app.media_store.get_settings", return_value=_Cfg()
    ):
        p = montar_payload_imagem_plano(estado)

    _assert(p["conversation_id"] == "3075", p)
    _assert(p["imagem_url"] == "https://api.teste.mov/media/planos/plano_1212_test.jpg", p)
    _assert("Internet ilimitada" in p["content"], p["content"])
    _assert(p["imagem_file_name"] == "plano_1212_test.jpg", p)
    _assert(p["chatwoot_attachment_field"] == "attachments[]", p)


def test_termos_webhook_dispara_com_url_configurada() -> None:
    """Com TERMOS_PROVIDER=webhook, nunca simula envio local — POST no n8n."""
    from unittest.mock import MagicMock, patch

    from app.termos import enviar_termos

    estado = {
        "id_cliente": "teste-local",
        "ixc_cliente_id": "83458",
        "id_contrato_ixc": "92405",
        "conversation_id": "2969",
        "nome": "Edrei",
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "resultado": "ok",
        "audio_enviado": True,
        "termo_enviado": True,
        "motivo": "Enviado",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.integrations.termos_webhook.httpx.Client") as mock_client:
        inst = mock_client.return_value.__enter__.return_value
        inst.post.return_value = mock_resp
        with patch("app.termos.get_settings") as mock_settings:
            s = mock_settings.return_value
            s.termos_provider = "webhook"
            s.termos_webhook_url = "https://n8n2.mov.pro.br/webhook/enviar_termos_sofia"
            s.termos_webhook_token = ""
            s.termos_timeout_seconds = 60
            out = enviar_termos(estado)

    _assert(out.get("provider") == "webhook", out)
    _assert(out.get("audio_enviado") is True, out)
    inst.post.assert_called_once()
    args, kwargs = inst.post.call_args
    _assert("enviar_termos_sofia" in args[0], args[0])
    _assert(kwargs["json"].get("conversation_id") == "2969", kwargs["json"])


def test_termos_parcial_n8n_nao_assusta_cliente() -> None:
    """PDF enviado + falso negativo no áudio (bug n8n) → mensagem normal, não 'dificuldade'."""
    from app.state_machine import decidir_resultado_termos
    from app.response import gerar_resposta

    estado = {
        "fase": "cadastro",
        "aguardando": "confirmacao_dados",
        "nome": "Edrei Tester",
        "plano_confirmado": "MOV SUPER+",
    }
    resultado = {
        "resultado": "erro",
        "audio_enviado": False,
        "termo_enviado": True,
        "motivo": "Parcial: audio=false termo=true",
        "erro": True,
        "transferir": False,
    }
    dec = decidir_resultado_termos(resultado, estado)
    _assert(not (dec.contexto_resposta or {}).get("termos_parcial"), dec.contexto_resposta)
    txt = gerar_resposta(dec, estado)
    _assert("dificuldade" not in txt.casefold(), txt)
    _assert("áudio" in txt.casefold() or "audio" in txt.casefold(), txt)


def test_termos_ok_nao_lista_planos() -> None:
    """'ok' em aceite_termos não pode cair em RAG/catálogo de planos."""
    estado = {
        "fase": "termos",
        "aguardando": "aceite_termos",
        "termos_enviados": True,
        "plano_confirmado": "MOV SUPER+",
        "nome": "Edrei",
        "id_contrato_ixc": "67890",
    }
    # LLM classifica errado como PERGUNTA/OUTRO (bug original)
    llm = {"eventos": ["PERGUNTA", "OUTRO"], "dados": {}, "confianca": 0.5}
    i = parse_interpretacao(_raw(llm), "ok", estado)
    _assert(Evento.CONFIRMACAO.value in i.eventos, f"ok → CONFIRMACAO, got {i.eventos}")
    _assert(Evento.PERGUNTA.value not in i.eventos, f"ok não deve manter PERGUNTA: {i.eventos}")

    dec = _decidir_sem_executar(estado, "ok", llm)
    _assert(dec.acao == "ATIVAR_CLIENTE", f"acao={dec.acao} obj={dec.objetivo_resposta}")
    _assert(dec.fase == "agendamento", dec.fase)

    for msg in ("sim", "aceito", "aceita"):
        dec2 = _decidir_sem_executar(estado, msg, llm)
        _assert(dec2.acao == "ATIVAR_CLIENTE", f"{msg} → ATIVAR_CLIENTE, got {dec2.acao}")


def test_cadastro_ok_dispara_enviar_termos() -> None:
    from app.state_machine import decidir_resultado_cadastro_ixc

    dec = decidir_resultado_cadastro_ixc(
        {
            "ok": True,
            "id_cliente_ixc": "12345",
            "id_contrato_ixc": "67890",
            "os_id": "111",
            "motivo": "Cadastro concluído",
        },
        {"nome": "Edrei", "plano_confirmado": "MOV SUPER+"},
    )
    _assert(dec.acao == "ENVIAR_TERMOS", f"acao={dec.acao}")
    _assert(dec.fase == "termos", dec.fase)
    _assert(dec.aguardando == "aceite_termos", dec.aguardando)


def test_data_nascimento_extracao() -> None:
    raw = _raw({"eventos": ["OUTRO"], "dados": {}, "confianca": 0.5})
    i = parse_interpretacao(raw, "16/08/2000", {"fase": "cadastro", "aguardando": "data_nascimento", "plano_confirmado": "X"})
    _assert(Evento.DADO_INFORMADO.value in i.eventos, "data → DADO_INFORMADO")
    _assert(i.dados.data_nascimento == "16/08/2000", i.dados.data_nascimento)
    _assert(not i.dados.cep, f"cep indevido={i.dados.cep}")


def _decidir_sem_executar(estado: dict, msg: str, llm: dict):
    interp = parse_interpretacao(_raw(llm), msg, estado)
    ctx = enriquecer_pergunta(
        msg,
        pergunta=interp.pergunta or msg,
        historico=[],
        plano_nome="MOV SUPER+",
        ultimo_topico=str(estado.get("ultimo_topico") or "") or None,
    )
    if ctx.get("pergunta"):
        interp.pergunta = str(ctx["pergunta"])
    res = resolver(estado, interp)
    res["mensagem"] = msg
    res["pergunta"] = interp.pergunta
    res["topico_contexto"] = ctx.get("topico")
    res["pergunta_original"] = msg
    return decidir(estado, res)


def test_confirmacao_dados_chama_cadastro() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "confirmacao_dados",
        "nome": "Edrei teste",
        "cpf": "60421079096",
        "email": "edreiteste@gmail.com",
        "telefone": "93992219098",
        "data_nascimento": "16/08/2000",
        "cep": "68020000",
        "rua": "sergio henn",
        "numero": "12",
        "plano_confirmado": "MOV SUPER+",
        "cidade": "Santarem",
        "bairro": "Centro",
        "documento_cpf_validado": True,
    }
    eco = {
        "eventos": ["DADO_INFORMADO"],
        "dados": {
            "nome": "Edrei teste",
            "email": "edreiteste@gmail.com",
            "telefone": "93992219098",
            "cpf": "60421079096",
        },
        "confianca": 0.8,
    }
    for msg in ("Sim", "Tá certo", "Está tudo certo"):
        dec = _decidir_sem_executar(estado, msg, eco)
        _assert(dec.acao == "CADASTRAR_IXC", f"{msg} → {dec.acao} {dec.objetivo_resposta}")


def test_cadastro_multiplos_campos_anticipados() -> None:
    """Cliente manda e-mail, tel, CEP, rua e número numa mensagem — não repetir pedidos."""
    base = {
        "fase": "cadastro",
        "aguardando": "email",
        "nome": "Edrei tester",
        "cpf": "60421079096",
        "plano_confirmado": "MOV FLEX",
        "documento_cpf_validado": True,
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    msg = "edreiteste@gmail.com, 93992219098, cep 68020000, rua sergio henn, 891"
    raw = _raw({"eventos": ["OUTRO"], "dados": {}, "confianca": 0.5})
    interp = parse_interpretacao(raw, msg, base)
    _assert(interp.dados.email == "edreiteste@gmail.com", f"email={interp.dados.email}")
    _assert(interp.dados.telefone == "93992219098", f"tel={interp.dados.telefone}")
    _assert(interp.dados.cep == "68020000", f"cep={interp.dados.cep}")
    _assert("sergio" in (interp.dados.rua or "").casefold(), f"rua={interp.dados.rua}")
    _assert(interp.dados.numero == "891", f"numero={interp.dados.numero}")
    _assert(not interp.dados.data_nascimento, f"dn={interp.dados.data_nascimento}")

    dec = _decidir_sem_executar(base, msg, {"eventos": ["DADO_INFORMADO"], "dados": interp.dados.model_dump()})
    anotados = list((dec.contexto_resposta or {}).get("campos_anotados") or [])
    _assert("email" in anotados, f"anotados={anotados}")
    _assert("telefone" in anotados, f"anotados={anotados}")
    _assert("cep" in anotados, f"anotados={anotados}")
    _assert("rua" in anotados, f"anotados={anotados}")
    _assert("numero" in anotados, f"anotados={anotados}")
    _assert(dec.aguardando == "data_nascimento", f"aguardando={dec.aguardando}")


def test_nome_com_interrogacao_nao_e_duvida() -> None:
    estado = {"fase": "cadastro", "aguardando": "nome", "plano_confirmado": "MOV ONE+"}
    msg = "João Silva?"
    _assert(not tem_duvida_informativa(msg, msg, aguardando="nome"), "nome? não é dúvida")
    raw = _raw({"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.7})
    i = parse_interpretacao(raw, msg, estado)
    _assert(i.dados.nome == "João Silva", f"nome={i.dados.nome}")
    _assert(Evento.DADO_INFORMADO.value in i.eventos, i.eventos)
    _assert(Evento.PERGUNTA.value not in i.eventos, i.eventos)


def test_pergunta_instalacao_nao_e_confirmacao() -> None:
    _assert(not eh_confirmacao("pode instalar amanhã?"), "pode instalar ≠ confirmação")
    _assert(not eh_confirmacao("isso inclui wifi?"), "isso inclui ≠ confirmação")
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "plano_em_negociacao": "MOV SUPER+",
        "tem_cobertura": True,
    }
    msg = "pode instalar amanhã?"
    i = parse_interpretacao(
        _raw({"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.8}),
        msg,
        estado,
    )
    _assert(Evento.CONFIRMACAO.value not in i.eventos, i.eventos)


def test_cpf_antes_do_nome_nao_vai_para_nome() -> None:
    estado = {"fase": "cadastro", "aguardando": "nome", "plano_confirmado": "MOV ONE+"}
    msg = "604.210.790-96"
    raw = _raw(
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {"nome": "604.210.790-96", "cpf": "60421079096"},
            "confianca": 0.8,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(not i.dados.nome, f"nome indevido={i.dados.nome}")
    _assert(i.dados.cpf == "60421079096", f"cpf={i.dados.cpf}")


def test_llm_nao_ecoa_estado_sem_repetir() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "telefone",
        "nome": "Ana Silva",
        "cpf": "60421079096",
        "email": "ana@test.com",
        "documento_cpf_validado": True,
        "plano_confirmado": "MOV ONE+",
    }
    msg = "93992219098"
    raw = _raw(
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {
                "nome": "Ana Silva",
                "email": "ana@test.com",
                "telefone": "93992219098",
            },
            "confianca": 0.85,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(i.dados.telefone == "93992219098", i.dados.telefone)
    _assert(not i.dados.nome, f"eco nome={i.dados.nome}")
    _assert(not i.dados.email, f"eco email={i.dados.email}")


def test_fluxo_edrei_rua_nao_vai_pro_nome() -> None:
    """Repro do chat real: data+CEP não preenche rua com nome; pede rua antes do número."""
    base = {
        "fase": "cadastro",
        "aguardando": "data_nascimento",
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "email": "edreiteste@gmail.com",
        "telefone": "93992219098",
        "plano_confirmado": "MOV SUPER",
        "documento_cpf_validado": True,
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    msg = "16/08/2000, 68020000"
    llm_ruim = {
        "eventos": ["DADO_INFORMADO"],
        "dados": {
            "data_nascimento": "16/08/2000",
            "cep": "68020000",
            "rua": "Edrei testes",
        },
        "confianca": 0.85,
    }
    interp = parse_interpretacao(_raw(llm_ruim), msg, base)
    _assert(not interp.dados.rua, f"rua indevida={interp.dados.rua}")
    _assert(interp.dados.data_nascimento == "16/08/2000", interp.dados)
    _assert(interp.dados.cep == "68020000", interp.dados.cep)

    estado, dec = _turno(dict(base), msg, llm_ruim)
    _assert(dec.aguardando == "rua", f"aguardando={dec.aguardando} objetivo={dec.objetivo_resposta}")
    _assert(not str(estado.get("rua") or ""), f"rua salva={estado.get('rua')}")

    estado2, dec2 = _turno(
        {**estado, "aguardando": "confirmacao_dados", "rua": "Edrei testes", "numero": "12"},
        "Rua: Sérgio henn",
        {"eventos": ["CORRECAO_DADO"], "dados": {"rua": "Sérgio henn"}, "campos_corrigidos": ["rua"]},
    )
    _assert("henn" in str(estado2.get("rua") or "").casefold(), f"rua={estado2.get('rua')}")

    estado3, dec3 = _turno(
        {**estado2, "aguardando": "confirmacao_dados"},
        "Pode colocar o bairro: Diamantino",
        {"eventos": ["CORRECAO_DADO"], "dados": {"bairro": "Diamantino"}, "campos_corrigidos": ["bairro"]},
    )
    _assert(str(estado3.get("bairro") or "").casefold() == "diamantino", f"bairro={estado3.get('bairro')}")


def test_correcao_rotulada_confirmacao_dados() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "confirmacao_dados",
        "nome": "Edrei testes",
        "rua": "Edrei testes",
        "numero": "12",
        "cep": "68020000",
        "plano_confirmado": "MOV SUPER",
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    i = parse_interpretacao(
        _raw({"eventos": [], "dados": {}, "confianca": 0.8}),
        "Rua: Sérgio henn",
        estado,
    )
    _assert("henn" in (i.dados.rua or "").casefold(), f"rua={i.dados.rua}")
    _assert("rua" in i.campos_corrigidos, i.campos_corrigidos)

    i2 = parse_interpretacao(
        _raw({"eventos": [], "dados": {}, "confianca": 0.8}),
        "Pode colocar o bairro: Diamantino",
        estado,
    )
    _assert(str(i2.dados.bairro or "").casefold() == "diamantino", f"bairro={i2.dados.bairro}")
    _assert("bairro" in i2.campos_corrigidos, i2.campos_corrigidos)


def test_termos_sim_apos_cancelamento_nao_ativa() -> None:
    base = {
        "fase": "termos",
        "aguardando": "aceite_termos",
        "termos_enviados": True,
        "ultimo_topico": "cancelamento",
        "plano_confirmado": "MOV SUPER+",
        "nome": "Edrei",
    }
    _assert(not eh_aceite_termos_explicito("Sim"), "sim sozinho ≠ aceite termos")
    _assert(eh_aceite_termos_explicito("aceito"), "aceito explícito")
    dec = _decidir_sem_executar(
        base,
        "Sim",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "RESPONDER", f"acao={dec.acao}")
    _assert(dec.acao != "ATIVAR_CLIENTE", "sim ambíguo não ativa contrato")
    _assert(
        dec.objetivo_resposta == "RESPONDER_DUVIDA_E_RETOMAR_TERMOS",
        dec.objetivo_resposta,
    )
    txt = gerar_resposta(dec, base)
    _assert("multa" in txt.casefold(), txt)
    _assert("aceito" in txt.casefold(), txt)


def test_termos_cancelamento_explica_sem_opcoes_vagas() -> None:
    base = {
        "fase": "termos",
        "aguardando": "aceite_termos",
        "termos_enviados": True,
        "plano_confirmado": "MOV SUPER+",
    }
    dec = _decidir_sem_executar(
        base,
        "Mas tenho que pagar se eu cancelar?",
        {"eventos": ["PERGUNTA"], "pergunta": "Mas tenho que pagar se eu cancelar?", "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "RESPONDER_DUVIDA_E_RETOMAR_TERMOS", dec.objetivo_resposta)
    txt = gerar_resposta(dec, {**base, **(dec.contexto_resposta or {})})
    _assert("multa" in txt.casefold(), txt)
    _assert("opções" not in txt.casefold() and "opcoes" not in txt.casefold(), txt)


def test_agendamento_sim_sem_horario() -> None:
    base = {
        "fase": "agendamento",
        "aguardando": "escolha_horario",
        "data_agendamento": "22/09/2026",
        "horarios_manha": "[]",
        "horarios_tarde": '["16h às 17h", "17h às 18h"]',
    }
    dec = _decidir_sem_executar(
        base,
        "Sim",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "PEDIR_HORARIO_ESPECIFICO", dec.objetivo_resposta)
    txt = gerar_resposta(dec, base)
    _assert("lista" in txt.casefold() or "16" in txt, txt)


def test_cadastro_nao_repete_nem_troca_nome_pela_rua() -> None:
    base = {
        "fase": "cadastro",
        "nome": "Edrei teste",
        "cpf": "60421079096",
        "email": "edreiteste@gmail.com",
        "plano_confirmado": "MOV SUPER+",
        "documento_cpf_validado": True,
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    dec = _decidir_sem_executar(
        {**base, "aguardando": "telefone"},
        "93992219098",
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {
                "nome": "Edrei teste",
                "email": "edreiteste@gmail.com",
                "telefone": "93992219098",
            },
        },
    )
    anotados = list((dec.contexto_resposta or {}).get("campos_anotados") or [])
    _assert(anotados == ["telefone"], f"anotados={anotados}")
    _assert("nome" not in (dec.atualizar_dados or {}), f"dados={dec.atualizar_dados}")

    # Caso real do bug: LLM manda CORRECAO_DADO do nome = rua
    dec_rua = _decidir_sem_executar(
        {
            **base,
            "aguardando": "rua",
            "telefone": "93992219098",
            "data_nascimento": "16/08/2000",
            "cep": "68020000",
        },
        "sergio henn",
        {
            "eventos": ["DADO_INFORMADO", "CORRECAO_DADO"],
            "dados": {"nome": "sergio henn", "rua": "sergio henn"},
            "campos_corrigidos": ["nome"],
        },
    )
    dados = dec_rua.atualizar_dados or {}
    _assert("nome" not in dados, f"nome indevido={dados.get('nome')} dados={dados}")
    _assert(str(dados.get("rua") or "").casefold() == "sergio henn", f"rua={dados.get('rua')}")
    anotados_rua = list((dec_rua.contexto_resposta or {}).get("campos_anotados") or [])
    _assert("nome" not in anotados_rua, f"anotados_rua={anotados_rua}")
    corrigidos = list((dec_rua.contexto_resposta or {}).get("campos_corrigidos") or [])
    _assert("nome" not in corrigidos, f"corrigidos={corrigidos}")
    from app.cadastro_mensagens import anotar_e_pedir_proximo

    msg = anotar_e_pedir_proximo(
        campos_anotados=anotados_rua or ["rua"],
        campos_corrigidos=corrigidos,
        pendente=str(dec_rua.aguardando or "numero"),
        estado={**base, "rua": "sergio henn", "telefone": "93992219098", "data_nascimento": "16/08/2000", "cep": "68020000"},
    )
    _assert("Atualizei seu nome" not in msg, msg)
    _assert("número" in msg.casefold() or "numero" in msg.casefold(), msg)


def test_pedido_lista_completa_planos() -> None:
    for msg in (
        "Quais os outros",
        "Mostra as outras opções",
        "me mostre todos",
    ):
        _assert(eh_pedido_lista_completa_planos(msg), msg)
    raw = _raw({"eventos": [], "dados": {}, "confianca": 0.9})
    estado = {"fase": "vendas", "aguardando": "confirmacao_plano", "tem_cobertura": True}
    for msg in ("Quais os outros", "Mostra as outras opções"):
        i = parse_interpretacao(raw, msg, estado)
        _assert(Evento.PEDIU_TROCAR_PLANO.value in i.eventos, f"{msg} → PEDIU_TROCAR_PLANO")
        _assert(Evento.PERGUNTA.value in i.eventos, f"{msg} → PERGUNTA")


def test_mais_forte_resolve_premium() -> None:
    planos = [
        {"id": 1, "nome": "ESSENCIAL", "valor": 129.0, "tags": []},
        {"id": 2, "nome": "SUPER", "valor": 139.0, "tags": []},
        {"id": 3, "nome": "INFINITY", "valor": 189.0, "tags": ["premium"]},
    ]
    r = resolver_plano("quero plano mais forte", planos, plano_atual_id=2)
    _assert(r.get("evento") == "PLANO_RESOLVIDO", r)
    _assert(r["plano"]["nome"] == "INFINITY", r)


def test_listar_todos_quando_pediu_outras_opcoes() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao_id": 2,
        "plano_em_negociacao": "SUPER",
    }
    raw = _raw({"eventos": [], "dados": {}, "confianca": 0.9})
    i = parse_interpretacao(raw, "Mostra as outras opções", estado)
    res = resolver(estado, i)
    res["mensagem"] = "Mostra as outras opções"
    dec = decidir(estado, res)
    _assert(dec.acao == "LISTAR_TODOS_PLANOS", dec.acao)


def main() -> None:
    tests = [
        test_pedido_lista_completa_planos,
        test_mais_forte_resolve_premium,
        test_listar_todos_quando_pediu_outras_opcoes,
        test_confirmacoes_typo,
        test_cadastro_telefone_mais_pergunta,
        test_data_nascimento_nao_preenche_rua_nem_numero,
        test_cadastro_instalacao_gratis,
        test_vendas_instalacao_hoje,
        test_cadastro_cep_mais_pergunta,
        test_cadastro_cpf_mais_pergunta,
        test_agendamento_sim_mais_duvida,
        test_confirmacao_dados_mais_duvida,
        test_mudanca_endereco_agendamento,
        test_cadastro_ok_dispara_enviar_termos,
        test_imagem_painel_com_conversation_id,
        test_payload_imagem_plano_pronto_chatwoot,
        test_termos_webhook_dispara_com_url_configurada,
        test_termos_parcial_n8n_nao_assusta_cliente,
        test_termos_ok_nao_lista_planos,
        test_data_nascimento_extracao,
        test_cadastro_pede_em_pares,
        test_confirmacao_dados_chama_cadastro,
        test_cadastro_multiplos_campos_anticipados,
        test_cadastro_nao_repete_nem_troca_nome_pela_rua,
        test_nome_com_interrogacao_nao_e_duvida,
        test_pergunta_instalacao_nao_e_confirmacao,
        test_cpf_antes_do_nome_nao_vai_para_nome,
        test_llm_nao_ecoa_estado_sem_repetir,
        test_fluxo_edrei_rua_nao_vai_pro_nome,
        test_correcao_rotulada_confirmacao_dados,
        test_termos_sim_apos_cancelamento_nao_ativa,
        test_termos_cancelamento_explica_sem_opcoes_vagas,
        test_agendamento_sim_sem_horario,
    ]
    falhas = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK {fn.__name__}")
        except Exception as e:
            falhas += 1
            print(f"  FALHOU {fn.__name__}: {e}")
    if falhas:
        print(f"\n❌ {falhas} falha(s)")
        sys.exit(1)
    print("\n✅ Regressão de contexto OK")


if __name__ == "__main__":
    main()
