"""Catálogo de ferramentas (webhooks) — seed + resolução de URL no runtime."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.db import _now, get_connection


# tool_key → metadados + getter da URL/token no .env (só para migração inicial)
CATALOGO_FERRAMENTAS: list[dict[str, Any]] = [
    {
        "tool_key": "enviar_mensagem",
        "nome": "Enviar mensagem (Chatwoot)",
        "descricao": (
            "Posta a resposta da Eva no WhatsApp via n8n/Chatwoot. "
            "Aceita mensagem única ou outputs[] (várias bolhas)."
        ),
        "destaque": True,
        "env_url": lambda s: s.chatwoot_msg_webhook_url,
        "parametros": [
            ("conversation_id", "texto", "Conversa Chatwoot", True),
            ("mensagem", "texto", "Texto único", False),
            ("outputs", "texto", "Lista de bolhas (JSON array)", False),
        ],
    },
    {
        "tool_key": "transferir_atendimento",
        "nome": "Transferir atendimento",
        "descricao": (
            "Transfere a conversa para um humano no Chatwoot "
            "(time/atendente/labels). Use quando o cliente pedir humano."
        ),
        "destaque": True,
        "env_url": lambda s: s.transfer_webhook_url,
        "parametros": [
            ("conversation_id", "texto", "ID da conversa no Chatwoot", True),
            ("motivo", "texto", "Motivo da transferência", False),
            ("id_cliente", "texto", "JID/sessão WhatsApp", False),
            ("contexto", "texto", "Snapshot resumido do estado (JSON)", False),
            ("assignee_id", "numero", "ID do atendente (opcional)", False),
            ("team_id", "numero", "ID do time (opcional)", False),
        ],
    },
    {
        "tool_key": "cadastrar_cliente",
        "nome": "Cadastrar cliente (IXC)",
        "descricao": "Envia cadastro completo ao n8n/IXC (cliente, contrato, OS).",
        "destaque": True,
        "env_url": lambda s: s.cadastro_webhook_url,
        "parametros": [
            ("id_cliente", "texto", "ID interno do lead", True),
            ("conversation_id", "texto", "Conversa Chatwoot", False),
            ("nome", "texto", "Nome completo", True),
            ("cpf", "texto", "CPF/CNPJ", True),
            ("telefone", "texto", "Telefone", True),
        ],
    },
    {
        "tool_key": "buscar_horarios_agenda",
        "nome": "Buscar horários (agenda)",
        "descricao": "Consulta técnicos/horários disponíveis no n8n/Sheets/IXC.",
        "destaque": False,
        "env_url": lambda s: s.agenda_webhook_url,
        "parametros": [
            ("cidade", "texto", "Cidade", False),
            ("bairro", "texto", "Bairro", False),
            ("conversation_id", "texto", "Conversa Chatwoot", False),
        ],
    },
    {
        "tool_key": "inserir_agendamento",
        "nome": "Inserir agendamento",
        "descricao": "Grava o horário escolhido e gera/atualiza OS.",
        "destaque": True,
        "env_url": lambda s: s.agenda_inserir_webhook_url,
        "parametros": [
            ("data_agendamento", "texto", "Data", True),
            ("horario_escolhido", "texto", "Horário", True),
            ("conversation_id", "texto", "Conversa Chatwoot", False),
        ],
    },
    {
        "tool_key": "enviar_termos",
        "nome": "Enviar termos / áudio fidelidade",
        "descricao": "Dispara envio de PDF de termos e áudio de fidelidade via n8n/Chatwoot.",
        "destaque": False,
        "env_url": lambda s: s.termos_webhook_url,
        "parametros": [
            ("conversation_id", "texto", "Conversa Chatwoot", True),
            ("ixc_cliente_id", "texto", "ID cliente IXC", False),
        ],
    },
    {
        "tool_key": "ativar_cliente",
        "nome": "Ativar cliente (IXC)",
        "descricao": "Ativa o cliente/contrato no IXC após aceite dos termos.",
        "destaque": False,
        "env_url": lambda s: s.ativacao_webhook_url,
        "parametros": [
            ("ixc_cliente_id", "texto", "ID cliente IXC", True),
            ("id_contrato_ixc", "texto", "ID contrato", False),
        ],
    },
    {
        "tool_key": "enviar_imagem_plano",
        "nome": "Enviar imagem do plano",
        "descricao": (
            "Envia imagem do plano via n8n/Chatwoot. "
            "Eva envia imagem_url + content prontos — n8n só baixa e posta."
        ),
        "destaque": False,
        "env_url": lambda s: s.imagem_plano_webhook_url,
        "parametros": [
            ("conversation_id", "texto", "Conversa Chatwoot", True),
            ("imagem_url", "texto", "URL pública da imagem (painel)", True),
            ("content", "texto", "Legenda Chatwoot (benefícios)", True),
            ("id_plano", "texto", "ID do plano", False),
            ("imagem_file_name", "texto", "Nome do arquivo", False),
            ("imagem_mime_type", "texto", "MIME (image/jpeg…)", False),
        ],
    },
    {
        "tool_key": "encerrar_atendimento",
        "nome": "Encerrar atendimento",
        "descricao": "Encerra a conversa (PDF final / resolve Chatwoot) via n8n.",
        "destaque": False,
        "env_url": lambda s: s.encerrar_webhook_url,
        "parametros": [
            ("conversation_id", "texto", "Conversa Chatwoot", True),
            ("motivo", "texto", "Motivo do encerramento", False),
        ],
    },
    {
        "tool_key": "consultar_rag",
        "nome": "Consultar RAG / conhecimento",
        "descricao": (
            "Webhook de conhecimento (FAQ, fidelidade, objeções). "
            "Também editável em Config IA; a ferramenta prevalece se tiver URL."
        ),
        "destaque": True,
        "env_url": lambda s: s.rag_webhook_url,
        "parametros": [
            ("pergunta", "texto", "Pergunta do cliente", True),
            ("mensagem", "texto", "Mensagem original", False),
        ],
    },
]


def chave_backup_url_ferramenta(tool_key: str) -> str:
    return f"ferramenta_webhook_url_{tool_key}"


def ler_backup_url_ferramenta(tool_key: str, *, unidade_id: int | None = None) -> str:
    """Backup operacional em sofia_config — sobrevive a redeploys e recriação de linhas."""
    if unidade_id is not None:
        return ""
    from app import admin_store

    return admin_store.get_config(chave_backup_url_ferramenta(tool_key), "").strip()


def gravar_backup_url_ferramenta(tool_key: str, url: str, *, unidade_id: int | None = None) -> None:
    if unidade_id is not None:
        return
    u = (url or "").strip()
    if not u:
        return
    from app import admin_store

    admin_store.set_config(chave_backup_url_ferramenta(tool_key), u, unidade_id=None)


def resolver_url_ferramenta(
    tool_key: str,
    *,
    unidade_id: int | None = None,
    fallback_env: str = "",
) -> str:
    """Painel → backup sofia_config → .env (nunca apaga URL já configurada)."""
    try:
        from app.ferramentas import obter_ferramenta_por_key

        tool = obter_ferramenta_por_key(tool_key, unidade_id=unidade_id)
        if tool:
            url = str(tool.get("webhook_url") or "").strip()
            if url:
                return url
    except Exception:
        pass
    backup = ler_backup_url_ferramenta(tool_key, unidade_id=unidade_id)
    if backup:
        return backup
    return (fallback_env or "").strip()


def resolver_token_ferramenta(
    tool_key: str,
    *,
    unidade_id: int | None = None,
    fallback_env: str = "",
) -> str:
    """Token opcional: parâmetro 'token' da ferramenta ou .env."""
    try:
        from app.ferramentas import obter_ferramenta_por_key

        tool = obter_ferramenta_por_key(tool_key, unidade_id=unidade_id)
        if tool:
            for p in tool.get("parametros") or []:
                if str(p.get("nome") or "").lower() == "token" and p.get("descricao"):
                    # descrição não guarda secret; secrets ficam só na URL Bearer via env por enquanto
                    pass
    except Exception:
        pass
    return (fallback_env or "").strip()


def _ler_backup_url_sql(cur: Any, tool_key: str) -> str:
    cur.execute(
        """
        SELECT valor FROM sofia_config
        WHERE chave = %s AND unidade_id IS NULL
        LIMIT 1
        """,
        (chave_backup_url_ferramenta(tool_key),),
    )
    row = cur.fetchone()
    return str(row["valor"]).strip() if row else ""


def sincronizar_persistencia_urls_ferramentas() -> dict[str, int]:
    """
    Backup/restaura URLs das ferramentas globais em sofia_config.
    Chamado no startup — configuração do painel não se perde entre deploys.
    """
    from app.ferramentas import atualizar_ferramenta, listar_ferramentas

    backupados = 0
    restaurados = 0
    for tool in listar_ferramentas():
        if tool.get("unidade_id") is not None:
            continue
        key = str(tool.get("tool_key") or "").strip()
        if not key:
            continue
        url = str(tool.get("webhook_url") or "").strip()
        backup = ler_backup_url_ferramenta(key)
        if url:
            if url != backup:
                gravar_backup_url_ferramenta(key, url)
                backupados += 1
        elif backup:
            atualizar_ferramenta(int(tool["id"]), {"webhook_url": backup})
            restaurados += 1
    return {"backupados": backupados, "restaurados": restaurados}


def seed_ferramentas_do_catalogo(cur: Any | None = None) -> int:
    """
    Garante que todas as ferramentas do catálogo existam no painel.
    - Cria se não existir (URL: .env → backup sofia_config → vazio).
    - Registro existente: não altera webhook_url nem metadados (painel é fonte da verdade).
    """
    settings = get_settings()
    own_conn = cur is None
    created = 0

    def _run(c: Any) -> int:
        nonlocal created
        now = _now()
        for item in CATALOGO_FERRAMENTAS:
            key = item["tool_key"]
            c.execute(
                "SELECT id, webhook_url FROM ferramentas WHERE tool_key = %s AND unidade_id IS NULL LIMIT 1",
                (key,),
            )
            row = c.fetchone()
            env_url = str(item["env_url"](settings) or "").strip()

            if row:
                continue

            url_inicial = env_url or _ler_backup_url_sql(c, key)

            c.execute(
                """
                INSERT INTO ferramentas (
                    tool_key, nome, descricao, webhook_url, integracao,
                    unidade_id, destaque_dashboard, ativo, chamadas_sucesso,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, 'global', NULL, %s, 1, 0, %s, %s)
                RETURNING id
                """,
                (
                    key,
                    item["nome"],
                    item["descricao"],
                    url_inicial,
                    1 if item.get("destaque") else 0,
                    now,
                    now,
                ),
            )
            fid = int(c.fetchone()["id"])
            for i, (nome, tipo, desc, obr) in enumerate(item.get("parametros") or []):
                c.execute(
                    """
                    INSERT INTO ferramenta_parametros (
                        ferramenta_id, nome, tipo, descricao, obrigatorio, ordem
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (fid, nome, tipo, desc, 1 if obr else 0, i),
                )
            created += 1
        return created

    if own_conn:
        with get_connection() as conn:
            with conn.cursor() as c:
                return _run(c)
    assert cur is not None
    return _run(cur)
