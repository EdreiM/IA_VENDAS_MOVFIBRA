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
import threading
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
COTACAO_PADRAO = 5.00  # R$ por US$ — só vale até a primeira busca automática dar certo

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
    cotacao = _numero(salvo.get("cotacao_dolar"), COTACAO_PADRAO) or COTACAO_PADRAO
    # O que foi buscado automaticamente vale mais que padrão e que valor digitado
    auto = referencias()
    for modelo, preco in (auto.get("modelos") or {}).items():
        if isinstance(preco, dict):
            modelos[str(modelo)] = {
                "entrada": _numero(preco.get("entrada"), 0.0),
                "cache": _numero(preco.get("cache"), 0.0),
                "saida": _numero(preco.get("saida"), 0.0),
            }
    if isinstance(auto.get("cotacao"), dict):
        cotacao = _numero(auto["cotacao"].get("valor"), cotacao) or cotacao
    cfg = {
        "cotacao_dolar": cotacao,
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
        # A cotação do dia fica gravada com a chamada: o custo em reais de um mês não
        # muda quando o dólar mudar depois.
        campos["cotacao_brl"] = configuracao()["cotacao_dolar"]
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


# ── Cotação e preços buscados automaticamente ────────────────────────────────
#
# Ninguém precisa digitar preço: uma vez por dia o backend busca
#   - a cotação do dólar no Banco Central (PTAX de venda), com a AwesomeAPI de reserva;
#   - o preço por token de cada modelo em uso no OpenRouter, que publica a tabela da
#     própria OpenAI (a OpenAI não tem API pública de preços).
# Se uma busca falhar, vale o último valor guardado. A transcrição da Groq não tem
# fonte pública consultável e fica no valor padrão.

CHAVE_AUTO = "custos_auto"
INTERVALO_ATUALIZACAO = 12 * 3600  # segundos
_URL_PTAX = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
_URL_AWESOME = "https://economia.awesomeapi.com.br/json/last/USD-BRL"
_URL_OPENROUTER = "https://openrouter.ai/api/v1/models/openai/{modelo}/endpoints"
_atualizando = threading.Lock()


def _http_json(url: str, params: dict[str, str] | None = None) -> Any:
    import httpx

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        resp = client.get(url, params=params, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


def buscar_cotacao() -> dict[str, Any] | None:
    """Dólar em reais: PTAX de venda do Banco Central; se falhar, AwesomeAPI."""
    from datetime import datetime, timedelta, timezone

    hoje = datetime.now(timezone.utc)
    try:
        # URL montada à mão: o Banco Central recusa o espaço do $orderby codificado como "+"
        inicio = (hoje - timedelta(days=10)).strftime("%m-%d-%Y")  # cobre fim de semana e feriado
        dados = _http_json(
            f"{_URL_PTAX}?@dataInicial='{inicio}'&@dataFinalCotacao='{hoje.strftime('%m-%d-%Y')}'"
            "&$format=json&$orderby=dataHoraCotacao%20desc&$top=1"
        )
        item = (dados.get("value") or [])[0]
        valor = float(item["cotacaoVenda"])
        if 1.0 < valor < 20.0:
            return {"valor": round(valor, 4), "data": str(item.get("dataHoraCotacao") or "")[:10],
                    "fonte": "Banco Central (PTAX venda)"}
    except Exception:  # noqa: BLE001
        logger.warning("Cotação PTAX indisponível; tentando a reserva", exc_info=True)
    try:
        item = _http_json(_URL_AWESOME)["USDBRL"]
        valor = float(item["ask"])
        if 1.0 < valor < 20.0:
            return {"valor": round(valor, 4), "data": str(item.get("create_date") or "")[:10],
                    "fonte": "AwesomeAPI"}
    except Exception:  # noqa: BLE001
        logger.warning("Cotação de reserva indisponível", exc_info=True)
    return None


def _modelo_base(modelo: str) -> str:
    """ "gpt-4.1-mini-2025-04-14" → "gpt-4.1-mini" (o nome com data usa o preço do modelo)."""
    import re

    return re.sub(r"-\d{4}-\d{2}-\d{2}$", "", str(modelo or "").strip().lower())


def buscar_preco_do_modelo(modelo: str) -> dict[str, float] | None:
    """US$ por 1 milhão de tokens do modelo, pela tabela da OpenAI publicada no OpenRouter."""
    base = _modelo_base(modelo)
    if not base or "/" in base or " " in base:
        return None
    try:
        dados = _http_json(_URL_OPENROUTER.format(modelo=base))
        endpoints = (dados.get("data") or {}).get("endpoints") or []
        oficiais = [e for e in endpoints if str(e.get("provider_name") or "").lower() == "openai"] or endpoints
        preco = (oficiais[0].get("pricing") or {}) if oficiais else {}
        entrada = float(preco["prompt"]) * 1_000_000
        saida = float(preco["completion"]) * 1_000_000
        cache = float(preco.get("input_cache_read") or preco["prompt"]) * 1_000_000
    except Exception:  # noqa: BLE001
        logger.warning("Preço do modelo %s indisponível", base, exc_info=True)
        return None
    # Faixa plausível: evita gravar lixo se a fonte mudar de formato
    if not (0 < entrada < 500 and 0 < saida < 2000 and 0 <= cache <= entrada):
        return None
    return {"entrada": round(entrada, 6), "cache": round(cache, 6), "saida": round(saida, 6)}


def referencias() -> dict[str, Any]:
    """O que foi buscado automaticamente por último (cotação, preços, quando e de onde)."""
    try:
        from app import admin_store

        bruto = admin_store.get_config(CHAVE_AUTO, "")
        dados = json.loads(bruto) if bruto else {}
        return dados if isinstance(dados, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _modelos_a_atualizar() -> list[str]:
    modelos: set[str] = set()
    try:
        from app import db, ia_config

        modelos.add(_modelo_base(ia_config.resolver_openai_model()))
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT modelo FROM uso_ia
                    WHERE provedor = 'openai' AND created_at >= NOW() - INTERVAL '90 days'
                    """
                )
                modelos.update(_modelo_base(r["modelo"]) for r in cur.fetchall() if r.get("modelo"))
    except Exception:  # noqa: BLE001
        logger.warning("Não foi possível listar os modelos em uso", exc_info=True)
    return sorted(m for m in modelos if m)


def atualizar_referencias() -> dict[str, Any]:
    """Busca a cotação e os preços dos modelos em uso e guarda. O que falhar mantém o valor anterior."""
    from datetime import datetime, timezone

    from app import admin_store

    with _atualizando:
        atual = referencias()
        novo: dict[str, Any] = {
            "cotacao": atual.get("cotacao"),
            "modelos": dict(atual.get("modelos") or {}),
            "fonte_precos": "OpenRouter (tabela da OpenAI)",
            "falhas": [],
        }
        cotacao = buscar_cotacao()
        if cotacao:
            novo["cotacao"] = cotacao
        else:
            novo["falhas"].append("cotação do dólar")
        for modelo in _modelos_a_atualizar():
            preco = buscar_preco_do_modelo(modelo)
            if preco:
                novo["modelos"][modelo] = preco
            else:
                novo["falhas"].append(f"preço de {modelo}")
        agora = datetime.now(timezone.utc).isoformat()
        novo["ultima_tentativa"] = agora
        # Só conta como atualizado se algo foi obtido; se tudo falhou (sem rede), tenta de novo depois
        obteve_algo = bool(cotacao) or len(novo["falhas"]) < 1 + len(_modelos_a_atualizar())
        novo["atualizado_em"] = agora if obteve_algo else atual.get("atualizado_em")
        admin_store.set_config(CHAVE_AUTO, json.dumps(novo, ensure_ascii=False))
        _cache_config.update(quando=0.0, valor=None)
        return novo


def _desatualizado(ref: dict[str, Any]) -> bool:
    from datetime import datetime, timezone

    try:
        quando = datetime.fromisoformat(str(ref.get("atualizado_em")))
        return (datetime.now(timezone.utc) - quando).total_seconds() > INTERVALO_ATUALIZACAO
    except (TypeError, ValueError):
        return True


def atualizar_se_preciso() -> None:
    """Dispara a atualização em segundo plano quando os valores têm mais de 12 horas."""
    if not _desatualizado(referencias()) or _atualizando.locked():
        return
    threading.Thread(target=_atualizar_sem_falhar, daemon=True, name="custos-atualizar").start()


def _atualizar_sem_falhar() -> None:
    try:
        atualizar_referencias()
    except Exception:  # noqa: BLE001
        logger.warning("Atualização de cotação e preços falhou", exc_info=True)


def iniciar_atualizador() -> None:
    """Na subida da API: atualiza já e depois confere a cada hora (só busca se passou de 12 h)."""

    def laco() -> None:
        while True:
            if _desatualizado(referencias()):
                _atualizar_sem_falhar()
            time.sleep(3600)

    threading.Thread(target=laco, daemon=True, name="custos-atualizador").start()
