"""Chatwoot — mensagens, labels, teams, assign e status."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "api_access_token": settings.chatwoot_api_token,
        "Content-Type": "application/json",
    }


def _base_account() -> tuple[str, str] | None:
    settings = get_settings()
    if not settings.chatwoot_api_token:
        return None
    base = settings.chatwoot_base_url.rstrip("/")
    account = settings.chatwoot_account_id
    return base, account


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    roots = _base_account()
    if not roots:
        return {"ok": False, "motivo": "chatwoot token/base ausente"}
    base, account = roots
    url = f"{base}/api/v1/accounts/{account}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, url, headers=_headers(), json=json_body)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            return {"ok": True, "data": data}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chatwoot %s %s falhou: %s", method, path, exc)
        return {"ok": False, "motivo": str(exc)}


def atualizar_cpf_contato(contact_id: str, cpf_formatado: str) -> None:
    """Equivalente ao n8n Atribui_cpf_chatwoot."""
    if not contact_id:
        return
    _request(
        "PATCH",
        f"/contacts/{contact_id}",
        json_body={"custom_attributes": {"cpf_cnpj": cpf_formatado}},
        timeout=20.0,
    )


def enviar_mensagem(
    conversation_id: str | int,
    content: str,
    *,
    message_type: str = "outgoing",
    private: bool = False,
) -> dict[str, Any]:
    """
    Posta mensagem na conversa (mesmo padrão do node Envia_msg_chatwoot).
    Com inbox Meta Cloud, outgoing chega no WhatsApp do cliente.
    """
    texto = (content or "").strip()
    if not conversation_id or not texto:
        return {"ok": False, "motivo": "chatwoot/token/conversation/content ausente"}
    return _request(
        "POST",
        f"/conversations/{conversation_id}/messages",
        json_body={
            "content": texto,
            "message_type": message_type,
            "private": bool(private),
        },
    )


def enviar_outgoing(conversation_id: str | int, content: str) -> dict[str, Any]:
    return enviar_mensagem(conversation_id, content, message_type="outgoing", private=False)


def enviar_outgoing_multiplas(
    conversation_id: str | int,
    contents: list[str],
    *,
    delay_seconds: float = 0.35,
) -> dict[str, Any]:
    """Envia várias bolhas em sequência (ex.: um plano por mensagem)."""
    import time

    textos = [c.strip() for c in contents if (c or "").strip()]
    if not textos:
        return {"ok": False, "motivo": "sem conteúdo"}

    resultados: list[dict[str, Any]] = []
    for i, texto in enumerate(textos):
        if i > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)
        resultados.append(enviar_outgoing(conversation_id, texto))

    ok = all(r.get("ok") for r in resultados)
    return {
        "ok": ok,
        "enviadas": len(resultados),
        "resultados": resultados,
    }


def enviar_anexo_imagem(
    conversation_id: str | int,
    file_path: str,
    *,
    content: str = "",
    content_type: str | None = None,
) -> dict[str, Any]:
    """
    Envia imagem como attachment na conversa Chatwoot (WhatsApp Meta).
    """
    roots = _base_account()
    if not roots:
        return {"ok": False, "motivo": "chatwoot token/base ausente"}
    if not conversation_id:
        return {"ok": False, "motivo": "conversation_id ausente"}

    from pathlib import Path

    path = Path(file_path)
    if not path.is_file():
        return {"ok": False, "motivo": f"arquivo não encontrado: {file_path}"}

    base, account = roots
    url = f"{base}/api/v1/accounts/{account}/conversations/{conversation_id}/messages"
    settings = get_settings()
    headers = {"api_access_token": settings.chatwoot_api_token}

    ext = path.suffix.lower()
    ct = content_type or {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")

    try:
        with path.open("rb") as fh:
            files = {"attachments[]": (path.name, fh, ct)}
            data = {
                "content": content or "",
                "message_type": "outgoing",
                "private": "false",
            }
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(url, headers=headers, data=data, files=files)
                resp.raise_for_status()
                payload = resp.json() if resp.content else {}
                return {"ok": True, "data": payload, "via": "chatwoot_attachment"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chatwoot anexo falhou: %s", exc)
        return {"ok": False, "motivo": str(exc)}


# ── Catálogo (agents / teams / labels) ─────────────────────────


def listar_agents() -> dict[str, Any]:
    return _request("GET", "/agents")


def listar_teams() -> dict[str, Any]:
    return _request("GET", "/teams")


def listar_labels() -> dict[str, Any]:
    return _request("GET", "/labels")


def listar_inboxes() -> dict[str, Any]:
    return _request("GET", "/inboxes")


# ── Ações na conversa ──────────────────────────────────────────


def atribuir_conversa(
    conversation_id: str | int,
    *,
    assignee_id: int | None = None,
    team_id: int | None = None,
) -> dict[str, Any]:
    """
    Assign conversation to agent and/or team.
    Se assignee_id e team_id forem enviados, o Chatwoot prioriza assignee_id.
    """
    if not conversation_id:
        return {"ok": False, "motivo": "conversation_id ausente"}
    body: dict[str, Any] = {}
    if assignee_id is not None:
        body["assignee_id"] = int(assignee_id)
    if team_id is not None:
        body["team_id"] = int(team_id)
    if not body:
        return {"ok": False, "motivo": "informe assignee_id e/ou team_id"}
    return _request("POST", f"/conversations/{conversation_id}/assignments", json_body=body)


def definir_labels(conversation_id: str | int, labels: list[str]) -> dict[str, Any]:
    """Substitui a lista de labels da conversa (API Chatwoot overwrite)."""
    if not conversation_id:
        return {"ok": False, "motivo": "conversation_id ausente"}
    limpos = [str(x).strip() for x in labels if str(x).strip()]
    return _request(
        "POST",
        f"/conversations/{conversation_id}/labels",
        json_body={"labels": limpos},
    )


def atualizar_status(
    conversation_id: str | int,
    status: str,
) -> dict[str, Any]:
    """status: open | resolved | pending | snoozed"""
    if not conversation_id:
        return {"ok": False, "motivo": "conversation_id ausente"}
    st = (status or "").strip().lower()
    if st not in {"open", "resolved", "pending", "snoozed"}:
        return {"ok": False, "motivo": f"status inválido: {status}"}
    return _request(
        "POST",
        f"/conversations/{conversation_id}/toggle_status",
        json_body={"status": st},
    )


def handoff_conversa(
    conversation_id: str | int,
    *,
    assignee_id: int | None = None,
    team_id: int | None = None,
    labels: list[str] | None = None,
    status: str | None = None,
    nota_privada: str | None = None,
) -> dict[str, Any]:
    """
    Handoff completo: assign + labels + status + nota privada opcional.
    Cada passo é independente; falha parcial é reportada.
    """
    passos: dict[str, Any] = {}
    if assignee_id is not None or team_id is not None:
        passos["assign"] = atribuir_conversa(
            conversation_id, assignee_id=assignee_id, team_id=team_id
        )
    if labels is not None:
        passos["labels"] = definir_labels(conversation_id, labels)
    if status:
        passos["status"] = atualizar_status(conversation_id, status)
    if nota_privada and str(nota_privada).strip():
        passos["nota"] = enviar_mensagem(
            conversation_id,
            str(nota_privada).strip(),
            message_type="outgoing",
            private=True,
        )
    ok = all(v.get("ok") for v in passos.values()) if passos else False
    return {"ok": ok, "conversation_id": str(conversation_id), "passos": passos}
