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
    eh_mensagem_sobre_planos,
    eh_pedido_contratacao,
    eh_pedido_lista_completa_planos,
    eh_esclarecimento_promo_plano,
    eh_pedido_plano_promocional,
    eh_pedido_planos_com_desconto,
    eh_pergunta_cobertura_informativa,
    eh_pergunta_instalacao,
    eh_pergunta_mudanca_endereco,
    eh_pergunta_plano_por_preco,
    parse_interpretacao,
    tem_duvida_informativa,
)
from app.validation import rua_parece_frase_invalida
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
    res["confianca"] = float(interp.confianca or 0)
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


def test_sanitizar_plano_informado_fantasma_llm() -> None:
    """LLM marca PLANO_INFORMADO em pergunta — guards removem e viram PERGUNTA."""
    from app.interpretacao_contexto import (
        referencia_parece_pergunta_nao_plano,
        sanitizar_plano_informado_llm,
    )
    from app.models import DadosExtraidos

    msg = "E quando vai ser a instalação?\nTem taxa para instalar?"
    _assert(referencia_parece_pergunta_nao_plano(msg, msg), msg)
    dados = DadosExtraidos(plano=msg)
    eventos = ["PLANO_INFORMADO", "PERGUNTA"]
    pergunta = sanitizar_plano_informado_llm(
        dados=dados,
        eventos=eventos,
        pergunta="",
        msg=msg,
        msg_bruto=msg,
        intencao_nao_dado=True,
        tem_duvida=True,
    )
    _assert(Evento.PLANO_INFORMADO.value not in eventos, eventos)
    _assert(Evento.PERGUNTA.value in eventos, eventos)
    _assert(dados.plano == "", dados.plano)
    _assert(pergunta, "pergunta vazia")


def test_mov_up_continua_plano_valido() -> None:
    from app.interpretacao_contexto import referencia_parece_plano

    _assert(referencia_parece_plano("mov up", "mov up"), "mov up")
    _assert(not referencia_parece_plano("quanto custa instalar?", "quanto custa instalar?"), "instalar")


def test_cadastro_instalacao_prazo_e_taxa_nao_resolve_plano() -> None:
    """Perguntas sobre prazo/taxa de instalação no cadastro ≠ busca de plano."""
    from app.response import gerar_resposta

    estado = {
        "fase": "cadastro",
        "aguardando": "data_nascimento",
        "tem_cobertura": True,
        "plano_confirmado": "MOV UP+",
        "plano_confirmado_id": 1215,
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "email": "edreitestes@gmail.com",
        "telefone": "93992219098",
        "documento_cpf_validado": True,
    }
    msg = "E quando vai ser a instalação?\nTem taxa para instalar?"
    raw = _raw(
        {
            "eventos": ["PLANO_INFORMADO", "PERGUNTA"],
            "dados": {"plano": msg},
            "confianca": 0.9,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PLANO_INFORMADO.value not in i.eventos, f"eventos={i.eventos}")
    _assert(Evento.PERGUNTA.value in i.eventos, f"eventos={i.eventos}")
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "RESPONDER", f"{dec.acao} {dec.motivo}")
    _assert(
        dec.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR",
        dec.objetivo_resposta,
    )
    _assert(dec.acao != "RESOLVER_PLANO", dec.acao)
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("nao encontrei um plano" not in txt.casefold(), txt)
    _assert("data de nascimento" in txt.casefold() or "cep" in txt.casefold(), txt)


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
        "cadastro_completo": True,
        "plano_confirmado": "MOV SUPER+",
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


def test_cancelamento_followup_nao_pede_data_nascimento_para_calcular() -> None:
    """'Nesse caso quanto que ficaria?' após dúvida de cancelamento — resposta fixa."""
    estado = {
        "fase": "cadastro",
        "aguardando": "data_nascimento",
        "plano_confirmado": "MOV SUPER+",
        "nome": "Edrei teste",
        "cpf": "60421079096",
        "email": "edreiteste@gmail.com",
        "telefone": "93992219098",
        "ultimo_topico": "cancelamento",
    }
    msg = "Nesse caso quanto que ficaria?"
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_CANCELAMENTO_E_RETOMAR", dec.objetivo_resposta)
    txt = gerar_resposta(dec, estado)
    low = txt.casefold()
    _assert("nao calcula" in low or "não calcula" in low, txt)
    _assert("para calcular" not in low, txt)
    _assert("preciso da sua data de nascimento" not in low, txt)
    _assert("proporcional" in low, txt)


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
    _assert(dec.objetivo_resposta == "INFORMAR_CANCELAMENTO_E_RETOMAR", dec.objetivo_resposta)
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


def test_cidades_atendidas_nao_viram_bairro() -> None:
    from types import SimpleNamespace

    from app.localizacao_heuristica import (
        aplicar_heuristica_localizacao,
        classificar_token_unico,
        extrair_par_cidade_bairro,
    )

    for cidade in (
        "Altamira",
        "Itaituba",
        "Belterra",
        "Mojuí dos Campos",
        "Medicilândia",
    ):
        _assert(classificar_token_unico(cidade) == "cidade", cidade)

    _assert(classificar_token_unico("Diamantino") == "bairro", "diamantino")

    par = extrair_par_cidade_bairro("aqui no diamantino, santarem")
    _assert(par is not None, par)
    _assert(str(par["cidade"]).casefold().startswith("santar"), par)
    _assert(str(par["bairro"]).casefold() == "diamantino", par)

    dados = SimpleNamespace(cidade="", bairro="Santarem")
    flags = aplicar_heuristica_localizacao(
        mensagem="Santarem",
        dados=dados,
        estado={},
        aguardando="localizacao",
        fase="inicio",
    )
    _assert(flags["ajustou"] is True, flags)
    _assert(str(dados.cidade).casefold().startswith("santar"), dados.cidade)
    _assert(not dados.bairro, dados.bairro)


