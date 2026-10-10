"""Métricas agregadas (PostgreSQL) — base do dashboard."""

from __future__ import annotations

from typing import Any

from app.db import get_connection


def _status_operacional(r: dict[str, Any]) -> str:
    fase = str(r.get("fase") or "")
    if r.get("transferido_humano") or fase == "transferido":
        return "transferido"
    if fase in ("finalizado", "pos_venda") and r.get("agendamento_confirmado"):
        return "finalizado"
    if fase == "finalizado":
        return "finalizado"
    return "com_ia"


def resumo() -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM estado_cliente_ia")
            total = cur.fetchone()["n"]
            cur.execute(
                """
                SELECT COALESCE(fase, 'inicio') AS fase, COUNT(*) AS n
                FROM estado_cliente_ia
                GROUP BY COALESCE(fase, 'inicio')
                ORDER BY n DESC
                """
            )
            por_fase = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE agendamento_confirmado = 1"
            )
            agendados = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE transferido_humano = 1"
            )
            transferidos = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE tem_cobertura = 1"
            )
            cobertura = cur.fetchone()["n"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE cadastro_completo = 1"
            )
            cadastros = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM historico_mensagens_ia")
            msgs = cur.fetchone()["n"]
            cur.execute(
                """
                SELECT COUNT(*) AS n FROM estado_cliente_ia
                WHERE COALESCE(transferido_humano, 0) = 0
                  AND COALESCE(fase, '') NOT IN ('transferido', 'finalizado')
                """
            )
            com_ia = cur.fetchone()["n"]

    ferramentas_destaque: list[dict[str, Any]] = []
    try:
        from app.ferramentas import metricas_ferramentas_destaque

        ferramentas_destaque = metricas_ferramentas_destaque()
    except Exception:
        ferramentas_destaque = []

    return {
        "conversas": total,
        "mensagens": msgs,
        "com_cobertura": cobertura,
        "cadastro_completo": cadastros,
        "agendamentos_confirmados": agendados,
        "transferidos_humano": transferidos,
        "com_ia": com_ia,
        "por_fase": {str(r["fase"]): int(r["n"]) for r in por_fase},
        "ferramentas_destaque": ferramentas_destaque,
    }


def funil() -> dict[str, Any]:
    ordem = [
        "inicio",
        "viabilidade",
        "sem_cobertura",
        "vendas",
        "cadastro",
        "termos",
        "agendamento",
        "pos_venda",
        "finalizado",
        "transferido",
    ]
    dados = resumo()["por_fase"]
    etapas = [{"fase": f, "quantidade": int(dados.get(f, 0))} for f in ordem]
    extras = [
        {"fase": k, "quantidade": v}
        for k, v in dados.items()
        if k not in ordem
    ]
    return {"etapas": etapas + extras, "totais": resumo()}


