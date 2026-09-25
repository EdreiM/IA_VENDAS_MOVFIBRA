"""Cadastro de cliente após confirmação do resumo — IXC direto, webhook n8n ou mock."""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.integrations.cadastro_webhook import cadastrar_cliente_webhook
from app.integrations.ixc_cliente import criar_cliente_ixc

logger = logging.getLogger(__name__)


def _resultado(
    *,
    ok: bool,
    erro: bool,
    motivo: str,
    id_cliente_ixc: str = "",
    os_id: str = "",
    id_contrato_ixc: str = "",
    ja_cadastrado: bool = False,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "erro": erro,
        "motivo": motivo,
        "id_cliente_ixc": id_cliente_ixc,
        "os_id": os_id,
        "id_contrato_ixc": id_contrato_ixc,
        "ja_cadastrado": ja_cadastrado,
    }


def _notificar_erro(mensagem: str) -> None:
    from app.alerts import enviar_alerta

    enviar_alerta("cadastro", mensagem)


def _dados_ixc_direto(estado: dict[str, Any]) -> dict[str, str]:
    return {
        "nome": str(estado.get("nome") or "").strip(),
        "cpf": str(estado.get("cpf") or "").strip(),
        "email": str(estado.get("email") or "").strip(),
        "telefone": str(estado.get("telefone") or "").strip(),
        "data_nascimento": str(estado.get("data_nascimento") or "").strip(),
        "cep": str(estado.get("cep") or "").strip(),
        "rua": str(estado.get("rua") or "").strip(),
        "numero": str(estado.get("numero") or "").strip(),
        "bairro": str(estado.get("bairro") or "").strip(),
        "cidade": str(estado.get("cidade") or "").strip(),
        "complemento": str(estado.get("complemento") or "").strip(),
        "rg": str(estado.get("rg") or "").strip(),
    }


def _url_cadastro(unidade_id: int | None = None) -> str:
    from app.ferramentas_catalog import resolver_url_ferramenta

    settings = get_settings()
    return resolver_url_ferramenta(
        "cadastrar_cliente",
        unidade_id=unidade_id,
        fallback_env=settings.cadastro_webhook_url,
    ).strip()


def cadastrar_cliente(estado: dict[str, Any]) -> dict[str, Any]:
    """Executa cadastro (mock, webhook n8n ou IXC direto)."""
    settings = get_settings()
    provider = (settings.cadastro_provider or "mock").lower()
    uid = None
    try:
        if estado.get("unidade_id") is not None:
            uid = int(estado["unidade_id"])
    except (TypeError, ValueError):
        uid = None

    url = _url_cadastro(uid)
    usar_webhook = bool(url) or provider == "webhook"

    try:
        if usar_webhook:
            if not url:
                return _resultado(
                    ok=False,
                    erro=True,
                    motivo="cadastrar_cliente sem webhook — cadastre no painel Ferramentas",
                )
            resp = cadastrar_cliente_webhook(estado)
            if resp.get("ja_cadastrado"):
                return _resultado(
                    ok=False,
                    erro=True,
                    ja_cadastrado=True,
                    motivo=resp.get("motivo") or "CPF já cadastrado",
                    id_cliente_ixc=str(resp.get("id_cliente_ixc") or ""),
                )
            if not resp.get("ok"):
                _notificar_erro(resp.get("motivo", "Erro webhook cadastro"))
                return _resultado(
                    ok=False,
                    erro=True,
                    motivo=resp.get("motivo") or "Falha no cadastro (n8n)",
                )
            return _resultado(
                ok=True,
                erro=False,
                motivo=resp.get("motivo") or "Cadastro concluído via n8n",
                id_cliente_ixc=str(resp.get("id_cliente_ixc") or ""),
                os_id=str(resp.get("os_id") or ""),
                id_contrato_ixc=str(resp.get("id_contrato_ixc") or ""),
            )

        if provider == "ixc":
            resp = criar_cliente_ixc(_dados_ixc_direto(estado))
            if not resp.get("ok"):
                _notificar_erro(resp.get("motivo", "Erro IXC"))
                return _resultado(
                    ok=False,
                    erro=True,
                    motivo=resp.get("motivo") or "Falha ao cadastrar no IXC",
                )
            return _resultado(
                ok=True,
                erro=False,
                motivo=resp.get("motivo") or "Cliente cadastrado no IXC",
                id_cliente_ixc=str(resp.get("id") or ""),
            )

        if provider == "mock":
            return _resultado(
                ok=True,
                erro=False,
                motivo="Cadastro registrado (mock local)",
                id_cliente_ixc="mock",
                os_id="mock",
                id_contrato_ixc="mock",
            )

        return _resultado(
            ok=False,
            erro=True,
            motivo=f"CADASTRO_PROVIDER inválido: {provider}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro no cadastro")
        _notificar_erro(str(exc))
        return _resultado(
            ok=False,
            erro=True,
            motivo="Falha técnica ao cadastrar — transferir atendimento",
        )