def test_payload_transferencia_inclui_contexto() -> None:
    import json

    from app.transfer_chatwoot import montar_payload_transferencia

    estado = {
        "id_cliente": "5593999999999@s.whatsapp.net",
        "conversation_id": "18422",
        "nome": "Maria Silva",
        "fase": "cadastro",
        "aguardando": "cpf",
        "plano_confirmado": "MOV SUPER",
        "cadastro_completo": False,
        "ixc_cliente_id": "",
        "ativado_ixc": False,
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    p = montar_payload_transferencia(estado, "Cliente pediu humano")
    _assert(p["motivo"] == "Cliente pediu humano", p)
    _assert(p["conversation_id"] == "18422", p)
    _assert(isinstance(p["contexto"], str), p)
    ctx = json.loads(p["contexto"])
    _assert(ctx["fase"] == "cadastro", ctx)
    _assert(ctx["objetivo"] == "Cliente pediu humano", ctx)
    _assert(p["transferido_humano"] == "true", p)
    _assert(p["cadastro_completo"] == "false", p)
    _assert(isinstance(p["mensagens"], str), p)
    _assert(json.loads(p["mensagens"]) == [], p)


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
        "cadastro_completo": True,
        "ixc_cliente_id": "12345",
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
    res["confianca"] = float(interp.confianca or 0)
    return decidir(estado, res)


def test_ta_com_pergunta_fantasma_llm_cadastra() -> None:
    """LLM marca PERGUNTA em 'Tá' — parser limpa e dispara CADASTRAR_IXC."""
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
        "bairro": "Diamantino",
        "documento_cpf_validado": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "Tá",
        {"eventos": ["CONFIRMACAO", "PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "CADASTRAR_IXC", f"acao={dec.acao} obj={dec.objetivo_resposta}")


def test_termos_mock_nao_afirma_envio() -> None:
    from app.state_machine import decidir_resultado_termos

    dec = decidir_resultado_termos(
        {
            "resultado": "ok",
            "audio_enviado": False,
            "termo_enviado": False,
            "provider": "mock",
            "motivo": "Termos mock local",
        },
        {"fase": "termos"},
    )
    _assert(dec.objetivo_resposta == "PEDIR_ACEITE_TERMOS", dec.objetivo_resposta)
    _assert(not (dec.contexto_resposta or {}).get("termos_enviados"), dec.contexto_resposta)
    txt = gerar_resposta(dec, {"termos_enviados": False})
    _assert("acabei de enviar" not in txt.casefold(), txt)


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
    for msg in ("Sim", "Tá", "Tá certo", "Está tudo certo"):
        dec = _decidir_sem_executar(estado, msg, eco)
        _assert(dec.acao == "CADASTRAR_IXC", f"{msg} → {dec.acao} {dec.objetivo_resposta}")


def test_cadastro_webhook_dispara_com_url_no_painel_mesmo_provider_mock() -> None:
    """URL cadastrada no painel deve disparar n8n mesmo com CADASTRO_PROVIDER=mock."""
    from unittest.mock import MagicMock, patch

    from app.cadastro_ixc import cadastrar_cliente

    estado = {
        "id_cliente": "teste-local",
        "conversation_id": "3075",
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "email": "edreitestes@gmail.com",
        "telefone": "93992219098",
        "plano_confirmado_id": "1180",
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "resultado": "ok",
        "ixc_cliente_id": "83458",
        "id_contrato_ixc": "92405",
        "os_id": "111",
        "motivo": "Cadastro concluído",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.integrations.cadastro_webhook.httpx.Client") as mock_client:
        inst = mock_client.return_value.__enter__.return_value
        inst.post.return_value = mock_resp
        with patch("app.cadastro_ixc.get_settings") as mock_settings:
            s = mock_settings.return_value
            s.cadastro_provider = "mock"
            s.cadastro_webhook_url = ""
            s.cadastro_webhook_token = ""
            s.cadastro_timeout_seconds = 90
        with patch(
            "app.cadastro_ixc._url_cadastro",
            return_value="https://n8n2.mov.pro.br/webhook/cadastrar_cliente_sofia",
        ):
            out = cadastrar_cliente(estado)

    _assert(out.get("ok") is True, out)
    _assert(out.get("id_cliente_ixc") == "83458", out)
    inst.post.assert_called_once()
    args, kwargs = inst.post.call_args
    _assert("cadastrar_cliente_sofia" in args[0], args[0])


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


def test_plano_simples_no_cadastro_vai_para_resolver() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "nome": "Isabelly Gamboa Martins",
        "plano_confirmado": "MOV SUPER+",
        "tem_cobertura": True,
        "cidade": "Santarem",
        "bairro": "Aparecida",
    }
    msg = "Plano simples"
    raw = _raw(
        {
            "eventos": ["PLANO_INFORMADO"],
            "dados": {"plano": "Plano simples"},
            "confianca": 0.85,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PLANO_INFORMADO.value in i.eventos, i.eventos)
    _assert(not i.dados.cpf, f"cpf indevido={i.dados.cpf}")
    _assert(
        "barato" in (i.dados.plano or "").casefold() or "simples" in (i.dados.plano or "").casefold(),
        f"plano={i.dados.plano}",
    )


def test_cpf_11_digitos_aguardando_cpf_nao_vai_telefone() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "nome": "Isabelly Gamboa Martins",
        "plano_confirmado": "MOV SUPER+",
        "tem_cobertura": True,
    }
    msg = "03225928283"
    raw = _raw(
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {"telefone": "03225928283", "cpf": ""},
            "confianca": 0.8,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(i.dados.cpf == "03225928283", f"cpf={i.dados.cpf}")
    _assert(not i.dados.telefone, f"telefone indevido={i.dados.telefone}")


def test_me_da_logo_nao_vai_para_nome() -> None:
    """'Me dá logo' é pedido de urgência — não é nome."""
    estado = {"fase": "cadastro", "aguardando": "nome", "plano_confirmado": "MOV SUPER+"}
    msg = "Me dá logo"
    raw = _raw(
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {"nome": "Me dá logo"},
            "confianca": 0.85,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(not i.dados.nome, f"nome indevido={i.dados.nome}")
    _assert(Evento.PERGUNTA.value in i.eventos or Evento.OUTRO.value in i.eventos, i.eventos)


def test_quanto_e_nao_anota_cpf() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "nome": "João Silva",
        "plano_confirmado": "MOV SUPER+",
    }
    msg = "Quanto é?"
    raw = _raw(
        {
            "eventos": ["DADO_INFORMADO", "PERGUNTA"],
            "dados": {"cpf": "Quanto é"},
            "pergunta": "Quanto é?",
            "confianca": 0.8,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(not i.dados.cpf, f"cpf indevido={i.dados.cpf}")
    _assert(Evento.PERGUNTA.value in i.eventos, i.eventos)


def test_ack_curto_confirmacao_horario() -> None:
    from app.parser import eh_ack_curto

    _assert(eh_ack_curto("certo"), "certo")
    _assert(eh_ack_curto("ok"), "ok")
    estado = {
        "fase": "agendamento",
        "aguardando": "confirmacao_horario",
        "horario_escolhido": "8h às 9h",
        "data_agendamento": "01/09/2026",
        "cadastro_completo": True,
        "plano_confirmado": "MOV SUPER+",
    }
    i = parse_interpretacao(
        _raw({"eventos": [], "dados": {}, "confianca": 0.9}),
        "certo",
        estado,
    )
    _assert(Evento.CONFIRMACAO.value in i.eventos, f"certo → CONFIRMACAO {i.eventos}")
    dec = _decidir_sem_executar(
        estado,
        "certo",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "INSERIR_AGENDAMENTO", f"{dec.acao} {dec.motivo}")


def test_termos_si_aceita_quando_nao_cancelamento() -> None:
    base = {
        "fase": "termos",
        "aguardando": "aceite_termos",
        "termos_enviados": True,
        "plano_confirmado": "MOV SUPER+",
        "cadastro_completo": True,
        "ixc_cliente_id": "12345",
        "nome": "Edrei",
    }
    dec = _decidir_sem_executar(
        base,
        "Si",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "ATIVAR_CLIENTE", f"{dec.acao} {dec.motivo}")


def test_plano_repetido_na_confirmacao_confirma() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "plano_em_negociacao": "MOV ESSENCIAL",
        "plano_em_negociacao_id": 1214,
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "mov essencial",
        {"eventos": ["PLANO_INFORMADO"], "dados": {"plano": "mov essencial"}, "confianca": 0.9},
    )
    _assert(dec.acao != "RESOLVER_PLANO", f"{dec.acao} {dec.motivo}")
    _assert(dec.fase == "cadastro", dec.fase)


def test_rua_cadastro_nao_revalida_cobertura() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "rua",
        "plano_confirmado": "MOV ESSENCIAL",
        "cidade": "Santarem",
        "bairro": "Centro",
        "tem_cobertura": True,
        "cep": "68020000",
    }
    msg = "Rua Sergio Henn, 872, Santarem"
    i = parse_interpretacao(
        _raw(
            {
                "eventos": ["DADO_INFORMADO"],
                "dados": {
                    "rua": "Rua Sergio Henn",
                    "numero": "872",
                    "cidade": "Santarem",
                },
                "confianca": 0.9,
            }
        ),
        msg,
        estado,
    )
    res = resolver(estado, i)
    loc = res.get("localizacao") or {}
    _assert(not loc.get("precisa_revalidar"), f"precisa_revalidar={loc}")
    campos = (res.get("dados") or {}).get("campos_informados") or []
    _assert("rua" in campos, campos)


def test_si_e_confirmacao() -> None:
    _assert(eh_confirmacao("Si"), "Si")
    _assert(eh_confirmacao("si"), "si")


def test_mov_essencial_repetido_no_cadastro_nao_reabre_vendas() -> None:
    from app.state_machine import _referencia_mesmo_plano_confirmado

    estado = {
        "fase": "cadastro",
        "plano_confirmado": "MOV ESSENCIAL",
        "plano_confirmado_id": 1214,
        "tem_cobertura": True,
        "nome": "Edrei testes",
    }
    _assert(_referencia_mesmo_plano_confirmado(estado, "mov essencial"), "mov essencial")
    i = parse_interpretacao(
        _raw({"eventos": ["PLANO_INFORMADO"], "dados": {"plano": "mov essencial"}, "confianca": 0.9}),
        "Mov essencial",
        estado,
    )
    res = resolver(estado, i)
    res["mensagem"] = "Mov essencial"
    dec = decidir(estado, res)
    _assert(dec.acao != "RESOLVER_PLANO", f"{dec.acao} {dec.motivo}")


def test_encerrar_explicito_na_vendas_dispara_ferramenta() -> None:
    """'Pode encerrar o atendimento' no meio de vendas — ação ENCERRAR, não cadastro."""
    from app.pos_venda_mensagens import eh_pedido_encerrar

    msg = "Pode encerrar o atendimento"
    _assert(eh_pedido_encerrar(msg), msg)
    _assert(eh_pedido_encerrar("**Pode encerrar o atendimento**"), msg)
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao": "MOV SUPER+",
        "plano_em_negociacao_id": 1212,
        "nome": "Edrei",
    }
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["NEGACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "ENCERRAR_ATENDIMENTO", f"{dec.acao} {dec.motivo}")
    _assert(dec.aguardando == "resultado_encerrar", dec.aguardando)


def test_encerrar_usa_webhook_quando_url_no_painel() -> None:
    """Com URL da ferramenta configurada, dispara webhook mesmo com provider mock."""
    from unittest.mock import patch

    from app.encerrar import encerrar_atendimento

    estado = {"id_cliente": "teste-encerrar-webhook", "conversation_id": "999"}
    with patch(
        "app.ferramentas_catalog.resolver_url_ferramenta",
        return_value="https://n8n.example/encerrar",
    ), patch(
        "app.encerrar.encerrar_atendimento_webhook",
        return_value={"resultado": "ok", "motivo": "Encerrado", "erro": False},
    ) as mock_hook:
        r = encerrar_atendimento(estado)
    _assert(r.get("resultado") == "ok", r)
    _assert(mock_hook.called, "webhook de encerrar deveria ter sido chamado")


def test_encerrar_no_cadastro_nao_anota_nome() -> None:
    from app.pos_venda_mensagens import eh_pedido_encerrar

    msg = "Pode encerrar o atendimento"
    _assert(eh_pedido_encerrar(msg), msg)
    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "plano_confirmado": "MOV SUPER+",
        "plano_confirmado_id": 1214,
        "tem_cobertura": True,
    }
    i = parse_interpretacao(
        _raw(
            {
                "eventos": ["DADO_INFORMADO"],
                "dados": {"nome": "Pode encerrar o atendimento"},
                "confianca": 0.9,
            }
        ),
        msg,
        estado,
    )
    _assert(i.dados.nome == "", f"nome={i.dados.nome!r}")
    _assert(Evento.NEGACAO.value in i.eventos, i.eventos)
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["NEGACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "ENCERRAR_ATENDIMENTO", f"{dec.acao} {dec.motivo}")


def test_cadastro_sem_plano_volta_vendas() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "plano_em_negociacao": "MOV SUPER+",
        "plano_em_negociacao_id": 1212,
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "João Silva",
        {"eventos": ["DADO_INFORMADO"], "dados": {"nome": "João Silva"}, "confianca": 0.9},
    )
    _assert(dec.fase == "vendas", dec.fase)
    _assert(dec.objetivo_resposta == "PRIORIZAR_PLANO_ANTES_CADASTRO", dec.objetivo_resposta)


def test_sim_apos_cancelamento_no_cadastro_continua() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "nome": "Edrei testes",
        "plano_confirmado": "MOV ESSENCIAL",
        "plano_confirmado_id": 1214,
        "cancelamento_esclarecido": True,
        "ultimo_topico": "cancelamento",
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "Si",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.fase == "cadastro", dec.fase)
    _assert(dec.aguardando == "cpf", dec.aguardando)
    _assert(dec.objetivo_resposta == "PEDIR_CPF", dec.objetivo_resposta)


def test_oi_quero_instalar_nao_transfere() -> None:
    """Abertura com intenção de contratar — pede localização, não transfere."""
    msg = "Oi, quero instalar"
    _assert(eh_pedido_contratacao(msg, msg), msg)
    _assert(not eh_mensagem_sobre_planos(msg, msg), msg)
    _assert(not eh_pergunta_instalacao(msg, msg), msg)

    estado = {"fase": "inicio"}
    i = parse_interpretacao(
        _raw({"eventos": ["CONFIRMACAO", "PLANO_INFORMADO"], "dados": {"plano": "instalar"}, "confianca": 0.8}),
        msg,
        estado,
    )
    _assert(Evento.PEDIDO_CONTRATACAO.value in i.eventos, i.eventos)
    _assert(Evento.CONFIRMACAO.value not in i.eventos, i.eventos)
    _assert(Evento.PLANO_INFORMADO.value not in i.eventos, i.eventos)
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["SAUDACAO", "PEDIDO_CONTRATACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(
        dec.objetivo_resposta == "APRESENTAR_E_PEDIR_LOCALIZACAO",
        dec.objetivo_resposta,
    )

    estado_vendas = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
    }
    dec2 = _decidir_sem_executar(
        estado_vendas,
        msg,
        {"eventos": ["SAUDACAO", "CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec2.acao != "TRANSFERIR_HUMANO", f"{dec2.acao} {dec2.objetivo_resposta}")
    _assert(dec2.acao == "BUSCAR_PLANO_INICIAL", dec2.acao)


def test_quero_contratar_nao_grava_localizacao() -> None:
    estado = {"fase": "viabilidade", "aguardando": "localizacao"}
    msg = "Quero contratar"
    raw = _raw(
        {
            "eventos": ["LOCALIZACAO_INFORMADA"],
            "dados": {"cidade": "Quero contratar"},
            "confianca": 0.7,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(not i.dados.cidade, f"cidade indevida={i.dados.cidade}")
    _assert(not i.dados.bairro, f"bairro indevido={i.dados.bairro}")


def test_nome_valido_continua_aceito() -> None:
    estado = {"fase": "cadastro", "aguardando": "nome", "plano_confirmado": "MOV SUPER+"}
    msg = "Maria Oliveira Santos"
    raw = _raw(
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {"nome": "Maria Oliveira Santos"},
            "confianca": 0.9,
        }
    )
    i = parse_interpretacao(raw, msg, estado)
    _assert(
        "Maria" in (i.dados.nome or ""),
        f"nome deveria ser aceito, veio={i.dados.nome}",
    )


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


def test_correcao_rua_natural_confirmacao_dados() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "confirmacao_dados",
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "email": "edreitestes@gmail.com",
        "telefone": "93992219098",
        "data_nascimento": "16/08/2000",
        "cep": "68020000",
        "rua": "Tem Qual Outros Planos Ai Quero Um Mais Barato",
        "numero": "12",
        "plano_confirmado": "MOV FLEX",
        "cidade": "Santarem",
        "bairro": "Diamantino",
        "ultimo_topico": "instalacao",
    }
    i = parse_interpretacao(
        _raw({"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.8}),
        "A rua é sergio henn",
        estado,
    )
    _assert("sergio" in (i.dados.rua or "").casefold(), f"rua={i.dados.rua}")
    _assert("rua" in i.campos_corrigidos, i.campos_corrigidos)
    _assert(Evento.CORRECAO_DADO.value in i.eventos, i.eventos)
    _assert(Evento.PERGUNTA.value not in i.eventos, i.eventos)

    dec = _decidir_sem_executar(
        estado,
        "A rua é sergio henn",
        {
            "eventos": ["CORRECAO_DADO", "DADO_INFORMADO"],
            "dados": {"rua": "sergio henn"},
            "campos_corrigidos": ["rua"],
        },
    )
    _assert(
        dec.objetivo_resposta == "CONFIRMAR_DADOS_CADASTRO",
        dec.objetivo_resposta,
    )
    _assert(
        str((dec.atualizar_dados or {}).get("rua") or "").casefold() == "sergio henn",
        dec.atualizar_dados,
    )

    dec2 = _decidir_sem_executar(
        estado,
        "A rua ta errada",
        {"eventos": ["CORRECAO_DADO", "NEGACAO"], "dados": {"rua": ""}, "campos_corrigidos": ["rua"]},
    )
    _assert(dec2.objetivo_resposta == "PEDIR_CORRECAO_RUA", dec2.objetivo_resposta)


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


def test_termos_instalar_hoje_nao_lista_planos() -> None:
    base = {
        "fase": "termos",
        "aguardando": "aceite_termos",
        "termos_enviados": True,
        "plano_confirmado": "MOV SUPER+",
    }
    dec = _decidir_sem_executar(
        base,
        "Mas tem como instalar hj?",
        {"eventos": ["PERGUNTA"], "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR", dec.objetivo_resposta)
    txt = gerar_resposta(dec, {**base, **(dec.contexto_resposta or {})})
    low = txt.casefold()
    _assert("mov essencial" not in low and "mov one" not in low, txt)
    _assert("aceite" in low or "aceito" in low, txt)
    _assert("instala" in low, txt)


def test_cadastro_apos_cancelamento_nao_repete_multa() -> None:
    """Data/CEP/número após dúvida de cancelamento — só anota e pede próximo campo."""
    base = {
        "fase": "cadastro",
        "plano_confirmado": "MOV SUPER+",
        "nome": "Edrei teste",
        "cpf": "60421079096",
        "email": "edreiteste@gmail.com",
        "telefone": "93992219098",
        "ultimo_topico": "cancelamento",
        "cancelamento_esclarecido": True,
    }
    acumulado = dict(base)
    casos = [
        ("16/08/2000", "data_nascimento", {"data_nascimento": "16/08/2000"}),
        ("68020000", "cep", {"cep": "68020000"}),
        ("12", "numero", {"numero": "12"}),
    ]
    for msg, aguardando, dados_ev in casos:
        st = {**acumulado, "aguardando": aguardando}
        dec = _decidir_sem_executar(
            st,
            msg,
            {"eventos": ["DADO_INFORMADO"], "dados": dados_ev, "confianca": 0.9},
        )
        _assert(
            dec.objetivo_resposta != "INFORMAR_CANCELAMENTO_E_RETOMAR",
            f"msg={msg!r} acao={dec.objetivo_resposta}",
        )
        txt = gerar_resposta(dec, {**st, **(dec.atualizar_dados or {}), **dados_ev})
        low = txt.casefold()
        _assert("proporcional" not in low, txt)
        _assert("12 meses" not in low, txt)
        acumulado.update(dados_ev)


def test_cadastro_email_telefone_mais_cancelamento() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "email",
        "plano_confirmado": "MOV SUPER+",
        "nome": "Edrei teste",
        "cpf": "60421079096",
    }
    msg = "edreiteste@gmail.com, 93992219098. Ah e tem que pagar se eu cancelar?"
    dec = _decidir_sem_executar(
        estado,
        msg,
        {
            "eventos": ["DADO_INFORMADO", "PERGUNTA"],
            "dados": {"email": "edreiteste@gmail.com", "telefone": "93992219098"},
            "confianca": 0.9,
        },
    )
    _assert(dec.objetivo_resposta == "INFORMAR_CANCELAMENTO_E_RETOMAR", dec.objetivo_resposta)
    txt = gerar_resposta(
        dec,
        {**estado, **(dec.atualizar_dados or {}), "email": "edreiteste@gmail.com", "telefone": "93992219098"},
    )
    low = txt.casefold()
    _assert("nao calcula" in low or "não calcula" in low or "proporcional" in low, txt)
    _assert("para calcular" not in low, txt)


def test_esclarecer_promo_6950_nao_50() -> None:
    from app.vendas_mensagens import esclarecer_promocao_plano

    plano = {
        "nome": "MOV SUPER+",
        "valor": 139.0,
        "descricao": (
            "COMBO MOV SUPER+ – R$ 139,00/mês\n"
            "🔥 Oferta especial: 50% de desconto nos 3 primeiros meses\n"
            "💰 Nos 3 primeiros meses, a mensalidade fica por apenas R$ 69,50"
        ),
        "beneficios": "50% de desconto nos 3 primeiros meses (R$ 69,50)",
        "tags": ["promo_inicial"],
    }
    txt = esclarecer_promocao_plano(plano)
    _assert("69,50" in txt or "69.50" in txt, txt)
    _assert("50,00" not in txt, txt)


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


def test_baixa_confianca_outro_clarifica() -> None:
    estado = {"fase": "vendas", "aguardando": "confirmacao_plano", "tem_cobertura": True}
    dec = _decidir_sem_executar(
        estado,
        "ah sla pow nem sei",
        {"eventos": ["OUTRO"], "dados": {}, "confianca": 0.35},
    )
    _assert(dec.objetivo_resposta == "CLARIFICAR_INTENCAO", dec.objetivo_resposta)
    txt = gerar_resposta(dec, estado)
    _assert("entendi" in txt.casefold(), txt)


def test_baixa_confianca_frase_como_nome_clarifica() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "plano_confirmado": "MOV SUPER+",
        "tem_cobertura": True,
    }
    msg = "Nossa fiquei confuso com essa parte toda"
    dec = _decidir_sem_executar(
        estado,
        msg,
        {
            "eventos": ["DADO_INFORMADO", "OUTRO"],
            "dados": {"nome": msg},
            "confianca": 0.4,
        },
    )
    _assert(dec.objetivo_resposta == "CLARIFICAR_INTENCAO", dec.objetivo_resposta)
    _assert(not (dec.atualizar_dados or {}).get("nome"), dec.atualizar_dados)


def test_alta_confianca_cpf_continua_cadastro() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "nome": "Maria Silva",
        "plano_confirmado": "MOV SUPER+",
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "03225928283",
        {"eventos": ["DADO_INFORMADO"], "dados": {"cpf": "03225928283"}, "confianca": 0.95},
    )
    _assert(dec.objetivo_resposta != "CLARIFICAR_INTENCAO", dec.objetivo_resposta)
    _assert(dec.acao in {"VALIDAR_CPF", "RESPONDER"}, dec.acao)


def test_confianca_zero_mantem_fluxo_anterior() -> None:
    """confianca=0 = LLM não informou — não forçar clarificação (regressão)."""
    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "plano_confirmado": "MOV SUPER+",
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "Tem como instalar amanhã?",
        {
            "eventos": ["PERGUNTA"],
            "dados": {},
            "confianca": 0,
        },
    )
    _assert(dec.objetivo_resposta != "CLARIFICAR_INTENCAO", dec.objetivo_resposta)


def test_agendamento_sim_sem_horario() -> None:
    base = {
        "fase": "agendamento",
        "aguardando": "escolha_horario",
        "data_agendamento": "22/09/2026",
        "horarios_manha": "[]",
        "horarios_tarde": '["16h às 17h", "17h às 18h"]',
        "cadastro_completo": True,
        "plano_confirmado": "MOV SUPER+",
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


def test_plano_no_meio_do_cadastro_nao_vai_para_rua() -> None:
    msg = "tem qual outros planos ai quero um mais barato"
    _assert(eh_mensagem_sobre_planos(msg), msg)
    _assert(
        rua_parece_frase_invalida("Tem Qual Outros Planos Ai Quero Um Mais Barato"),
        "rua invalida",
    )
    estado = {
        "fase": "cadastro",
        "aguardando": "telefone",
        "plano_confirmado": "MOV INFINITY",
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "email": "edreitestes@gmail.com",
    }
    raw = _raw({"eventos": ["PEDIU_TROCAR_PLANO"], "dados": {}, "confianca": 0.9})
    i = parse_interpretacao(raw, msg, estado)
    _assert(not i.dados.rua, f"rua={i.dados.rua}")
    _assert(
        Evento.PEDIU_TROCAR_PLANO.value in i.eventos
        or Evento.PLANO_INFORMADO.value in i.eventos,
        i.eventos,
    )

    dec = _decidir_sem_executar(
        {
            **estado,
            "telefone": "93992219098",
            "data_nascimento": "16/08/2000",
            "cep": "68020000",
            "aguardando": "rua",
        },
        "sergio henn",
        {"eventos": ["DADO_INFORMADO"], "dados": {"rua": "sergio henn"}},
    )
    _assert(str((dec.atualizar_dados or {}).get("rua") or "") == "sergio henn", dec.atualizar_dados)

    dec_plano = _decidir_sem_executar(
        {**estado, "aguardando": "telefone"},
        msg,
        {
            "eventos": ["PEDIU_TROCAR_PLANO", "PLANO_INFORMADO"],
            "dados": {"rua": msg, "plano": msg},
        },
    )
    dados = dec_plano.atualizar_dados or {}
    _assert(not dados.get("rua"), f"rua indevida={dados.get('rua')}")


def test_titulo_categoria_sem_chip_indevido() -> None:
    from app.vendas_mensagens import _titulo_categoria_plano

    flex = {"nome": "MOV FLEX", "tags": ["flex", "pontualidade"], "beneficios": "Internet ilimitada"}
    super_ = {"nome": "MOV SUPER", "tags": ["super", "combo", "pontualidade"], "beneficios": "Internet ilimitada"}
    super_plus = {
        "nome": "MOV SUPER+",
        "tags": ["super_plus", "combo", "mesh"],
        "beneficios": "Internet ilimitada\nRepetidor Mesh",
    }
    combo = {
        "nome": "MOV COMBO TOTAL 22GB",
        "tags": ["combo", "chip_22gb", "chip"],
        "beneficios": "Chip com 22 GB\nLigações ilimitadas",
    }
    _assert(_titulo_categoria_plano(flex) == "📶 INTERNET + BENEFÍCIOS", flex)
    _assert(_titulo_categoria_plano(super_) == "📶 INTERNET + BENEFÍCIOS", super_)
    _assert(_titulo_categoria_plano(super_plus) == "📶 INTERNET + BENEFÍCIOS", super_plus)
    _assert(_titulo_categoria_plano(combo) == "📶 INTERNET + CHIP", combo)


def test_mostre_os_planos_dispara_lista_completa() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "escolha_plano",
        "tem_cobertura": True,
        "plano_em_negociacao_id": 1214,
        "plano_em_negociacao": "MOV FLEX",
    }
    for msg in ("Mostre os planos", "mostra os planos", "me mostre os planos"):
        dec = _decidir_sem_executar(
            estado,
            msg,
            {"eventos": ["PEDIU_TROCAR_PLANO", "PERGUNTA"], "dados": {}, "confianca": 0.9},
        )
        _assert(dec.acao == "LISTAR_TODOS_PLANOS", f"{msg} → {dec.acao}")


def test_esclarecimento_promo_nao_lista_planos() -> None:
    """'Ah é só nos 3 primeiros meses' — confirma promo, não relista catálogo."""
    msg = "Ah é só nos 3 primeiros meses"
    _assert(eh_esclarecimento_promo_plano(msg), msg)
    _assert(not eh_pedido_planos_com_desconto(msg), msg)
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao": "MOV SUPER+",
        "plano_em_negociacao_id": 1212,
        "plano_apresentado": "MOV SUPER+",
        "plano_apresentado_id": 1212,
    }
    raw = _raw({"eventos": ["PEDIU_TROCAR_PLANO"], "dados": {}, "confianca": 0.9})
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PERGUNTA.value in i.eventos, f"eventos={i.eventos}")
    _assert(Evento.PEDIU_TROCAR_PLANO.value not in i.eventos, f"eventos={i.eventos}")
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "RESPONDER", dec.acao)
    _assert(dec.objetivo_resposta == "ESCLARECER_PROMO_PLANO", dec.objetivo_resposta)
    _assert(dec.acao != "LISTAR_TODOS_PLANOS", dec.acao)
    dec.contexto_resposta = {
        **(dec.contexto_resposta or {}),
        "plano": {
            "id": 1212,
            "nome": "MOV SUPER+",
            "valor": 139.0,
            "descricao": "Nos 3 primeiros meses, a mensalidade fica por apenas R$ 69,50",
            "beneficios": "50% de desconto nos 3 primeiros meses (R$ 69,50)",
            "tags": ["promo_inicial"],
        },
    }
    txt = gerar_resposta(dec, estado)
    _assert("somente nos 3 primeiros meses" in txt.casefold(), txt)
    _assert("69,50" in txt or "69.50" in txt, txt)
    _assert("qual desses" not in txt.casefold(), txt)


