"""Executor de cobertura — substitui o sub-workflow do n8n."""

from __future__ import annotations

import logging
from typing import Any

from app.coverage_config import resolver_coverage_provider, resolver_google_maps_api_key
from app.integrations.google_maps import geocode_endereco, montar_endereco, reverse_geocode
from app.integrations.ixc import consultar_viabilidade

logger = logging.getLogger(__name__)

# Mock local (testes sem IXC)
COBERTURA_MOCK: dict[str, set[str]] = {
    "santarem": {"diamantino", "prainha", "aldeia", "santissimo"},
    "maceio": {"jatiuca", "ponta verde", "pajuçara", "pajucara"},
}


def _norm(s: str) -> str:
    t = (s or "").casefold().strip()
    for a, b in [
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("ô", "o"), ("õ", "o"),
        ("ú", "u"), ("ç", "c"),
    ]:
        t = t.replace(a, b)
    return t


def _parse_gps(localizacao_fixa: str) -> tuple[float, float] | None:
    from app.geo_coords import extrair_gps_mensagem

    norm = extrair_gps_mensagem(localizacao_fixa or "")
    if not norm:
        return None
    partes = [p.strip() for p in norm.split(",", 1)]
    try:
        return float(partes[0]), float(partes[1])
    except ValueError:
        return None


def _resultado(
    *,
    resultado: str,
    tem_cobertura: bool,
    cidade: str = "",
    bairro: str = "",
    rua: str = "",
    motivo: str = "",
    localizacao_fixa: str = "",
    caixa_fibra: str = "",
    precisa_esclarecer: bool = False,
    bairros_sugeridos: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "resultado": resultado,
        "tem_cobertura": tem_cobertura,
        "precisa_esclarecer": precisa_esclarecer,
        "cidade_normalizada": cidade,
        "bairro_normalizado": bairro,
        "rua_normalizada": rua,
        "motivo": motivo,
        "localizacao_fixa": localizacao_fixa,
        "caixa_fibra": caixa_fibra,
        "bairros_sugeridos": bairros_sugeridos or [],
    }


def _checar_mock(cidade: str, bairro: str) -> dict[str, Any]:
    c = _norm(cidade)
    b = _norm(bairro)
    bairros = COBERTURA_MOCK.get(c)
    if not bairros:
        return _resultado(
            resultado="sem_cobertura",
            tem_cobertura=False,
            cidade=cidade,
            bairro=bairro,
            motivo="Cidade fora da área de cobertura (mock)",
        )
    if b in bairros:
        return _resultado(
            resultado="cobertura_confirmada",
            tem_cobertura=True,
            cidade=cidade,
            bairro=bairro,
            motivo="Cobertura confirmada (mock)",
        )
    return _resultado(
        resultado="sem_cobertura",
        tem_cobertura=False,
        cidade=cidade,
        bairro=bairro,
        motivo="Bairro sem cobertura (mock)",
    )


def _notificar_erro(mensagem: str) -> None:
    from app.alerts import enviar_alerta

    enviar_alerta("viabilidade", mensagem)


def _pos_viabilidade(
    *,
    viabilidade: dict[str, Any],
    cidade: str,
    bairro: str,
    rua: str,
    localizacao_fixa: str,
    escape_geocoding: bool = False,
) -> dict[str, Any]:
    if not viabilidade.get("ok"):
        _notificar_erro(viabilidade.get("motivo", "Erro IXC"))
        return _resultado(
            resultado="erro_cobertura",
            tem_cobertura=False,
            cidade=cidade,
            bairro=bairro,
            motivo=viabilidade.get("motivo", "Falha na consulta IXC"),
        )

    caixa = viabilidade.get("caixa_fibra") or ""

    if viabilidade.get("viavel"):
        if not bairro and not escape_geocoding:
            return _resultado(
                resultado="bairro_ambiguo",
                tem_cobertura=False,
                cidade=cidade,
                bairro=bairro,
                rua=rua,
                localizacao_fixa=localizacao_fixa,
                caixa_fibra=caixa,
                precisa_esclarecer=True,
                motivo="Bairro precisa ser esclarecido",
            )
        return _resultado(
            resultado="cobertura_confirmada",
            tem_cobertura=True,
            cidade=cidade,
            bairro=bairro,
            rua=rua,
            localizacao_fixa=localizacao_fixa,
            caixa_fibra=caixa,
            motivo="Endereço com cobertura disponível",
        )

    return _resultado(
        resultado="sem_cobertura",
        tem_cobertura=False,
        cidade=cidade,
        bairro=bairro,
        rua=rua,
        localizacao_fixa=localizacao_fixa,
        motivo="Bairro fora da área de cobertura",
    )


