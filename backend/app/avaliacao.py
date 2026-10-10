"""Avaliação do interpretador com o modelo real, disparada pelo painel.

Os testes do repositório simulam a leitura do modelo; só esta avaliação mede o que o
modelo configurado em Config IA realmente devolve. Antes ela só rodava no console do
container (`python scripts/eval_interpretador.py rodar`). Aqui a mesma rotina roda em
segundo plano e o último resultado fica guardado para a aba Pontos de atenção.

Cada caso é uma chamada ao modelo: rodar custa o equivalente a ~75 mensagens de cliente.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

CHAVE_RESULTADO = "avaliacao_interpretador"
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_BACKEND, "scripts", "eval_interpretador.py")

_lock = threading.Lock()
_andamento: dict[str, Any] = {"rodando": False, "feitos": 0, "total": 0, "erro": ""}


def _avaliador() -> Any:
    spec = importlib.util.spec_from_file_location("eval_interpretador", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"avaliador não encontrado em {_SCRIPT}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _resultado(mod: Any, resultados: list[dict[str, Any]]) -> dict[str, Any]:
    from app.llm import modelo_ativo

    def item(r: dict[str, Any], chave: str) -> dict[str, Any]:
        return {
            "id": r.get("id"),
            "etapa": f"{r.get('fase') or ''}/{r.get('aguardando') or ''}".strip("/"),
            "mensagem": str(r.get("mensagem") or "")[:160],
            "problemas": list(r.get(chave) or []),
        }

    return {
        "quando": datetime.now(timezone.utc).isoformat(),
        "modelo": modelo_ativo(),
        "resumo": mod.resumir(resultados),
        "erros": [item(r, "problemas_final") for r in resultados if r.get("problemas_final")],
        "modelo_errou_regras_consertaram": [
            item(r, "problemas_llm")
            for r in resultados
            if r.get("problemas_llm") and not r.get("problemas_final")
        ],
    }


def _rodar() -> None:
    from app import admin_store

    try:
        from app import custos

        mod = _avaliador()
        casos = mod.carregar_casos(mod.CASOS_PADRAO)
        with _lock:
            _andamento.update(feitos=0, total=len(casos), erro="")
        resultados: list[dict[str, Any]] = []
        for caso in casos:
            custos.definir_cliente("")  # avaliação não é atendimento de cliente
            resultados.append(mod.avaliar_caso(caso))
            with _lock:
                _andamento["feitos"] = len(resultados)
        admin_store.set_config(
            CHAVE_RESULTADO, json.dumps(_resultado(mod, resultados), ensure_ascii=False)
        )
    except Exception as exc:  # noqa: BLE001 — o erro aparece no painel, não derruba a API
        logger.exception("Avaliação do interpretador falhou")
        with _lock:
            _andamento["erro"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        with _lock:
            _andamento["rodando"] = False


def iniciar() -> dict[str, Any]:
    """Dispara a avaliação em segundo plano (uma por vez)."""
    with _lock:
        if _andamento["rodando"]:
            return status()
        _andamento.update(rodando=True, feitos=0, total=0, erro="")
    threading.Thread(target=_rodar, daemon=True, name="avaliacao-interpretador").start()
    return status()


def status() -> dict[str, Any]:
    from app import admin_store

    ultimo = None
    bruto = admin_store.get_config(CHAVE_RESULTADO, "")
    if bruto:
        try:
            ultimo = json.loads(bruto)
        except ValueError:
            ultimo = None
    return {**_andamento, "ultimo": ultimo}
