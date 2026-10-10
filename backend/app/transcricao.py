"""Transcrição de áudio do cliente — o áudio vira texto antes de a Eva interpretar.

O Chatwoot entrega o áudio do WhatsApp como anexo (`data_url`). Aqui ele é baixado e
enviado à API de transcrição cuja chave está em Config IA ("API Key transcrição de
áudio"). O provedor sai do prefixo da chave: `gsk_` é Groq; as demais usam a OpenAI.

Qualquer falha devolve `ok=False`: a mensagem segue como `[audio]` e a Eva pede para
o cliente escrever (ver `app/conversa.py`, situação MIDIA).
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Limite das APIs de transcrição é 25 MB; áudio de WhatsApp raramente passa de 2 MB
MAX_BYTES_AUDIO = 20 * 1024 * 1024
TIMEOUT_DOWNLOAD = 30.0
TIMEOUT_TRANSCRICAO = 60.0

_PROVEDORES = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "whisper-large-v3-turbo"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "whisper-1"),
}
_EXTENSOES_ACEITAS = {"flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "opus", "wav", "webm"}
_TIPO_POR_EXTENSAO = {
    "ogg": "audio/ogg", "opus": "audio/ogg", "mp3": "audio/mpeg", "mpeg": "audio/mpeg",
    "mpga": "audio/mpeg", "m4a": "audio/mp4", "mp4": "audio/mp4", "wav": "audio/wav",
    "webm": "audio/webm", "flac": "audio/flac",
}
# O Whisper "ouve" estas frases em áudio mudo ou só com ruído
_RE_ALUCINACAO = re.compile(
    r"^\W*(legendas? (pela|por|da) comunidade.*|.*amara\.org.*|obrigad[oa] por assistir.*|"
    r"inscreva-se no canal.*|tchau,? tchau\W*)$",
    re.I,
)


def chave_de_transcricao(*, unidade_id: int | None = None) -> str:
    from app import ia_config

    return ia_config._cfg("transcription_api_key", "", unidade_id=unidade_id).strip()


def provedor_da_chave(chave: str) -> tuple[str, str, str]:
    """(nome, url, modelo) pelo prefixo da chave."""
    from app import ia_config

    nome = "groq" if chave.startswith("gsk_") else "openai"
    url, modelo = _PROVEDORES[nome]
    # Config opcional (sem campo no painel) para trocar o modelo sem novo deploy
    return nome, url, ia_config._cfg("transcription_model", "").strip() or modelo


def _url_permitida(url: str) -> bool:
    """Só baixa de http(s). Fora do host do Chatwoot, exige https (armazenamento externo)."""
    try:
        partes = urlparse(url)
    except ValueError:
        return False
    if partes.scheme not in {"http", "https"} or not partes.hostname:
        return False
    from app.chatwoot_config import resolver_chatwoot_base_url

    host_chatwoot = urlparse(resolver_chatwoot_base_url()).hostname or ""
    if partes.hostname == host_chatwoot:
        return True
    # Endereço numérico interno (metadados de nuvem, localhost, rede privada) nunca é anexo
    try:
        ip = ipaddress.ip_address(partes.hostname)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        return False
    return partes.scheme == "https"


def _nome_do_arquivo(url: str, content_type: str) -> tuple[str, str]:
    """Nome e tipo que a API de transcrição aceita (áudio do WhatsApp chega como .oga/.ogg)."""
    ext = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
    if ext == "oga":
        ext = "ogg"
    if ext not in _EXTENSOES_ACEITAS:
        tipo = (content_type or "").split(";")[0].strip().lower()
        ext = next((e for e, t in _TIPO_POR_EXTENSAO.items() if t == tipo), "ogg")
    return f"audio.{ext}", _TIPO_POR_EXTENSAO.get(ext, "audio/ogg")


def _baixar_audio(url: str) -> tuple[bytes, str]:
    """Bytes do áudio e o content-type. Para de ler se passar do limite de tamanho."""
    partes: list[bytes] = []
    total = 0
    with httpx.Client(timeout=TIMEOUT_DOWNLOAD, follow_redirects=True) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            for bloco in resp.iter_bytes():
                total += len(bloco)
                if total > MAX_BYTES_AUDIO:
                    raise ValueError("áudio maior que o limite de transcrição")
                partes.append(bloco)
    return b"".join(partes), content_type


def _enviar_para_transcricao(
    conteudo: bytes, nome: str, tipo: str, *, chave: str, url_api: str, modelo: str
) -> tuple[str, float]:
    """(texto, duração em segundos)."""
    with httpx.Client(timeout=TIMEOUT_TRANSCRICAO) as client:
        resp = client.post(
            url_api,
            headers={"Authorization": f"Bearer {chave}"},
            # verbose_json traz a duração do áudio, que é a base da cobrança
            data={"model": modelo, "language": "pt", "response_format": "verbose_json", "temperature": "0"},
            files={"file": (nome, conteudo, tipo)},
        )
        resp.raise_for_status()
        corpo = resp.json() or {}
        return str(corpo.get("text") or ""), float(corpo.get("duration") or 0)


def transcrever_audio(
    url: str, *, unidade_id: int | None = None, id_cliente: str = ""
) -> dict[str, Any]:
    """Texto do áudio em `url`. Nunca levanta exceção: devolve {ok, texto, motivo, provedor}."""
    chave = chave_de_transcricao(unidade_id=unidade_id)
    if not chave:
        return {"ok": False, "texto": "", "motivo": "sem chave de transcrição em Config IA"}
    if not _url_permitida(url):
        return {"ok": False, "texto": "", "motivo": "endereço do áudio não permitido"}
    provedor, url_api, modelo = provedor_da_chave(chave)
    try:
        conteudo, content_type = _baixar_audio(url)
        if not conteudo:
            return {"ok": False, "texto": "", "motivo": "áudio vazio", "provedor": provedor}
        nome, tipo = _nome_do_arquivo(url, content_type)
        retorno = _enviar_para_transcricao(
            conteudo, nome, tipo, chave=chave, url_api=url_api, modelo=modelo
        )
        texto, duracao = retorno if isinstance(retorno, tuple) else (retorno, 0.0)
        # Sem a duração na resposta, estima pelo tamanho (áudio de WhatsApp ~3 KB por segundo)
        from app import custos

        custos.registrar_transcricao(
            provedor, modelo, duracao or len(conteudo) / 3000, id_cliente=id_cliente
        )
    except Exception as exc:  # noqa: BLE001 — falha de rede ou da API não derruba o atendimento
        logger.warning("Transcrição de áudio falhou (%s): %s", provedor, exc)
        return {"ok": False, "texto": "", "motivo": f"falha na transcrição: {exc}"[:200],
                "provedor": provedor}

    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto or _RE_ALUCINACAO.match(texto):
        return {"ok": False, "texto": "", "motivo": "áudio sem fala reconhecível", "provedor": provedor}
    return {"ok": True, "texto": texto[:2000], "motivo": "", "provedor": provedor}
