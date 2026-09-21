"""Validação de CPF — executor (substitui sub-workflow n8n)."""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.integrations.chatwoot import atualizar_cpf_contato
from app.integrations.ixc_cliente import buscar_cliente_por_cpf
from app.utils.cpf import cpf_valido_formato, formatar_cpf_cnpj, somente_numeros

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


def _resultado(
    *,
    ja_cadastrado: bool,
    erro: bool,
    motivo: str,
    cpf_formatado: str = "",
) -> dict[str, Any]:
    return {
        "ja_cadastrado": ja_cadastrado,
        "erro": erro,
        "motivo": motivo,
        "cpf_formatado": cpf_formatado,
        "cpf_numeros": somente_numeros(cpf_formatado),
    }


def _notificar_erro(mensagem: str) -> None:
    from app.alerts import enviar_alerta

    enviar_alerta("checagem de CPF", mensagem)


def validar_cpf(
    *,
    cpf_cnpj: str,
    id_cliente: str = "",
    contact_id: str = "",
) -> dict[str, Any]:
    """
    Entrada: cpf_cnpj, id_cliente, contact_id
    Saída: ja_cadastrado, erro, motivo (igual n8n)
    """
    _ = id_cliente

    cpf_fmt = formatar_cpf_cnpj(cpf_cnpj)
    if not cpf_fmt or not cpf_valido_formato(cpf_cnpj):
        return _resultado(
            ja_cadastrado=False,
            erro=True,
            motivo="CPF/CNPJ inválido — verifique o número informado",
            cpf_formatado=cpf_fmt,
        )

    settings = get_settings()

    try:
        if settings.cpf_provider.lower() != "ixc":
            # Mock: sempre CPF novo (testes locais)
            resultado = _resultado(
                ja_cadastrado=False,
                erro=False,
                motivo="CPF liberado para cadastro",
                cpf_formatado=cpf_fmt,
            )
        else:
            consulta = buscar_cliente_por_cpf(cpf_fmt)
            if not consulta.get("ok"):
                _notificar_erro(consulta.get("motivo", "Erro IXC"))
                return _resultado(
                    ja_cadastrado=False,
                    erro=True,
                    motivo="Falha técnica ao consultar CPF — transferir atendimento",
                    cpf_formatado=cpf_fmt,
                )

            if consulta.get("existe"):
                resultado = _resultado(
                    ja_cadastrado=True,
                    erro=False,
                    motivo="O CPF já está cadastrado no sistema",
                    cpf_formatado=cpf_fmt,
                )
            else:
                resultado = _resultado(
                    ja_cadastrado=False,
                    erro=False,
                    motivo="CPF novo, pode prosseguir cadastro",
                    cpf_formatado=cpf_fmt,
                )

        # Side effect Chatwoot (como no n8n)
        if contact_id:
            atualizar_cpf_contato(contact_id, cpf_fmt)

        return resultado

    except Exception as exc:  # noqa: BLE001
        logger.exception("Erro na validação de CPF")
        _notificar_erro(str(exc))
        return _resultado(
            ja_cadastrado=False,
            erro=True,
            motivo="Falha técnica ao consultar CPF — transferir atendimento",
            cpf_formatado=cpf_fmt,
        )