def conversas(
    limite: int = 50,
    *,
    unidade_id: int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite or 50), 200))
    clauses: list[str] = []
    params: list[Any] = []
    if unidade_id is not None:
        clauses.append("unidade_id = %s")
        params.append(unidade_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limite)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id_cliente, fase, aguardando, cidade, bairro, plano_confirmado,
                       nome, telefone, tem_cobertura, cadastro_completo,
                       agendamento_confirmado, transferido_humano,
                       conversation_id, contact_id, unidade_id, updated_at
                FROM estado_cliente_ia
                {where}
                ORDER BY updated_at DESC NULLS LAST
                LIMIT %s
                """,
                tuple(params),
            )
            rows = cur.fetchall()
            out = []
            for r in rows:
                item = dict(r)
                if item.get("updated_at") is not None and not isinstance(item["updated_at"], str):
                    item["updated_at"] = item["updated_at"].isoformat()
                item["status"] = _status_operacional(item)
                if status and item["status"] != status:
                    continue
                out.append(item)
            return out


# ── Pontos de atenção: onde a conversa não fluiu ─────────────────────────────

ROTULO_SINAL = {
    "travado": "Cliente não avançou no passo",
    "impedimento": "Cliente não tinha / não conseguiu o que foi pedido",
    "objecao_preco": "Achou caro",
    "nao_entendeu": "Não entendeu o pedido",
    "espera": "Pediu um tempo",
    "adiamento": "Quis deixar para depois",
    "midia": "Mandou áudio ou arquivo que a Eva não leu",
    "audio_transcrito": "Áudio transcrito",
    "audio_nao_transcrito": "Áudio que não deu para transcrever",
    "repeticao": "Respondeu outra coisa",
    "esclarecimento": "Eva pediu esclarecimento",
    "sem_base": "Base de conhecimento sem resposta",
    "suporte": "Já era cliente (suporte/financeiro)",
    "alteracao_pos_cadastro": "Quis alterar dados após o cadastro",
    "transferido_por_travar": "Transferido por não avançar",
    "reenvio_termos": "Termos reenviados",
    "voltou_apos_encerrar": "Voltou após o encerramento",
    "retomou_de_onde_parou": "Retomou de onde parou",
    "silencio": "Eva não respondeu",
    "llm_fora_do_ar": "Modelo de IA fora do ar",
    "transferido_por_instabilidade": "Transferido por instabilidade do modelo",
    "rag_fora_do_ar": "Base de conhecimento fora do ar",
    "resposta_reescrita": "Resposta reescrita (citava dado sem fonte)",
    "resposta_barrada": "Resposta barrada (insistiu em dado sem fonte)",
    "regra_mudou_leitura": "Regras mudaram a leitura do modelo",
}

# Sinais que não são problema — ficam fora do total de turnos com atenção
_SINAIS_NEUTROS = {
    "espera", "voltou_apos_encerrar", "retomou_de_onde_parou", "reenvio_termos", "audio_transcrito",
    "regra_mudou_leitura", "resposta_reescrita",
}


def _sinais_do_turno(row: dict[str, Any]) -> list[str]:
    import json

    bruto = row.get("sinais")
    sinais: list[str] = []
    if bruto:
        try:
            lidos = json.loads(bruto) if isinstance(bruto, str) else bruto
            sinais = [str(s) for s in lidos or []]
        except (TypeError, ValueError):
            sinais = []
    # Turnos anteriores à coluna de sinais: o que dá para inferir do objetivo
    objetivo = str(row.get("objetivo") or "")
    if objetivo == "CLARIFICAR_INTENCAO" and "esclarecimento" not in sinais:
        sinais.append("esclarecimento")
    if objetivo == "RESPONDER_SEM_BASE_RAG" and "sem_base" not in sinais:
        sinais.append("sem_base")
    return sinais


def _etapa_do_turno(row: dict[str, Any]) -> str:
    """O passo em que o cliente estava ANTES do turno (depois de transferir já não há passo)."""
    import json

    try:
        antes = json.loads(row.get("estado_antes") or "{}")
    except (TypeError, ValueError):
        antes = {}
    return str(
        antes.get("aguardando") or antes.get("fase") or row.get("aguardando") or row.get("fase") or "—"
    )


def atencao(dias: int = 7, limite: int = 60) -> dict[str, Any]:
    """Onde a Eva e o cliente não se entenderam nos últimos dias."""
    from collections import Counter

    from app.db import listar_perguntas_sem_resposta

    dias = max(1, min(int(dias or 7), 90))
    limite = max(1, min(int(limite or 60), 300))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS turnos, COUNT(DISTINCT id_cliente) AS conversas
                FROM turno_log_ia
                WHERE created_at >= NOW() - (%s || ' days')::interval
                """,
                (str(dias),),
            )
            totais = cur.fetchone() or {}
            cur.execute(
                """
                SELECT id, id_cliente, mensagem_cliente, acao, objetivo, fase, aguardando,
                       sinais, estado_antes, divergencias, created_at
                FROM turno_log_ia
                WHERE created_at >= NOW() - (%s || ' days')::interval
                  AND (
                    sinais IS NOT NULL
                    OR objetivo IN ('CLARIFICAR_INTENCAO', 'RESPONDER_SEM_BASE_RAG')
                  )
                ORDER BY created_at DESC
                LIMIT 5000
                """,
                (str(dias),),
            )
            rows = [dict(r) for r in cur.fetchall()]

    regras_mudaram: list[dict[str, Any]] = []
    por_sinal: Counter[str] = Counter()
    por_etapa: Counter[str] = Counter()
    clientes_com_atencao: set[str] = set()
    itens: list[dict[str, Any]] = []
    for r in rows:
        sinais = _sinais_do_turno(r)
        relevantes = [s for s in sinais if s not in _SINAIS_NEUTROS]
        for s in sinais:
            por_sinal[s] += 1
        if r.get("divergencias") and len(regras_mudaram) < limite:
            import json

            try:
                lista = json.loads(r["divergencias"])
            except (TypeError, ValueError):
                lista = []
            criado_div = r.get("created_at")
            regras_mudaram.append({
                "id": r.get("id"),
                "id_cliente": r.get("id_cliente"),
                "etapa": _etapa_do_turno(r),
                "mensagem": r.get("mensagem_cliente") or "",
                "mudancas": [str(x) for x in lista],
                "created_at": criado_div.isoformat()
                if criado_div is not None and not isinstance(criado_div, str) else criado_div,
            })
        if not relevantes:
            continue
        clientes_com_atencao.add(str(r.get("id_cliente") or ""))
        if "travado" in sinais or "transferido_por_travar" in sinais:
            por_etapa[_etapa_do_turno(r)] += 1
        if len(itens) < limite:
            criado = r.get("created_at")
            itens.append({
                "id": r.get("id"),
                "id_cliente": r.get("id_cliente"),
                "mensagem": r.get("mensagem_cliente") or "",
                "etapa": _etapa_do_turno(r),
                "fase": r.get("fase") or "",
                "aguardando": r.get("aguardando") or "",
                "acao": r.get("acao") or "",
                "objetivo": r.get("objetivo") or "",
                "sinais": sinais,
                "created_at": criado.isoformat() if criado is not None and not isinstance(criado, str) else criado,
            })

    perguntas = listar_perguntas_sem_resposta(resolvidas=False, limite=100)
    return {
        "dias": dias,
        "turnos": int(totais.get("turnos") or 0),
        "conversas": int(totais.get("conversas") or 0),
        "conversas_com_atencao": len(clientes_com_atencao - {""}),
        "por_sinal": [
            {"sinal": s, "rotulo": ROTULO_SINAL.get(s, s), "quantidade": n}
            for s, n in por_sinal.most_common()
        ],
        "por_etapa": [{"etapa": e, "quantidade": n} for e, n in por_etapa.most_common(12)],
        "turnos_recentes": itens,
        "regras_mudaram": regras_mudaram,
        "perguntas_sem_resposta": perguntas,
    }



