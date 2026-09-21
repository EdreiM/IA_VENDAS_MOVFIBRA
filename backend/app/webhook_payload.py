"""Monta o pacote de dados do cliente para webhooks n8n."""

from __future__ import annotations

from typing import Any

from app import db


def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def historico_completo(id_cliente: str, limite: int = 500) -> list[dict[str, str]]:
    """Todas as mensagens da conversa (ordem cronológica)."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, remetente, mensagem, created_at
                FROM historico_mensagens_ia
                WHERE id_cliente = %s
                ORDER BY id ASC
                LIMIT %s
                """,
                (id_cliente, limite),
            )
            rows = cur.fetchall()
    return [
        {
            "id": str(r["id"]),
            "remetente": str(r["remetente"] or ""),
            "mensagem": str(r["mensagem"] or ""),
            "created_at": str(r["created_at"] or ""),
            "author": "Atendente"
            if str(r["remetente"] or "").lower() in {"eva", "sofia", "assistente", "bot"}
            else "Cliente",
            "role": "assistant"
            if str(r["remetente"] or "").lower() in {"eva", "sofia", "assistente", "bot"}
            else "user",
            "text": str(r["mensagem"] or ""),
        }
        for r in rows
    ]


def buffer_mensagens(mensagens: list[dict[str, str]]) -> str:
    """
    Texto linear no formato esperado pelo Padroniza_html do n8n:
    Cliente (HH:MM): texto
    Atendente (HH:MM): texto
    """
    linhas: list[str] = []
    for m in mensagens:
        author = m.get("author") or (
            "Atendente"
            if m.get("remetente", "").lower() in {"eva", "sofia", "assistente", "bot", "ia"}
            else "Cliente"
        )
        created = m.get("created_at") or ""
        # ISO: 2026-08-27T22:15:00+00:00 → 22:15
        hora = created[11:16] if len(created) >= 16 and created[11:13].isdigit() else "00:00"
        texto = (m.get("text") or m.get("mensagem") or "").strip()
        if not texto:
            continue
        linhas.append(f"{author} ({hora}): {texto}")
    return "\n".join(linhas)


def snapshot_cliente(estado: dict[str, Any], *, incluir_historico: bool = False) -> dict[str, Any]:
    """
    Pacote único do atendimento — o n8n usa só isso, sem SELECT no Postgres.
    Nomes alinhados aos inputs dos subfluxos antigos.
    """
    id_cliente = _texto(estado.get("id_cliente"))
    ixc_id = _texto(estado.get("ixc_cliente_id") or estado.get("ixc_id_cliente"))

    snap: dict[str, Any] = {
        # identidade sessão / canais
        "id_cliente": id_cliente,
        "conversation_id": _texto(estado.get("conversation_id")),
        "contact_id": _texto(estado.get("contact_id")),
        # IXC
        "ixc_id_cliente": ixc_id,
        "ixc_cliente_id": ixc_id,  # alias
        "id_contrato_ixc": _texto(estado.get("id_contrato_ixc") or ""),
        "os_id": _texto(estado.get("os_id")),
        # cadastro
        "nome": _texto(estado.get("nome")),
        "cpf": _texto(estado.get("cpf")),
        "email": _texto(estado.get("email")),
        "telefone": _texto(estado.get("telefone")),
        "data_nascimento": _texto(estado.get("data_nascimento")),
        "rg": _texto(estado.get("rg")),
        # endereço / cobertura
        "cidade": _texto(estado.get("cidade")),
        "bairro": _texto(estado.get("bairro")),
        "cep": _texto(estado.get("cep")),
        "rua": _texto(estado.get("rua")),
        "numero": _texto(estado.get("numero")),
        "complemento": _texto(estado.get("complemento")),
        "localizacao_forma": _texto(estado.get("localizacao_forma")),
        "caixa_fibra": _texto(estado.get("caixa_fibra")),
        "tem_cobertura": bool(estado.get("tem_cobertura")),
        # plano (IDs como string — schema n8n Execute Workflow exige string)
        "plano_confirmado": _texto(estado.get("plano_confirmado")),
        "plano_confirmado_id": _texto(estado.get("plano_confirmado_id")),
        "plano_em_negociacao": _texto(estado.get("plano_em_negociacao")),
        "plano_em_negociacao_id": _texto(estado.get("plano_em_negociacao_id")),
        # agenda
        "tecnico_id": _texto(estado.get("tecnico_id")),
        "id_tecnico": _texto(estado.get("tecnico_id")),  # alias
        "data_agendamento": _texto(estado.get("data_agendamento")),
        "horario_escolhido": _texto(estado.get("horario_escolhido")),
        "preferencia_horario": _texto(estado.get("preferencia_horario")),
        "agendamento_confirmado": bool(estado.get("agendamento_confirmado")),
        # fluxo
        "fase": _texto(estado.get("fase")),
        "aguardando": _texto(estado.get("aguardando")),
        "cadastro_completo": bool(estado.get("cadastro_completo")),
    }

    # Aliases legados n8n (subfluxo cadastro MOV)
    cpf = _texto(estado.get("cpf"))
    tel = _texto(estado.get("telefone"))
    pid = _texto(
        estado.get("plano_confirmado_id") or estado.get("plano_em_negociacao_id")
    )
    snap.update(
        {
            "cpf_cnpj": cpf,
            "numero_endereco": _texto(estado.get("numero")),
            "plano_id": pid,
            "id_vd_contrato": pid,
            "rg_cliente": _texto(estado.get("rg")),
            "localizacao": _texto(estado.get("localizacao_fixa")),
            "localizacao_fixa": _texto(estado.get("localizacao_fixa")),
            "data_vencimento": _texto(estado.get("data_vencimento_pref") or "5"),
            "data_vencimento_pref": _texto(estado.get("data_vencimento_pref") or "5"),
            "whatsapp": tel,
            "cadastrado": "sim" if ixc_id else "nao",
        }
    )

    if incluir_historico and id_cliente:
        msgs = historico_completo(id_cliente)
        snap["mensagens"] = msgs
        snap["buffer"] = buffer_mensagens(msgs)
        snap["total_mensagens"] = len(msgs)

    return snap