def test_pedido_planos_com_desconto_lista_filtrada() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "escolha_plano",
        "tem_cobertura": True,
        "plano_em_negociacao_id": 1214,
    }
    dec = _decidir_sem_executar(
        estado,
        "Que tem desconto",
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "LISTAR_TODOS_PLANOS", dec.acao)
    _assert((dec.contexto_resposta or {}).get("filtro") == "desconto", dec.contexto_resposta)


def test_sim_apos_oferta_desconto_lista_planos() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "escolha_plano",
        "tem_cobertura": True,
        "ultima_mensagem_sofia": "Quer que eu te mostre os planos com esse benefício?",
    }
    dec = _decidir_sem_executar(
        estado,
        "Sim",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.acao == "LISTAR_TODOS_PLANOS", dec.acao)
    _assert((dec.contexto_resposta or {}).get("filtro") == "desconto", dec.contexto_resposta)


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


def test_quero_na_promocao_nao_confirma_plano_atual() -> None:
    """'Quero um na promoção' após MOV SUPER não deve avançar para cadastro."""
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao": "MOV SUPER",
        "plano_em_negociacao_id": 1209,
        "plano_apresentado": "MOV SUPER",
        "plano_apresentado_id": 1209,
    }
    msg = "Quero um na promoção"
    _assert(eh_pedido_plano_promocional(msg), msg)
    _assert(not eh_confirmacao(msg), msg)
    raw = _raw({"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9})
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.CONFIRMACAO.value not in i.eventos, f"eventos={i.eventos}")
    _assert(Evento.PEDIU_TROCAR_PLANO.value in i.eventos, f"eventos={i.eventos}")
    dec = _decidir_sem_executar(estado, msg, {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9})
    _assert(dec.acao == "RESOLVER_PLANO", f"acao={dec.acao} obj={dec.objetivo_resposta}")
    _assert(dec.aguardando != "nome", f"aguardando={dec.aguardando}")


def test_cancelamento_no_cadastro_nao_resolve_plano() -> None:
    """'Taxa se cancelar' no meio do cadastro — explica multa, não busca plano."""
    estado = {
        "fase": "cadastro",
        "aguardando": "email",
        "tem_cobertura": True,
        "plano_confirmado": "MOV INFINITY",
        "plano_confirmado_id": 1215,
        "nome": "Edrei testes",
        "cpf": "60421079096",
        "documento_cpf_validado": True,
    }
    msg = "Quero tbm ver se eu tenho que pagar taxa se cancelar"
    from app.parser import parse_interpretacao, eh_mensagem_sobre_planos

    _assert(not eh_mensagem_sobre_planos(msg, msg), msg)
    i = parse_interpretacao(
        _raw({"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9}),
        msg,
        estado,
    )
    _assert(Evento.PLANO_INFORMADO.value not in i.eventos, i.eventos)
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(
        dec.objetivo_resposta == "INFORMAR_CANCELAMENTO_E_RETOMAR",
        dec.objetivo_resposta,
    )
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("nao encontrei um plano" not in txt.casefold(), txt)


def test_preco_mov_up_nao_usa_plano_em_negociacao() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao": "MOV ESSENCIAL",
        "plano_em_negociacao_id": 1213,
    }
    msg = "Quanto custa o mov up?"
    dec = _decidir_sem_executar(
        estado, msg, {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9}
    )
    _assert(dec.objetivo_resposta == "INFORMAR_PRECO_PLANO_E_RETOMAR", dec.objetivo_resposta)
    ctx = dec.contexto_resposta or {}
    plano = ctx.get("plano") or {}
    nome = str(plano.get("nome") or "").casefold()
    _assert("up" in nome, f"plano={plano.get('nome')}")
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("149" in txt or "up" in txt.casefold(), txt)
    _assert("129" not in txt or "up" in txt.casefold(), txt)


def test_detalhe_mov_up_no_cadastro() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "tem_cobertura": True,
        "plano_confirmado": "MOV SUPER+",
        "plano_em_negociacao": "MOV SUPER+",
    }
    msg = "O que vem no mov up?"
    dec = _decidir_sem_executar(
        estado, msg, {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9}
    )
    _assert(dec.objetivo_resposta == "INFORMAR_DETALHES_PLANO", dec.objetivo_resposta)
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("up" in txt.casefold(), txt)
    _assert("super+" not in txt.casefold() or "up" in txt.casefold(), txt)


def test_detalhe_mov_up_na_pergunta_mostra_plano_correto() -> None:
    """'O que vem no mov up?' — detalha UP+, não o plano em negociacao."""
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "cidade": "Santarem",
        "bairro": "Diamantino",
        "plano_em_negociacao": "MOV ESSENCIAL",
        "plano_em_negociacao_id": 1213,
        "plano_apresentado": "MOV ESSENCIAL",
        "plano_apresentado_id": 1213,
    }
    msg = "O que vem mais nese mov up?"
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_DETALHES_PLANO", dec.objetivo_resposta)
    ctx = dec.contexto_resposta or {}
    plano_ctx = ctx.get("plano") or {}
    nome_ctx = str(plano_ctx.get("nome") or "").casefold()
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("mov up" in nome_ctx or "up+" in nome_ctx, f"plano={plano_ctx.get('nome')}")
    _assert("mov up" in txt.casefold() or "up+" in txt.casefold(), txt)
    _assert("mov essencial" not in txt.casefold() or "up" in txt.casefold(), txt)


