"""Testa acumulador de mensagens rápidas (debounce)."""

from __future__ import annotations

import sys
import threading
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.message_buffer import chave_buffer, limpar_buffer, processar_com_buffer


def test_duas_mensagens_viram_uma() -> None:
    cid = "teste-buffer"
    key = chave_buffer(cid, "conv-1")
    limpar_buffer(key)
    processados: list[str] = []
    lock = threading.Lock()

    def _process(_cid: str, msg: str) -> str:
        with lock:
            processados.append(msg)
        return msg

    def _enviar(texto: str) -> None:
        processar_com_buffer(key, texto, _process, id_cliente=cid)

    t1 = threading.Thread(target=_enviar, args=("E ae",))
    t2 = threading.Thread(target=_enviar, args=("Quero saber se tem disney",))
    t1.start()
    time.sleep(0.8)
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)
    limpar_buffer(key)

    assert len(processados) == 1, f"esperava 1 processamento, veio {len(processados)}: {processados}"
    combinada = processados[0]
    assert "E ae" in combinada, combinada
    assert "disney" in combinada.casefold(), combinada
    print("  OK test_duas_mensagens_viram_uma")


def test_apenas_ultimo_waiter_envia_resposta() -> None:
    cid = "teste-buffer-envio"
    key = chave_buffer(cid, "conv-2")
    limpar_buffer(key)
    flags: list[bool] = []
    lock = threading.Lock()

    def _process(_cid: str, msg: str) -> str:
        return msg

    def _enviar(texto: str) -> None:
        _, enviar = processar_com_buffer(key, texto, _process, id_cliente=cid)
        with lock:
            flags.append(enviar)

    t1 = threading.Thread(target=_enviar, args=("oi",))
    t2 = threading.Thread(target=_enviar, args=("boa noite",))
    t1.start()
    time.sleep(0.8)
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)
    limpar_buffer(key)

    assert len(flags) == 2, flags
    assert sum(1 for f in flags if f) == 1, f"só 1 webhook deve enviar: flags={flags}"
    print("  OK test_apenas_ultimo_waiter_envia_resposta")


def main() -> None:
    test_duas_mensagens_viram_uma()
    test_apenas_ultimo_waiter_envia_resposta()
    print("\n✅ Buffer de mensagens OK")


if __name__ == "__main__":
    main()
