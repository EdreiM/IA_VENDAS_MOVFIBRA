"""Persistência PostgreSQL — pool de conexões para escala."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS estado_cliente_ia (
        id_cliente TEXT PRIMARY KEY,
        fase TEXT NOT NULL DEFAULT 'inicio',
        aguardando TEXT,
        versao_fluxo INTEGER NOT NULL DEFAULT 4,
        retorno_estado TEXT,
        cidade TEXT,
        bairro TEXT,
        tem_cobertura INTEGER,
        localizacao_fixa TEXT,
        caixa_fibra TEXT,
        plano_apresentado TEXT,
        plano_apresentado_id INTEGER,
        plano_em_negociacao TEXT,
        plano_em_negociacao_id INTEGER,
        plano_confirmado TEXT,
        plano_confirmado_id INTEGER,
        nome TEXT,
        cpf TEXT,
        email TEXT,
        telefone TEXT,
        data_nascimento TEXT,
        rg TEXT,
        cep TEXT,
        rua TEXT,
        numero TEXT,
        complemento TEXT,
        metodo_pagamento TEXT,
        fidelidade_aceita INTEGER,
        taxa_instalacao_pagar INTEGER,
        documento_cpf_validado INTEGER DEFAULT 0,
        transferido_humano INTEGER DEFAULT 0,
        motivo_transferencia TEXT,
        cumprimento_feito INTEGER DEFAULT 0,
        ultima_mensagem_sofia TEXT,
        fase_anterior TEXT,
        aguardando_anterior TEXT,
        cadastro_completo INTEGER DEFAULT 0,
        ixc_cliente_id TEXT,
        tecnico_id TEXT,
        data_agendamento TEXT,
        horarios_manha TEXT,
        horarios_tarde TEXT,
        horario_escolhido TEXT,
        preferencia_horario TEXT,
        agendamento_confirmado INTEGER DEFAULT 0,
        tentativas_sem_cobertura INTEGER DEFAULT 0,
        tentativas_plano_invalido INTEGER DEFAULT 0,
        conversation_id TEXT,
        contact_id TEXT,
        os_id TEXT,
        id_contrato_ixc TEXT,
        ultimo_topico TEXT,
        ultima_pergunta_cliente TEXT,
        termos_enviados INTEGER DEFAULT 0,
        audio_fidelidade_enviado INTEGER DEFAULT 0,
        ativado_ixc INTEGER DEFAULT 0,
        imagem_plano_enviada INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS historico_mensagens_ia (
        id BIGSERIAL PRIMARY KEY,
        id_cliente TEXT NOT NULL,
        remetente TEXT NOT NULL,
        mensagem TEXT NOT NULL,
        imagem_url TEXT,
        created_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS turno_log_ia (
        id BIGSERIAL PRIMARY KEY,
        id_cliente TEXT NOT NULL,
        mensagem_cliente TEXT,
        eventos TEXT,
        acao TEXT,
        objetivo TEXT,
        fase TEXT,
        aguardando TEXT,
        topico TEXT,
        rag_hit INTEGER DEFAULT 0,
        duracao_ms INTEGER,
        message_id TEXT,
        created_at TIMESTAMPTZ,
        estado_antes TEXT,
        interpretacao_llm TEXT,
        confianca REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mensagens_processadas_ia (
        message_id TEXT PRIMARY KEY,
        id_cliente TEXT NOT NULL,
        created_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS unidades (
        id SERIAL PRIMARY KEY,
        codigo TEXT NOT NULL UNIQUE,
        nome TEXT NOT NULL,
        ativo INTEGER DEFAULT 1,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS planos (
        id SERIAL PRIMARY KEY,
        nome TEXT NOT NULL,
        velocidade TEXT,
        modalidade TEXT,
        requer_cartao INTEGER DEFAULT 0,
        valor DOUBLE PRECISION NOT NULL,
        parcelas INTEGER,
        descricao TEXT,
        dispositivos_max INTEGER,
        max_dispositivos INTEGER,
        beneficios TEXT,
        ordem INTEGER DEFAULT 100,
        ativo INTEGER DEFAULT 1,
        destaque INTEGER DEFAULT 0,
        unidade_id INTEGER REFERENCES unidades(id) ON DELETE SET NULL,
        imagem_url TEXT,
        valor_pontualidade DOUBLE PRECISION,
        condicao_valor_pontualidade TEXT,
        tags TEXT DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sofia_config (
        id SERIAL PRIMARY KEY,
        unidade_id INTEGER REFERENCES unidades(id) ON DELETE CASCADE,
        chave TEXT NOT NULL,
        valor TEXT NOT NULL,
        updated_at TIMESTAMPTZ,
        UNIQUE (unidade_id, chave)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS promocoes (
        id SERIAL PRIMARY KEY,
        codigo TEXT NOT NULL,
        titulo TEXT NOT NULL,
        descricao TEXT,
        ativo INTEGER DEFAULT 1,
        valido_ate TEXT,
        unidade_id INTEGER REFERENCES unidades(id) ON DELETE CASCADE,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        UNIQUE (unidade_id, codigo)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS excecoes (
        id SERIAL PRIMARY KEY,
        tipo TEXT NOT NULL,
        valor TEXT NOT NULL,
        motivo TEXT,
        ativo INTEGER DEFAULT 1,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ferramentas (
        id SERIAL PRIMARY KEY,
        tool_key TEXT NOT NULL,
        nome TEXT NOT NULL,
        descricao TEXT,
        webhook_url TEXT NOT NULL DEFAULT '',
        integracao TEXT NOT NULL DEFAULT 'global',
        unidade_id INTEGER REFERENCES unidades(id) ON DELETE CASCADE,
        destaque_dashboard INTEGER DEFAULT 0,
        ativo INTEGER DEFAULT 1,
        chamadas_sucesso INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ,
        UNIQUE (tool_key, unidade_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ferramenta_parametros (
        id SERIAL PRIMARY KEY,
        ferramenta_id INTEGER NOT NULL REFERENCES ferramentas(id) ON DELETE CASCADE,
        nome TEXT NOT NULL,
        tipo TEXT NOT NULL DEFAULT 'texto',
        descricao TEXT,
        obrigatorio INTEGER DEFAULT 0,
        ordem INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ferramenta_chamadas (
        id BIGSERIAL PRIMARY KEY,
        ferramenta_id INTEGER NOT NULL REFERENCES ferramentas(id) ON DELETE CASCADE,
        ok INTEGER DEFAULT 0,
        conversation_id TEXT,
        motivo TEXT,
        created_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS perguntas_sem_resposta_ia (
        id BIGSERIAL PRIMARY KEY,
        id_cliente TEXT NOT NULL,
        pergunta TEXT NOT NULL,
        mensagem TEXT,
        fase TEXT,
        motivo TEXT,
        resolvida INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS uso_ia (
        id BIGSERIAL PRIMARY KEY,
        id_cliente TEXT,
        finalidade TEXT,
        provedor TEXT,
        modelo TEXT,
        tokens_entrada INTEGER DEFAULT 0,
        tokens_cache INTEGER DEFAULT 0,
        tokens_saida INTEGER DEFAULT 0,
        segundos_audio REAL,
        custo_usd DOUBLE PRECISION,
        created_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_uso_ia_criado ON uso_ia(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_uso_ia_cliente ON uso_ia(id_cliente)",
    "CREATE INDEX IF NOT EXISTS idx_perguntas_sem_resposta ON perguntas_sem_resposta_ia(resolvida, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_turno_log_criado ON turno_log_ia(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_historico_cliente ON historico_mensagens_ia(id_cliente, id)",
    "CREATE INDEX IF NOT EXISTS idx_turno_log_cliente ON turno_log_ia(id_cliente, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_estado_conversation ON estado_cliente_ia(conversation_id)",
    "CREATE INDEX IF NOT EXISTS idx_estado_fase ON estado_cliente_ia(fase)",
    "CREATE INDEX IF NOT EXISTS idx_estado_updated ON estado_cliente_ia(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_planos_ativo_ordem ON planos(ativo, ordem, valor)",
    "CREATE INDEX IF NOT EXISTS idx_planos_unidade ON planos(unidade_id)",
    "CREATE INDEX IF NOT EXISTS idx_ferramentas_key ON ferramentas(tool_key)",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database_url() -> str:
    settings = get_settings()
    url = (settings.database_url or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL não configurada. Ex.: "
            "postgresql://sofia:sofia@localhost:5432/sofia"
        )
    return url


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=_database_url(),
            min_size=max(1, int(settings.db_pool_min_size)),
            max_size=max(2, int(settings.db_pool_max_size)),
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )
        logger.info(
            "Pool PostgreSQL aberto (min=%s max=%s)",
            settings.db_pool_min_size,
            settings.db_pool_max_size,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_connection() -> Iterator[Any]:
    """Yields a psycopg connection (dict rows). Commit on success."""
    pool = get_pool()
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in (
        "tem_cobertura",
        "requer_cartao",
        "fidelidade_aceita",
        "taxa_instalacao_pagar",
        "documento_cpf_validado",
        "transferido_humano",
        "cumprimento_feito",
        "cadastro_completo",
        "agendamento_confirmado",
        "ativo",
        "destaque",
        "termos_enviados",
        "audio_fidelidade_enviado",
        "ativado_ixc",
        "imagem_plano_enviada",
        "rag_hit",
        "resolvida",
    ):
        if key in data and data[key] is not None:
            data[key] = bool(data[key])
    if data.get("retorno_estado") and isinstance(data["retorno_estado"], str):
        try:
            data["retorno_estado"] = json.loads(data["retorno_estado"])
        except json.JSONDecodeError:
            pass
    for key in ("horarios_manha", "horarios_tarde", "imagens_plano_enviadas"):
        if key in data and isinstance(data[key], str) and data[key]:
            try:
                data[key] = json.loads(data[key])
            except json.JSONDecodeError:
                if key == "imagens_plano_enviadas":
                    data[key] = []
    for key in ("created_at", "updated_at"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            data[key] = data[key].isoformat()
    return data


def init_schema() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            for stmt in SCHEMA_STATEMENTS:
                cur.execute(stmt)
            _migrar_colunas(cur)
            _migrar_turno_log(cur)
            _migrar_painel(cur)
            _seed_unidades_se_vazio(cur)
            from app.planos_catalog_seed import seed_planos_do_catalogo

            seed_planos_do_catalogo(cur)
            from app.ferramentas_catalog import (
                seed_ferramentas_do_catalogo,
                sincronizar_persistencia_urls_ferramentas,
            )

            seed_ferramentas_do_catalogo(cur)

    sincronizar_persistencia_urls_ferramentas()


def _colunas_existentes(cur: Any, tabela: str) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (tabela,),
    )
    return {str(r["column_name"]) for r in cur.fetchall()}


def _migrar_colunas(cur: Any) -> None:
    cols = _colunas_existentes(cur, "estado_cliente_ia")
    extras = [
        ("cadastro_completo", "INTEGER DEFAULT 0"),
        ("ixc_cliente_id", "TEXT"),
        ("tecnico_id", "TEXT"),
        ("data_agendamento", "TEXT"),
        ("horarios_manha", "TEXT"),
        ("horarios_tarde", "TEXT"),
        ("horario_escolhido", "TEXT"),
        ("preferencia_horario", "TEXT"),
        ("agendamento_confirmado", "INTEGER DEFAULT 0"),
        ("tentativas_sem_cobertura", "INTEGER DEFAULT 0"),
        ("tentativas_plano_invalido", "INTEGER DEFAULT 0"),
        ("conversation_id", "TEXT"),
        ("contact_id", "TEXT"),
        ("os_id", "TEXT"),
        ("id_contrato_ixc", "TEXT"),
        ("ultimo_topico", "TEXT"),
        ("ultima_pergunta_cliente", "TEXT"),
        ("termos_enviados", "INTEGER DEFAULT 0"),
        ("audio_fidelidade_enviado", "INTEGER DEFAULT 0"),
        ("ativado_ixc", "INTEGER DEFAULT 0"),
        ("imagem_plano_enviada", "INTEGER DEFAULT 0"),
        ("imagens_plano_enviadas", "TEXT DEFAULT '[]'"),
        ("unidade_id", "INTEGER"),
        ("followup_count", "INTEGER DEFAULT 0"),
        ("last_client_message_at", "TIMESTAMPTZ"),
        ("last_followup_at", "TIMESTAMPTZ"),
        ("contexto_plano", "TEXT"),
        ("tentativas_travadas", "INTEGER DEFAULT 0"),
        ("notas_conversa", "TEXT"),
    ]
    for nome, tipo in extras:
        if nome not in cols:
            cur.execute(f"ALTER TABLE estado_cliente_ia ADD COLUMN {nome} {tipo}")


def _migrar_turno_log(cur: Any) -> None:
    """Colunas para avaliação: estado antes do turno e interpretação bruta do LLM."""
    cols = _colunas_existentes(cur, "turno_log_ia")
    extras = [
        ("estado_antes", "TEXT"),
        ("interpretacao_llm", "TEXT"),
        ("confianca", "REAL"),
        ("sinais", "TEXT"),
        ("divergencias", "TEXT"),
    ]
    for nome, tipo in extras:
        if nome not in cols:
            cur.execute(f"ALTER TABLE turno_log_ia ADD COLUMN {nome} {tipo}")


def _migrar_painel(cur: Any) -> None:
    """Migrações idempotentes para painel multiunidade."""
    # sofia_config legado (chave PK) → nova estrutura
    cfg_cols = _colunas_existentes(cur, "sofia_config")
    if cfg_cols and "id" not in cfg_cols:
        cur.execute("ALTER TABLE sofia_config RENAME TO sofia_config_legacy")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sofia_config (
                id SERIAL PRIMARY KEY,
                unidade_id INTEGER REFERENCES unidades(id) ON DELETE CASCADE,
                chave TEXT NOT NULL,
                valor TEXT NOT NULL,
                updated_at TIMESTAMPTZ,
                UNIQUE (unidade_id, chave)
            )
            """
        )
        cur.execute(
            """
            INSERT INTO sofia_config (unidade_id, chave, valor, updated_at)
            SELECT NULL, chave, valor, updated_at FROM sofia_config_legacy
            ON CONFLICT DO NOTHING
            """
        )

    planos_cols = _colunas_existentes(cur, "planos")
    if "unidade_id" not in planos_cols:
        cur.execute("ALTER TABLE planos ADD COLUMN unidade_id INTEGER")
    if "imagem_url" not in planos_cols:
        cur.execute("ALTER TABLE planos ADD COLUMN imagem_url TEXT")
    if "valor_pontualidade" not in planos_cols:
        cur.execute("ALTER TABLE planos ADD COLUMN valor_pontualidade DOUBLE PRECISION")
    if "condicao_valor_pontualidade" not in planos_cols:
        cur.execute("ALTER TABLE planos ADD COLUMN condicao_valor_pontualidade TEXT")
    if "tags" not in planos_cols:
        cur.execute("ALTER TABLE planos ADD COLUMN tags TEXT DEFAULT '[]'")

    hist_cols = _colunas_existentes(cur, "historico_mensagens_ia")
    if hist_cols and "imagem_url" not in hist_cols:
        cur.execute("ALTER TABLE historico_mensagens_ia ADD COLUMN imagem_url TEXT")

    promo_cols = _colunas_existentes(cur, "promocoes")
    if "unidade_id" not in promo_cols:
        cur.execute("ALTER TABLE promocoes ADD COLUMN unidade_id INTEGER")
        # remove unique só em codigo se existir — PG: dropar constraint se houver
        cur.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'promocoes_codigo_key'
              ) THEN
                ALTER TABLE promocoes DROP CONSTRAINT promocoes_codigo_key;
              END IF;
            END $$;
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS promocoes_unidade_codigo_uidx
            ON promocoes (unidade_id, codigo)
            """
        )


def _seed_unidades_se_vazio(cur: Any) -> None:
    cur.execute("SELECT COUNT(*) AS n FROM unidades")
    if int(cur.fetchone()["n"]) > 0:
        return
    now = _now()
    cur.execute(
        """
        INSERT INTO unidades (codigo, nome, ativo, created_at, updated_at)
        VALUES ('DEFAULT', 'Unidade padrão', 1, %s, %s)
        """,
        (now, now),
    )


def _seed_ferramenta_transferir(cur: Any) -> None:
    cur.execute(
        "SELECT id FROM ferramentas WHERE tool_key = %s AND unidade_id IS NULL LIMIT 1",
        ("transferir_atendimento",),
    )
    if cur.fetchone():
        return
    now = _now()
    cur.execute(
        """
        INSERT INTO ferramentas (
            tool_key, nome, descricao, webhook_url, integracao,
            unidade_id, destaque_dashboard, ativo, chamadas_sucesso, created_at, updated_at
        ) VALUES (
            'transferir_atendimento',
            'Transferir atendimento',
            'Transfere a conversa para um humano no Chatwoot (time/atendente/labels). Use quando o cliente pedir humano ou houver erro que exija equipe.',
            '',
            'global',
            NULL,
            1,
            1,
            0,
            %s,
            %s
        )
        RETURNING id
        """,
        (now, now),
    )
    row = cur.fetchone()
    fid = int(row["id"])
    params = [
        ("conversation_id", "texto", "ID da conversa no Chatwoot", 1, 0),
        ("motivo", "texto", "Motivo da transferência", 0, 1),
        ("assignee_id", "numero", "ID do atendente (opcional)", 0, 2),
        ("team_id", "numero", "ID do time (opcional)", 0, 3),
    ]
    for nome, tipo, desc, obr, ordem in params:
        cur.execute(
            """
            INSERT INTO ferramenta_parametros (
                ferramenta_id, nome, tipo, descricao, obrigatorio, ordem
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (fid, nome, tipo, desc, obr, ordem),
        )


