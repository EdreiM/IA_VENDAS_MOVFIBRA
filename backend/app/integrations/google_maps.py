"""Google Maps — geocodificação (mesma lógica do n8n)."""

from __future__ import annotations

from typing import Any

import httpx

from app.coverage_config import resolver_google_maps_api_key


def _get_by_type(components: list[dict], tipos: list[str]) -> str | None:
    for tipo in tipos:
        for comp in components or []:
            if tipo in (comp.get("types") or []):
                return comp.get("long_name")
    return None


def extrair_endereco_gps(results: list[dict]) -> dict[str, Any]:
    """Reverse geocode → cidade, bairro, rua, numero."""
    rooftop = [r for r in results if r.get("geometry", {}).get("location_type") == "ROOFTOP"]
    lista = rooftop or results

    def extrair(tipos: list[str], excluir: str = "") -> str:
        for item in lista:
            valor = _get_by_type(item.get("address_components") or [], tipos)
            if valor and (not excluir or valor.lower() != excluir.lower()):
                return valor
        return ""

    cidade = extrair(["administrative_area_level_2", "locality"])
    bairro = extrair(
        [
            "neighborhood",
            "sublocality",
            "sublocality_level_1",
            "administrative_area_level_4",
            "administrative_area_level_3",
        ],
        cidade,
    )
    rua = extrair(["route"])
    numero = extrair(["street_number"])

    return {
        "cidade": cidade,
        "bairro": bairro,
        "rua": rua,
        "numero": numero,
        "bairro_indefinido": not bairro,
    }


def reverse_geocode(lat: float, lng: float) -> dict[str, Any]:
    api_key = resolver_google_maps_api_key()
    if not api_key:
        return {"ok": False, "status": "MISSING_API_KEY", "results": []}

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lng}", "key": api_key}

    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "OK":
        return {"ok": False, "status": data.get("status"), "results": []}

    results = data.get("results") or []
    endereco = extrair_endereco_gps(results)
    return {"ok": True, "status": "OK", "results": results, **endereco}


def geocode_endereco(endereco: str) -> dict[str, Any]:
    """Endereço textual → lat/lng."""
    api_key = resolver_google_maps_api_key()
    if not api_key:
        return {"ok": False, "status": "MISSING_API_KEY", "results": []}

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": f"{endereco}-PA", "key": api_key}

    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    status = data.get("status")
    if status == "REQUEST_DENIED":
        return {"ok": False, "status": status, "message": data.get("error_message", "")}

    if status != "OK" or not data.get("results"):
        return {"ok": False, "status": status or "ZERO_RESULTS", "results": []}

    loc = data["results"][0]["geometry"]["location"]
    return {
        "ok": True,
        "status": "OK",
        "latitude": loc["lat"],
        "longitude": loc["lng"],
        "localizacao": f"{loc['lat']}, {loc['lng']}",
        "results": data.get("results") or [],
    }


def montar_endereco(rua: str, numero: str, bairro: str, cidade: str) -> str:
    rua = (rua or "").strip()
    numero = (numero or "").strip()
    bairro = (bairro or "").strip()
    cidade = (cidade or "").strip()

    if numero and numero.upper() != "SN":
        return f"{rua}, {numero}, {bairro}, {cidade}"
    return f"{rua}, {bairro}, {cidade}"
