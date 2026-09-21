"""Catálogo oficial de planos MOV — seed/migração para o painel PostgreSQL."""

from __future__ import annotations

import json
from typing import Any

# IDs alinhados ao n8n (imagem/planos) para não quebrar webhooks antigos.
# Plano inicial padrão: MOV SUPER (destaque=True).
CATALOGO_PLANOS: list[dict[str, Any]] = [
    {
        "id": 1214,
        "nome": "MOV FLEX",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 119.0,
        "parcelas": 1,
        "descricao": (
            "📦 PLANO MOV FLEX – R$ 119,00/mês\n"
            "💰 Pagando até o vencimento, a mensalidade fica por apenas R$ 99,00\n"
            "✅ Você economiza R$ 20,00 todos os meses com o desconto de pontualidade\n"
            "✅ Internet ilimitada, sem franquia e sem redução de velocidade por consumo 📶"
        ),
        "dispositivos_max": None,
        "beneficios": (
            "Internet ilimitada\n"
            "Sem franquia\n"
            "Sem redução de velocidade por consumo\n"
            "Desconto de pontualidade"
        ),
        "ordem": 1,
        "destaque": False,
        "valor_pontualidade": 99.0,
        "condicao_valor_pontualidade": (
            "Pagando até o vencimento, a mensalidade fica por R$ 99,00."
        ),
        "tags": ["pontualidade", "economico", "fibra", "flex"],
    },
    {
        "id": 1212,
        "nome": "MOV SUPER+",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 139.0,
        "parcelas": 1,
        "descricao": (
            "📦 COMBO MOV SUPER+ – R$ 139,00/mês\n"
            "🔥 Oferta especial: 50% de desconto nos 3 primeiros meses\n"
            "💰 Nos 3 primeiros meses, a mensalidade fica por apenas R$ 69,50\n"
            "✅ A partir do 4º mês, a mensalidade volta para R$ 139,00\n"
            "✅ Internet ilimitada 📶\n"
            "✅ Repetidor Mesh com 2 roteadores em comodato 📡\n"
            "✅ Instalação e configuração inclusas\n"
            "✅ Cobertura Wi-Fi para toda a casa\n"
            "✅ Imagina Só e Ubook 📚"
        ),
        "dispositivos_max": 6,
        "beneficios": (
            "Internet ilimitada\n"
            "50% de desconto nos 3 primeiros meses (R$ 69,50)\n"
            "Repetidor Mesh\n"
            "2 roteadores em comodato\n"
            "Instalação e configuração inclusas\n"
            "Cobertura Wi-Fi para toda a casa\n"
            "Imagina Só\n"
            "Ubook"
        ),
        "ordem": 2,
        "destaque": False,
        "valor_pontualidade": None,
        "condicao_valor_pontualidade": None,
        "tags": ["super_plus", "combo", "mesh", "prime", "faixa_139", "combo_internet_chip"],
    },
    {
        "id": 1180,
        "nome": "MOV ONE+",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 139.0,
        "parcelas": 1,
        "descricao": (
            "📶 PLANO MOV ONE+ – R$ 139,00/mês\n"
            "✅ Internet ilimitada 📶\n"
            "✅ Escolha entre Disney+, Max ou Globoplay 🎬\n"
            "✅ Escolha entre Deezer ou Looke 🎵🎥\n"
            "✅ Kaspersky – proteção para seus dispositivos 🛡️\n"
            "✅ Clube de Vantagens – descontos em lojas parceiras 🛍️\n"
            "✅ Imagina Só e Ubook 📚"
        ),
        "dispositivos_max": 5,
        "beneficios": (
            "Internet ilimitada\n"
            "Disney+, Max ou Globoplay\n"
            "Deezer ou Looke\n"
            "Kaspersky\n"
            "Clube de Vantagens\n"
            "Imagina Só\n"
            "Ubook"
        ),
        "ordem": 3,
        "destaque": False,
        "valor_pontualidade": None,
        "condicao_valor_pontualidade": None,
        "tags": [
            "one_plus",
            "kaspersky",
            "disney",
            "max",
            "globoplay",
            "deezer",
            "looke",
            "faixa_139",
            "fibra",
        ],
    },
    {
        "id": 1209,
        "nome": "MOV SUPER",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 139.0,
        "parcelas": 1,
        "descricao": (
            "📦 COMBO MOV SUPER – R$ 139,00/mês\n"
            "✅ Internet ilimitada 📶\n"
            "✅ Imagina Só e Ubook 📚\n"
            "✅ Clube de Vantagens – descontos em lojas parceiras 🛍️\n"
            "💰 Desconto de pontualidade: pagando até o vencimento, "
            "a mensalidade fica por apenas R$ 119,00"
        ),
        "dispositivos_max": 5,
        "beneficios": (
            "Internet ilimitada\n"
            "Imagina Só\n"
            "Ubook\n"
            "Clube de Vantagens\n"
            "Desconto de pontualidade"
        ),
        "ordem": 4,
        "destaque": True,  # plano inicial padrão da Eva
        "valor_pontualidade": 119.0,
        "condicao_valor_pontualidade": (
            "Pagando até o vencimento, a mensalidade fica por R$ 119,00."
        ),
        "tags": ["super", "combo", "pontualidade", "faixa_139", "combo_internet_chip"],
    },
    {
        "id": 1185,
        "nome": "MOV UP+",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 149.0,
        "parcelas": 1,
        "descricao": (
            "📶 PLANO MOV UP+ – R$ 149,00/mês\n"
            "✅ Internet ilimitada 📶\n"
            "✅ Escolha entre Disney+, Max ou Globoplay 🎬\n"
            "✅ Telemedicina – consultas online quando precisar 🩺\n"
            "✅ Escolha entre Deezer ou Looke 🎵🎥\n"
            "✅ Clube de Vantagens – descontos em lojas parceiras 🛍️\n"
            "✅ Imagina Só e Ubook 📚"
        ),
        "dispositivos_max": 6,
        "beneficios": (
            "Internet ilimitada\n"
            "Disney+, Max ou Globoplay\n"
            "Telemedicina\n"
            "Deezer ou Looke\n"
            "Clube de Vantagens\n"
            "Imagina Só\n"
            "Ubook"
        ),
        "ordem": 5,
        "destaque": False,
        "valor_pontualidade": None,
        "condicao_valor_pontualidade": None,
        "tags": [
            "up_plus",
            "telemedicina",
            "disney",
            "max",
            "globoplay",
            "deezer",
            "looke",
            "fibra",
        ],
    },
    {
        "id": 1176,
        "nome": "MOV INFINITY",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 189.0,
        "parcelas": 1,
        "descricao": (
            "📶 PLANO MOV INFINITY – R$ 189,00/mês\n"
            "✅ Internet ilimitada 📶\n"
            "✅ Escolha entre Disney+, Max ou Globoplay 🎬\n"
            "✅ Repetidor Mesh – maior cobertura do Wi-Fi 📡\n"
            "✅ ExitLag – otimização de conexão para jogos 🎮\n"
            "✅ Telemedicina – consultas online quando precisar 🩺\n"
            "✅ Escolha entre Deezer ou Looke 🎵🎥\n"
            "✅ Clube de Vantagens – descontos em lojas parceiras 🛍️\n"
            "✅ Imagina Só e Ubook 📚"
        ),
        "dispositivos_max": 12,
        "beneficios": (
            "Internet ilimitada\n"
            "Disney+, Max ou Globoplay\n"
            "Repetidor Mesh\n"
            "ExitLag\n"
            "Telemedicina\n"
            "Deezer ou Looke\n"
            "Clube de Vantagens\n"
            "Imagina Só\n"
            "Ubook"
        ),
        "ordem": 6,
        "destaque": False,
        "valor_pontualidade": None,
        "condicao_valor_pontualidade": None,
        "tags": [
            "infinity",
            "mesh",
            "game",
            "telemedicina",
            "disney",
            "max",
            "globoplay",
            "deezer",
            "looke",
            "premium",
            "muitos_dispositivos",
            "fibra",
        ],
    },
    {
        "id": 1208,
        "nome": "MOV ESSENCIAL",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 129.0,
        "parcelas": 1,
        "descricao": (
            "📦 COMBO MOV ESSENCIAL – R$ 129,00/mês\n"
            "✅ Internet ilimitada 📶\n"
            "✅ Escolha entre Amazon Prime ou Globoplay com anúncios 🎬\n"
            "✅ Amazon Prime inclui Prime Video, Prime Music, Prime Gaming "
            "e benefícios em compras\n"
            "✅ Clube de Vantagens – descontos em lojas parceiras 🛍️\n"
            "✅ Ubook Go e Imagina Só 📚"
        ),
        "dispositivos_max": 4,
        "beneficios": (
            "Internet ilimitada\n"
            "Amazon Prime ou Globoplay\n"
            "Clube de Vantagens\n"
            "Ubook Go\n"
            "Imagina Só"
        ),
        "ordem": 10,
        "destaque": False,
        "valor_pontualidade": None,
        "condicao_valor_pontualidade": None,
        "tags": [
            "essencial",
            "combo",
            "globoplay",
            "prime",
            "economico",
            "poucos_dispositivos",
            "combo_internet_chip",
        ],
    },
    {
        "id": 1207,
        "nome": "MOV COMBO TOTAL 12GB",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 147.0,
        "parcelas": 1,
        "descricao": (
            "📦 MOV COMBO TOTAL 12GB – R$ 147,00/mês\n"
            "📱 Chip incluso com 12 GB\n"
            "☎️ Ligações, SMS e WhatsApp ilimitados\n"
            "🎁 Clube de Vantagens, Ubook & Imagina Só"
        ),
        "dispositivos_max": None,
        "beneficios": (
            "Chip com 12 GB\n"
            "Ligações ilimitadas\n"
            "SMS ilimitados\n"
            "WhatsApp ilimitado\n"
            "Clube de Vantagens\n"
            "Ubook\n"
            "Imagina Só"
        ),
        "ordem": 20,
        "destaque": False,
        "valor_pontualidade": None,
        "condicao_valor_pontualidade": None,
        "tags": ["combo", "chip_12gb", "chip", "combo_internet_chip"],
    },
    {
        "id": 1206,
        "nome": "MOV COMBO TOTAL 22GB",
        "velocidade": "Ilimitada",
        "modalidade": "mensal",
        "requer_cartao": False,
        "valor": 167.0,
        "parcelas": 1,
        "descricao": (
            "📦 MOV COMBO TOTAL 22GB – R$ 167,00/mês\n"
            "📱 Chip incluso com 22 GB\n"
            "☎️ Ligações, SMS e WhatsApp ilimitados\n"
            "🎬 Escolha 1: HBO Max, Disney+ ou Globoplay"
        ),
        "dispositivos_max": None,
        "beneficios": (
            "Chip com 22 GB\n"
            "Ligações ilimitadas\n"
            "SMS ilimitados\n"
            "WhatsApp ilimitado\n"
            "HBO Max ou Disney+ ou Globoplay"
        ),
        "ordem": 21,
        "destaque": False,
        "valor_pontualidade": None,
        "condicao_valor_pontualidade": None,
        "tags": [
            "combo",
            "chip_22gb",
            "chip",
            "disney",
            "max",
            "globoplay",
            "combo_internet_chip",
        ],
    },
]