def _seed_planos_se_vazio(cur: Any) -> None:
    cur.execute("SELECT COUNT(*) AS n FROM planos")
    total = int(cur.fetchone()["n"])
    if total > 0:
        return

    planos = [
        ("MOV ESSENCIAL", "400 Mega", "residencial", 0, 129.90,
         "Ideal para uso do dia a dia.", 8, "Wi-Fi incluso; suporte 24h", 10, 1, 1),
        ("MOV SUPER", "600 Mega", "residencial", 0, 159.90,
         "Mais velocidade para streaming e home office.", 12,
         "Wi-Fi incluso; prioridade no suporte", 20, 1, 0),
        ("MOV INFINITY", "700 Mega", "residencial", 1, 189.90,
         "Alta performance com benefícios extras.", 16,
         "Wi-Fi 6; apps inclusos; instalação facilitada", 30, 1, 0),
        ("MOV ONE+", "1 Giga", "residencial", 1, 229.90,
         "Top de linha para quem não quer travar.", 20,
         "Wi-Fi 6; múltiplos dispositivos; prioridade máxima", 40, 1, 0),
    ]
    cur.executemany(
        """
        INSERT INTO planos (
            nome, velocidade, modalidade, requer_cartao, valor,
            descricao, dispositivos_max, beneficios, ordem, ativo, destaque
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        planos,
    )


def carregar_ou_criar_estado(id_cliente: str) -> dict[str, Any]:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO estado_cliente_ia (id_cliente, fase, versao_fluxo, created_at, updated_at)
                VALUES (%s, 'inicio', 4, %s, %s)
                ON CONFLICT (id_cliente) DO NOTHING
                """,
                (id_cliente, now, now),
            )
            cur.execute(
                "SELECT * FROM estado_cliente_ia WHERE id_cliente = %s",
                (id_cliente,),
            )
            return _row_to_dict(cur.fetchone()) or {}


