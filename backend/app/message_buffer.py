"""Acumula mensagens rápidas do mesmo cliente antes de processar."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class _Waiter:
    event: threading.Event
    enviar_resposta: bool = False


@dataclass
class _Buffer:
    messages: list[str] = field(default_factory=list)
    timer: threading.Timer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    waiters: list[_Waiter] = field(default_factory=list)
    result: Any = None
    error: BaseException | None = None


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


def processar_com_buffer(
    chave: str,
    mensagem: str,
    process_fn: Callable[[str, str], Any],
    *,
    id_cliente: str | None = None,
) -> tuple[Any, bool]:
    """
    Debounce: aguarda MESSAGE_BUFFER_SECONDS por novas mensagens
    e processa tudo junto em um único turno.

    Retorna (resultado, enviar_resposta). Só o último webhook da leva
    deve enviar a resposta ao Chatwoot — evita duplicata.
    """
    from app.ia_config import resolver_message_buffer_seconds

    buf = _get_buffer(chave)
    waiter = _Waiter(event=threading.Event())
    cid = str(id_cliente or chave or "").strip()
    segundos = resolver_message_buffer_seconds()

    with buf.lock:
        buf.messages.append(mensagem.strip())
        buf.waiters.append(waiter)

        if buf.timer is not None:
            buf.timer.cancel()

        def _flush() -> None:
            with buf.lock:
                mensagens = list(buf.messages)
                waiters = list(buf.waiters)
                buf.messages.clear()
                buf.waiters.clear()
                buf.timer = None
                buf.result = None
                buf.error = None

            if waiters:
                waiters[-1].enviar_resposta = True

            combinada = _juntar_mensagens(mensagens)
            try:
                resultado = process_fn(cid, combinada)
                with buf.lock:
                    buf.result = resultado
            except BaseException as exc:  # noqa: BLE001
                logger.exception("Erro ao processar buffer de mensagens")
                with buf.lock:
                    buf.error = exc
            finally:
                for w in waiters:
                    w.event.set()

        buf.timer = threading.Timer(segundos, _flush)
        buf.timer.start()

    if not waiter.event.wait(timeout=segundos + 15):
        raise TimeoutError("Tempo esgotado aguardando acumulador de mensagens")

    with buf.lock:
        if buf.error is not None:
            raise buf.error
        return buf.result, waiter.enviar_resposta


def limpar_buffer(chave: str) -> None:
    with _meta_lock:
        buf = _buffers.pop(chave, None)
    if buf and buf.timer:
        buf.timer.cancel()
