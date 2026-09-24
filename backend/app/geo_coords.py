"""Coordenadas GPS — extração e normalização (WhatsApp / Chatwoot)."""

from __future__ import annotations

import re

# lat,lng ou lng,lat com . ou , decimal
_GPS_PAIR = re.compile(
    r"^\s*(-?\d{1,3}(?:[.,]\d+)?)\s*,\s*(-?\d{1,3}(?:[.,]\d+)?)\s*$"
)


def _to_float(valor: str) -> float:
    return float(valor.strip().replace(",", "."))


def normalizar_lat_lng_br(lat: float, lng: float) -> tuple[float, float]:
    """
    Corrige inversão lat/lng comum no Brasil.
    Ex.: -54.71, -2.44 → -2.44, -54.71
    """
    br_lat = (-35.0, 6.0)
    br_lng = (-75.0, -28.0)

    def lat_ok(v: float) -> bool:
        return br_lat[0] <= v <= br_lat[1]

    def lng_ok(v: float) -> bool:
        return br_lng[0] <= v <= br_lng[1]

    if lat_ok(lat) and lng_ok(lng):
        return lat, lng
    if lat_ok(lng) and lng_ok(lat):
        return lng, lat
    return lat, lng


def extrair_gps_mensagem(mensagem: str) -> str | None:
    """Retorna 'lat,lng' normalizado ou None."""
    m = _GPS_PAIR.match((mensagem or "").strip())
    if not m:
        return None
    try:
        a, b = _to_float(m.group(1)), _to_float(m.group(2))
        lat, lng = normalizar_lat_lng_br(a, b)
    except ValueError:
        return None
    return f"{lat},{lng}"


def parece_coordenada(valor: str) -> bool:
    v = (valor or "").strip()
    if not v:
        return False
    return _GPS_PAIR.match(v) is not None