def log_mensagem(
    id_cliente: str,
    remetente: str,
    mensagem: str,
    *,
    imagem_url: str = "",
) -> None:
    now = _now()
    img = str(imagem_url or "").strip() or None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO historico_mensagens_ia (id_cliente, remetente, mensagem, imagem_url, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (id_cliente, remetente, mensagem, img, now),
            )
            if remetente == "cliente":
                cur.execute(
                    """
                    UPDATE estado_cliente_ia
                    SET last_client_message_at = %s,
                        followup_count = 0,
                        updated_at = %s
                    WHERE id_cliente = %s
                    """,
                    (now, now, id_cliente),
                )


def listar_estados_followup_candidatos(*, limite: int = 80) -> list[dict[str, Any]]:
    """Estados onde a Eva aguarda resposta do cliente (follow-up de inatividade)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM estado_cliente_ia
                WHERE conversation_id IS NOT NULL
                  AND TRIM(conversation_id) <> ''
                  AND COALESCE(transferido_humano, 0) = 0
                  AND COALESCE(fase, '') NOT IN ('finalizado', 'transferido')
                  AND aguardando IS NOT NULL
                  AND TRIM(aguardando) <> ''
                  AND aguardando NOT LIKE 'resultado_%%'
                ORDER BY COALESCE(last_client_message_at, updated_at) ASC
                LIMIT %s
                """,
                (max(1, int(limite)),),
            )
            return [_row_to_dict(r) or {} for r in cur.fetchall()]


