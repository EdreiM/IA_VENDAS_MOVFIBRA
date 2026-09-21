"""Teste do webhook insere_agenda (n8n)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agenda_datetime import slot_para_data_hora
from app.config import get_settings
from app.integrations.agenda_inserir_webhook import inserir_agendamento_webhook


def main() -> None:
    settings = get_settings()
    print("URL:", settings.agenda_inserir_webhook_url or "(vazia)")
    print()

    data_hora = slot_para_data_hora("28/08/2026", "8h às 9h")
    print("Conversão slot → datetime:", data_hora)
    print()

    payload = {
        "ixc_id_cliente": input("ixc_id_cliente (ID IXC real): ").strip() or "999999",
        "data_hora_agendamento": input(f"data_hora [{data_hora}]: ").strip() or data_hora,
        "id_tecnico": input("id_tecnico [466]: ").strip() or "466",
    }
    print("\nPayload:", json.dumps(payload, ensure_ascii=False))
    print()

    confirmar = input("Enviar para o webhook? (s/N): ").strip().lower()
    if confirmar != "s":
        print("Cancelado.")
        return

    out = inserir_agendamento_webhook(**payload)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