def test_qual_o_de_6950_nao_trata_como_escolha() -> None:
    """'Qual o de 69,50?' após lista — identifica plano, não 'anotei a troca'."""
    msg = "Qual o de 69,50?"
    _assert(eh_pergunta_plano_por_preco(msg), msg)
    _assert(not eh_confirmacao(msg), msg)
    estado = {
        "fase": "vendas",
        "aguardando": "lista_planos",
        "tem_cobertura": True,
        "fase_anterior": "cadastro",
        "aguardando_anterior": "nome",
        "plano_em_negociacao": "MOV FLEX",
        "plano_em_negociacao_id": 1214,
    }
    raw = _raw({"eventos": ["PLANO_INFORMADO", "PERGUNTA"], "dados": {"plano": "69"}, "confianca": 0.9})
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.PERGUNTA.value in i.eventos, f"eventos={i.eventos}")
    _assert(Evento.PLANO_INFORMADO.value not in i.eventos, f"eventos={i.eventos}")
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["PLANO_INFORMADO"], "dados": {"plano": "69"}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_DETALHES_PLANO", dec.objetivo_resposta)
    _assert((dec.contexto_resposta or {}).get("identificacao_por_preco") is True, dec.contexto_resposta)
    txt = gerar_resposta(dec, {**estado, **(dec.contexto_resposta or {})})
    _assert("anotei a troca" not in txt.casefold(), txt)
    _assert("esse valor é do" in txt.casefold() or "mov super+" in txt.casefold(), txt)