def registrar_followup_enviado(id_cliente: str) -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE estado_cliente_ia
                SET followup_count = COALESCE(followup_count, 0) + 1,
                    last_followup_at = %s,
                    updated_at = %s
                WHERE id_cliente = %s
                """,
                (now, now, id_cliente),
            )


def marcar_encerrado_inatividade(id_cliente: str, *, motivo: str = "") -> None:
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE estado_cliente_ia
                SET retorno_estado = CASE
                        WHEN COALESCE(fase, '') NOT IN ('finalizado', 'transferido')
                        THEN json_build_object('fase', fase, 'aguardando', aguardando)::text
                        ELSE retorno_estado
                    END,
                    fase = 'finalizado',
                    aguardando = NULL,
                    tentativas_travadas = 0,
                    motivo_transferencia = COALESCE(NULLIF(%s, ''), motivo_transferencia),
                    updated_at = %s
                WHERE id_cliente = %s
                """,
                (motivo, now, id_cliente),
            )


def historico_recente(id_cliente: str, limite: int = 6) -> list[dict[str, str]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT remetente, mensagem
                FROM historico_mensagens_ia
                WHERE id_cliente = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (id_cliente, limite),
            )
            rows = cur.fetchall()
    itens = [{"remetente": r["remetente"], "mensagem": r["mensagem"]} for r in rows]
    itens.reverse()
    return itens


