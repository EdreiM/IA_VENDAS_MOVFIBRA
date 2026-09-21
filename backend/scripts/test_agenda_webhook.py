"""Teste rápido do webhook de horários (n8n verifica_tecnicos)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.integrations.agenda_webhook import _extrair_payload, buscar_horarios_webhook


def _estados_com_ixc() -> list[dict]:
    db = ROOT / "sofia_local.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id_cliente, cidade, bairro, ixc_cliente_id, fase
        FROM estado_cliente_ia
        WHERE ixc_cliente_id IS NOT NULL AND trim(ixc_cliente_id) != ''
        ORDER BY updated_at DESC
        LIMIT 5
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _raw_post(url: str, payload: dict) -> tuple[int, object]:
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json=payload, headers={"Accept": "application/json"})
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body


def main() -> None:
    settings = get_settings()
    url = (settings.agenda_webhook_url or "").strip()
    print("URL:", url or "(vazia)")
    print("Provider:", settings.agenda_provider)
    print()

    estados = _estados_com_ixc()
    if estados:
        print("Estados locais com ixc_cliente_id:")
        for e in estados:
            print(
                f"  - sessao={e['id_cliente']} | ixc={e['ixc_cliente_id']} | "
                f"{e.get('bairro')}, {e.get('cidade')} | fase={e.get('fase')}"
            )
        base = estados[0]
        payload = {
            "id_cliente": str(base["ixc_cliente_id"]),
            "cidade": str(base.get("cidade") or ""),
            "bairro": str(base.get("bairro") or ""),
        }
        print("\nUsando dados do banco local (primeiro registro).")
    else:
        payload = {
            "id_cliente": "999999",
            "cidade": "Porto Alegre",
            "bairro": "Centro",
        }
        print("Nenhum ixc_cliente_id no banco — usando payload de exemplo:")
    print("Payload:", json.dumps(payload, ensure_ascii=False))
    print()

    status, raw = _raw_post(url, payload)
    print("HTTP status:", status)
    print("Resposta bruta:")
    print(json.dumps(raw, ensure_ascii=False, indent=2) if isinstance(raw, (dict, list)) else raw)
    print()

    parsed = _extrair_payload(raw)
    print("Parse Sofia (_extrair_payload):")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
    print()

    via_client = buscar_horarios_webhook(**payload)
    print("Via buscar_horarios_webhook():")
    print(json.dumps(via_client, ensure_ascii=False, indent=2))

    if parsed.get("resultado") == "ok" and (parsed.get("manha") or parsed.get("tarde")):
        print("\nOK — horários retornados com sucesso.")
    elif parsed.get("resultado") == "sem_horarios":
        print("\nWebhook respondeu sem horários disponíveis (sem_horarios).")
    else:
        print("\nATENÇÃO — verifique workflow n8n (Respond to Webhook / mapeamento).")


if __name__ == "__main__":
    main()
