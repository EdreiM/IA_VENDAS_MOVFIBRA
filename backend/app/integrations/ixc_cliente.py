"""IXC — consulta de cliente por CPF/CNPJ."""

from __future__ import annotations

import logging
import re
from typing import Any
import httpx

from app.config import get_settings
from app.coverage_config import (
    resolver_ixc_base_url,
    resolver_ixc_password,
    resolver_ixc_user,
)
from app.utils.cpf import somente_numeros

logger = logging.getLogger(__name__)


def _registros_de(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        raw_regs = data.get("registros") or data.get("rows") or []
    elif isinstance(data, list):
        raw_regs = data
    else:
        raw_regs = []

    return [r for r in raw_regs if isinstance(r, dict)]


def _cpf_do_registro(reg: dict[str, Any]) -> str:
    for chave in ("cnpj_cpf", "cpf_cnpj", "cpf", "documento"):
        if reg.get(chave):
            return somente_numeros(str(reg[chave]))
    return ""


def _consultar_ixc(query: str) -> dict[str, Any]:
    ixc_user = resolver_ixc_user()
    ixc_password = resolver_ixc_password()
    if not ixc_user or not ixc_password:
        raise RuntimeError("Credenciais IXC ausentes — configure na aba Viabilidade do painel")

    url = f"{resolver_ixc_base_url()}/cliente"
    payload = {"qtype": "cnpj_cpf", "query": query, "oper": "="}

    with httpx.Client(timeout=45) as client:
        resp = client.post(
            url,
            data=payload,
            auth=(ixc_user, ixc_password),
            headers={"ixcsoft": "listar"},
        )
        resp.raise_for_status()
        data = resp.json()

    registros = _registros_de(data)
    total_raw = 0
    if isinstance(data, dict):
        try:
            total_raw = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total_raw = len(registros)

    return {
        "ok": True,
        "total_raw": total_raw,
        "registros": registros,
        "raw": data,
        "query_usada": query,
    }


def buscar_cliente_por_cpf(cpf_formatado: str) -> dict[str, Any]:
    """
    Equivalente ao n8n busca_cliente.
    Confirma existência só com match EXATO do CPF/CNPJ nos registros.
    """
    cpf_nums = somente_numeros(cpf_formatado)
    tentativas = []
    for q in (cpf_formatado, cpf_nums):
        q = (q or "").strip()
        if q and q not in tentativas:
            tentativas.append(q)

    ultimo: dict[str, Any] | None = None
    registros_exatos: list[dict[str, Any]] = []

    for query in tentativas:
        ultimo = _consultar_ixc(query)
        registros_exatos = [
            r for r in ultimo.get("registros") or []
            if _cpf_do_registro(r) == cpf_nums
        ]
        if registros_exatos:
            break

    if not ultimo:
        return {"ok": False, "total": 0, "existe": False, "registros": [], "raw": {}}

    existe = len(registros_exatos) > 0
    if not existe and (ultimo.get("total_raw") or 0) > 0:
        logger.warning(
            "IXC retornou total=%s mas sem CPF exato %s — tratando como CPF novo",
            ultimo.get("total_raw"),
            cpf_nums,
        )

    return {
        "ok": True,
        "total": len(registros_exatos),
        "existe": existe,
        "registros": registros_exatos,
        "raw": ultimo.get("raw"),
        "query_usada": ultimo.get("query_usada"),
    }


def _data_ixc(data: str) -> str:
    """Converte dd/mm/yyyy → yyyy-mm-dd (formato comum no IXC)."""
    import re

    t = (data or "").strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", t)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return t


def _extrair_id_ixc(data: dict[str, Any]) -> str:
    for chave in ("id", "id_cliente", "id_cliente_ixc"):
        val = str(data.get(chave) or "").strip()
        if val.isdigit():
            return val

    registros = data.get("registros")
    if isinstance(registros, list) and registros:
        rid = str(registros[0].get("id") or "").strip()
        if rid.isdigit():
            return rid

    msg = str(data.get("message") or data.get("mensagem") or "")
    m = re.search(r"\bid[:\s]+(\d+)", msg, re.I)
    if m:
        return m.group(1)

    return ""


def _formatar_cep_ixc(cep: str) -> str:
    n = somente_numeros(cep)
    if len(n) == 8:
        return f"{n[:5]}-{n[5:]}"
    return cep


def _cidade_ixc_id(cidade: str, settings) -> str:
    """Mapeia nome → ID IXC quando conhecido; senão usa default do .env."""
    t = (cidade or "").casefold()
    for a, b in [("á", "a"), ("ã", "a"), ("â", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ç", "c")]:
        t = t.replace(a, b)
    if "santarem" in t or "santarém" in (cidade or "").casefold():
        return settings.ixc_cidade_id or "209"
    return settings.ixc_cidade_id or "209"


def criar_cliente_ixc(dados: dict[str, Any]) -> dict[str, Any]:
    """
    Inclui cliente no IXC (header ixcsoft: incluir).
    Campos mínimos para cadastro comercial.
    """
    settings = get_settings()
    ixc_user = resolver_ixc_user()
    ixc_password = resolver_ixc_password()
    if not ixc_user or not ixc_password:
        return {"ok": False, "motivo": "Credenciais IXC ausentes — configure na aba Viabilidade do painel"}

    nome = str(dados.get("nome") or "").strip()
    cpf_nums = somente_numeros(str(dados.get("cpf") or ""))
    if not nome or not cpf_nums:
        return {"ok": False, "motivo": "Nome e CPF são obrigatórios para cadastro"}

    email = str(dados.get("email") or "").strip()
    tel = somente_numeros(str(dados.get("telefone") or ""))
    cep_fmt = _formatar_cep_ixc(str(dados.get("cep") or ""))

    payload: dict[str, str] = {
        "razao": nome[:200],
        "fantasia": nome[:200],
        "tipo_pessoa": "F",
        "cnpj_cpf": cpf_nums,
        "email": email,
        "telefone_celular": tel,
        "cep": cep_fmt,
        "endereco": str(dados.get("rua") or "").strip(),
        "numero": str(dados.get("numero") or "").strip(),
        "bairro": str(dados.get("bairro") or "").strip(),
        "cidade": _cidade_ixc_id(str(dados.get("cidade") or ""), settings),
        "uf": settings.ixc_uf or "20",
        "ativo": "S",
        "filial_id": settings.ixc_filial_id or "3",
        "id_tipo_cliente": settings.ixc_id_tipo_cliente or "19",
        "tipo_assinante": settings.ixc_tipo_assinante or "3",
        "iss_classificacao_padrao": settings.ixc_iss_classificacao or "99",
        "contribuinte_icms": settings.ixc_contribuinte_icms or "I",
        "tipo_localidade": settings.ixc_tipo_localidade or "U",
        "id_conta": settings.ixc_id_conta or "70302",
        "id_candato_tipo": settings.ixc_id_candidato_tipo or "45",
        "hotsite_email": cpf_nums,
        "senha": settings.ixc_senha_hotsite or "movbrasil",
        "cob_envia_email": "S",
        "cob_envia_sms": "S",
        "participa_cobranca": "S",
        "participa_pre_cobranca": "S",
    }

    complemento = str(dados.get("complemento") or "").strip()
    if complemento:
        payload["complemento"] = complemento

    rg = str(dados.get("rg") or "").strip()
    if rg:
        payload["ie_identidade"] = rg

    nasc = _data_ixc(str(dados.get("data_nascimento") or ""))
    if nasc:
        payload["data_nascimento"] = nasc

    url = f"{resolver_ixc_base_url()}/cliente"
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            url,
            data=payload,
            auth=(ixc_user, ixc_password),
            headers={"ixcsoft": "incluir"},
        )
        resp.raise_for_status()
        data = resp.json()

    id_cliente = _extrair_id_ixc(data) if isinstance(data, dict) else ""
    if not id_cliente and isinstance(data, dict) and str(data.get("type") or "").lower() == "success":
        id_cliente = str(data.get("id") or "").strip()
    if not id_cliente:
        logger.warning("IXC incluir cliente sem id parseável: %s", data)
        return {
            "ok": False,
            "motivo": "IXC cadastrou mas não retornou ID do cliente",
            "raw": data,
        }

    return {
        "ok": True,
        "id": id_cliente,
        "motivo": "Cliente cadastrado com sucesso no IXC",
        "raw": data,
    }