def aplicar_transicao(
    estado: dict[str, Any],
    fase: str,
    aguardando: str | None,
    atualizar: dict[str, Any],
) -> dict[str, Any]:
    """Regras de atualização do estado, sem tocar no banco.

    Separada de `salvar_transicao` para que os testes de funil apliquem exatamente
    as mesmas regras em memória.
    """
    novo = dict(estado)
    if atualizar.get("reiniciar_atendimento"):
        # Cliente voltou depois de encerrado sem venda: funil limpo, histórico mantido
        from app.conversa import estado_reiniciado

        novo = estado_reiniciado(novo)
    novo["fase"] = fase
    novo["aguardando"] = aguardando
    novo["versao_fluxo"] = 4
    novo["updated_at"] = _now()

    mapeamento = [
        "cidade", "bairro", "nome", "cpf", "email", "telefone", "data_nascimento",
        "rg", "cep", "rua", "numero", "complemento", "metodo_pagamento",
        "tem_cobertura", "localizacao_fixa", "caixa_fibra",
        "plano_apresentado", "plano_apresentado_id", "plano_em_negociacao",
        "plano_em_negociacao_id", "plano_confirmado", "plano_confirmado_id",
        "ixc_cliente_id", "tecnico_id", "data_agendamento", "horario_escolhido",
        "preferencia_horario", "motivo_transferencia", "conversation_id",
        "contact_id", "os_id", "id_contrato_ixc", "ultimo_topico",
        "ultima_pergunta_cliente", "termos_enviados", "audio_fidelidade_enviado",
        "fidelidade_aceita", "ativado_ixc", "imagem_plano_enviada",
        "imagens_plano_enviadas",
        "contexto_plano",
    ]

    for chave in mapeamento:
        if chave in atualizar and atualizar[chave] is not None and atualizar[chave] != "":
            novo[chave] = atualizar[chave]

    for chave in ("horarios_manha", "horarios_tarde"):
        if chave in atualizar and atualizar[chave] is not None:
            val = atualizar[chave]
            novo[chave] = json.dumps(val, ensure_ascii=False) if isinstance(val, list) else val

    if atualizar.get("limpar_bairro"):
        novo["bairro"] = None
    if atualizar.get("limpar_cidade"):
        novo["cidade"] = None
    if atualizar.get("resetar_cobertura"):
        novo["tem_cobertura"] = None
        novo["localizacao_fixa"] = None
        novo["caixa_fibra"] = None
    if atualizar.get("invalidar_plano"):
        novo["plano_apresentado"] = None
        novo["plano_apresentado_id"] = None
        novo["plano_em_negociacao"] = None
        novo["plano_em_negociacao_id"] = None
        novo["plano_confirmado"] = None
        novo["plano_confirmado_id"] = None
        novo["imagem_plano_enviada"] = False
        novo["imagens_plano_enviadas"] = "[]"
    if atualizar.get("limpar_plano_em_negociacao"):
        novo["plano_em_negociacao"] = None
        novo["plano_em_negociacao_id"] = None
    if atualizar.get("invalidar_validacao_cpf"):
        novo["documento_cpf_validado"] = False
    if "documento_cpf_validado" in atualizar:
        novo["documento_cpf_validado"] = bool(atualizar["documento_cpf_validado"])
    if atualizar.get("transferido_humano"):
        novo["transferido_humano"] = True
    if "cadastro_completo" in atualizar:
        novo["cadastro_completo"] = bool(atualizar["cadastro_completo"])
    if "agendamento_confirmado" in atualizar:
        novo["agendamento_confirmado"] = bool(atualizar["agendamento_confirmado"])
    if "termos_enviados" in atualizar:
        novo["termos_enviados"] = bool(atualizar["termos_enviados"])
    if "audio_fidelidade_enviado" in atualizar:
        novo["audio_fidelidade_enviado"] = bool(atualizar["audio_fidelidade_enviado"])
    if "fidelidade_aceita" in atualizar:
        novo["fidelidade_aceita"] = bool(atualizar["fidelidade_aceita"])
    if "ativado_ixc" in atualizar:
        novo["ativado_ixc"] = bool(atualizar["ativado_ixc"])
    if "imagem_plano_enviada" in atualizar:
        novo["imagem_plano_enviada"] = bool(atualizar["imagem_plano_enviada"])
    if "imagens_plano_enviadas" in atualizar:
        val = atualizar["imagens_plano_enviadas"]
        if isinstance(val, (list, tuple, set)):
            novo["imagens_plano_enviadas"] = json.dumps(
                [int(x) for x in val], ensure_ascii=False
            )
        else:
            novo["imagens_plano_enviadas"] = str(val or "[]")
    if "tentativas_sem_cobertura" in atualizar:
        try:
            novo["tentativas_sem_cobertura"] = int(atualizar["tentativas_sem_cobertura"])
        except (TypeError, ValueError):
            novo["tentativas_sem_cobertura"] = 0
    if "tentativas_plano_invalido" in atualizar:
        try:
            novo["tentativas_plano_invalido"] = int(atualizar["tentativas_plano_invalido"])
        except (TypeError, ValueError):
            novo["tentativas_plano_invalido"] = 0
    if "fase_anterior" in atualizar:
        novo["fase_anterior"] = atualizar["fase_anterior"]
    if "aguardando_anterior" in atualizar:
        novo["aguardando_anterior"] = atualizar["aguardando_anterior"]
    if atualizar.get("limpar_desvio"):
        novo["fase_anterior"] = None
        novo["aguardando_anterior"] = None
    if atualizar.get("limpar_topico"):
        novo["ultimo_topico"] = None
    if "contexto_plano" in atualizar:
        val_ctx = atualizar["contexto_plano"]
        novo["contexto_plano"] = (
            str(val_ctx).strip() if val_ctx is not None else None
        ) or None
    if "tentativas_travadas" in atualizar:
        try:
            novo["tentativas_travadas"] = max(0, int(atualizar["tentativas_travadas"] or 0))
        except (TypeError, ValueError):
            novo["tentativas_travadas"] = 0
    if "notas_conversa" in atualizar:
        novo["notas_conversa"] = str(atualizar["notas_conversa"] or "").strip() or None
    if "retorno_estado" in atualizar:
        # Onde o atendimento estava quando foi encerrado sem venda (ver conversa.retomar_encerrado)
        novo["retorno_estado"] = atualizar["retorno_estado"] or None
    return novo


