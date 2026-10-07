# -*- coding: utf-8 -*-
"""Transcrição de áudio — o áudio do cliente vira texto antes de a Eva interpretar.

Sem rede: o download do Chatwoot e a chamada à API de transcrição são simulados.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import test_auditoria_interpretacao as aud  # bloqueia a rede e simula as integrações

from app import chatwoot_config, main, response, transcricao
from app.chatwoot_webhook import analisar_evento_chatwoot

URL_AUDIO = "https://chatwoot.mov.pro.br/rails/active_storage/blobs/redirect/abc/audio.oga"


def _assert(cond: bool, msg: object) -> None:
    if not cond:
        raise AssertionError(msg)


class _Simular:
    """Troca a chave, o download e a API de transcrição por versões de teste."""

    def __init__(self, *, chave: str = "gsk_teste", texto: str = "", erro: Exception | None = None,
                 fase: str = "cadastro"):
        self.chave, self.texto, self.erro, self.fase = chave, texto, erro, fase
        self.envios: list[dict] = []
        self.downloads: list[str] = []

    def __enter__(self):
        self._antes = (transcricao.chave_de_transcricao, transcricao._baixar_audio,
                       transcricao._enviar_para_transcricao, main.__dict__.get("db"))
        transcricao.chave_de_transcricao = lambda **k: self.chave

        def baixar(url):
            self.downloads.append(url)
            return b"OggS-bytes-de-audio", "audio/ogg"

        def enviar(conteudo, nome, tipo, **k):
            self.envios.append({"nome": nome, "tipo": tipo, **k})
            if self.erro:
                raise self.erro
            return self.texto

        transcricao._baixar_audio = baixar
        transcricao._enviar_para_transcricao = enviar
        from app import db

        self._carregar = db.carregar_ou_criar_estado
        db.carregar_ou_criar_estado = lambda id_cliente: {"id_cliente": id_cliente, "fase": self.fase}
        return self

    def __exit__(self, *exc):
        from app import db

        (transcricao.chave_de_transcricao, transcricao._baixar_audio,
         transcricao._enviar_para_transcricao, _) = self._antes
        db.carregar_ou_criar_estado = self._carregar


def _payload_audio(**extra) -> dict:
    p = chatwoot_config.payload_exemplo_message_created()
    p["content"] = None
    p["attachments"] = [{"id": 1, "file_type": "audio", "data_url": URL_AUDIO, "file_size": 12000}]
    p.update(extra)
    return p


def test_evento_de_audio_traz_o_endereco() -> None:
    evento = analisar_evento_chatwoot(_payload_audio())["evento"]
    _assert(evento["mensagem"] == "[audio]" and evento["audio_url"] == URL_AUDIO, evento)
    # Mensagem de texto e imagem não têm áudio para transcrever
    texto = analisar_evento_chatwoot(chatwoot_config.payload_exemplo_message_created())["evento"]
    _assert(texto["audio_url"] is None, texto)
    img = _payload_audio()
    img["attachments"][0]["file_type"] = "image"
    _assert(analisar_evento_chatwoot(img)["evento"]["audio_url"] is None, "imagem")


def test_provedor_sai_do_prefixo_da_chave() -> None:
    nome, url, modelo = transcricao.provedor_da_chave("gsk_abc")
    _assert(nome == "groq" and "api.groq.com" in url and modelo.startswith("whisper"), (nome, url, modelo))
    nome, url, modelo = transcricao.provedor_da_chave("sk-abc")
    _assert(nome == "openai" and "api.openai.com" in url, (nome, url))


def test_audio_transcrito_vira_a_mensagem_do_cliente() -> None:
    evento = {"id_cliente": "t", "mensagem": "[audio]", "audio_url": URL_AUDIO}
    with _Simular(texto="  Meu nome é Maria Souza,\n CPF 529 982 247 25 ") as sim:
        sinais = main._transcrever_se_for_audio(evento)
    _assert(sinais == ["audio_transcrito"], sinais)
    _assert(evento["mensagem"] == "Meu nome é Maria Souza, CPF 529 982 247 25", evento["mensagem"])
    envio = sim.envios[0]
    # WhatsApp manda .oga; a API só aceita o nome .ogg
    _assert(envio["nome"] == "audio.ogg" and envio["tipo"] == "audio/ogg", envio)
    _assert(envio["chave"] == "gsk_teste" and "groq" in envio["url_api"], envio)
    _assert(sim.downloads == [URL_AUDIO], sim.downloads)


def test_falha_mantem_audio_e_a_eva_pede_texto() -> None:
    for sim in (
        _Simular(erro=RuntimeError("503 da API")),
        _Simular(texto=""),                                   # áudio mudo
        _Simular(texto="Legendas pela comunidade Amara.org"),  # o que o Whisper inventa em silêncio
        _Simular(chave=""),                                   # sem chave em Config IA
    ):
        evento = {"id_cliente": "t", "mensagem": "[audio]", "audio_url": URL_AUDIO}
        with sim:
            sinais = main._transcrever_se_for_audio(evento)
        _assert(sinais == ["audio_nao_transcrito"] and evento["mensagem"] == "[audio]", (sinais, evento))
    # E o atendimento segue: a Eva avisa que não ouviu e retoma o pedido
    estado, dec, _ = aud.turno(aud.E("cad/nome"), "[audio]", aud.L(["OUTRO"], {}))
    texto = response.gerar_resposta(dec, estado, historico=[], mensagem_cliente="[audio]")
    _assert("áudio" in texto and "nome" in texto.casefold(), texto)


def test_nao_transcreve_o_que_nao_precisa() -> None:
    with _Simular(texto="oi") as sim:
        # Texto normal, imagem e mensagem sem endereço de áudio
        for evento in (
            {"id_cliente": "t", "mensagem": "oi", "audio_url": URL_AUDIO},
            {"id_cliente": "t", "mensagem": "[image]", "audio_url": URL_AUDIO},
            {"id_cliente": "t", "mensagem": "[audio]", "audio_url": None},
        ):
            _assert(main._transcrever_se_for_audio(evento) == [], evento)
        _assert(not sim.downloads, sim.downloads)
    # Conversa já com a equipe: a Eva não responde, então não gasta transcrição
    with _Simular(texto="oi", fase="transferido") as sim:
        evento = {"id_cliente": "t", "mensagem": "[audio]", "audio_url": URL_AUDIO}
        _assert(main._transcrever_se_for_audio(evento) == [] and not sim.downloads, sim.downloads)


def test_so_baixa_de_endereco_permitido() -> None:
    for url, ok in (
        (URL_AUDIO, True),
        ("https://bucket.s3.amazonaws.com/audio.ogg", True),
        ("http://chatwoot.mov.pro.br/audio.ogg", True),   # host do Chatwoot configurado
        ("http://169.254.169.254/latest/meta-data", False),
        ("file:///etc/passwd", False),
        ("ftp://x/audio.ogg", False),
        ("", False),
    ):
        _assert(transcricao._url_permitida(url) is ok, (url, ok))
    with _Simular(texto="oi") as sim:
        r = transcricao.transcrever_audio("http://169.254.169.254/latest/meta-data")
        _assert(not r["ok"] and not sim.downloads, r)


def test_nome_e_tipo_do_arquivo() -> None:
    casos = {
        ("https://x/a/audio.oga", "audio/ogg"): ("audio.ogg", "audio/ogg"),
        ("https://x/a/voz.mp3", ""): ("audio.mp3", "audio/mpeg"),
        ("https://x/blobs/redirect/abc", "audio/mp4; codecs=aac"): ("audio.m4a", "audio/mp4"),
        ("https://x/blobs/redirect/abc", "application/octet-stream"): ("audio.ogg", "audio/ogg"),
    }
    for (url, tipo), esperado in casos.items():
        _assert(transcricao._nome_do_arquivo(url, tipo) == esperado, (url, transcricao._nome_do_arquivo(url, tipo)))


def main_() -> None:
    tests = [
        test_evento_de_audio_traz_o_endereco,
        test_provedor_sai_do_prefixo_da_chave,
        test_audio_transcrito_vira_a_mensagem_do_cliente,
        test_falha_mantem_audio_e_a_eva_pede_texto,
        test_nao_transcreve_o_que_nao_precisa,
        test_so_baixa_de_endereco_permitido,
        test_nome_e_tipo_do_arquivo,
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
    print("\n✅ Transcrição OK")


if __name__ == "__main__":
    main_()
