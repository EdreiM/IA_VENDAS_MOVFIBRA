"""Cliente HTTP — catálogo de planos via n8n."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    settings = get_settings()
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.plans_webhook_token:
        h["Authorization"] = f"Bearer {settings.plans_webhook_token}"
    return h


def _normalizar_plano(raw: dict[str, Any]) -> dict[str, Any]:
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    valor = raw.get("valor")
    try:
        valor_f = float(valor) if valor is not None else 0.0
    except (TypeError, ValueError):
        valor_f = 0.0

    vp = raw.get("valor_pontualidade")
    try:
        valor_pont = float(vp) if vp not in (None, "") else None
    except (TypeError, ValueError):
        valor_pont = None

    disp = raw.get("dispositivos_max")
    try:
        disp_i = int(disp) if disp not in (None, "") else None
    except (TypeError, ValueError):
        disp_i = None

    return {
        "id": int(raw["id"]),
        "nome": str(raw.get("nome") or "").strip(),
        "velocidade": str(raw.get("velocidade") or ""),
        "modalidade": str(raw.get("modalidade") or ""),
        "requer_cartao": bool(raw.get("requer_cartao")),
        "valor": valor_f,
        "parcelas": raw.get("parcelas"),
        "descricao": str(raw.get("descricao") or ""),
        "dispositivos_max": disp_i,
        "beneficios": str(raw.get("beneficios") or ""),
        "ordem": int(raw.get("ordem") or 100),
        "ativo": bool(raw.get("ativo", True)),
        "destaque": bool(raw.get("destaque")),
        "valor_pontualidade": valor_pont,
        "condicao_valor_pontualidade": raw.get("condicao_valor_pontualidade") or None,
        "tags": list(tags),
    }


def _extrair_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        return {"ok": False, "planos": [], "motivo": "Resposta inválida"}

    if isinstance(data.get("body"), dict):
        data = {**data, **data["body"]}

    planos_raw = data.get("planos") or []
    planos = [_normalizar_plano(p) for p in planos_raw if isinstance(p, dict)]

    destaque_id = data.get("plano_destaque_id")
    if destaque_id is not None:
        try:
            destaque_id = int(destaque_id)
        except (TypeError, ValueError):
            destaque_id = None

    if destaque_id is None:
        for p in planos:
            if p.get("destaque"):
                destaque_id = int(p["id"])
                break
    if destaque_id is None and planos:
        destaque_id = int(planos[0]["id"])

    return {
        "ok": bool(data.get("ok", bool(planos))),
        "planos": planos,
        "plano_destaque_id": destaque_id,
        "motivo": str(data.get("motivo") or ""),
    }


def buscar_planos_webhook(contexto: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    ctx = contexto or {}
    uid = None
    try:
        if ctx.get("unidade_id") is not None:
            uid = int(ctx["unidade_id"])
    except (TypeError, ValueError):
        uid = None
    url = resolver_url_ferramenta(
        "listar_planos",
        unidade_id=uid,
        fallback_env=settings.plans_webhook_url,
    )
    if not url:
        return {
            "ok": False,
            "planos": [],
            "motivo": "listar_planos sem webhook — cadastre no painel Ferramentas",
        }

    ctx = contexto or {}
    # Flatten: n8n recebe campos no root E em contexto (compatível)
    payload = {
        "acao": "listar",
        "contexto": ctx,
        **{k: v for k, v in ctx.items() if k not in {"mensagens", "buffer"}},
    }

    try:
        with httpx.Client(timeout=settings.plans_timeout_seconds) as client:
            resp = client.post(url, headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.warning("Plans webhook timeout: %s", url)
        return {"ok": False, "planos": [], "motivo": "timeout", "erro": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Plans webhook falhou: %s", exc)
        return {"ok": False, "planos": [], "motivo": str(exc), "erro": True}

    return _extrair_payload(data)