def salvar_transicao(
    id_cliente: str,
    fase: str,
    aguardando: str | None,
    atualizar: dict[str, Any],
) -> dict[str, Any]:
    novo = aplicar_transicao(carregar_ou_criar_estado(id_cliente), fase, aguardando, atualizar)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE estado_cliente_ia SET
                    fase = %s, aguardando = %s, versao_fluxo = 4,
                    cidade = %s, bairro = %s, tem_cobertura = %s,
                    localizacao_fixa = %s, caixa_fibra = %s,
                    plano_apresentado = %s, plano_apresentado_id = %s,
                    plano_em_negociacao = %s, plano_em_negociacao_id = %s,
                    plano_confirmado = %s, plano_confirmado_id = %s,
                    nome = %s, cpf = %s, email = %s, telefone = %s,
                    data_nascimento = %s, rg = %s, cep = %s, rua = %s,
                    numero = %s, complemento = %s, metodo_pagamento = %s,
                    motivo_transferencia = %s, documento_cpf_validado = %s,
                    transferido_humano = %s, fase_anterior = %s,
                    aguardando_anterior = %s, cadastro_completo = %s,
                    ixc_cliente_id = %s, tecnico_id = %s, data_agendamento = %s,
                    horarios_manha = %s, horarios_tarde = %s,
                    horario_escolhido = %s, preferencia_horario = %s,
                    agendamento_confirmado = %s, tentativas_sem_cobertura = %s,
                    tentativas_plano_invalido = %s, conversation_id = %s,
                    contact_id = %s, os_id = %s, id_contrato_ixc = %s,
                    ultimo_topico = %s, ultima_pergunta_cliente = %s,
                    termos_enviados = %s, audio_fidelidade_enviado = %s,
                    fidelidade_aceita = %s, ativado_ixc = %s,
                    imagem_plano_enviada = %s, imagens_plano_enviadas = %s,
                    contexto_plano = %s,
                    tentativas_travadas = %s, notas_conversa = %s, retorno_estado = %s,
                    updated_at = %s
                WHERE id_cliente = %s
                """,
                (
                    novo.get("fase"),
                    novo.get("aguardando"),
                    novo.get("cidade"),
                    novo.get("bairro"),
                    None if novo.get("tem_cobertura") is None else int(bool(novo.get("tem_cobertura"))),
                    novo.get("localizacao_fixa"),
                    novo.get("caixa_fibra"),
                    novo.get("plano_apresentado"),
                    novo.get("plano_apresentado_id"),
                    novo.get("plano_em_negociacao"),
                    novo.get("plano_em_negociacao_id"),
                    novo.get("plano_confirmado"),
                    novo.get("plano_confirmado_id"),
                    novo.get("nome"),
                    novo.get("cpf"),
                    novo.get("email"),
                    novo.get("telefone"),
                    novo.get("data_nascimento"),
                    novo.get("rg"),
                    novo.get("cep"),
                    novo.get("rua"),
                    novo.get("numero"),
                    novo.get("complemento"),
                    novo.get("metodo_pagamento"),
                    novo.get("motivo_transferencia"),
                    int(bool(novo.get("documento_cpf_validado"))),
                    int(bool(novo.get("transferido_humano"))),
                    novo.get("fase_anterior"),
                    novo.get("aguardando_anterior"),
                    int(bool(novo.get("cadastro_completo"))),
                    novo.get("ixc_cliente_id"),
                    novo.get("tecnico_id"),
                    novo.get("data_agendamento"),
                    json.dumps(novo.get("horarios_manha"), ensure_ascii=False)
                    if isinstance(novo.get("horarios_manha"), list)
                    else novo.get("horarios_manha"),
                    json.dumps(novo.get("horarios_tarde"), ensure_ascii=False)
                    if isinstance(novo.get("horarios_tarde"), list)
                    else novo.get("horarios_tarde"),
                    novo.get("horario_escolhido"),
                    novo.get("preferencia_horario"),
                    int(bool(novo.get("agendamento_confirmado"))),
                    int(novo.get("tentativas_sem_cobertura") or 0),
                    int(novo.get("tentativas_plano_invalido") or 0),
                    novo.get("conversation_id"),
                    novo.get("contact_id"),
                    novo.get("os_id"),
                    novo.get("id_contrato_ixc"),
                    novo.get("ultimo_topico"),
                    novo.get("ultima_pergunta_cliente"),
                    int(bool(novo.get("termos_enviados"))),
                    int(bool(novo.get("audio_fidelidade_enviado"))),
                    int(bool(novo.get("fidelidade_aceita"))),
                    int(bool(novo.get("ativado_ixc"))),
                    int(bool(novo.get("imagem_plano_enviada"))),
                    json.dumps(novo.get("imagens_plano_enviadas") or [], ensure_ascii=False)
                    if isinstance(novo.get("imagens_plano_enviadas"), list)
                    else (novo.get("imagens_plano_enviadas") or "[]"),
                    novo.get("contexto_plano"),
                    int(novo.get("tentativas_travadas") or 0),
                    novo.get("notas_conversa"),
                    json.dumps(novo.get("retorno_estado"), ensure_ascii=False)
                    if isinstance(novo.get("retorno_estado"), dict)
                    else (novo.get("retorno_estado") or None),
                    _now(),
                    id_cliente,
                ),
            )
            if atualizar.get("reiniciar_atendimento"):
                cur.execute(
                    """
                    UPDATE estado_cliente_ia
                    SET cumprimento_feito = 0, followup_count = 0, ultima_mensagem_sofia = NULL
                    WHERE id_cliente = %s
                    """,
                    (id_cliente,),
                )

    return carregar_ou_criar_estado(id_cliente)


def salvar_resposta(id_cliente: str, texto: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE estado_cliente_ia
                SET cumprimento_feito = 1,
                    ultima_mensagem_sofia = %s,
                    updated_at = %s
                WHERE id_cliente = %s
                """,
                (texto, _now(), id_cliente),
            )
            cur.execute(
                """
                INSERT INTO historico_mensagens_ia (id_cliente, remetente, mensagem, created_at)
                VALUES (%s, 'eva', %s, %s)
                """,
                (id_cliente, texto, _now()),
            )


