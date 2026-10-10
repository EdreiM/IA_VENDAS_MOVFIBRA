"""Custo da IA — quanto cada chamada ao modelo custou, por cliente e por finalidade.

A API de custos da OpenAI exige chave de administrador e não separa por cliente. Mas
toda resposta do modelo traz quantos tokens foram usados; aqui cada chamada é gravada
(`uso_ia`) com o cliente do turno, a finalidade e o custo em dólar, calculado pela
tabela de preços configurada no painel. A transcrição de áudio entra pelo tempo de áudio.

É uma estimativa fiel à fatura enquanto a tabela de preços estiver atualizada — a fatura
da OpenAI continua sendo a referência. Só há dados a partir do deploy deste módulo.

Registrar o custo nunca derruba o atendimento: qualquer erro aqui é só registrado em log.
"""

from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

CHAVE_CONFIG = "custos_config"

# US$ por 1 milhão de tokens (entrada, entrada em cache, saída). Confira em
# https://platform.openai.com/docs/pricing — os valores ficam editáveis no painel.
PRECOS_PADRAO: dict[str, dict[str, float]] = {
    "gpt-4.1": {"entrada": 2.00, "cache": 0.50, "saida": 8.00},
    "gpt-4.1-mini": {"entrada": 0.40, "cache": 0.10, "saida": 1.60},
    "gpt-4.1-nano": {"entrada": 0.10, "cache": 0.025, "saida": 0.40},
    "gpt-4o": {"entrada": 2.50, "cache": 1.25, "saida": 10.00},
    "gpt-4o-mini": {"entrada": 0.15, "cache": 0.075, "saida": 0.60},
}
# US$ por hora de áudio transcrito
TRANSCRICAO_PADRAO: dict[str, float] = {"groq": 0.04, "openai": 0.36}
# A Groq cobra no mínimo 10 segundos por áudio
MINIMO_SEGUNDOS_AUDIO = {"groq": 10.0}
COTACAO_PADRAO = 5.50  # R$ por US$ — editável no painel

_cliente: ContextVar[str] = ContextVar("custos_cliente", default="")
_finalidade: ContextVar[str] = ContextVar("custos_finalidade", default="")
_cache_config: dict[str, Any] = {"quando": 0.0, "valor": None}
_TTL_CONFIG = 60.0


def definir_cliente(id_cliente: str | None) -> None:
    """De quem é o turno em andamento (chamado no começo de cada mensagem processada)."""
    _cliente.set(str(id_cliente or ""))


def marcar(finalidade: str) -> None:
    """Para que serve a próxima chamada ao modelo: interpretador, resposta, consultor, avaliacao."""
    _finalidade.set(finalidade)


# ── Configuração de preços ───────────────────────────────────────────────────


def _numero(valor: Any, padrao: float) -> float:
    try:
        n = float(str(valor).replace(",", "."))
        return n if n >= 0 else padrao
    except (TypeError, ValueError):
        return padrao


def configuracao(*, usar_cache: bool = True) -> dict[str, Any]:
    """Cotação do dólar e preços por modelo: o que está no painel por cima dos padrões."""
    agora = time.time()
    if usar_cache and _cache_config["valor"] is not None and agora - _cache_config["quando"] < _TTL_CONFIG:
        return _cache_config["valor"]
    salvo: dict[str, Any] = {}
    try:
        from app import admin_store

        bruto = admin_store.get_config(CHAVE_CONFIG, "")
        salvo = json.loads(bruto) if bruto else {}
    except Exception:  # noqa: BLE001 — sem banco, valem os padrões
        salvo = {}
    modelos = {m: dict(p) for m, p in PRECOS_PADRAO.items()}
    for modelo, preco in (salvo.get("modelos") or {}).items():
        if isinstance(preco, dict):
            base = modelos.get(str(modelo), {"entrada": 0.0, "cache": 0.0, "saida": 0.0})
            modelos[str(modelo)] = {
                "entrada": _numero(preco.get("entrada"), base["entrada"]),
                "cache": _numero(preco.get("cache"), base["cache"]),
                "saida": _numero(preco.get("saida"), base["saida"]),
            }
    transcricao = dict(TRANSCRICAO_PADRAO)
    for prov, valor in (salvo.get("transcricao_usd_hora") or {}).items():
        transcricao[str(prov)] = _numero(valor, transcricao.get(str(prov), 0.0))
    cfg = {
        "cotacao_dolar": _numero(salvo.get("cotacao_dolar"), COTACAO_PADRAO) or COTACAO_PADRAO,
        "modelos": modelos,
        "transcricao_usd_hora": transcricao,
    }
    _cache_config.update(quando=agora, valor=cfg)
    return cfg