def test_resolver_plano_preco_promocional_6950() -> None:
    planos = [
        {
            "id": 1214,
            "nome": "MOV FLEX",
            "valor": 119.0,
            "valor_pontualidade": 99.0,
            "descricao": "",
            "beneficios": "",
            "tags": ["flex"],
        },
        {
            "id": 1212,
            "nome": "MOV SUPER+",
            "valor": 139.0,
            "valor_pontualidade": None,
            "descricao": (
                "COMBO MOV SUPER+ – R$ 139,00/mês\n"
                "Nos 3 primeiros meses, a mensalidade fica por apenas R$ 69,50"
            ),
            "beneficios": "50% de desconto nos 3 primeiros meses (R$ 69,50)",
            "tags": ["super_plus", "promo_inicial"],
        },
    ]
    for msg in ("Qual o de 69,50?", "quero o de 69", "plano dos primeiros meses"):
        r = resolver_plano(msg, planos, plano_atual_id=1214)
        _assert(r.get("evento") == "PLANO_RESOLVIDO", f"{msg} → {r}")
        _assert(r["plano"]["nome"] == "MOV SUPER+", f"{msg} → {r}")


def test_beleza_mas_tem_disney_nao_confirma_plano() -> None:
    """'Beleza mas tem disney?' — responde benefício, não pede cadastro."""
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao": "MOV SUPER+",
        "plano_em_negociacao_id": 1212,
        "plano_apresentado": "MOV SUPER+",
        "plano_apresentado_id": 1212,
    }
    msg = "Beleza mas tem disney?"
    raw = _raw({"eventos": ["CONFIRMACAO", "PERGUNTA"], "dados": {}, "confianca": 0.9})
    i = parse_interpretacao(raw, msg, estado)
    _assert(Evento.CONFIRMACAO.value not in i.eventos, f"eventos={i.eventos}")
    _assert(Evento.PERGUNTA.value in i.eventos, f"eventos={i.eventos}")
    dec = _decidir_sem_executar(
        estado,
        msg,
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_PLANOS_POR_BENEFICIO", dec.objetivo_resposta)
    _assert(dec.fase == "vendas", dec.fase)
    _assert(dec.aguardando == "confirmacao_plano", dec.aguardando)
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("disney" in txt.casefold(), txt)
    _assert("cpf" not in txt.casefold(), txt)


def test_mais_barato_com_disney_resolve_plano() -> None:
    planos = [
        {"id": 1, "nome": "MOV SUPER+", "valor": 139.0, "tags": [], "beneficios": ""},
        {"id": 2, "nome": "MOV ONE+", "valor": 149.0, "tags": ["disney"], "beneficios": "Disney+"},
        {"id": 3, "nome": "MOV UP+", "valor": 169.0, "tags": ["disney"], "beneficios": "Disney+"},
        {"id": 4, "nome": "MOV INFINITY", "valor": 189.0, "tags": ["disney"], "beneficios": "Disney+"},
    ]
    r = resolver_plano("quero o mais barato que tem disney", planos, plano_atual_id=1)
    _assert(r.get("evento") == "PLANO_RESOLVIDO", r)
    _assert(r["plano"]["nome"] == "MOV ONE+", r)


def test_mais_barato_disney_dispara_resolver_nao_detalhe() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "tem_cobertura": True,
        "plano_em_negociacao": "MOV SUPER+",
        "plano_em_negociacao_id": 1212,
        "plano_apresentado": "MOV SUPER+",
        "plano_apresentado_id": 1212,
    }
    msg = "Quero o mais barato que tem Disney"
    raw = _raw({"eventos": ["PLANO_INFORMADO", "PERGUNTA"], "dados": {"plano": msg}, "confianca": 0.9})
    i = parse_interpretacao(raw, msg, estado)
    _assert(
        Evento.PLANO_INFORMADO.value in i.eventos or Evento.PERGUNTA.value in i.eventos,
        i.eventos,
    )
    dec = _decidir_sem_executar(
        estado,
        msg,
        {
            "eventos": list(i.eventos),
            "dados": {"plano": msg} if Evento.PLANO_INFORMADO.value in i.eventos else {},
            "confianca": 0.9,
        },
    )
    _assert(dec.acao == "RESOLVER_PLANO", f"{dec.acao} {dec.objetivo_resposta}")
    _assert(dec.objetivo_resposta != "INFORMAR_DETALHES_PLANO", dec.objetivo_resposta)


