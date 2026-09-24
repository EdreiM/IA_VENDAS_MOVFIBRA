"""IXC — viabilidade técnica."""

from __future__ import annotations

from typing import Any

import httpx

from app.coverage_config import (
    resolver_ixc_base_url,
    resolver_ixc_password,
    resolver_ixc_user,
)


def consultar_viabilidade(latitude: float | str, longitude: float | str) -> dict[str, Any]:
    ixc_user = resolver_ixc_user()
    ixc_password = resolver_ixc_password()
    if not ixc_user or not ixc_password:
        return {
            "ok": False,
            "viavel": False,
            "motivo": "Credenciais IXC ausentes — configure na aba Viabilidade do painel",
        }

    url = f"{resolver_ixc_base_url()}/viabilidade_tecnica"
    payload = {"latitude": str(latitude), "longitude": str(longitude)}

    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(
                url,
                data=payload,
                auth=(ixc_user, ixc_password),
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return {
            "ok": False,
            "viavel": False,
            "motivo": f"IXC HTTP {exc.response.status_code}: {exc.response.text[:200]}",
        }
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "viavel": False,
            "motivo": f"IXC indisponível: {exc}",
        }
    except ValueError as exc:
        return {
            "ok": False,
            "viavel": False,
            "motivo": f"Resposta IXC inválida: {exc}",
        }

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
