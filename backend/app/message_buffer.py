"""Acumula mensagens rápidas do mesmo cliente antes de processar."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Quanto o webhook espera pela resposta além da janela do acumulador
ESPERA_EXTRA_SEGUNDOS = 15.0


class RespostaAtrasada(Exception):
    """O turno ainda está sendo processado: a resposta é enviada quando ficar pronta."""


@dataclass
class _Waiter:
    event: threading.Event
    enviar_resposta: bool = False
    desistiu: bool = False
    ao_atrasar: Callable[[Any], None] | None = None


@dataclass
class _Buffer:
    messages: list[str] = field(default_factory=list)
    timer: threading.Timer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    waiters: list[_Waiter] = field(default_factory=list)
    result: Any = None
    error: BaseException | None = None
    processando: bool = False


_buffers: dict[str, _Buffer] = {}
_meta_lock = threading.Lock()


def chave_buffer(id_cliente: str, conversation_id: str | None = None) -> str:
    """Chave estável por conversa — agrupa mensagens rápidas no mesmo chat."""
    cid = str(conversation_id or "").strip()
    if cid:
        return f"cw:{cid}"
    return str(id_cliente or "").strip() or "anon"


def _get_buffer(chave: str) -> _Buffer:
    with _meta_lock:
        if chave not in _buffers:
            _buffers[chave] = _Buffer()
        return _buffers[chave]


def _juntar_mensagens(mensagens: list[str]) -> str:
    partes = [m.strip() for m in mensagens if m and m.strip()]
    return "\n".join(partes)


def _resolver_mensagens_conflitantes(mensagens: list[str]) -> str:
    """Se a leva mistura confirmação e negação, usa a última intenção."""
    if len(mensagens) <= 1:
        return _juntar_mensagens(mensagens)
    try:
        from app.parser import eh_confirmacao, eh_recusa, normalizar_texto

        tem_conf = any(eh_confirmacao(normalizar_texto(m)) for m in mensagens)
        tem_neg = any(eh_recusa(normalizar_texto(m)) for m in mensagens)
        if tem_conf and tem_neg:
            return mensagens[-1].strip()
    except Exception:
        pass
    return _juntar_mensagens(mensagens)


def processar_com_buffer(
    chave: str,
    mensagem: str,
    process_fn: Callable[[str, str], Any],
    *,
    id_cliente: str | None = None,
    ao_atrasar: Callable[[Any], None] | None = None,
) -> tuple[Any, bool]:
    """
    Debounce: aguarda MESSAGE_BUFFER_SECONDS por novas mensagens
    e processa tudo junto em um único turno.

    Retorna (resultado, enviar_resposta). Só o último webhook da leva
    deve enviar a resposta ao Chatwoot — evita duplicata.

    Se o turno demorar mais que a espera do webhook (modelo lento, cadastro, agenda), levanta
    RespostaAtrasada e, quando o resultado ficar pronto, chama `ao_atrasar(resultado)` — a
    resposta era gerada, aparecia no painel e nunca chegava ao cliente.
    """
    from app.ia_config import resolver_message_buffer_seconds

    buf = _get_buffer(chave)
    waiter = _Waiter(event=threading.Event(), ao_atrasar=ao_atrasar)
    cid = str(id_cliente or chave or "").strip()
    segundos = resolver_message_buffer_seconds()

    with buf.lock:
        buf.messages.append(mensagem.strip())
        buf.waiters.append(waiter)

        if buf.timer is not None:
            buf.timer.cancel()

        def _flush() -> None:
            with buf.lock:
                if buf.processando:
                    buf.timer = threading.Timer(segundos, _flush)
                    buf.timer.start()
                    return
                mensagens = list(buf.messages)
                waiters = list(buf.waiters)
                buf.messages.clear()
                buf.waiters.clear()
                buf.timer = None
                buf.result = None
                buf.error = None
                buf.processando = True

            if waiters:
                waiters[-1].enviar_resposta = True

            combinada = _resolver_mensagens_conflitantes(mensagens)
            resultado = None
            try:
                resultado = process_fn(cid, combinada)
                with buf.lock:
                    buf.result = resultado
            except BaseException as exc:  # noqa: BLE001
                logger.exception("Erro ao processar buffer de mensagens")
                with buf.lock:
                    buf.error = exc
            finally:
                with buf.lock:
                    buf.processando = False
                    # Dentro da trava: quem está desistindo agora ou vê o evento ou já marcou
                    for w in waiters:
                        w.event.set()
                    ultimo = waiters[-1] if waiters else None
                    atrasado = ultimo if ultimo is not None and ultimo.desistiu else None
            if atrasado is not None and resultado is not None and atrasado.ao_atrasar is not None:
                # O webhook que enviaria a resposta já tinha desistido de esperar: envia daqui
                try:
                    atrasado.ao_atrasar(resultado)
                except Exception:  # noqa: BLE001
                    logger.exception("Falha ao enviar a resposta atrasada de %s", cid)

        buf.timer = threading.Timer(segundos, _flush)
        buf.timer.start()

    if not waiter.event.wait(timeout=segundos + ESPERA_EXTRA_SEGUNDOS):
        with buf.lock:
            if not waiter.event.is_set():
                waiter.desistiu = True
                raise RespostaAtrasada("Turno ainda em processamento — a resposta segue quando ficar pronta")

    with buf.lock:
        if buf.error is not None:
            raise buf.error
        return buf.result, waiter.enviar_resposta


def limpar_buffer(chave: str) -> None:
    with _meta_lock:
        buf = _buffers.pop(chave, None)
    if buf and buf.timer:
        buf.timer.cancel()
