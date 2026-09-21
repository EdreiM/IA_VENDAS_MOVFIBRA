"""IXC — viabilidade técnica."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings


def consultar_viabilidade(latitude: float | str, longitude: float | str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.ixc_user or not settings.ixc_password:
        raise RuntimeError("IXC_USER e IXC_PASSWORD não configurados no .env")

    url = f"{settings.ixc_base_url.rstrip('/')}/viabilidade_tecnica"
    payload = {"latitude": str(latitude), "longitude": str(longitude)}

    with httpx.Client(timeout=45) as client:
        resp = client.post(
            url,
            data=payload,
            auth=(settings.ixc_user, settings.ixc_password),
        )
        resp.raise_for_status()
        data = resp.json()

    # IXC pode retornar lista ou dict com chave "0"
    registro: dict[str, Any] | None = None
    if isinstance(data, list) and data:
        registro = data[0] if isinstance(data[0], dict) else None
    elif isinstance(data, dict):
        if "0" in data and isinstance(data["0"], dict):
            registro = data["0"]
        elif data:
            registro = data

    if not registro:
        return {"ok": False, "viavel": False, "raw": data, "motivo": "Resposta IXC vazia"}

    viavel = str(registro.get("status_viabilidade", "")).upper() == "S"

    caixa_fibra = ""
    id_caixa = registro.get("id_caixa")
    if isinstance(id_caixa, list) and id_caixa:
        caixa = id_caixa[0] if isinstance(id_caixa[0], dict) else {}
        caixa_fibra = f"id_caixa: {caixa.get('id', '')}, {caixa.get('descricao', '')}".strip(", ")

    return {
        "ok": True,
        "viavel": viavel,
        "caixa_fibra": caixa_fibra,
        "raw": registro,
    }
