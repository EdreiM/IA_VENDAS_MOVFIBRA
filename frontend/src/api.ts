const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || "";

function token(): string {
  return localStorage.getItem("sofia_admin_token") || "";
}

export function setAdminToken(value: string) {
  localStorage.setItem("sofia_admin_token", value);
}

export function getAdminToken() {
  return token();
}

export function clearAdminToken() {
  localStorage.removeItem("sofia_admin_token");
}

export async function postAdminLogin(email: string, password: string) {
  const res = await fetch(`${API_BASE}/admin/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  return data as { ok: boolean; token: string; email: string };
}

export async function fetchAdminMe() {
  return api<{ ok: boolean; email: string }>("/admin/me");
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  const t = token();
  if (t) headers["X-Admin-Token"] = t;
  if (init?.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail
          ? JSON.stringify(detail)
          : `HTTP ${res.status}`,
    );
  }
  return data as T;
}

export type Unidade = {
  id: number;
  codigo: string;
  nome: string;
  ativo: number | boolean;
};

export type Resumo = {
  conversas: number;
  mensagens: number;
  com_cobertura: number;
  cadastro_completo: number;
  agendamentos_confirmados: number;
  transferidos_humano: number;
  com_ia?: number;
  por_fase: Record<string, number>;
  ferramentas_destaque?: { id: number; tool_key: string; nome: string; chamadas_sucesso: number }[];
};

export type Funil = {
  etapas: { fase: string; quantidade: number }[];
  totais: Resumo;
};

export type Conversa = {
  id_cliente: string;
  fase: string;
  status?: string;
  aguardando: string | null;
  cidade: string | null;
  bairro: string | null;
  plano_confirmado: string | null;
  nome: string | null;
  telefone: string | null;
  tem_cobertura: number | boolean | null;
  cadastro_completo: number | boolean | null;
  agendamento_confirmado: number | boolean | null;
  transferido_humano: number | boolean | null;
  conversation_id: string | null;
  contact_id: string | null;
  unidade_id?: number | null;
  updated_at: string | null;
};

export type Cliente = Conversa & {
  label?: string;
  cpf?: string | null;
  email?: string | null;
  data_nascimento?: string | null;
  rg?: string | null;
  cep?: string | null;
  rua?: string | null;
  numero?: string | null;
  complemento?: string | null;
  metodo_pagamento?: string | null;
  plano_apresentado?: string | null;
  plano_em_negociacao?: string | null;
  tem_cobertura?: boolean | null;
  localizacao_fixa?: string | null;
  caixa_fibra?: string | null;
  ixc_cliente_id?: string | null;
  id_contrato_ixc?: string | null;
  os_id?: string | null;
  data_agendamento?: string | null;
  horario_escolhido?: string | null;
  preferencia_horario?: string | null;
  termos_enviados?: boolean;
  ativado_ixc?: boolean;
  cadastro_completo?: boolean;
  agendamento_confirmado?: boolean;
  transferido_humano?: boolean;
  created_at?: string | null;
  ultima_mensagem_sofia?: string | null;
  motivo_transferencia?: string | null;
  [key: string]: unknown;
};

export type MensagemHistorico = {
  id: number;
  remetente: string;
  mensagem: string;
  created_at: string | null;
};

export const fetchClientes = (params?: {
  q?: string;
  fase?: string;
  status?: string;
  unidade_id?: number;
  limite?: number;
}) => {
  const sp = new URLSearchParams();
  if (params?.q) sp.set("q", params.q);
  if (params?.fase) sp.set("fase", params.fase);
  if (params?.status) sp.set("status", params.status);
  if (params?.unidade_id != null) sp.set("unidade_id", String(params.unidade_id));
  if (params?.limite != null) sp.set("limite", String(params.limite));
  const q = sp.toString();
  return api<{ items: Cliente[]; total: number }>(`/admin/clientes${q ? `?${q}` : ""}`);
};

export const fetchCliente = (id_cliente: string) =>
  api<Cliente>(`/admin/clientes/${encodeURIComponent(id_cliente)}`);

export const fetchMensagensCliente = (id_cliente: string, limite = 100) =>
  api<{ id_cliente: string; items: MensagemHistorico[] }>(
    `/admin/clientes/${encodeURIComponent(id_cliente)}/mensagens?limite=${limite}`,
  );

export const patchCliente = (id_cliente: string, body: Record<string, string>) =>
  api<Cliente>(`/admin/clientes/${encodeURIComponent(id_cliente)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export type Plano = {
  id: number;
  nome: string;
  velocidade: string | null;
  modalidade: string | null;
  requer_cartao: boolean;
  valor: number;
  parcelas: number | null;
  descricao: string;
  dispositivos_max: number | null;
  beneficios: string;
  ordem: number;
  ativo: boolean;
  destaque: boolean;
  unidade_id: number | null;
  imagem_url: string;
  valor_pontualidade?: number | null;
  condicao_valor_pontualidade?: string;
  tags?: string[];
};

export type Promocao = {
  id: number;
  codigo: string;
  titulo: string;
  descricao: string;
  ativo: number | boolean;
  valido_ate: string | null;
  unidade_id: number | null;
};

export type FerramentaParam = {
  id?: number;
  nome: string;
  tipo: string;
  descricao: string;
  obrigatorio: boolean;
  ordem: number;
};

export type Ferramenta = {
  id: number;
  tool_key: string;
  nome: string;
  descricao: string;
  webhook_url: string;
  integracao: string;
  unidade_id: number | null;
  destaque_dashboard: boolean;
  ativo: boolean;
  chamadas_sucesso: number;
  parametros: FerramentaParam[];
};

export const fetchHealth = () => api<{ ok: boolean; version?: string }>("/health");
export const fetchResumo = () => api<Resumo>("/metrics/resumo");
export const fetchFunil = () => api<Funil>("/metrics/funil");
export const fetchConversas = (limite = 40, opts?: { unidade_id?: number; status?: string }) => {
  const q = new URLSearchParams({ limite: String(limite) });
  if (opts?.unidade_id) q.set("unidade_id", String(opts.unidade_id));
  if (opts?.status) q.set("status", opts.status);
  return api<{ items: Conversa[] }>(`/metrics/conversas?${q}`);
};
export const fetchTurnos = (idCliente: string) =>
  api<{ items: unknown[] }>(`/metrics/turnos/${encodeURIComponent(idCliente)}`);

export const deleteConversa = (id_cliente: string) =>
  api<{ ok: boolean; id_cliente: string }>(
    `/admin/conversas/${encodeURIComponent(id_cliente)}`,
    { method: "DELETE" },
  );

export const fetchUnidades = () => api<{ items: Unidade[] }>("/admin/unidades");
export const createUnidade = (body: { codigo: string; nome: string; ativo: boolean }) =>
  api<Unidade>("/admin/unidades", { method: "POST", body: JSON.stringify(body) });

export const fetchPlanos = (unidade_id?: number) => {
  const q = unidade_id ? `?unidade_id=${unidade_id}` : "";
  return api<{ items: Plano[] }>(`/admin/planos${q}`);
};
export const createPlano = (body: Partial<Plano>) =>
  api<Plano>("/admin/planos", { method: "POST", body: JSON.stringify(body) });
export const updatePlano = (id: number, body: Partial<Plano>) =>
  api<Plano>(`/admin/planos/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deletePlano = (id: number) =>
  api<{ ok: boolean }>(`/admin/planos/${id}`, { method: "DELETE" });
export const setPlanoInicial = (id: number) =>
  api<Plano>(`/admin/planos/${id}/plano-inicial`, { method: "POST" });

export async function uploadPlanoImagem(id: number, file: File): Promise<Plano> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const t = getAdminToken();
  if (t) headers["X-Admin-Token"] = t;
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/admin/planos/${id}/imagem`, {
    method: "POST",
    headers,
    body: fd,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail
          ? JSON.stringify(detail)
          : `HTTP ${res.status}`,
    );
  }
  return data as Plano;
}

export const fetchPromocoes = (unidade_id?: number) => {
  const q = unidade_id ? `?unidade_id=${unidade_id}` : "";
  return api<{ items: Promocao[] }>(`/admin/promocoes${q}`);
};
export const upsertPromocao = (body: Partial<Promocao> & { codigo: string }) =>
  api<Promocao>("/admin/promocoes", { method: "POST", body: JSON.stringify(body) });
export const deletePromocao = (id: number) =>
  api<{ ok: boolean }>(`/admin/promocoes/${id}`, { method: "DELETE" });

export const fetchConfig = (unidade_id?: number) => {
  const q = unidade_id ? `?unidade_id=${unidade_id}` : "";
  return api<{ items: unknown[]; mapa: Record<string, string> }>(`/admin/config${q}`);
};
export const setConfig = (chave: string, valor: string, unidade_id?: number | null) =>
  api<unknown>("/admin/config", {
    method: "PUT",
    body: JSON.stringify({ chave, valor, unidade_id: unidade_id ?? null }),
  });

export type ConfigIa = {
  nome_ia: string;
  tom_voz: string;
  pode_emoji: boolean;
  llm_provider: string;
  openai_model: string;
  llm_temperature: number;
  openai_api_key_mask: string;
  openai_api_key_configured: boolean;
  transcription_api_key_mask: string;
  transcription_api_key_configured: boolean;
  rag_provider: string;
  rag_webhook_url: string;
  rag_webhook_token_mask: string;
  rag_webhook_token_configured: boolean;
};

export const fetchConfigIa = (unidade_id?: number) => {
  const q = unidade_id ? `?unidade_id=${unidade_id}` : "";
  return api<ConfigIa>(`/admin/config/ia${q}`);
};

export const saveConfigIa = (body: Record<string, unknown>) =>
  api<ConfigIa>("/admin/config/ia", {
    method: "PUT",
    body: JSON.stringify(body),
  });

export type ConfigChatwoot = {
  inbound_enabled: boolean;
  inbox_id: string;
  inbound_mode: string;
  allowlist_phones: string;
  buffer_enabled: boolean;
  public_base_url: string;
  webhook_url: string;
  webhook_token_configured: boolean;
  webhook_token_mask: string;
  envio_resposta_configurado: boolean;
  eventos_recomendados: string[];
  chatwoot_base_url: string;
  chatwoot_api_configured: boolean;
  chatwoot_api_token_mask: string;
};

export type ChatwootParseResult = {
  processavel: boolean;
  motivo: string | null;
  evento: Record<string, unknown> | null;
  inbox_esperado: string | null;
  inbox_recebido: string | null;
  allowlist_ok: boolean | null;
  allowlist_motivo: string | null;
  inbound_mode: string;
};

export const fetchConfigChatwoot = (unidade_id?: number) => {
  const q = unidade_id ? `?unidade_id=${unidade_id}` : "";
  return api<ConfigChatwoot>(`/admin/config/chatwoot${q}`);
};

export const saveConfigChatwoot = (body: Record<string, unknown>) =>
  api<ConfigChatwoot>("/admin/config/chatwoot", {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const fetchExemploPayloadChatwoot = () =>
  api<{ payload: Record<string, unknown> }>("/admin/config/chatwoot/exemplo-payload");

export const testParseChatwoot = (payload: Record<string, unknown>) =>
  api<ChatwootParseResult>("/admin/config/chatwoot/test-parse", {
    method: "POST",
    body: JSON.stringify({ payload }),
  });

export type ConfigCobertura = {
  coverage_provider: string;
  ixc_base_url: string;
  google_maps_configured: boolean;
  google_maps_api_key_mask: string;
  ixc_configured: boolean;
  ixc_user_mask: string;
  ixc_password_configured: boolean;
  ixc_password_mask: string;
  cobertura_pronta: boolean;
  faltando: string[];
};

export type CoberturaTestResult = {
  ok: boolean;
  resultado: {
    resultado: string;
    tem_cobertura: boolean;
    motivo?: string;
    cidade_normalizada?: string;
    bairro_normalizado?: string;
    caixa_fibra?: string;
  };
};

export const fetchConfigCobertura = (unidade_id?: number) => {
  const q = unidade_id ? `?unidade_id=${unidade_id}` : "";
  return api<ConfigCobertura>(`/admin/config/cobertura${q}`);
};

export const saveConfigCobertura = (body: Record<string, unknown>) =>
  api<ConfigCobertura>("/admin/config/cobertura", {
    method: "PUT",
    body: JSON.stringify(body),
  });

export const testCobertura = (body: Record<string, unknown>) =>
  api<CoberturaTestResult>("/admin/config/cobertura/test", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const fetchInboxes = () =>
  api<{ ok: boolean; data?: unknown; motivo?: string }>("/chatwoot/inboxes");

export const fetchFerramentas = (unidade_id?: number) => {
  const q = unidade_id ? `?unidade_id=${unidade_id}` : "";
  return api<{ items: Ferramenta[] }>(`/admin/ferramentas${q}`);
};
export const syncCatalogoFerramentas = () =>
  api<{ ok: boolean; criadas: number; items: Ferramenta[] }>(
    "/admin/ferramentas/sync-catalogo",
    { method: "POST" },
  );
export const createFerramenta = (body: Omit<Ferramenta, "id" | "chamadas_sucesso">) =>
  api<Ferramenta>("/admin/ferramentas", { method: "POST", body: JSON.stringify(body) });
export const updateFerramenta = (id: number, body: Partial<Ferramenta>) =>
  api<Ferramenta>(`/admin/ferramentas/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteFerramenta = (id: number) =>
  api<{ ok: boolean }>(`/admin/ferramentas/${id}`, { method: "DELETE" });

export const fetchAgents = () => api<{ ok: boolean; data?: unknown; motivo?: string }>("/chatwoot/agents");
export const fetchTeams = () => api<{ ok: boolean; data?: unknown; motivo?: string }>("/chatwoot/teams");
export const fetchLabels = () => api<{ ok: boolean; data?: unknown; motivo?: string }>("/chatwoot/labels");

export const postHandoff = (body: {
  conversation_id: string;
  assignee_id?: number | null;
  team_id?: number | null;
  labels?: string[];
  status?: string;
  motivo?: string;
}) =>
  api<unknown>("/chatwoot/handoff", {
    method: "POST",
    body: JSON.stringify(body),
  });

export type ChatResult = {
  resposta?: string;
  outputs?: string[];
  imagens?: { url: string; plano_id?: number; plano_nome?: string }[];
  estado?: {
    fase?: string;
    aguardando?: string | null;
    cidade?: string | null;
    bairro?: string | null;
    plano_confirmado?: string | null;
    nome?: string | null;
    [key: string]: unknown;
  };
  decisao?: { acao?: string; motivo?: string };
};

export const postChat = (body: {
  mensagem: string;
  id_cliente?: string;
  conversation_id?: string;
  contact_id?: string;
  buffer?: boolean;
}) =>
  api<ChatResult>("/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const postReset = (id_cliente?: string) =>
  api<{ ok: boolean; id_cliente: string }>("/reset", {
    method: "POST",
    body: JSON.stringify({ id_cliente: id_cliente || null }),
  });
