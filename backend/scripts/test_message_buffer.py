"""Testa acumulador de mensagens rápidas (debounce)."""

from __future__ import annotations

import sys
import threading
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.message_buffer import limpar_buffer, processar_com_buffer


def test_duas_mensagens_viram_uma() -> None:
    cid = "teste-buffer"
    limpar_buffer(cid)
    processados: list[str] = []
    lock = threading.Lock()

    def _process(_cid: str, msg: str) -> str:
        with lock:
            processados.append(msg)
        return msg

    def _enviar(texto: str) -> None:
        processar_com_buffer(cid, texto, _process)

    t1 = threading.Thread(target=_enviar, args=("E ae",))
    t2 = threading.Thread(target=_enviar, args=("Quero saber se tem disney",))
    t1.start()
    time.sleep(0.8)
    t2.start()
    t1.join(timeout=20)
    t2.join(timeout=20)
    limpar_buffer(cid)

    assert len(processados) == 1, f"esperava 1 processamento, veio {len(processados)}: {processados}"
    combinada = processados[0]
    assert "E ae" in combinada, combinada
    assert "disney" in combinada.casefold(), combinada
    print("  OK test_duas_mensagens_viram_uma")


def main() -> None:
    test_duas_mensagens_viram_uma()
    print("\n✅ Buffer de mensagens OK")


if __name__ == "__main__":
    main()