def listar_planos_ativos() -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nome, velocidade, modalidade, requer_cartao, valor,
                       parcelas, descricao,
                       COALESCE(dispositivos_max, max_dispositivos) AS dispositivos_max,
                       beneficios, ordem, destaque, unidade_id, imagem_url,
                       valor_pontualidade, condicao_valor_pontualidade, tags
                FROM planos
                WHERE ativo = 1
                ORDER BY ordem ASC, valor ASC, id ASC
                """
            )
            out: list[dict[str, Any]] = []
            for r in cur.fetchall():
                row = _row_to_dict(r) or {}
                raw_tags = row.get("tags")
                if isinstance(raw_tags, str):
                    try:
                        row["tags"] = json.loads(raw_tags) if raw_tags.strip() else []
                    except json.JSONDecodeError:
                        row["tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]
                elif raw_tags is None:
                    row["tags"] = []
                if "destaque" in row:
                    row["destaque"] = bool(row["destaque"])
                if "requer_cartao" in row:
                    row["requer_cartao"] = bool(row["requer_cartao"])
                out.append(row)
            return out


def plano_destaque() -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nome, velocidade, modalidade, requer_cartao, valor,
                       parcelas, descricao,
                       COALESCE(dispositivos_max, max_dispositivos) AS dispositivos_max,
                       beneficios, ordem, destaque, unidade_id, imagem_url
                FROM planos
                WHERE ativo = 1 AND destaque = 1
                ORDER BY id ASC
                LIMIT 1
                """
            )
            return _row_to_dict(cur.fetchone())