def test_abertura_prioriza_localizacao_fixa() -> None:
    from app.saudacao import mensagem_abertura, texto_pedir_localizacao_instalacao

    txt = mensagem_abertura("oi")
    _assert("localização fixa" in txt.casefold(), txt)
    _assert("cidade" in txt.casefold() and "bairro" in txt.casefold(), txt)
    compacto = texto_pedir_localizacao_instalacao(compacto=True)
    _assert("localização fixa" in compacto.casefold(), compacto)


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


def test_plano_nao_encontrado_instalacao_redireciona() -> None:
    """Barreira final: RESOLVER_PLANO com pergunta de instalação ≠ 'plano não encontrado'."""
    from app.state_machine import decidir_plano_resolvido

    msg = "E quando vai ser a instalação?\nTem taxa para instalar?"
    estado = {
        "fase": "cadastro",
        "aguardando": "data_nascimento",
        "fase_anterior": "cadastro",
        "aguardando_anterior": "data_nascimento",
        "plano_confirmado": "MOV UP+",
        "nome": "Edrei testes",
        "email": "edreitestes@gmail.com",
        "telefone": "93992219098",
    }
    dec = decidir_plano_resolvido(
        {"evento": "PLANO_NAO_ENCONTRADO", "referencia": msg},
        estado,
    )
    _assert(dec.objetivo_resposta == "INFORMAR_INSTALACAO_E_RETOMAR", dec.objetivo_resposta)
    _assert(dec.fase == "cadastro", dec.fase)
    txt = gerar_resposta(dec, estado)
    _assert("nao encontrei um plano" not in txt.casefold(), txt)
    _assert("instala" in txt.casefold(), txt)


def test_email_nao_herda_topico_instalacao() -> None:
    ctx = enriquecer_pergunta(
        "edreiteste@gmail.com",
        ultimo_topico="instalacao",
        plano_nome="MOV ONE+",
    )
    _assert(ctx.get("topico") is None, ctx)


def test_cadastro_email_apos_instalacao_nao_repete() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "email",
        "nome": "Edrei maciel testes",
        "cpf": "60421079096",
        "plano_confirmado": "MOV ONE+",
        "documento_cpf_validado": True,
        "ultimo_topico": "instalacao",
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "edreiteste@gmail.com",
        {
            "eventos": ["DADO_INFORMADO"],
            "dados": {"email": "edreiteste@gmail.com"},
            "confianca": 0.9,
        },
    )
    _assert(
        dec.objetivo_resposta != "INFORMAR_INSTALACAO_E_RETOMAR",
        dec.objetivo_resposta,
    )
    _assert(dec.aguardando == "telefone", dec.aguardando)


def test_pode_ser_confirma_plano_mesmo_com_plano_informado_llm() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "plano_em_negociacao": "MOV ONE+",
        "plano_em_negociacao_id": 1211,
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "Pode ser",
        {
            "eventos": ["CONFIRMACAO", "PLANO_INFORMADO"],
            "dados": {"plano": "pode ser"},
            "confianca": 0.9,
        },
    )
    _assert(dec.objetivo_resposta == "CONFIRMAR_PLANO_E_AVANCAR", dec.objetivo_resposta)
    _assert(dec.fase == "cadastro", dec.fase)


def test_confirmar_plano_resposta_pula_nome_ja_informado() -> None:
    from app.cadastro_mensagens import confirmar_plano_e_avancar

    estado = {"nome": "Edrei maciel testes"}
    txt = confirmar_plano_e_avancar("MOV ONE+", "R$ 139,00", estado)
    _assert("CPF" in txt, txt)
    _assert("nome completo" not in txt.casefold(), txt)


