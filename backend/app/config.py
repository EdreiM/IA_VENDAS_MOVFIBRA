"""Configuração da Eva local."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py → backend/ → projeto (IA VENDAS)
BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
# Compat: .env e SQLite continuam na raiz do projeto (não quebra instalação atual)
ROOT = PROJECT_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(BACKEND_ROOT / ".env"),
            str(PROJECT_ROOT / ".env"),
            ".env",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "openai"  # openai | ollama
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"

    sqlite_path: str = str(ROOT / "sofia_local.db")  # legado — não usado
    default_client_id: str = "teste-local"

    # PostgreSQL (obrigatório)
    database_url: str = "postgresql://sofia:sofia@127.0.0.1:5432/sofia"
    db_pool_min_size: int = 2
    db_pool_max_size: int = 20

    # CORS do dashboard (frontend Vite)
    cors_origins: str = "http://127.0.0.1:5180,http://localhost:5180,http://127.0.0.1:5173,http://localhost:5173"
    # URL pública da API (para n8n/WhatsApp acessarem /media/planos/...)
    public_base_url: str = "http://127.0.0.1:8001"

    # Cobertura: mock | ixc
    coverage_provider: str = "mock"

    # Google Maps (geocodificação)
    google_maps_api_key: str = ""

    # IXC — viabilidade técnica
    ixc_base_url: str = "https://ixc.mov.pro.br/webservice/v1"
    ixc_user: str = ""
    ixc_password: str = ""

    # Defaults cadastro IXC (MOV FIBRA — ajuste no .env se necessário)
    ixc_filial_id: str = "3"
    ixc_id_tipo_cliente: str = "19"
    ixc_tipo_assinante: str = "3"
    ixc_iss_classificacao: str = "99"
    ixc_contribuinte_icms: str = "I"
    ixc_tipo_localidade: str = "U"
    ixc_id_conta: str = "70302"
    ixc_id_candidato_tipo: str = "45"
    ixc_uf: str = "20"
    ixc_cidade_id: str = "209"  # Santarém/PA no IXC
    ixc_senha_hotsite: str = "movbrasil"

    # CPF / IXC
    cpf_provider: str = "mock"  # mock | ixc

    # Cadastro final — mock | ixc (API direta) | webhook (n8n: cliente + contrato + OS)
    cadastro_provider: str = "mock"
    cadastro_webhook_url: str = ""
    cadastro_webhook_token: str = ""
    cadastro_timeout_seconds: float = 90.0

    # Agenda — horários de técnicos (n8n + Google Sheets + IXC)
    agenda_provider: str = "mock"  # mock | webhook
    agenda_webhook_url: str = ""
    agenda_inserir_webhook_url: str = ""
    agenda_webhook_token: str = ""
    agenda_timeout_seconds: float = 25.0

    # Encerramento — PDF IXC + resolve Chatwoot (n8n)
    encerrar_provider: str = "mock"  # mock | webhook
    encerrar_webhook_url: str = ""
    encerrar_webhook_token: str = ""
    encerrar_timeout_seconds: float = 90.0

    # Termos — áudio fidelidade + PDF contrato (n8n → Chatwoot)
    termos_provider: str = "mock"  # mock | webhook
    termos_webhook_url: str = ""
    termos_webhook_token: str = ""
    termos_timeout_seconds: float = 60.0

    # Ativação — cliente_contrato_ativar_cliente (n8n → IXC)
    ativacao_provider: str = "mock"  # mock | webhook
    ativacao_webhook_url: str = ""
    ativacao_webhook_token: str = ""
    ativacao_timeout_seconds: float = 45.0

    # Imagem do plano — Chatwoot multipart (n8n)
    imagem_plano_provider: str = "mock"  # mock | webhook
    imagem_plano_webhook_url: str = ""
    imagem_plano_webhook_token: str = ""
    imagem_plano_timeout_seconds: float = 45.0

    # RAG — objeções / FAQ (conteúdo externo, atualizável sem redeploy)
    # none | mock | webhook  — use mock em dev/teste, webhook em staging/prod
    rag_provider: str = "mock"
    rag_webhook_url: str = ""
    rag_webhook_token: str = ""
    rag_timeout_seconds: float = 12.0

    # Planos — postgres (tabela local) | webhook (n8n / Postgres externo)
    plans_provider: str = "postgres"
    plans_webhook_url: str = ""
    plans_webhook_token: str = ""
    plans_timeout_seconds: float = 15.0
    plans_cache_ttl_seconds: float = 300.0
    plans_plano_inicial: str = "MOV SUPER"  # sobrescreve destaque do n8n/banco

    # Acumula mensagens rápidas (debounce) antes de 1 resposta
    message_buffer_enabled: bool = True
    message_buffer_seconds: float = 3.5
    # Webhook Chatwoot: desligado por padrão (n8n já pode agrupar; evita debounce duplo)
    chatwoot_buffer_enabled: bool = False

    # Chatwoot (contato + mensagens outgoing na inbox Meta)
    chatwoot_base_url: str = "https://chatwoot.mov.pro.br"
    chatwoot_api_token: str = ""
    chatwoot_account_id: str = "2"
    chatwoot_inbox_id: str = "6"  # caixa MOV IA (Meta) — vazio = não filtra
    # Se true, /webhooks/chatwoot e /chat (com conversation_id) postam outgoing
    chatwoot_reply_enabled: bool = False
    # Webhook n8n envia_mensagem_eva (prioridade sobre CHATWOOT_REPLY_ENABLED)
    chatwoot_msg_webhook_url: str = ""
    chatwoot_msg_webhook_token: str = ""
    chatwoot_msg_webhook_timeout_seconds: float = 30.0

    # Handoff automático ao TRANSFERIR_HUMANO (opcional)
    chatwoot_transfer_enabled: bool = False
    chatwoot_transfer_team_id: str = ""
    chatwoot_transfer_assignee_id: str = ""
    chatwoot_transfer_labels: str = "sofia_transferido"  # CSV de labels
    chatwoot_transfer_status: str = "open"  # open | pending | resolved | snoozed

    # Entrada: closed | allowlist | open
    # allowlist = só SOFIA_ALLOWLIST_PHONES (teste sem Meta produção)
    sofia_inbound_mode: str = "allowlist"
    sofia_allowlist_phones: str = "93992219098"
    # Se true, /chat também respeita allowlist (padrão false = chat local livre)
    sofia_enforce_allowlist_on_chat: bool = False

    # Token opcional para /metrics e /admin (vazio = sem auth em local)
    admin_api_token: str = ""

    # Alerta quando ferramenta falha: none | evolution | chatwoot
    alert_provider: str = "evolution"
    alert_message_template: str = "Eva alerta: {contexto} — {detalhe}"
    # Números extras (CSV) para alertas Evolution; vazio usa evolution_alert_number
    alert_phones: str = ""

    # Alerta Evolution quando ferramenta falha
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_alert_number: str = ""
    # Conversa Chatwoot onde postar alertas (private note se private=true)
    alert_chatwoot_conversation_id: str = ""
    alert_chatwoot_private: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