def resetar_cliente(id_cliente: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM historico_mensagens_ia WHERE id_cliente = %s", (id_cliente,))
            cur.execute("DELETE FROM turno_log_ia WHERE id_cliente = %s", (id_cliente,))
            cur.execute("DELETE FROM estado_cliente_ia WHERE id_cliente = %s", (id_cliente,))


def log_turno(
    id_cliente: str,
    *,
    mensagem_cliente: str = "",
    eventos: list[str] | None = None,
    acao: str = "",
    objetivo: str = "",
    fase: str = "",
    aguardando: str | None = None,
    topico: str = "",
    rag_hit: bool = False,
    duracao_ms: int | None = None,
    message_id: str = "",
    estado_antes: dict[str, Any] | None = None,
    interpretacao_llm: str = "",
    confianca: float | None = None,
    sinais: list[str] | None = None,
    divergencias: list[str] | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO turno_log_ia (
                    id_cliente, mensagem_cliente, eventos, acao, objetivo,
                    fase, aguardando, topico, rag_hit, duracao_ms, message_id, created_at,
                    estado_antes, interpretacao_llm, confianca, sinais, divergencias
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_cliente,
                    mensagem_cliente[:2000],
                    json.dumps(eventos or [], ensure_ascii=False),
                    acao,
                    objetivo or "",
                    fase,
                    aguardando,
                    topico or "",
                    int(bool(rag_hit)),
                    duracao_ms,
                    message_id or None,
                    _now(),
                    json.dumps(estado_antes, ensure_ascii=False) if estado_antes else None,
                    (interpretacao_llm or "")[:4000] or None,
                    confianca,
                    json.dumps(sinais, ensure_ascii=False) if sinais else None,
                    json.dumps(divergencias, ensure_ascii=False) if divergencias else None,
                ),
            )


def registrar_uso_ia(
    *,
    id_cliente: str | None,
    finalidade: str,
    provedor: str,
    modelo: str,
    tokens_entrada: int = 0,
    tokens_cache: int = 0,
    tokens_saida: int = 0,
    segundos_audio: float | None = None,
    custo_usd: float | None = None,
) -> None:
    """Uma chamada ao modelo (ou transcrição) e o que ela custou — ver app/custos.py."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uso_ia (
                    id_cliente, finalidade, provedor, modelo, tokens_entrada, tokens_cache,
                    tokens_saida, segundos_audio, custo_usd, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    id_cliente or None, finalidade, provedor, modelo, int(tokens_entrada or 0),
                    int(tokens_cache or 0), int(tokens_saida or 0), segundos_audio, custo_usd, _now(),
                ),
            )


def registrar_pergunta_sem_resposta(
    id_cliente: str, pergunta: str, *, mensagem: str = "", fase: str = "", motivo: str = ""
) -> None:
    """Dúvida que a base de conhecimento não respondeu — vira pendência no painel."""
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO perguntas_sem_resposta_ia
                    (id_cliente, pergunta, mensagem, fase, motivo, resolvida, created_at)
                VALUES (%s, %s, %s, %s, %s, 0, %s)
                """,
                (id_cliente, pergunta[:500], (mensagem or "")[:1000], fase, motivo[:200], _now()),
            )


def listar_perguntas_sem_resposta(*, resolvidas: bool = False, limite: int = 100) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite or 100), 500))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, id_cliente, pergunta, mensagem, fase, motivo, resolvida, created_at
                FROM perguntas_sem_resposta_ia
                WHERE resolvida = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (int(bool(resolvidas)), limite),
            )
            return [_row_to_dict(r) or {} for r in cur.fetchall()]


def marcar_pergunta_resolvida(pergunta_id: int, resolvida: bool = True) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE perguntas_sem_resposta_ia SET resolvida = %s WHERE id = %s",
                (int(bool(resolvida)), int(pergunta_id)),
            )
            return cur.rowcount > 0


def mensagem_ja_processada(message_id: str) -> bool:
    mid = (message_id or "").strip()
    if not mid:
        return False
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 AS ok FROM mensagens_processadas_ia WHERE message_id = %s LIMIT 1",
                (mid,),
            )
            return cur.fetchone() is not None


def marcar_mensagem_processada(message_id: str, id_cliente: str) -> None:
    mid = (message_id or "").strip()
    if not mid:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mensagens_processadas_ia (message_id, id_cliente, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (mid, id_cliente, _now()),
            )


def turnos_recentes(id_cliente: str, limite: int = 20) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite or 20), 100))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mensagem_cliente, eventos, acao, objetivo, fase, aguardando,
                       topico, rag_hit, duracao_ms, message_id, created_at
                FROM turno_log_ia
                WHERE id_cliente = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (id_cliente, limite),
            )
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        item = _row_to_dict(r) or {}
        try:
            item["eventos"] = json.loads(item.get("eventos") or "[]")
        except json.JSONDecodeError:
            item["eventos"] = []
        out.append(item)
    out.reverse()
    return out


def turnos_para_avaliacao(limite: int = 500) -> list[dict[str, Any]]:
    """Turnos mais recentes de todos os clientes, com o histórico que o interpretador viu."""
    limite = max(1, min(int(limite or 500), 5000))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, id_cliente, mensagem_cliente, eventos, acao, objetivo,
                       fase, aguardando, estado_antes,
                       interpretacao_llm, confianca, created_at
                FROM turno_log_ia
                ORDER BY id DESC
                LIMIT %s
                """,
                (limite,),
            )
            turnos = [_row_to_dict(r) or {} for r in cur.fetchall()]
            turnos.reverse()
            for t in turnos:
                cur.execute(
                    """
                    SELECT remetente, mensagem
                    FROM historico_mensagens_ia
                    WHERE id_cliente = %s AND created_at < %s
                    ORDER BY id DESC
                    LIMIT 16
                    """,
                    (t.get("id_cliente"), t.get("created_at")),
                )
                hist = [
                    {"remetente": r["remetente"], "mensagem": r["mensagem"]}
                    for r in cur.fetchall()
                ]
                hist.reverse()
                # O log do turno é gravado depois da resposta — corta na mensagem do cliente
                msg = str(t.get("mensagem_cliente") or "").strip()
                for i in range(len(hist) - 1, -1, -1):
                    if (
                        hist[i]["remetente"] == "cliente"
                        and str(hist[i]["mensagem"] or "").strip()[:2000] == msg
                    ):
                        hist = hist[:i]
                        break
                t["historico"] = hist[-8:]
    for t in turnos:
        try:
            t["eventos"] = json.loads(t.get("eventos") or "[]")
        except json.JSONDecodeError:
            t["eventos"] = []
        try:
            t["estado_antes"] = json.loads(t.get("estado_antes") or "null")
        except json.JSONDecodeError:
            t["estado_antes"] = None
    return turnos


def limpar_historico(id_cliente: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM historico_mensagens_ia WHERE id_cliente = %s",
                (id_cliente,),
            )