def salvar_configuracao(dados: dict[str, Any]) -> dict[str, Any]:
    from app import admin_store

    atual = configuracao(usar_cache=False)
    novo = {
        "cotacao_dolar": _numero(dados.get("cotacao_dolar"), atual["cotacao_dolar"]) or COTACAO_PADRAO,
        "modelos": {},
        "transcricao_usd_hora": {},
    }
    for modelo, preco in (dados.get("modelos") or {}).items():
        nome = str(modelo).strip()
        if nome and isinstance(preco, dict):
            novo["modelos"][nome] = {
                "entrada": _numero(preco.get("entrada"), 0.0),
                "cache": _numero(preco.get("cache"), 0.0),
                "saida": _numero(preco.get("saida"), 0.0),
            }
    for prov, valor in (dados.get("transcricao_usd_hora") or {}).items():
        novo["transcricao_usd_hora"][str(prov)] = _numero(valor, 0.0)
    admin_store.set_config(CHAVE_CONFIG, json.dumps(novo, ensure_ascii=False))
    _cache_config.update(quando=0.0, valor=None)
    return configuracao(usar_cache=False)


def preco_do_modelo(modelo: str, cfg: dict[str, Any] | None = None) -> dict[str, float] | None:
    """Preço do modelo; "gpt-4.1-mini-2025-04-14" usa o de "gpt-4.1-mini" (prefixo mais longo)."""
    modelos = (cfg or configuracao())["modelos"]
    nome = str(modelo or "").strip().lower()
    if nome in modelos:
        return modelos[nome]
    candidatos = [m for m in modelos if nome.startswith(m.lower())]
    return modelos[max(candidatos, key=len)] if candidatos else None


def custo_de_tokens(
    modelo: str, entrada: int, cache: int, saida: int, cfg: dict[str, Any] | None = None
) -> float | None:
    """US$ da chamada. None quando o modelo não tem preço cadastrado."""
    preco = preco_do_modelo(modelo, cfg)
    if preco is None:
        return None
    sem_cache = max(0, int(entrada) - int(cache))
    return (
        sem_cache * preco["entrada"] + int(cache) * preco["cache"] + int(saida) * preco["saida"]
    ) / 1_000_000


# ── Registro ─────────────────────────────────────────────────────────────────


def _gravar(**campos: Any) -> None:
    try:
        from app import db

        explicito = campos.pop("id_cliente", "")
        finalidade = campos.pop("finalidade", "")
        db.registrar_uso_ia(
            id_cliente=explicito or _cliente.get() or None,
            finalidade=finalidade or _finalidade.get() or "outro",
            **campos,
        )
    except Exception:  # noqa: BLE001 — custo é registro; nunca derruba o atendimento
        logger.warning("Falha ao registrar uso da IA", exc_info=True)


def registrar_chat(provedor: str, modelo: str, usage: Any) -> None:
    """Grava os tokens de uma chamada de chat (objeto `usage` da resposta do modelo)."""
    if usage is None:
        return
    entrada = int(getattr(usage, "prompt_tokens", 0) or 0)
    saida = int(getattr(usage, "completion_tokens", 0) or 0)
    detalhes = getattr(usage, "prompt_tokens_details", None)
    cache = int(getattr(detalhes, "cached_tokens", 0) or 0) if detalhes is not None else 0
    custo = 0.0 if provedor == "ollama" else custo_de_tokens(modelo, entrada, cache, saida)
    _gravar(
        provedor=provedor, modelo=modelo, tokens_entrada=entrada, tokens_cache=cache,
        tokens_saida=saida, segundos_audio=None, custo_usd=custo,
    )


def registrar_transcricao(provedor: str, modelo: str, segundos: float, *, id_cliente: str = "") -> None:
    """Grava uma transcrição de áudio; o custo é por tempo de áudio."""
    cobrados = max(float(segundos or 0), MINIMO_SEGUNDOS_AUDIO.get(provedor, 0.0))
    por_hora = configuracao()["transcricao_usd_hora"].get(provedor)
    custo = None if por_hora is None else cobrados / 3600 * float(por_hora)
    _gravar(
        id_cliente=id_cliente, finalidade="transcricao", provedor=provedor, modelo=modelo,
        tokens_entrada=0, tokens_cache=0, tokens_saida=0, segundos_audio=cobrados, custo_usd=custo,
    )
