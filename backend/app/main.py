"""API local da Eva."""

from __future__ import annotations

import traceback
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import admin_store, metrics, planos_admin, unidades as unidades_mod, ferramentas as ferramentas_mod
from app.allowlist import entrada_permitida, motivo_bloqueio, modo_entrada
from app.chatwoot_webhook import analisar_evento_chatwoot, extrair_evento_chatwoot
from app.admin_auth import exigir_admin as _exigir_admin
from app.admin_auth import login as admin_login
from app.config import get_settings
from app.db import init_schema, mensagem_ja_processada, marcar_mensagem_processada, resetar_cliente, turnos_recentes
from app.integrations import chatwoot as chatwoot_api
from app.media_store import ensure_upload_dirs, remover_arquivo_se_local, salvar_imagem_plano
from app.message_buffer import limpar_buffer, processar_com_buffer
from app.pipeline import process_message
from app.transfer_chatwoot import handoff_por_config

app = FastAPI(title="Eva MOV FIBRA — Local", version="4.4.0")

_settings_boot = get_settings()
_cors = [o.strip() for o in (_settings_boot.cors_origins or "").split(",") if o.strip()]
if _cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

ensure_upload_dirs()
app.mount("/media/planos", StaticFiles(directory=str(ensure_upload_dirs())), name="media_planos")


class ChatIn(BaseModel):
    mensagem: str = Field(min_length=1)
    id_cliente: str | None = None
    conversation_id: str | None = None  # Chatwoot — necessário p/ encerrar / outgoing
    contact_id: str | None = None
    buffer: bool = True  # false = mensagem já agrupada no cliente (WhatsApp/web)
    enviar_chatwoot: bool | None = None  # None = usa CHATWOOT_REPLY_ENABLED


class ResetIn(BaseModel):
    id_cliente: str | None = None


class PromocaoIn(BaseModel):
    id: int | None = None
    codigo: str
    titulo: str | None = None
    descricao: str = ""
    ativo: bool = True
    valido_ate: str | None = None
    unidade_id: int | None = None


class ExcecaoIn(BaseModel):
    tipo: str  # cidade | bairro | telefone | plano | outro
    valor: str
    motivo: str = ""
    ativo: bool = True


class AlertaIn(BaseModel):
    contexto: str = "teste"
    detalhe: str = "Alerta manual da Eva"
    telefone: str | None = None


class ConfigIn(BaseModel):
    chave: str
    valor: str
    unidade_id: int | None = None


class ConfigIaIn(BaseModel):
    nome_ia: str = "Eva"
    tom_voz: str = ""
    pode_emoji: bool = True
    llm_provider: str = "openai"
    openai_model: str = "gpt-4.1-mini"
    llm_temperature: float = 0.3
    openai_api_key: str = ""
    transcription_api_key: str = ""
    rag_provider: str = "webhook"
    rag_webhook_url: str = ""
    rag_webhook_token: str = ""
    message_buffer_enabled: bool = True
    message_buffer_seconds: float = 3.5
    unidade_id: int | None = None


class ConfigChatwootIn(BaseModel):
    inbound_enabled: bool = True
    inbox_id: str = ""
    inbound_mode: str = "allowlist"  # closed | allowlist | open
    allowlist_phones: str = ""
    buffer_enabled: bool = False
    public_base_url: str = ""
    webhook_token: str = ""
    chatwoot_base_url: str = ""
    chatwoot_api_token: str = ""
    unidade_id: int | None = None


class ConfigCoberturaIn(BaseModel):
    coverage_provider: str = "ixc"  # mock | ixc
    google_maps_api_key: str = ""
    ixc_base_url: str = ""
    ixc_user: str = ""
    ixc_password: str = ""
    unidade_id: int | None = None