def seed_planos_do_catalogo(cur: Any) -> dict[str, int]:
    """
    Upsert dos planos oficiais (IDs fixos).
    - Preserva imagem_url já cadastrada no painel.
    - Remove planos globais antigos que não estão no catálogo.
    - Garante um único destaque (plano inicial).
    """
    ids = [int(p["id"]) for p in CATALOGO_PLANOS]
    atualizados = 0
    criados = 0

    # Imagens já no painel (por id ou nome)
    cur.execute(
        "SELECT id, nome, imagem_url FROM planos WHERE unidade_id IS NULL"
    )
    imgs_por_id: dict[int, str] = {}
    imgs_por_nome: dict[str, str] = {}
    for row in cur.fetchall():
        url = str(row["imagem_url"] or "").strip()
        if not url:
            continue
        imgs_por_id[int(row["id"])] = url
        imgs_por_nome[str(row["nome"] or "").casefold().strip()] = url

    # Remove duplicatas/antigos do seed local (IDs baixos ou mesmo nome com outro id)
    nomes = [str(p["nome"]).casefold() for p in CATALOGO_PLANOS]
    cur.execute(
        """
        DELETE FROM planos
        WHERE unidade_id IS NULL
          AND id <> ALL(%s)
          AND (
            id < 1000
            OR lower(trim(nome)) = ANY(%s)
          )
        """,
        (ids, nomes),
    )

    for item in CATALOGO_PLANOS:
        pid = int(item["id"])
        nome = str(item["nome"])
        img = (
            imgs_por_id.get(pid)
            or imgs_por_nome.get(nome.casefold().strip())
            or None
        )
        tags_json = json.dumps(item.get("tags") or [], ensure_ascii=False)
        cur.execute("SELECT id FROM planos WHERE id = %s", (pid,))
        existe = cur.fetchone() is not None

        if existe:
            # Não sobrescreve destaque/imagem já editados no painel
            cur.execute(
                """
                UPDATE planos SET
                    nome = %s,
                    velocidade = %s,
                    modalidade = %s,
                    requer_cartao = %s,
                    valor = %s,
                    parcelas = %s,
                    descricao = %s,
                    dispositivos_max = %s,
                    max_dispositivos = %s,
                    beneficios = %s,
                    ordem = %s,
                    ativo = 1,
                    unidade_id = NULL,
                    imagem_url = COALESCE(NULLIF(TRIM(imagem_url), ''), %s),
                    valor_pontualidade = %s,
                    condicao_valor_pontualidade = %s,
                    tags = %s
                WHERE id = %s
                """,
                (
                    nome,
                    item.get("velocidade"),
                    item.get("modalidade"),
                    1 if item.get("requer_cartao") else 0,
                    float(item["valor"]),
                    item.get("parcelas"),
                    item.get("descricao") or "",
                    item.get("dispositivos_max"),
                    item.get("dispositivos_max"),
                    item.get("beneficios") or "",
                    int(item.get("ordem") or 100),
                    img,
                    item.get("valor_pontualidade"),
                    item.get("condicao_valor_pontualidade"),
                    tags_json,
                    pid,
                ),
            )
            atualizados += 1
        else:
            cur.execute(
                """
                INSERT INTO planos (
                    id, nome, velocidade, modalidade, requer_cartao, valor, parcelas,
                    descricao, dispositivos_max, max_dispositivos, beneficios,
                    ordem, ativo, destaque, unidade_id, imagem_url,
                    valor_pontualidade, condicao_valor_pontualidade, tags
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,NULL,%s,%s,%s,%s
                )
                """,
                (
                    pid,
                    nome,
                    item.get("velocidade"),
                    item.get("modalidade"),
                    1 if item.get("requer_cartao") else 0,
                    float(item["valor"]),
                    item.get("parcelas"),
                    item.get("descricao") or "",
                    item.get("dispositivos_max"),
                    item.get("dispositivos_max"),
                    item.get("beneficios") or "",
                    int(item.get("ordem") or 100),
                    1 if item.get("destaque") else 0,
                    img,
                    item.get("valor_pontualidade"),
                    item.get("condicao_valor_pontualidade"),
                    tags_json,
                ),
            )
            criados += 1

    # Sequência SERIAL após IDs manuais
    cur.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('planos', 'id'),
            GREATEST((SELECT COALESCE(MAX(id), 1) FROM planos), 1)
        )
        """
    )

    # Se ninguém marcou plano inicial, aplica o padrão do catálogo (MOV SUPER)
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM planos
        WHERE unidade_id IS NULL AND ativo = 1 AND destaque = 1
        """
    )
    if int(cur.fetchone()["n"]) == 0:
        padrao = next((p for p in CATALOGO_PLANOS if p.get("destaque")), None)
        if padrao:
            cur.execute(
                "UPDATE planos SET destaque = 1 WHERE id = %s",
                (int(padrao["id"]),),
            )

    return {"criados": criados, "atualizados": atualizados, "total": len(CATALOGO_PLANOS)}
