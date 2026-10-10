# -*- coding: utf-8 -*-
"""Endereço — bloco com rótulos e campo número no formato que o IXC aceita.

Caso real de 08/10/2026: a cliente mandou o endereço inteiro numa lista com rótulos;
a Eva pediu cidade e bairro de novo e gravou no campo número
"nº 729, Bloco 04, Apartamento 104 (cond. boulevard tapajós)". Sem LLM e sem rede.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import test_auditoria_interpretacao as aud  # bloqueia a rede e simula as integrações

from app.cadastro_ixc import _dados_ixc_direto
from app.cadastro_resumo import montar_resumo_cadastro
from app.endereco import extrair_endereco_rotulado, numero_e_complemento, separar_numero
from app.webhook_payload import snapshot_cliente

E, L, turno = aud.E, aud.L, aud.turno

BLOCO = """Cidade: Santarém/PA
Rua: Rua São Marco
Bairro: Nova Vitória
Número da residência: nº 729,  Bloco 04, Apartamento 104 (cond. boulevard tapajós)
CEP ou localização fixa: 68038-040
Ponto de referência: próximo ao supermercado Atacadão"""
NUMERO_COMO_VEIO = "nº 729,  Bloco 04, Apartamento 104 (cond. boulevard tapajós)"
COMPLEMENTO = "Bloco 04, Apartamento 104 (cond. boulevard tapajós), ref.: próximo ao supermercado Atacadão"


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


def test_numero_fica_so_com_o_numero() -> None:
    casos = {
        NUMERO_COMO_VEIO: ("729", "Bloco 04, Apartamento 104 (cond. boulevard tapajós)"),
        "729": ("729", ""),
        "729-B": ("729B", ""),
        "729 B": ("729B", ""),
        "Nº 10A": ("10A", ""),
        "número 45": ("45", ""),
        "n° 1200, fundos": ("1200", "fundos"),
        "891 residencial plácido": ("891", "residencial plácido"),
        "729 bloco 4 apto 104": ("729", "bloco 4 apto 104"),
        "2040, casa B": ("2040", "casa B"),
        "casa 12 fundos": ("12", "fundos"),
        # Endereço por lote/quadra/km não tem número de casa
        "lote 5 quadra 12": ("S/N", "lote 5 quadra 12"),
        "km 14": ("S/N", "km 14"),
        "s/n": ("S/N", ""),
        "sem número": ("S/N", ""),
        # Só complemento: o número continua faltando
        "bloco B apto 3": ("", "bloco B apto 3"),
        "próximo ao mercado": ("", "próximo ao mercado"),
    }
    for valor, esperado in casos.items():
        _assert(separar_numero(valor) == esperado, (valor, separar_numero(valor)))


def test_bloco_com_rotulos_e_lido_campo_a_campo() -> None:
    r = extrair_endereco_rotulado(BLOCO)
    _assert(r == {"cidade": "Santarém", "bairro": "Nova Vitória", "rua": "Rua São Marco", "cep": "68038040",
                  "numero": "729", "complemento": COMPLEMENTO}, r)
    _assert(extrair_endereco_rotulado("cidade: itaituba - PA\nbairro: centro") == {"cidade": "itaituba", "bairro": "centro"}, "uf")
    # Uma linha só, ou texto com dois-pontos que não é endereço, não é bloco
    _assert(extrair_endereco_rotulado("Bairro: Aparecida") == {}, "uma linha")
    _assert(extrair_endereco_rotulado("olha só: quero internet\nmeu nome: João") == {}, "não é endereço")


def test_endereco_completo_no_inicio_ja_checa_cobertura() -> None:
    """Qualquer que seja a leitura do modelo, o bloco vale: cobertura checada e plano mostrado."""
    leituras = [
        L(["LOCALIZACAO_INFORMADA", "DADO_INFORMADO"], {"cidade": "Santarém", "bairro": "Nova Vitória",
                                                       "rua": "Rua São Marco", "numero": NUMERO_COMO_VEIO, "cep": "68038040"}),
        L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém/PA", "bairro": "Nova Vitória"}),
        L(["OUTRO"], {}),
        L(["PERGUNTA"], {}, pergunta=BLOCO),
    ]
    for llm in leituras:
        estado, dec, _ = turno(E("viab"), BLOCO, llm)
        _assert(estado.get("cidade") == "Santarém" and estado.get("bairro") == "Nova Vitória", (estado.get("cidade"), estado.get("bairro")))
        _assert(estado.get("tem_cobertura") is True and estado.get("fase") == "vendas", (estado.get("tem_cobertura"), estado.get("fase")))
        _assert(dec.objetivo_resposta == "APRESENTAR_PLANO_INICIAL", dec.objetivo_resposta)
        # O resto do endereço já fica guardado para o cadastro
        _assert(estado.get("rua") == "Rua São Marco" and estado.get("cep") == "68038040", (estado.get("rua"), estado.get("cep")))
        _assert(estado.get("numero") == "729" and estado.get("complemento") == COMPLEMENTO, (estado.get("numero"), estado.get("complemento")))


def test_cadastro_nao_pede_de_novo_o_endereco_ja_informado() -> None:
    estado, _, _ = turno(E("viab"), BLOCO, L(["LOCALIZACAO_INFORMADA"], {"cidade": "Santarém", "bairro": "Nova Vitória"}))
    passos = [
        ("sim", L(["CONFIRMACAO"], {})),
        ("Maria Teodora de Brito Leão", L(["DADO_INFORMADO"], {"nome": "Maria Teodora de Brito Leão"})),
        ("529.982.247-25", L(["DADO_INFORMADO"], {"cpf": "52998224725"})),
        ("leaoteodora6@gmail.com\n91 98020-4601", L(["DADO_INFORMADO"], {"email": "leaoteodora6@gmail.com", "telefone": "91980204601"})),
        ("30/12/1999", L(["DADO_INFORMADO"], {"data_nascimento": "30/12/1999"})),
    ]
    for msg, llm in passos:
        estado, dec, _ = turno(estado, msg, llm)
        _assert(estado.get("aguardando") not in {"localizacao", "cep", "rua", "numero"}, (msg, estado.get("aguardando")))
    # Depois da data de nascimento já vem o resumo: CEP, rua e número vieram no primeiro bloco
    _assert(estado.get("aguardando") == "confirmacao_dados", estado.get("aguardando"))
    resumo = montar_resumo_cadastro(estado)
    _assert("• Número: 729\n" in resumo and "• Rua: Rua São Marco" in resumo, resumo)
    _assert("• Complemento: Bloco 04, Apartamento 104" in resumo, resumo)


def test_numero_no_cadastro_nunca_guarda_texto() -> None:
    casos = [
        ("cad/numero", NUMERO_COMO_VEIO, {"numero": NUMERO_COMO_VEIO}, "729"),
        ("cad/numero", "729 bloco 4 apto 104", {"numero": "729 bloco 4 apto 104"}, "729"),
        ("cad/numero", "casa 12 fundos", {"numero": "casa 12 fundos"}, "12"),
        ("cad/numero", "lote 5 quadra 12", {"numero": "lote 5 quadra 12"}, "S/N"),
        ("cad/numero", "729-B", {"numero": "729-B"}, "729B"),
        ("cad/rua", "Rua São Marco, " + NUMERO_COMO_VEIO, {"rua": "Rua São Marco", "numero": NUMERO_COMO_VEIO}, "729"),
    ]
    for est, msg, dados, esperado in casos:
        estado, _, _ = turno(E(est), msg, L(["DADO_INFORMADO"], dados))
        _assert(estado.get("numero") == esperado, (msg, estado.get("numero")))
        _assert(len(str(estado.get("numero"))) <= 7, estado.get("numero"))
    # Só complemento, sem número: guarda o complemento e continua pedindo o número
    estado, _, _ = turno(E("cad/numero"), "bloco B apto 3", L(["DADO_INFORMADO"], {"numero": "bloco B apto 3"}))
    _assert(not estado.get("numero") and estado.get("aguardando") == "numero", (estado.get("numero"), estado.get("aguardando")))
    _assert(estado.get("complemento") == "bloco B apto 3", estado.get("complemento"))


def test_o_que_vai_para_o_ixc_e_sempre_limpo() -> None:
    """Trava final: atendimento antigo com texto no campo número não chega assim ao IXC."""
    antigo = dict(E("cad/confirmacao_dados"), numero=NUMERO_COMO_VEIO, complemento="")
    _assert(numero_e_complemento(antigo) == ("729", "Bloco 04, Apartamento 104 (cond. boulevard tapajós)"), numero_e_complemento(antigo))
    direto = _dados_ixc_direto(antigo)
    _assert(direto["numero"] == "729" and direto["complemento"].startswith("Bloco 04"), direto)
    snap = snapshot_cliente(antigo, incluir_historico=False)
    _assert(snap["numero"] == "729" and snap["numero_endereco"] == "729", (snap["numero"], snap["numero_endereco"]))
    _assert(snap["complemento"].startswith("Bloco 04"), snap["complemento"])
    resumo = montar_resumo_cadastro(antigo)
    _assert("• Número: 729\n" in resumo and "Bloco 04" in resumo.split("Complemento:")[1], resumo)
    # Estado já limpo sai igual
    limpo = dict(E("cad/confirmacao_dados"), numero="10", complemento="casa B")
    _assert(numero_e_complemento(limpo) == ("10", "casa B"), numero_e_complemento(limpo))


def main() -> None:
    tests = [
        test_numero_fica_so_com_o_numero,
        test_bloco_com_rotulos_e_lido_campo_a_campo,
        test_endereco_completo_no_inicio_ja_checa_cobertura,
        test_cadastro_nao_pede_de_novo_o_endereco_ja_informado,
        test_numero_no_cadastro_nunca_guarda_texto,
        test_o_que_vai_para_o_ixc_e_sempre_limpo,
    ]
    falhas = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            falhas += 1
            print(f"  FALHOU {fn.__name__}: {type(e).__name__}: {e}")
    if falhas:
        print(f"\n❌ {falhas} falha(s)")
        sys.exit(1)
    print("\n✅ Endereço OK")


if __name__ == "__main__":
    main()