def test_ja_disse_o_nome_reconhece() -> None:
    from app.parser import eh_mensagem_correcao_cadastro

    _assert(
        eh_mensagem_correcao_cadastro("Ja disse o nome", "Ja disse o nome"),
        "ja disse o nome",
    )
    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "nome": "Edrei maciel testes",
        "plano_confirmado": "MOV ONE+",
    }
    dec = _decidir_sem_executar(
        estado,
        "Ja disse o nome",
        {"eventos": ["OUTRO"], "dados": {}, "confianca": 0.8},
    )
    _assert(dec.objetivo_resposta == "PEDIR_CPF", dec.objetivo_resposta)


def test_sim_apos_cancelamento_com_nome_no_estado() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "nome",
        "nome": "Edrei maciel testes",
        "plano_confirmado": "MOV ONE+",
        "plano_confirmado_id": 1211,
        "ultimo_topico": "cancelamento",
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "Sim",
        {"eventos": ["CONFIRMACAO", "DADO_INFORMADO"], "dados": {"nome": "Edrei maciel testes"}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "PEDIR_CPF", dec.objetivo_resposta)


def test_plano_bloqueado_pos_cadastro() -> None:
    estado = {
        "fase": "termos",
        "aguardando": "aceite_termos",
        "cadastro_completo": True,
        "plano_confirmado": "MOV SUPER+",
        "plano_confirmado_id": 1212,
        "tem_cobertura": True,
        "nome": "João Silva",
    }
    dec = _decidir_sem_executar(
        estado,
        "quero trocar pro mov up",
        {
            "eventos": ["PLANO_INFORMADO", "PEDIU_TROCAR_PLANO"],
            "dados": {"plano": "mov up"},
            "confianca": 0.9,
        },
    )
    _assert(
        dec.objetivo_resposta == "INFORMAR_PLANO_BLOQUEADO_POS_CADASTRO",
        dec.objetivo_resposta,
    )
    txt = gerar_resposta(dec, estado)
    _assert("atendente" in txt.casefold() or "equipe" in txt.casefold(), txt)
    _assert("super+" in txt.casefold(), txt)


def test_alteracao_bloqueada_pos_cadastro() -> None:
    estado = {
        "fase": "agendamento",
        "aguardando": "escolha_horario",
        "cadastro_completo": True,
        "plano_confirmado": "MOV SUPER+",
        "nome": "João Silva",
        "email": "joao@mail.com",
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "meu email é outro@mail.com",
        {
            "eventos": ["DADO_INFORMADO", "CORRECAO_DADO"],
            "dados": {"email": "outro@mail.com"},
            "confianca": 0.9,
        },
    )
    _assert(
        dec.objetivo_resposta == "INFORMAR_ALTERACAO_BLOQUEADA_POS_CADASTRO",
        dec.objetivo_resposta,
    )
    txt = gerar_resposta(dec, estado)
    _assert("atendente" in txt.casefold() or "equipe" in txt.casefold(), txt)


def test_troca_plano_retoma_cadastro() -> None:
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "fase_anterior": "cadastro",
        "aguardando_anterior": "cpf",
        "nome": "João Silva",
        "plano_em_negociacao": "MOV UP+",
        "plano_em_negociacao_id": 1211,
        "plano_confirmado": "MOV ESSENCIAL",
        "plano_confirmado_id": 1214,
        "tem_cobertura": True,
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    dec = _decidir_sem_executar(
        estado,
        "sim quero o up",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(
        dec.objetivo_resposta == "CONFIRMAR_TROCA_PLANO_E_RETOMAR_CADASTRO",
        f"{dec.objetivo_resposta} {dec.motivo}",
    )
    _assert(dec.fase == "cadastro", dec.fase)
    _assert(dec.aguardando == "cpf", dec.aguardando)
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("up" in txt.casefold(), txt)
    _assert("cpf" in txt.casefold(), txt)


def test_cadastro_buffer_cep_fora_ordem() -> None:
    """Cliente manda CEP enquanto pendente é e-mail — aceita e pede o que falta."""
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
    msg = "68020000"
    raw = _raw({"eventos": ["DADO_INFORMADO"], "dados": {"cep": "68020000"}, "confianca": 0.9})
    interp = parse_interpretacao(raw, msg, base)
    _assert(interp.dados.cep == "68020000", f"cep={interp.dados.cep}")
    dec = _decidir_sem_executar(base, msg, {"eventos": ["DADO_INFORMADO"], "dados": {"cep": "68020000"}, "confianca": 0.9})
    anotados = list((dec.contexto_resposta or {}).get("campos_anotados") or [])
    _assert("cep" in anotados, f"anotados={anotados}")
    _assert(dec.aguardando == "email", f"aguardando={dec.aguardando}")


def test_pode_ser_com_nome_confirma_e_anota() -> None:
    """'Pode ser, Nome Completo' confirma plano e já anota o nome."""
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "plano_em_negociacao": "MOV ONE+",
        "plano_em_negociacao_id": 1211,
        "tem_cobertura": True,
    }
    msg = "Pode ser, Edrei maciel testes"
    raw = _raw(
        {
            "eventos": ["CONFIRMACAO", "DADO_INFORMADO"],
            "dados": {"nome": "Edrei maciel testes"},
            "confianca": 0.9,
        }
    )
    interp = parse_interpretacao(raw, msg, estado)
    _assert(Evento.CONFIRMACAO.value in interp.eventos, interp.eventos)
    _assert(interp.dados.nome == "Edrei maciel testes", f"nome={interp.dados.nome}")
    dec = _decidir_sem_executar(
        estado,
        msg,
        {
            "eventos": list(interp.eventos),
            "dados": interp.dados.model_dump(),
            "confianca": 0.9,
        },
    )
    _assert(dec.objetivo_resposta == "CONFIRMAR_PLANO_E_AVANCAR", dec.objetivo_resposta)
    _assert(dec.fase == "cadastro", dec.fase)
    _assert(dec.aguardando == "cpf", f"aguardando={dec.aguardando} (nome já anotado)")
    _assert(
        (dec.atualizar_dados or {}).get("nome") == "Edrei maciel testes",
        dec.atualizar_dados,
    )