# ── Custo da IA ──────────────────────────────────────────────────────────────

FUSO_DO_NEGOCIO = "America/Belem"
ROTULO_FINALIDADE = {
    "interpretador": "Ler a mensagem do cliente",
    "resposta": "Escrever a resposta",
    "consultor": "Indicar plano",
    "transcricao": "Transcrever áudio",
    "avaliacao": "Avaliação do modelo (painel)",
    "outro": "Outros",
}


def custos(meses: int = 6, limite_clientes: int = 50) -> dict[str, Any]:
    """Custo da IA: geral, por mês, por finalidade, por cliente e por venda.

    Calculado a partir dos tokens gravados em `uso_ia` (ver app/custos.py). Linha sem
    custo gravado (modelo sem preço na época) é calculada com a tabela de preços atual.
    """
    from app import custos as custos_mod

    meses = max(1, min(int(meses or 6), 24))
    limite_clientes = max(1, min(int(limite_clientes or 50), 200))
    custos_mod.atualizar_se_preciso()  # cotação e preços com mais de 12 h: busca em segundo plano
    cfg = custos_mod.configuracao(usar_cache=False)
    cotacao = float(cfg["cotacao_dolar"])

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT to_char(date_trunc('month', created_at AT TIME ZONE %s), 'YYYY-MM') AS mes,
                       COALESCE(id_cliente, '') AS id_cliente,
                       COALESCE(finalidade, 'outro') AS finalidade,
                       COALESCE(modelo, '') AS modelo,
                       COUNT(*) AS chamadas,
                       SUM(tokens_entrada) AS entrada, SUM(tokens_cache) AS cache,
                       SUM(tokens_saida) AS saida, SUM(COALESCE(segundos_audio, 0)) AS audio,
                       SUM(custo_usd) AS custo,
                       SUM(custo_usd * COALESCE(cotacao_brl, %s)) AS custo_brl,
                       SUM(CASE WHEN custo_usd IS NULL THEN 1 ELSE 0 END) AS sem_custo,
                       SUM(CASE WHEN custo_usd IS NULL THEN tokens_entrada ELSE 0 END) AS entrada_sc,
                       SUM(CASE WHEN custo_usd IS NULL THEN tokens_cache ELSE 0 END) AS cache_sc,
                       SUM(CASE WHEN custo_usd IS NULL THEN tokens_saida ELSE 0 END) AS saida_sc,
                       MIN(created_at) AS primeiro
                FROM uso_ia
                GROUP BY 1, 2, 3, 4
                """,
                (FUSO_DO_NEGOCIO, cotacao),
            )
            linhas = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT to_char(date_trunc('month', NOW() AT TIME ZONE %s), 'YYYY-MM') AS mes",
                (FUSO_DO_NEGOCIO,),
            )
            mes_atual = cur.fetchone()["mes"]
            cur.execute(
                "SELECT COUNT(*) AS n FROM estado_cliente_ia WHERE agendamento_confirmado = 1"
            )
            vendas = int(cur.fetchone()["n"] or 0)

    sem_preco: set[str] = set()

    def valores(linha: dict[str, Any]) -> tuple[float, float]:
        """(US$, R$) da linha. O real usa a cotação gravada no dia de cada chamada."""
        total = float(linha.get("custo") or 0)
        reais = float(linha.get("custo_brl") or 0)
        if linha.get("sem_custo"):
            extra = custos_mod.custo_de_tokens(
                linha["modelo"], int(linha["entrada_sc"] or 0), int(linha["cache_sc"] or 0),
                int(linha["saida_sc"] or 0), cfg,
            )
            if extra is None:
                if linha["finalidade"] != "transcricao":
                    sem_preco.add(linha["modelo"] or "(desconhecido)")
            else:
                total += extra
                reais += extra * cotacao
        return total, reais

    por_mes: dict[str, dict[str, Any]] = {}
    por_finalidade: dict[str, float] = {}
    por_cliente: dict[str, dict[str, Any]] = {}
    por_cliente_mes: dict[str, float] = {}
    total = total_clientes = total_brl = total_clientes_brl = 0.0
    por_finalidade_brl: dict[str, float] = {}
    por_cliente_mes_brl: dict[str, float] = {}
    tokens = {"entrada": 0, "cache": 0, "saida": 0, "segundos_audio": 0.0}
    primeiro = None
    for linha in linhas:
        valor, reais = valores(linha)
        total += valor
        total_brl += reais
        m = por_mes.setdefault(
            linha["mes"], {"mes": linha["mes"], "usd": 0.0, "brl": 0.0, "chamadas": 0, "clientes": set()}
        )
        m["usd"] += valor
        m["brl"] += reais
        m["chamadas"] += int(linha["chamadas"] or 0)
        tokens["entrada"] += int(linha["entrada"] or 0)
        tokens["cache"] += int(linha["cache"] or 0)
        tokens["saida"] += int(linha["saida"] or 0)
        tokens["segundos_audio"] += float(linha["audio"] or 0)
        if linha["mes"] == mes_atual:
            por_finalidade[linha["finalidade"]] = por_finalidade.get(linha["finalidade"], 0.0) + valor
            por_finalidade_brl[linha["finalidade"]] = por_finalidade_brl.get(linha["finalidade"], 0.0) + reais
        if linha["id_cliente"]:
            cid = linha["id_cliente"]
            m["clientes"].add(cid)
            total_clientes += valor
            total_clientes_brl += reais
            c = por_cliente.setdefault(cid, {"id_cliente": cid, "usd": 0.0, "brl": 0.0, "chamadas": 0})
            c["usd"] += valor
            c["brl"] += reais
            c["chamadas"] += int(linha["chamadas"] or 0)
            if linha["mes"] == mes_atual:
                por_cliente_mes[cid] = por_cliente_mes.get(cid, 0.0) + valor
                por_cliente_mes_brl[cid] = por_cliente_mes_brl.get(cid, 0.0) + reais
        if linha.get("primeiro") is not None and (primeiro is None or linha["primeiro"] < primeiro):
            primeiro = linha["primeiro"]

    # Nome e situação dos clientes que mais custaram
    maiores = sorted(por_cliente.values(), key=lambda c: c["usd"], reverse=True)[:limite_clientes]
    if maiores:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id_cliente, nome, telefone, fase, agendamento_confirmado
                    FROM estado_cliente_ia WHERE id_cliente = ANY(%s)
                    """,
                    ([c["id_cliente"] for c in maiores],),
                )
                info = {r["id_cliente"]: dict(r) for r in cur.fetchall()}
        for c in maiores:
            i = info.get(c["id_cliente"], {})
            c.update(
                nome=i.get("nome") or "", telefone=i.get("telefone") or "", fase=i.get("fase") or "",
                vendeu=bool(i.get("agendamento_confirmado")),
                usd_mes=por_cliente_mes.get(c["id_cliente"], 0.0),
                brl_mes=por_cliente_mes_brl.get(c["id_cliente"], 0.0),
            )

    serie = sorted(por_mes.values(), key=lambda m: m["mes"])[-meses:]
    for m in serie:
        m["clientes"] = len(m["clientes"])
    atual = next(
        (m for m in serie if m["mes"] == mes_atual), {"usd": 0.0, "brl": 0.0, "chamadas": 0, "clientes": 0}
    )
    n_clientes = len(por_cliente)

    def dinheiro(valor_usd: float, valor_brl: float) -> dict[str, float]:
        return {"usd": round(valor_usd, 4), "brl": round(valor_brl, 2)}

    zero = dinheiro(0.0, 0.0)

    return {
        "cotacao_dolar": cotacao,
        "mes_atual": mes_atual,
        "desde": primeiro.isoformat() if primeiro is not None and not isinstance(primeiro, str) else primeiro,
        "referencias": custos_mod.referencias(),
        "total": dinheiro(total, total_brl),
        "mes": {
            **dinheiro(float(atual["usd"]), float(atual["brl"])),
            "chamadas": int(atual["chamadas"]), "clientes": int(atual["clientes"]),
        },
        "clientes_atendidos": n_clientes,
        "media_por_cliente": (
            dinheiro(total_clientes / n_clientes, total_clientes_brl / n_clientes) if n_clientes else zero
        ),
        "media_por_cliente_mes": (
            dinheiro(
                sum(por_cliente_mes.values()) / len(por_cliente_mes),
                sum(por_cliente_mes_brl.values()) / len(por_cliente_mes),
            )
            if por_cliente_mes else zero
        ),
        "vendas": vendas,
        "custo_por_venda": dinheiro(total_clientes / vendas, total_clientes_brl / vendas) if vendas else None,
        "por_mes": [
            {"mes": m["mes"], "usd": round(m["usd"], 4), "brl": round(m["brl"], 2),
             "chamadas": m["chamadas"], "clientes": m["clientes"]}
            for m in serie
        ],
        "por_finalidade": sorted(
            (
                {"finalidade": f, "rotulo": ROTULO_FINALIDADE.get(f, f),
                 **dinheiro(v, por_finalidade_brl.get(f, 0.0))}
                for f, v in por_finalidade.items()
            ),
            key=lambda x: x["usd"], reverse=True,
        ),
        "clientes": [
            {**c, "usd": round(c["usd"], 4), "brl": round(c["brl"], 2),
             "usd_mes": round(c["usd_mes"], 4), "brl_mes": round(c["brl_mes"], 2)}
            for c in maiores
        ],
        "tokens": tokens,
        "modelos_sem_preco": sorted(sem_preco),
    }
