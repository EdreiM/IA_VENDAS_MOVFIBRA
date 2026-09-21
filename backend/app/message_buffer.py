"""Acumula mensagens rápidas do mesmo cliente antes de processar."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class _Buffer:
    messages: list[str] = field(default_factory=list)
    timer: threading.Timer | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    waiters: list[threading.Event] = field(default_factory=list)
    result: Any = None
    error: BaseException | None = None


_buffers: dict[str, _Buffer] = {}
_meta_lock = threading.Lock()


def _get_buffer(id_cliente: str) -> _Buffer:
    with _meta_lock:
        if id_cliente not in _buffers:
            _buffers[id_cliente] = _Buffer()
        return _buffers[id_cliente]


def _juntar_mensagens(mensagens: list[str]) -> str:
    partes = [m.strip() for m in mensagens if m and m.strip()]
    return "\n".join(partes)


def processar_com_buffer(
    id_cliente: str,
    mensagem: str,
    process_fn: Callable[[str, str], Any],
) -> Any:
    """
    Debounce: aguarda MESSAGE_BUFFER_SECONDS por novas mensagens
    e processa tudo junto em um único turno.
    """
    settings = get_settings()
    if not settings.message_buffer_enabled:
        return process_fn(id_cliente, mensagem)

    buf = _get_buffer(id_cliente)
    evento = threading.Event()
    segundos = max(0.5, float(settings.message_buffer_seconds))

    with buf.lock:
        buf.messages.append(mensagem.strip())
        buf.waiters.append(evento)

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

            combinada = _juntar_mensagens(mensagens)
            try:
                resultado = process_fn(id_cliente, combinada)
                with buf.lock:
                    buf.result = resultado
            except BaseException as exc:  # noqa: BLE001
                logger.exception("Erro ao processar buffer de mensagens")
                with buf.lock:
                    buf.error = exc
            finally:
                for ev in waiters:
                    ev.set()

        buf.timer = threading.Timer(segundos, _flush)
        buf.timer.start()

    if not evento.wait(timeout=segundos + 15):
        raise TimeoutError("Tempo esgotado aguardando acumulador de mensagens")

    with buf.lock:
        if buf.error is not None:
            raise buf.error
        return buf.result


def limpar_buffer(id_cliente: str) -> None:
    with _meta_lock:
        buf = _buffers.pop(id_cliente, None)
    if buf and buf.timer:
        buf.timer.cancel()
