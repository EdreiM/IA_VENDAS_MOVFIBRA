"""Padroniza retornos de ferramentas n8n (sucesso / erro / transferir)."""

from __future__ import annotations

from typing import Any


def unwrap_body(data: Any) -> dict[str, Any]:
    """Extrai dict útil de lista / body / json do Respond to Webhook."""
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return {}
    for _ in range(3):
        if isinstance(data.get("body"), dict):
            data = {**data, **data["body"]}
        elif isinstance(data.get("json"), dict):
            data = {**data, **data["json"]}
        else:
            break
    return data if isinstance(data, dict) else {}


def motivo_erro_ferramenta(data: dict[str, Any], *, padrao: str = "Falha na ferramenta") -> str:
    """Monta motivo legível a partir do JSON Eva ou do erro nativo do n8n."""
    for key in (
        "motivo",
        "errorDescription",
        "errorMessage",
        "message",
        "description",
        "retorno",
    ):
        val = str(data.get(key) or "").strip()
        if val:
            return val[:500]
    return padrao


def eh_erro_ferramenta(data: dict[str, Any]) -> bool:
    """True quando a ferramenta falhou e a Eva deve transferir."""
    if not data:
        return True
    if data.get("transferir") is True:
        return True
    if data.get("erro") is True:
        return True
    if data.get("ok") is False:
        return True
    if data.get("errorMessage") or data.get("errorDescription"):
        return True
    resultado = str(data.get("resultado") or "").strip().lower()
    if resultado in {"erro", "error", "falha", "failed", "fail"}:
        return True
    return False


def resposta_erro_padrao(
    *,
    motivo: str,
    ferramenta: str = "",
    transferir: bool = True,
) -> dict[str, Any]:
    """
    Formato canônico que a Eva espera de qualquer ferramenta em falha.
    Use no Respond to Webhook do ramo de erro no n8n.
    """
    return {
        "resultado": "erro",
        "ok": False,
        "erro": True,
        "transferir": bool(transferir),
        "motivo": (motivo or "Falha na ferramenta")[:500],
        "ferramenta": ferramenta or "",
    }