def checar_cobertura(
    *,
    cidade: str = "",
    bairro: str = "",
    rua: str = "",
    numero: str = "",
    localizacao_fixa: str = "",
    id_cliente: str = "",
) -> dict[str, Any]:
    """
    Mesma interface do sub-workflow n8n.

    Entrada: cidade, bairro, rua, numero, localizacao_fixa, id_cliente
    Saída: resultado, tem_cobertura, cidade_normalizada, etc.
    """
    _ = id_cliente  # reservado para logs/alertas futuros

    if resolver_coverage_provider().lower() != "ixc":
        return _checar_mock(cidade, bairro)

    gps = _parse_gps(localizacao_fixa)

    try:
        # ── Caminho GPS (WhatsApp location pin) ──
        if gps:
            lat, lng = gps
            loc_fixa = localizacao_fixa
            cidade_gps = cidade
            bairro_gps = bairro
            rua_gps = rua

            # Google só enriquece labels — IXC usa lat/lng direto (pin já tem coordenadas)
            if resolver_google_maps_api_key():
                try:
                    geo = reverse_geocode(lat, lng)
                    if geo.get("ok"):
                        cidade_gps = geo.get("cidade") or cidade_gps
                        bairro_gps = geo.get("bairro") or bairro_gps
                        rua_gps = geo.get("rua") or rua_gps
                    else:
                        logger.warning(
                            "Reverse geocode GPS falhou (%s) — consulta IXC direto",
                            geo.get("status"),
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Reverse geocode GPS indisponível: %s", exc)
            else:
                logger.warning("GOOGLE_MAPS_API_KEY ausente — consulta IXC direto com GPS")

            viab = consultar_viabilidade(lat, lng)
            return _pos_viabilidade(
                viabilidade=viab,
                cidade=cidade_gps,
                bairro=bairro_gps,
                rua=rua_gps,
                localizacao_fixa=loc_fixa,
            )

        # ── Caminho endereço textual ──
        endereco = montar_endereco(rua, numero, bairro, cidade)
        geo = geocode_endereco(endereco)

        if geo.get("status") == "REQUEST_DENIED":
            # Escape geocoding — igual ao n8n: confirma só com cidade/bairro
            logger.warning("Google geocode negado — escape geocoding")
            return _resultado(
                resultado="cobertura_confirmada",
                tem_cobertura=True,
                cidade=cidade,
                bairro=bairro,
                rua=rua,
                localizacao_fixa=localizacao_fixa,
                motivo="Endereço com cobertura (geocoding indisponível)",
            )

        if not geo.get("ok"):
            status = geo.get("status") or "ERRO"
            if status == "MISSING_API_KEY":
                motivo = "GOOGLE_MAPS_API_KEY não configurada no serviço api"
            else:
                motivo = f"Endereço não geocodificado: {status}"
            _notificar_erro(f"Google geocode: {status}")
            return _resultado(
                resultado="erro_cobertura",
                tem_cobertura=False,
                cidade=cidade,
                bairro=bairro,
                motivo=motivo,
            )

        lat = geo["latitude"]
        lng = geo["longitude"]
        loc_fixa = geo.get("localizacao") or f"{lat}, {lng}"

        viab = consultar_viabilidade(lat, lng)
        return _pos_viabilidade(
            viabilidade=viab,
            cidade=cidade,
            bairro=bairro,
            rua=rua,
            localizacao_fixa=loc_fixa,
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro na viabilidade")
        _notificar_erro(str(exc))
        return _resultado(
            resultado="erro_cobertura",
            tem_cobertura=False,
            cidade=cidade,
            bairro=bairro,
            motivo=str(exc),
        )