class CoberturaTestIn(BaseModel):
    cidade: str = "Santarém"
    bairro: str = "Diamantino"
    localizacao_fixa: str = ""
    unidade_id: int | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class ChatwootTestParseIn(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class UnidadeIn(BaseModel):
    codigo: str
    nome: str
    ativo: bool = True


class PlanoIn(BaseModel):
    nome: str
    velocidade: str | None = None
    modalidade: str | None = None
    requer_cartao: bool = False
    valor: float
    parcelas: int | None = None
    descricao: str = ""
    dispositivos_max: int | None = None
    beneficios: str = ""
    ordem: int = 100
    ativo: bool = True
    destaque: bool = False
    unidade_id: int | None = None
    imagem_url: str | None = None
    valor_pontualidade: float | None = None
    condicao_valor_pontualidade: str = ""
    tags: list[str] = Field(default_factory=list)


class FerramentaParamIn(BaseModel):
    nome: str
    tipo: str = "texto"
    descricao: str = ""
    obrigatorio: bool = False
    ordem: int = 0


class FerramentaIn(BaseModel):
    tool_key: str
    nome: str
    descricao: str = ""
    webhook_url: str = ""
    integracao: str = "global"
    unidade_id: int | None = None
    destaque_dashboard: bool = False
    ativo: bool = True
    parametros: list[FerramentaParamIn] = Field(default_factory=list)

@app.post("/admin/login")
def admin_login_route(body: LoginIn):
    return admin_login(body.email, body.password)


@app.get("/admin/me")
def admin_me(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    settings = get_settings()
    return {"ok": True, "email": settings.admin_email or "admin@movfibra.com"}


@app.post("/admin/logout")
def admin_logout():
    return {"ok": True}


def _talvez_enviar_chatwoot(
    result: Any,
    *,
    forcar: bool | None = None,
) -> dict[str, Any] | None:
    from app.integrations.mensagem_chatwoot_webhook import enviar_mensagens_chatwoot_webhook

    settings = get_settings()
    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    cid = data.get("conversation_id") or (data.get("estado") or {}).get("conversation_id")
    contact_id = data.get("contact_id") or (data.get("estado") or {}).get("contact_id")
    id_cliente = data.get("id_cliente") or (data.get("estado") or {}).get("id_cliente")
    outputs = [str(o).strip() for o in (data.get("outputs") or []) if str(o).strip()]
    if not outputs:
        texto = (data.get("output") or data.get("resposta") or "").strip()
        if texto:
            outputs = [texto]
    if not cid or not outputs:
        return {"ok": False, "motivo": "sem conversation_id ou resposta vazia"}

    # Prioridade: webhook n8n (envia_mensagem_eva)
    from app.ferramentas_catalog import resolver_url_ferramenta

    msg_webhook = resolver_url_ferramenta(
        "enviar_mensagem",
        fallback_env=settings.chatwoot_msg_webhook_url,
    )
    if msg_webhook:
        return enviar_mensagens_chatwoot_webhook(
            cid,
            outputs,
            id_cliente=str(id_cliente or ""),
            contact_id=str(contact_id or ""),
        )

    from app.chatwoot_config import resolver_chatwoot_api_token

    api_direto = bool(resolver_chatwoot_api_token())
    if forcar is True:
        ativo = True
    elif forcar is False:
        ativo = False
    else:
        ativo = settings.chatwoot_reply_enabled or api_direto
    if not ativo:
        return {
            "ok": False,
            "motivo": "Resposta não enviada — configure token API Chatwoot no painel ou ferramenta enviar_mensagem",
        }
    if len(outputs) == 1:
        return chatwoot_api.enviar_outgoing(cid, outputs[0])
    return chatwoot_api.enviar_outgoing_multiplas(cid, outputs)


@app.on_event("startup")
def startup() -> None:
    print("Iniciando Eva (PostgreSQL)...")
    init_schema()
    settings = get_settings()
    print(
        f"Pronto. Entrada={settings.sofia_inbound_mode} "
        f"allowlist={settings.sofia_allowlist_phones!r} "
        f"reply_chatwoot={settings.chatwoot_reply_enabled} "
        f"pool={settings.db_pool_min_size}-{settings.db_pool_max_size}"
    )
    print("API: http://127.0.0.1:8000  |  Dash: frontend (Vite :5173)")


@app.on_event("shutdown")
def shutdown() -> None:
    from app.db import close_pool

    close_pool()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Eva — Chat Local</title>
  <style>
    :root { --bg:#0f1419; --panel:#1a2332; --line:#2a3648; --text:#e8eef7; --muted:#9aa8bc; --accent:#3d9cf0; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: "Segoe UI", system-ui, sans-serif; background:var(--bg); color:var(--text); min-height:100vh; display:flex; flex-direction:column; }
    header { padding:16px 20px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
    header strong { font-size:1.1rem; }
    header .hint { font-size:12px; color:var(--muted); }
    header button { background:transparent; border:1px solid var(--line); color:var(--muted); padding:6px 12px; border-radius:8px; cursor:pointer; }
    #log { flex:1; overflow:auto; padding:20px; display:flex; flex-direction:column; gap:12px; max-width:720px; width:100%; margin:0 auto; }
    .msg { max-width:85%; padding:10px 14px; border-radius:14px; line-height:1.4; white-space:pre-wrap; }
    .cliente { align-self:flex-end; background:#243247; }
    .sofia { align-self:flex-start; background:var(--panel); border:1px solid var(--line); }
    .meta { font-size:11px; color:var(--muted); margin-top:4px; }
    form { display:flex; gap:8px; padding:16px 20px; border-top:1px solid var(--line); max-width:720px; width:100%; margin:0 auto; }
    input { flex:1; background:var(--panel); border:1px solid var(--line); color:var(--text); padding:12px 14px; border-radius:12px; outline:none; }
    button.send { background:var(--accent); border:none; color:#fff; padding:0 18px; border-radius:12px; cursor:pointer; font-weight:600; }
  </style>
</head>
<body>
  <header>
    <div>
      <strong>Eva · MOV FIBRA (local)</strong>
      <div class="hint" id="hint">Teste local — ?id_cliente=93992219098&amp;conversation_id=ID</div>
    </div>
    <button type="button" id="reset">Reiniciar conversa</button>
  </header>
  <div id="log"></div>
  <form id="f">
    <input id="m" autocomplete="off" placeholder="Digite como o cliente..." />
    <button class="send" type="submit">Enviar</button>
  </form>
  <script>
    const params = new URLSearchParams(location.search);
    const CLIENT_ID = params.get('id_cliente') || null;
    const CONV_ID = params.get('conversation_id') || null;
    const CONTACT_ID = params.get('contact_id') || null;
    const hint = document.getElementById('hint');
    if (CLIENT_ID || CONV_ID) {
      hint.textContent = `id_cliente=${CLIENT_ID || '(default)'} · conversation_id=${CONV_ID || '—'}`;
    }
    const log = document.getElementById('log');
    const form = document.getElementById('f');
    const input = document.getElementById('m');
    function add(who, text, meta) {
      const d = document.createElement('div');
      d.className = 'msg ' + who;
      d.textContent = text;
      if (meta) {
        const m = document.createElement('div');
        m.className = 'meta';
        m.textContent = meta;
        d.appendChild(m);
      }
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    }
    const BUFFER_MS = 3500;
    let pending = [];
    let timer = null;
    let sending = false;
    let waitEl = null;

    function showWait() {
      if (waitEl) return;
      waitEl = document.createElement('div');
      waitEl.className = 'msg sofia meta';
      waitEl.textContent = '...';
      log.appendChild(waitEl);
      log.scrollTop = log.scrollHeight;
    }

    function hideWait() {
      if (waitEl) { waitEl.remove(); waitEl = null; }
    }

    function scheduleSend() {
      showWait();
      if (timer) clearTimeout(timer);
      timer = setTimeout(sendPending, BUFFER_MS);
    }

    async function sendPending() {
      timer = null;
      if (sending || !pending.length) return;
      sending = true;
      const batch = pending.splice(0);
      const combined = batch.join('\\n');
      const payload = { mensagem: combined, buffer: false };
      if (CLIENT_ID) payload.id_cliente = CLIENT_ID;
      if (CONV_ID) payload.conversation_id = CONV_ID;
      if (CONTACT_ID) payload.contact_id = CONTACT_ID;
      try {
        const r = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify(payload)
        });
        const data = await r.json();
        hideWait();
        if (!r.ok) { add('sofia', data.detail || 'Erro'); return; }
        const st = data.estado || {};
        const meta = `fase=${st.fase || ''} · aguardando=${st.aguardando || ''} · eventos=${(data.interpretacao?.eventos||[]).join(',')}`;
        const bolhas = (data.outputs && data.outputs.length) ? data.outputs : [data.resposta || '(sem resposta)'];
        bolhas.forEach((b, i) => add('sofia', b, i === bolhas.length - 1 ? meta : ''));
      } catch (err) {
        hideWait();
        add('sofia', 'Erro de conexão.');
      } finally {
        sending = false;
        input.focus();
        if (pending.length) scheduleSend();
      }
    }

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const msg = input.value.trim();
      if (!msg) return;
      input.value = '';
      add('cliente', msg);
      pending.push(msg);
      scheduleSend();
    });

    document.getElementById('reset').onclick = async () => {
      if (timer) clearTimeout(timer);
      timer = null;
      pending = [];
      hideWait();
      sending = false;
      const body = CLIENT_ID ? { id_cliente: CLIENT_ID } : {};
      await fetch('/reset', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      log.innerHTML = '';
      add('sofia', 'Conversa reiniciada. Pode mandar um oi.');
    };
  </script>
</body>
</html>"""


@app.post("/chat")
def chat_endpoint(body: ChatIn):
    settings = get_settings()
    id_cliente = body.id_cliente or settings.default_client_id

    if settings.sofia_enforce_allowlist_on_chat and not entrada_permitida(id_cliente):
        raise HTTPException(status_code=403, detail=motivo_bloqueio())

    try:

        def _process(cid: str, msg: str):
            return process_message(
                cid,
                msg,
                conversation_id=body.conversation_id,
                contact_id=body.contact_id,
            )

        from app.ia_config import resolver_message_buffer_enabled

        if body.buffer and resolver_message_buffer_enabled():
            result = processar_com_buffer(id_cliente, body.mensagem, _process)
        else:
            result = _process(id_cliente, body.mensagem)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    payload = result.model_dump()
    envio = _talvez_enviar_chatwoot(result, forcar=body.enviar_chatwoot)
    if envio is not None:
        payload["chatwoot_envio"] = envio
    return payload


@app.post("/webhooks/chatwoot")
async def webhook_chatwoot(
    request: Request,
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
):
    """
    Entrada direta do Chatwoot (ou n8n repassando o evento).
    Em teste: SOFIA_INBOUND_MODE=allowlist + SOFIA_ALLOWLIST_PHONES.
    Meta produção fica fora até mudar para open.
    """
    from app import chatwoot_config

    if not chatwoot_config.resolver_inbound_enabled():
        return {"ok": True, "ignored": True, "motivo": "Entrada Chatwoot desligada no painel"}

    if not chatwoot_config.verificar_webhook_token(x_webhook_token):
        raise HTTPException(status_code=401, detail="Token do webhook inválido")

    try:
        raw = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Body deve ser objeto JSON")

    analise = analisar_evento_chatwoot(raw)
    evento = analise.get("evento")
    if not evento:
        return {
            "ok": True,
            "ignored": True,
            "motivo": analise.get("motivo") or "evento não processável",
            "inbox_esperado": analise.get("inbox_esperado"),
            "inbox_recebido": analise.get("inbox_recebido"),
        }

    id_cliente = evento["id_cliente"]
    if not entrada_permitida(id_cliente, telefone=evento.get("telefone")):
        return {
            "ok": True,
            "ignored": True,
            "motivo": motivo_bloqueio(),
            "inbound_mode": modo_entrada(),
            "id_cliente": id_cliente,
        }

    message_id = evento.get("message_id")
    if mensagem_ja_processada(message_id):
        return {
            "ok": True,
            "ignored": True,
            "motivo": "mensagem já processada",
            "message_id": message_id,
            "id_cliente": id_cliente,
        }

    def _process(cid: str, msg: str):
        return process_message(
            cid,
            msg,
            conversation_id=evento.get("conversation_id"),
            contact_id=evento.get("contact_id"),
            message_id=message_id,
        )

    try:
        if chatwoot_config.resolver_buffer_enabled():
            result = processar_com_buffer(id_cliente, evento["mensagem"], _process)
        else:
            result = _process(id_cliente, evento["mensagem"])
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if message_id:
        marcar_mensagem_processada(message_id, id_cliente)

    payload = result.model_dump()
    envio = _talvez_enviar_chatwoot(result)
    if envio is not None:
        payload["chatwoot_envio"] = envio
    payload["ok"] = True
    return payload


@app.post("/reset")
def reset_endpoint(body: ResetIn | None = None):
    settings = get_settings()
    id_cliente = (body.id_cliente if body else None) or settings.default_client_id
    limpar_buffer(id_cliente)
    resetar_cliente(id_cliente)
    return {"ok": True, "id_cliente": id_cliente}


@app.get("/health")
def health():
    settings = get_settings()
    db_ok = False
    db_erro = ""
    try:
        from app.db import get_connection

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                db_ok = cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        db_erro = str(exc)
    return {
        "ok": db_ok,
        "database": "postgresql" if db_ok else "erro",
        "database_erro": db_erro or None,
        "provider": settings.llm_provider,
        "inbound_mode": settings.sofia_inbound_mode,
        "chatwoot_reply_enabled": settings.chatwoot_reply_enabled,
        "version": "4.4.0",
    }


# ── Métricas (dash) ───────────────────────────────────────────


@app.get("/metrics/resumo")
def metrics_resumo(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return metrics.resumo()


@app.get("/metrics/funil")
def metrics_funil(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return metrics.funil()


@app.get("/metrics/conversas")
def metrics_conversas(
    limite: int = 50,
    unidade_id: int | None = None,
    status: str | None = None,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {
        "items": metrics.conversas(limite, unidade_id=unidade_id, status=status),
    }


@app.get("/metrics/turnos/{id_cliente}")
def metrics_turnos_cliente(
    id_cliente: str,
    limite: int = 20,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {"id_cliente": id_cliente, "items": turnos_recentes(id_cliente, limite)}


@app.delete("/admin/conversas/{id_cliente}")
def admin_deletar_conversa(
    id_cliente: str,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    """Remove estado, histórico e turnos da conversa (irreversível)."""
    _exigir_admin(authorization, x_admin_token)
    cid = (id_cliente or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="id_cliente obrigatório")
    limpar_buffer(cid)
    resetar_cliente(cid)
    return {"ok": True, "id_cliente": cid}


class ClientePatchIn(BaseModel):
    nome: str | None = None
    cpf: str | None = None
    email: str | None = None
    telefone: str | None = None
    data_nascimento: str | None = None
    rg: str | None = None
    cep: str | None = None
    rua: str | None = None
    numero: str | None = None
    complemento: str | None = None
    cidade: str | None = None
    bairro: str | None = None
    metodo_pagamento: str | None = None


@app.get("/admin/clientes")
def admin_list_clientes(
    q: str = "",
    fase: str | None = None,
    status: str | None = None,
    unidade_id: int | None = None,
    limite: int = 80,
    offset: int = 0,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import clientes_admin

    return clientes_admin.listar_clientes(
        q=q,
        fase=fase,
        status=status,
        unidade_id=unidade_id,
        limite=limite,
        offset=offset,
    )


@app.get("/admin/clientes/{id_cliente}")
def admin_get_cliente(
    id_cliente: str,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import clientes_admin

    item = clientes_admin.obter_cliente(id_cliente)
    if not item:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return item


@app.get("/admin/clientes/{id_cliente}/mensagens")
def admin_mensagens_cliente(
    id_cliente: str,
    limite: int = 100,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import clientes_admin

    return {
        "id_cliente": id_cliente,
        "items": clientes_admin.historico_mensagens(id_cliente, limite),
    }


@app.patch("/admin/clientes/{id_cliente}")
def admin_patch_cliente(
    id_cliente: str,
    body: ClientePatchIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import clientes_admin

    dados = {k: v for k, v in body.model_dump().items() if v is not None}
    return clientes_admin.atualizar_cliente(id_cliente, dados)


# ── Admin: unidades / planos / config / promoções / ferramentas ─


@app.get("/admin/unidades")
def admin_list_unidades(
    ativas: bool = False,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {"items": unidades_mod.listar_unidades(apenas_ativas=ativas)}


@app.post("/admin/unidades")
def admin_criar_unidade(
    body: UnidadeIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    try:
        return unidades_mod.criar_unidade(**body.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/admin/unidades/{unidade_id}")
def admin_atualizar_unidade(
    unidade_id: int,
    body: UnidadeIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    row = unidades_mod.atualizar_unidade(unidade_id, **body.model_dump())
    if not row:
        raise HTTPException(status_code=404, detail="Unidade não encontrada")
    return row


@app.delete("/admin/unidades/{unidade_id}")
def admin_deletar_unidade(
    unidade_id: int,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    if not unidades_mod.deletar_unidade(unidade_id):
        raise HTTPException(status_code=404, detail="Unidade não encontrada")
    return {"ok": True, "id": unidade_id}


@app.get("/admin/planos")
def admin_list_planos(
    unidade_id: int | None = None,
    ativos: bool = False,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {
        "items": planos_admin.listar_planos_admin(
            unidade_id=unidade_id,
            apenas_ativos=ativos,
        )
    }


@app.post("/admin/planos")
def admin_criar_plano(
    body: PlanoIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return planos_admin.criar_plano(body.model_dump())


@app.put("/admin/planos/{plano_id}")
def admin_atualizar_plano(
    plano_id: int,
    body: PlanoIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    row = planos_admin.atualizar_plano(plano_id, body.model_dump())
    if not row:
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    return row


@app.post("/admin/planos/{plano_id}/plano-inicial")
def admin_definir_plano_inicial(
    plano_id: int,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    """Marca este plano como o que a Eva apresenta primeiro."""
    _exigir_admin(authorization, x_admin_token)
    row = planos_admin.definir_plano_inicial(plano_id)
    if not row:
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    return row


@app.post("/admin/planos/{plano_id}/imagem")
async def admin_upload_imagem_plano(
    plano_id: int,
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    atual = planos_admin.obter_plano(plano_id)
    if not atual:
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    url = await salvar_imagem_plano(plano_id, file)
    antigo = atual.get("imagem_url") or ""
    row = planos_admin.atualizar_plano(plano_id, {"imagem_url": url})
    if antigo and antigo != url:
        remover_arquivo_se_local(antigo)
    return row


@app.delete("/admin/planos/{plano_id}")
def admin_deletar_plano(
    plano_id: int,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    atual = planos_admin.obter_plano(plano_id)
    if not atual:
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    remover_arquivo_se_local(atual.get("imagem_url"))
    if not planos_admin.deletar_plano(plano_id):
        raise HTTPException(status_code=404, detail="Plano não encontrado")
    return {"ok": True, "id": plano_id}


@app.get("/admin/config")
def admin_list_config(
    unidade_id: int | None = None,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {
        "items": admin_store.listar_config(unidade_id=unidade_id),
        "mapa": admin_store.listar_config_mapa(unidade_id=unidade_id),
    }


@app.put("/admin/config")
def admin_set_config(
    body: ConfigIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return admin_store.set_config(body.chave, body.valor, unidade_id=body.unidade_id)


@app.get("/admin/config/ia")
def admin_get_config_ia(
    unidade_id: int | None = None,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import ia_config

    return ia_config.obter_config_ia(unidade_id=unidade_id)


@app.put("/admin/config/ia")
def admin_put_config_ia(
    body: ConfigIaIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import ia_config

    return ia_config.salvar_config_ia(body.model_dump(), unidade_id=body.unidade_id)


@app.get("/admin/config/chatwoot")
def admin_get_config_chatwoot(
    unidade_id: int | None = None,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import chatwoot_config

    return chatwoot_config.obter_config_chatwoot(unidade_id=unidade_id)


@app.put("/admin/config/chatwoot")
def admin_put_config_chatwoot(
    body: ConfigChatwootIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import chatwoot_config

    mode = (body.inbound_mode or "allowlist").strip().lower()
    if mode not in {"closed", "allowlist", "open"}:
        raise HTTPException(status_code=400, detail="inbound_mode inválido")
    return chatwoot_config.salvar_config_chatwoot(body.model_dump(), unidade_id=body.unidade_id)


@app.get("/admin/config/cobertura")
def admin_get_config_cobertura(
    unidade_id: int | None = None,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import coverage_config

    return coverage_config.obter_config_cobertura(unidade_id=unidade_id)


@app.put("/admin/config/cobertura")
def admin_put_config_cobertura(
    body: ConfigCoberturaIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import coverage_config

    return coverage_config.salvar_config_cobertura(body.model_dump(), unidade_id=body.unidade_id)


@app.post("/admin/config/cobertura/test")
def admin_test_cobertura(
    body: CoberturaTestIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    """Testa viabilidade com as credenciais salvas (sem passar pelo LLM)."""
    _exigir_admin(authorization, x_admin_token)
    from app.coverage import checar_cobertura

    resultado = checar_cobertura(
        cidade=body.cidade.strip(),
        bairro=body.bairro.strip(),
        localizacao_fixa=body.localizacao_fixa.strip(),
        id_cliente="admin-teste-cobertura",
    )
    return {"ok": True, "resultado": resultado}


@app.get("/admin/config/chatwoot/exemplo-payload")
def admin_exemplo_payload_chatwoot(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app import chatwoot_config

    return {"payload": chatwoot_config.payload_exemplo_message_created()}


@app.post("/admin/config/chatwoot/test-parse")
def admin_test_parse_chatwoot(
    body: ChatwootTestParseIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    """Simula o parser do webhook sem processar a IA."""
    _exigir_admin(authorization, x_admin_token)
    from app.allowlist import entrada_permitida, motivo_bloqueio, modo_entrada

    analise = analisar_evento_chatwoot(body.payload)
    evento = analise.get("evento")
    allowlist_ok = None
    allowlist_motivo = None
    if evento:
        allowlist_ok = entrada_permitida(evento.get("id_cliente"), telefone=evento.get("telefone"))
        if not allowlist_ok:
            allowlist_motivo = motivo_bloqueio()

    return {
        **analise,
        "allowlist_ok": allowlist_ok,
        "allowlist_motivo": allowlist_motivo,
        "inbound_mode": modo_entrada(),
    }


@app.get("/admin/promocoes")
def admin_list_promocoes(
    ativas: bool = False,
    unidade_id: int | None = None,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {
        "items": admin_store.listar_promocoes(
            apenas_ativas=ativas,
            unidade_id=unidade_id,
        )
    }


@app.post("/admin/promocoes")
def admin_upsert_promocao(
    body: PromocaoIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    try:
        return admin_store.upsert_promocao(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/admin/promocoes/{promo_id}")
def admin_deletar_promocao(
    promo_id: int,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    if not admin_store.deletar_promocao(promo_id):
        raise HTTPException(status_code=404, detail="Promoção não encontrada")
    return {"ok": True, "id": promo_id}


@app.get("/admin/ferramentas")
def admin_list_ferramentas(
    unidade_id: int | None = None,
    ativas: bool = False,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {
        "items": ferramentas_mod.listar_ferramentas(
            unidade_id=unidade_id,
            apenas_ativas=ativas,
        )
    }


@app.post("/admin/ferramentas/sync-catalogo")
def admin_sync_catalogo_ferramentas(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    """Garante no painel todas as ferramentas do catálogo (URLs do .env se vazias)."""
    _exigir_admin(authorization, x_admin_token)
    from app.ferramentas_catalog import seed_ferramentas_do_catalogo

    criadas = seed_ferramentas_do_catalogo()
    return {
        "ok": True,
        "criadas": criadas,
        "items": ferramentas_mod.listar_ferramentas(),
    }


@app.post("/admin/ferramentas")
def admin_criar_ferramenta(
    body: FerramentaIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return ferramentas_mod.criar_ferramenta(body.model_dump())


@app.put("/admin/ferramentas/{ferramenta_id}")
def admin_atualizar_ferramenta(
    ferramenta_id: int,
    body: FerramentaIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    row = ferramentas_mod.atualizar_ferramenta(ferramenta_id, body.model_dump())
    if not row:
        raise HTTPException(status_code=404, detail="Ferramenta não encontrada")
    return row


@app.delete("/admin/ferramentas/{ferramenta_id}")
def admin_deletar_ferramenta(
    ferramenta_id: int,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    if not ferramentas_mod.deletar_ferramenta(ferramenta_id):
        raise HTTPException(status_code=404, detail="Ferramenta não encontrada")
    return {"ok": True, "id": ferramenta_id}


@app.get("/admin/excecoes")
def admin_list_excecoes(
    ativas: bool = False,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return {"items": admin_store.listar_excecoes(apenas_ativas=ativas)}


@app.post("/admin/excecoes")
def admin_criar_excecao(
    body: ExcecaoIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    try:
        return admin_store.criar_excecao(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/admin/excecoes/{excecao_id}")
def admin_desativar_excecao(
    excecao_id: int,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    ok = admin_store.desativar_excecao(excecao_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Exceção não encontrada")
    return {"ok": True, "id": excecao_id}


@app.post("/admin/alertas/teste")
def admin_teste_alerta(
    body: AlertaIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    from app.alerts import enviar_alerta

    detalhe = body.detalhe
    if body.telefone:
        detalhe = f"{detalhe} (ref telefone {body.telefone})"
    return enviar_alerta(body.contexto, detalhe)


# ── Chatwoot: catálogo + handoff ───────────────────────────────


class HandoffIn(BaseModel):
    conversation_id: str
    assignee_id: int | None = None
    team_id: int | None = None
    labels: list[str] | None = None
    status: str | None = None
    motivo: str = ""


class AssignIn(BaseModel):
    conversation_id: str
    assignee_id: int | None = None
    team_id: int | None = None


class LabelsIn(BaseModel):
    conversation_id: str
    labels: list[str]


class StatusIn(BaseModel):
    conversation_id: str
    status: str  # open | pending | resolved | snoozed


@app.get("/chatwoot/agents")
def chatwoot_agents(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return chatwoot_api.listar_agents()


@app.get("/chatwoot/teams")
def chatwoot_teams(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return chatwoot_api.listar_teams()


@app.get("/chatwoot/labels")
def chatwoot_labels(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return chatwoot_api.listar_labels()


@app.get("/chatwoot/inboxes")
def chatwoot_inboxes(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    return chatwoot_api.listar_inboxes()


@app.post("/chatwoot/assign")
def chatwoot_assign(
    body: AssignIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    result = chatwoot_api.atribuir_conversa(
        body.conversation_id,
        assignee_id=body.assignee_id,
        team_id=body.team_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("motivo") or "Falha no assign")
    return result


@app.post("/chatwoot/labels")
def chatwoot_set_labels(
    body: LabelsIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    result = chatwoot_api.definir_labels(body.conversation_id, body.labels)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("motivo") or "Falha nas labels")
    return result


@app.post("/chatwoot/status")
def chatwoot_set_status(
    body: StatusIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    _exigir_admin(authorization, x_admin_token)
    result = chatwoot_api.atualizar_status(body.conversation_id, body.status)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("motivo") or "Falha no status")
    return result


@app.post("/chatwoot/handoff")
def chatwoot_handoff(
    body: HandoffIn,
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
):
    """Assign + labels + status em um passo (para o dash e n8n)."""
    _exigir_admin(authorization, x_admin_token)
    result = handoff_por_config(
        body.conversation_id,
        motivo=body.motivo,
        assignee_id=body.assignee_id,
        team_id=body.team_id,
        labels=body.labels,
        status=body.status,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=result.get("motivo") or result,
        )
    return result