def test_preco_plano_limpa_topico() -> None:
    """Após responder preço, limpar_topico evita repetir a mesma dúvida."""
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "nome": "João Silva",
        "plano_confirmado": "MOV SUPER+",
        "plano_confirmado_id": 1212,
        "ultimo_topico": "preco",
        "tem_cobertura": True,
    }
    dec = _decidir_sem_executar(
        estado,
        "Quanto custa o mov up?",
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_PRECO_PLANO_E_RETOMAR", dec.objetivo_resposta)
    _assert((dec.atualizar_dados or {}).get("limpar_topico") is True, dec.atualizar_dados)


def test_perfil_dificil_desvios_e_dados_fora_ordem() -> None:
    """Roteiro estilo Edrei: dúvida + dados fora de ordem sem travar."""
    estado = {
        "fase": "vendas",
        "aguardando": "confirmacao_plano",
        "plano_em_negociacao": "MOV ONE+",
        "plano_em_negociacao_id": 1211,
        "tem_cobertura": True,
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    estado, dec = _turno(
        estado,
        "Pode ser, Edrei maciel testes",
        {
            "eventos": ["CONFIRMACAO", "DADO_INFORMADO"],
            "dados": {"nome": "Edrei maciel testes"},
            "confianca": 0.9,
        },
    )
    _assert(dec.objetivo_resposta == "CONFIRMAR_PLANO_E_AVANCAR", dec.objetivo_resposta)
    _assert(estado.get("nome") == "Edrei maciel testes", estado.get("nome"))
    _assert(estado.get("aguardando") == "cpf", estado.get("aguardando"))

    estado, dec = _turno(
        estado,
        "68020000",
        {"eventos": ["DADO_INFORMADO"], "dados": {"cep": "68020000"}, "confianca": 0.9},
    )
    _assert("cep" in list((dec.contexto_resposta or {}).get("campos_anotados") or []), dec.contexto_resposta)
    _assert(estado.get("cep") == "68020000", estado.get("cep"))

    estado, dec = _turno(
        estado,
        "tem multa se cancelar?",
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_CANCELAMENTO_E_RETOMAR", dec.objetivo_resposta)
    _assert((dec.atualizar_dados or {}).get("limpar_topico") is True, dec.atualizar_dados)

    estado, dec = _turno(
        estado,
        "Sim",
        {"eventos": ["CONFIRMACAO"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "PEDIR_CPF", dec.objetivo_resposta)


def test_flex_coloquial_nao_dispara_plano() -> None:
    from app.parser import _detectar_plano_na_mensagem, parse_interpretacao

    _assert(_detectar_plano_na_mensagem("preciso de algo mais flexivel") == "", "flex coloquial")
    estado = {
        "fase": "cadastro",
        "aguardando": "telefone",
        "plano_confirmado": "MOV ONE+",
        "nome": "Ana",
        "cpf": "60421079096",
        "email": "a@t.com",
    }
    i = parse_interpretacao(
        _raw({"eventos": ["OUTRO"], "dados": {}, "confianca": 0.8}),
        "preciso de algo mais flexivel",
        estado,
    )
    _assert(Evento.PLANO_INFORMADO.value not in i.eventos, i.eventos)


def test_agendamento_tem_outro_horario_nao_troca_plano() -> None:
    estado = {
        "fase": "agendamento",
        "aguardando": "escolha_horario",
        "horarios_manha": '["08h às 10h", "10h às 12h"]',
        "horarios_tarde": '["14h às 16h"]',
        "plano_confirmado": "MOV ONE+",
    }
    msg = "tem outro horario?"
    i = parse_interpretacao(
        _raw({"eventos": ["NEGACAO"], "dados": {}, "confianca": 0.9}),
        msg,
        estado,
    )
    _assert(Evento.PEDIU_TROCAR_PLANO.value not in i.eventos, i.eventos)
    _assert(Evento.NEGACAO.value in i.eventos, i.eventos)


def test_followup_nao_herda_topico_sem_ser_curto() -> None:
    ctx = enriquecer_pergunta(
        "quanto custa o mov up?",
        ultimo_topico="cancelamento",
        historico=[],
        plano_nome="MOV ONE+",
    )
    _assert(ctx.get("topico") != "cancelamento", ctx.get("topico"))


def test_buffer_conflito_usa_ultima_intencao() -> None:
    from app.message_buffer import _resolver_mensagens_conflitantes

    msg = _resolver_mensagens_conflitantes(["sim", "nao quero esse"])
    _assert("nao" in msg.casefold(), msg)


def test_preco_plano_no_cadastro_retoma() -> None:
    estado = {
        "fase": "cadastro",
        "aguardando": "cpf",
        "nome": "João Silva",
        "plano_confirmado": "MOV SUPER+",
        "plano_confirmado_id": 1212,
        "tem_cobertura": True,
        "cidade": "Santarem",
        "bairro": "Centro",
    }
    dec = _decidir_sem_executar(
        estado,
        "Quanto custa o mov up?",
        {"eventos": ["PERGUNTA"], "dados": {}, "confianca": 0.9},
    )
    _assert(dec.objetivo_resposta == "INFORMAR_PRECO_PLANO_E_RETOMAR", dec.objetivo_resposta)
    txt = gerar_resposta(dec, {**estado, **(dec.atualizar_dados or {})})
    _assert("up" in txt.casefold() or "149" in txt, txt)
    _assert("voltando ao cadastro" in txt.casefold() or "cpf" in txt.casefold(), txt)


def main() -> None:
    tests = [
        test_plano_nao_encontrado_instalacao_redireciona,
        test_email_nao_herda_topico_instalacao,
        test_cadastro_email_apos_instalacao_nao_repete,
        test_pode_ser_confirma_plano_mesmo_com_plano_informado_llm,
        test_pode_ser_com_nome_confirma_e_anota,
        test_cadastro_buffer_cep_fora_ordem,
        test_preco_plano_limpa_topico,
        test_perfil_dificil_desvios_e_dados_fora_ordem,
        test_flex_coloquial_nao_dispara_plano,
        test_agendamento_tem_outro_horario_nao_troca_plano,
        test_followup_nao_herda_topico_sem_ser_curto,
        test_buffer_conflito_usa_ultima_intencao,
        test_confirmar_plano_resposta_pula_nome_ja_informado,
        test_ja_disse_o_nome_reconhece,
        test_sim_apos_cancelamento_com_nome_no_estado,
        test_plano_bloqueado_pos_cadastro,
        test_alteracao_bloqueada_pos_cadastro,
        test_troca_plano_retoma_cadastro,
        test_preco_plano_no_cadastro_retoma,
        test_correcao_rua_natural_confirmacao_dados,
        test_plano_no_meio_do_cadastro_nao_vai_para_rua,
        test_titulo_categoria_sem_chip_indevido,
        test_mostre_os_planos_dispara_lista_completa,
        test_cancelamento_followup_nao_pede_data_nascimento_para_calcular,
        test_esclarecimento_promo_nao_lista_planos,
        test_pedido_planos_com_desconto_lista_filtrada,
        test_sim_apos_oferta_desconto_lista_planos,
        test_pedido_lista_completa_planos,
        test_mais_forte_resolve_premium,
        test_quero_na_promocao_nao_confirma_plano_atual,
        test_cancelamento_no_cadastro_nao_resolve_plano,
        test_preco_mov_up_nao_usa_plano_em_negociacao,
        test_detalhe_mov_up_no_cadastro,
        test_detalhe_mov_up_na_pergunta_mostra_plano_correto,
        test_qual_o_de_6950_nao_trata_como_escolha,
        test_resolver_plano_preco_promocional_6950,
        test_beleza_mas_tem_disney_nao_confirma_plano,
        test_mais_barato_com_disney_resolve_plano,
        test_mais_barato_disney_dispara_resolver_nao_detalhe,
        test_abertura_prioriza_localizacao_fixa,
        test_listar_todos_quando_pediu_outras_opcoes,
        test_confirmacoes_typo,
        test_cadastro_telefone_mais_pergunta,
        test_data_nascimento_nao_preenche_rua_nem_numero,
        test_sanitizar_plano_informado_fantasma_llm,
        test_mov_up_continua_plano_valido,
        test_cadastro_instalacao_prazo_e_taxa_nao_resolve_plano,
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
        test_cidades_atendidas_nao_viram_bairro,
        test_payload_transferencia_inclui_contexto,
        test_termos_webhook_dispara_com_url_configurada,
        test_termos_parcial_n8n_nao_assusta_cliente,
        test_termos_ok_nao_lista_planos,
        test_data_nascimento_extracao,
        test_cadastro_pede_em_pares,
        test_ta_com_pergunta_fantasma_llm_cadastra,
        test_termos_mock_nao_afirma_envio,
        test_confirmacao_dados_chama_cadastro,
        test_cadastro_webhook_dispara_com_url_no_painel_mesmo_provider_mock,
        test_cadastro_multiplos_campos_anticipados,
        test_cadastro_nao_repete_nem_troca_nome_pela_rua,
        test_nome_com_interrogacao_nao_e_duvida,
        test_pergunta_instalacao_nao_e_confirmacao,
        test_plano_simples_no_cadastro_vai_para_resolver,
        test_cpf_11_digitos_aguardando_cpf_nao_vai_telefone,
        test_me_da_logo_nao_vai_para_nome,
        test_quanto_e_nao_anota_cpf,
        test_ack_curto_confirmacao_horario,
        test_termos_si_aceita_quando_nao_cancelamento,
        test_plano_repetido_na_confirmacao_confirma,
        test_rua_cadastro_nao_revalida_cobertura,
        test_si_e_confirmacao,
        test_mov_essencial_repetido_no_cadastro_nao_reabre_vendas,
        test_encerrar_explicito_na_vendas_dispara_ferramenta,
        test_encerrar_usa_webhook_quando_url_no_painel,
        test_encerrar_no_cadastro_nao_anota_nome,
        test_cadastro_sem_plano_volta_vendas,
        test_sim_apos_cancelamento_no_cadastro_continua,
        test_oi_quero_instalar_nao_transfere,
        test_quero_contratar_nao_grava_localizacao,
        test_nome_valido_continua_aceito,
        test_cpf_antes_do_nome_nao_vai_para_nome,
        test_llm_nao_ecoa_estado_sem_repetir,
        test_fluxo_edrei_rua_nao_vai_pro_nome,
        test_correcao_rotulada_confirmacao_dados,
        test_termos_sim_apos_cancelamento_nao_ativa,
        test_termos_instalar_hoje_nao_lista_planos,
        test_cadastro_apos_cancelamento_nao_repete_multa,
        test_cadastro_email_telefone_mais_cancelamento,
        test_esclarecer_promo_6950_nao_50,
        test_termos_cancelamento_explica_sem_opcoes_vagas,
        test_baixa_confianca_outro_clarifica,
        test_baixa_confianca_frase_como_nome_clarifica,
        test_alta_confianca_cpf_continua_cadastro,
        test_confianca_zero_mantem_fluxo_anterior,
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
