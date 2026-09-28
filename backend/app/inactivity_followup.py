"""Follow-up de inatividade — retoma conversas paradas e encerra após N tentativas."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app import db
from app.encerrar import encerrar_atendimento
from app.inactivity_mensagens import (
    mensagem_encerramento_inatividade,
    mensagem_followup_inatividade,
)

logger = logging.getLogger(__name__)

_FASES_TERMINAIS = frozenset({"finalizado", "transferido"})
_AGUARDANDO_SISTEMA_PREFIXO = "resultado_"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _elegivel(estado: dict[str, Any]) -> bool:
    if not str(estado.get("conversation_id") or "").strip():
        return False
    if bool(estado.get("transferido_humano")):
        return False
    fase = str(estado.get("fase") or "").strip().casefold()
    if fase in _FASES_TERMINAIS:
        return False
    aguardando = str(estado.get("aguardando") or "").strip()
    if not aguardando or aguardando.startswith(_AGUARDANDO_SISTEMA_PREFIXO):
        return False
    return True


def _referencia_espera(estado: dict[str, Any]) -> datetime | None:
    count = int(estado.get("followup_count") or 0)
    if count > 0:
        return _parse_ts(estado.get("last_followup_at")) or _parse_ts(estado.get("updated_at"))
    # Primeira tentativa: conta a partir da última interação (Eva perguntou e ficou aguardando).
    updated = _parse_ts(estado.get("updated_at"))
    last_client = _parse_ts(estado.get("last_client_message_at"))
    if updated and last_client:
        return max(updated, last_client)
    return updated or last_client


def _cliente_respondeu_apos_ultimo_followup(estado: dict[str, Any]) -> bool:
    last_client = _parse_ts(estado.get("last_client_message_at"))
    last_follow = _parse_ts(estado.get("last_followup_at"))
    if not last_client or not last_follow:
        return False
    return last_client > last_follow


def _enviar_texto(estado: dict[str, Any], texto: str) -> bool:
    from app.integrations.mensagem_chatwoot_webhook import enviar_mensagens_chatwoot_webhook

    cid = str(estado.get("conversation_id") or "").strip()
    id_cliente = str(estado.get("id_cliente") or "").strip()
    if not cid or not texto.strip():
        return False
    out = enviar_mensagens_chatwoot_webhook(
        cid,
        [texto.strip()],
        id_cliente=id_cliente,
        contact_id=str(estado.get("contact_id") or ""),
    )
    ok = bool(out.get("ok"))
    if ok:
        db.salvar_resposta(id_cliente, texto.strip())
    return ok


def _encerrar_estado(estado: dict[str, Any]) -> None:
    id_cliente = str(estado.get("id_cliente") or "").strip()
    if not id_cliente:
        return
    texto = mensagem_encerramento_inatividade(estado)
    _enviar_texto(estado, texto)
    encerrar_atendimento({**estado, "id_cliente": id_cliente})
    db.marcar_encerrado_inatividade(
        id_cliente,
        motivo="Encerrado por inatividade após follow-ups sem resposta",
    )


def processar_estado_inatividade(
    estado: dict[str, Any],
    *,
    delay_minutes: int,
    max_followups: int,
) -> str | None:
    """
    Processa um estado elegível. Retorna ação: followup_N, encerrado ou None.
    """
    if not _elegivel(estado):
        return None
    if _cliente_respondeu_apos_ultimo_followup(estado):
        return None

    ref = _referencia_espera(estado)
    if not ref:
        return None
    if _agora() - ref < timedelta(minutes=max(1, delay_minutes)):
        return None

    count = int(estado.get("followup_count") or 0)
    id_cliente = str(estado.get("id_cliente") or "").strip()
    if not id_cliente:
        return None

    if count >= max_followups:
        _encerrar_estado(estado)
        return "encerrado"

    tentativa = count + 1
    texto = mensagem_followup_inatividade(estado, tentativa)
    if not _enviar_texto(estado, texto):
        logger.warning("Follow-up inatividade não enviado para %s", id_cliente)
        return None

    db.registrar_followup_enviado(id_cliente)
    return f"followup_{tentativa}"


def processar_inatividade(*, unidade_id: int | None = None) -> dict[str, int]:
    from app.ia_config import (
        resolver_inactivity_followup_delay_minutes,
        resolver_inactivity_followup_enabled,
        resolver_inactivity_followup_max,
    )

    if not resolver_inactivity_followup_enabled(unidade_id=unidade_id):
        return {"processados": 0, "followups": 0, "encerrados": 0}

    delay = resolver_inactivity_followup_delay_minutes(unidade_id=unidade_id)
    max_f = resolver_inactivity_followup_max(unidade_id=unidade_id)
    estados = db.listar_estados_followup_candidatos(limite=80)
    stats = {"processados": 0, "followups": 0, "encerrados": 0}

    for estado in estados:
        uid = estado.get("unidade_id")
        if unidade_id is not None and uid is not None and int(uid) != int(unidade_id):
            continue
        acao = processar_estado_inatividade(
            estado,
            delay_minutes=delay,
            max_followups=max_f,
        )
        if not acao:
            continue
        stats["processados"] += 1
        if acao == "encerrado":
            stats["encerrados"] += 1
        elif acao.startswith("followup_"):
            stats["followups"] += 1

    return stats


def iniciar_worker_inatividade() -> None:
    import threading
    import time

    def _loop() -> None:
        while True:
            try:
                stats = processar_inatividade()
                if stats.get("processados"):
                    logger.info("Follow-up inatividade: %s", stats)
            except Exception:
                logger.exception("Erro no worker de follow-up de inatividade")
            time.sleep(60)

    t = threading.Thread(target=_loop, name="inactivity-followup", daemon=True)
    t.start()
    logger.info("Worker de follow-up de inatividade iniciado (intervalo 60s)")
