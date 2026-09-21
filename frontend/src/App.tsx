import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  Conversa,
  Ferramenta,
  FerramentaParam,
  Funil,
  Plano,
  Promocao,
  Resumo,
  Unidade,
  createFerramenta,
  createPlano,
  createUnidade,
  deleteFerramenta,
  deletePlano,
  deletePromocao,
  fetchAgents,
  fetchConfigIa,
  fetchConfigChatwoot,
  fetchExemploPayloadChatwoot,
  fetchInboxes,
  saveConfigIa,
  saveConfigChatwoot,
  testParseChatwoot,
  ChatwootParseResult,
  fetchCliente,
  fetchClientes,
  fetchConversas,
  fetchMensagensCliente,
  patchCliente,
  Cliente,
  MensagemHistorico,
  fetchFerramentas,
  syncCatalogoFerramentas,
  fetchFunil,
  fetchHealth,
  fetchLabels,
  fetchPlanos,
  fetchPromocoes,
  fetchResumo,
  fetchTeams,
  fetchTurnos,
  fetchUnidades,
  getAdminToken,
  postHandoff,
  postChat,
  postReset,
  setAdminToken,
  setPlanoInicial,
  updateFerramenta,
  updatePlano,
  uploadPlanoImagem,
  upsertPromocao,
} from "./api";

type Tab =
  | "chat"
  | "metricas"
  | "conversas"
  | "clientes"
  | "planos"
  | "promocoes"
  | "config"
  | "integracao"
  | "ferramentas"
  | "unidades";

type Option = { id: number; label: string };

type ChatMsg = {
  who: "cliente" | "eva" | "sistema";
  text: string;
  meta?: string;
  imageUrl?: string;
};

const GUIA_TESTE: { titulo: string; dica: string; msgs: string[] }[] = [
  {
    titulo: "1. Abertura",
    dica: "Veja se ela se apresenta como Eva e pede cidade/bairro.",
    msgs: ["Oi", "Quem é você?"],
  },
  {
    titulo: "2. Localização",
    dica: "Informe cidade e bairro (cobertura mock/IXC conforme .env).",
    msgs: ["Santarém, Centro", "Belém, Batista Campos"],
  },
  {
    titulo: "3. Planos",
    dica: "Peça lista, detalhes ou escolha um plano.",
    msgs: ["Quero ver os planos", "Quais os benefícios?", "Quero esse"],
  },
  {
    titulo: "4. Cadastro",
    dica: "Depois de confirmar o plano, envie os dados um a um.",
    msgs: [
      "Maria Silva",
      "12345678909",
      "maria@teste.com",
      "93992219098",
      "01/01/1990",
    ],
  },
  {
    titulo: "5. Transferência",
    dica: "Testa handoff / ferramenta transferir_atendimento.",
    msgs: ["Quero falar com um humano", "Me passa pra um atendente"],
  },
];

function asList(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (payload && typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    if (Array.isArray(o.payload)) return o.payload;
    if (Array.isArray(o.data)) return o.data;
  }
  return [];
}

function mapAgents(raw: unknown): Option[] {
  return asList(raw)
    .map((item) => {
      const a = item as Record<string, unknown>;
      const id = Number(a.id);
      if (!Number.isFinite(id)) return null;
      const name = String(a.name || a.available_name || a.email || `Agent ${id}`);
      return { id, label: name };
    })
    .filter(Boolean) as Option[];
}

function mapTeams(raw: unknown): Option[] {
  return asList(raw)
    .map((item) => {
      const t = item as Record<string, unknown>;
      const id = Number(t.id);
      if (!Number.isFinite(id)) return null;
      return { id, label: String(t.name || `Team ${id}`) };
    })
    .filter(Boolean) as Option[];
}

function mapInboxes(raw: unknown): Option[] {
  return asList(raw)
    .map((item) => {
      const box = item as Record<string, unknown>;
      const id = Number(box.id);
      if (!Number.isFinite(id)) return null;
      const channel = String(box.channel_type || box.provider || "").trim();
      const suffix = channel ? ` (${channel})` : "";
      return { id, label: `${String(box.name || `Inbox ${id}`)}${suffix}` };
    })
    .filter(Boolean) as Option[];
}

function mapLabelTitles(raw: unknown): string[] {
  return asList(raw)
    .map((item) => {
      if (typeof item === "string") return item;
      const l = item as Record<string, unknown>;
      return String(l.title || l.name || "").trim();
    })
    .filter(Boolean);
}

function statusBadge(status?: string) {
  const s = status || "com_ia";
  const label =
    s === "transferido" ? "Transferido" : s === "finalizado" ? "Finalizado" : "Com IA";
  return <span className={`badge badge-${s}`}>{label}</span>;
}

function fmtCampo(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  return String(v);
}

function rotuloCliente(c: { nome?: string | null; telefone?: string | null; id_cliente: string }) {
  return (c.nome || "").trim() || (c.telefone || "").trim() || c.id_cliente;
}

const TABS: { id: Tab; label: string }[] = [
  { id: "chat", label: "Chat teste" },
  { id: "metricas", label: "Métricas" },
  { id: "conversas", label: "Conversas" },
  { id: "clientes", label: "Clientes" },
  { id: "planos", label: "Planos" },
  { id: "promocoes", label: "Promoções" },
  { id: "config", label: "Config IA" },
  { id: "integracao", label: "Chatwoot" },
  { id: "ferramentas", label: "Ferramentas" },
  { id: "unidades", label: "Unidades" },
];

const emptyTool = (): Omit<Ferramenta, "id" | "chamadas_sucesso"> => ({
  tool_key: "",
  nome: "",
  descricao: "",
  webhook_url: "",
  integracao: "global",
  unidade_id: null,
  destaque_dashboard: false,
  ativo: true,
  parametros: [],
});

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [tokenInput, setTokenInput] = useState(getAdminToken());
  const [unidades, setUnidades] = useState<Unidade[]>([]);
  const [unidadeFiltro, setUnidadeFiltro] = useState<number | "">("");
  const [error, setError] = useState("");
  const [okMsg, setOkMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  const [chatId, setChatId] = useState("teste-local");
  const [chatConversationId, setChatConversationId] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatMsgs, setChatMsgs] = useState<ChatMsg[]>([
    {
      who: "sistema",
      text: "Guia de teste da Eva. Use as sugestões à direita ou digite livremente. Reinicie a conversa antes de um fluxo novo.",
    },
  ]);
  const [chatEstado, setChatEstado] = useState<string>("—");

  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [funil, setFunil] = useState<Funil | null>(null);
  const [conversas, setConversas] = useState<Conversa[]>([]);
  const [statusFiltro, setStatusFiltro] = useState("");
  const [sel, setSel] = useState<Conversa | null>(null);
  const [turnos, setTurnos] = useState<unknown[]>([]);
  const [mensagensConv, setMensagensConv] = useState<MensagemHistorico[]>([]);
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [clienteBusca, setClienteBusca] = useState("");
  const [selCliente, setSelCliente] = useState<Cliente | null>(null);
  const [clienteForm, setClienteForm] = useState<Record<string, string>>({});
  const [agents, setAgents] = useState<Option[]>([]);
  const [teams, setTeams] = useState<Option[]>([]);
  const [labelOptions, setLabelOptions] = useState<string[]>([]);
  const [assigneeId, setAssigneeId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [labelsCsv, setLabelsCsv] = useState("sofia_transferido");
  const [statusHandoff, setStatusHandoff] = useState("open");

  const [planos, setPlanos] = useState<Plano[]>([]);
  const [planoForm, setPlanoForm] = useState<Partial<Plano>>({
    nome: "",
    valor: 0,
    ativo: true,
    ordem: 100,
    imagem_url: "",
  });
  const [editPlanoId, setEditPlanoId] = useState<number | null>(null);
  const [planoImagemFile, setPlanoImagemFile] = useState<File | null>(null);
  const [planoImagemPreview, setPlanoImagemPreview] = useState("");

  const [promos, setPromos] = useState<Promocao[]>([]);
  const [promoForm, setPromoForm] = useState<Partial<Promocao>>({
    codigo: "",
    titulo: "",
    descricao: "",
    ativo: true,
  });

  const [iaForm, setIaForm] = useState({
    nome_ia: "Eva",
    tom_voz: "Calorosa, simpática, objetiva",
    pode_emoji: true,
    llm_provider: "openai",
    openai_model: "gpt-4.1-mini",
    llm_temperature: 0.3,
    openai_api_key: "",
    transcription_api_key: "",
    rag_provider: "webhook",
    rag_webhook_url: "",
    rag_webhook_token: "",
  });
  const [iaMasks, setIaMasks] = useState({
    openai: "",
    transcription: "",
    rag_token: "",
  });

  const [cwForm, setCwForm] = useState({
    inbound_enabled: true,
    inbox_id: "",
    inbound_mode: "allowlist",
    allowlist_phones: "",
    buffer_enabled: false,
    public_base_url: "",
    webhook_token: "",
  });
  const [cwMeta, setCwMeta] = useState({
    webhook_url: "",
    envio_ok: false,
    token_mask: "",
    token_configured: false,
  });
  const [inboxes, setInboxes] = useState<Option[]>([]);
  const [cwTestPayload, setCwTestPayload] = useState("");
  const [cwTestResult, setCwTestResult] = useState<ChatwootParseResult | null>(null);

  const [tools, setTools] = useState<Ferramenta[]>([]);
  const [toolForm, setToolForm] = useState(emptyTool());
  const [editToolId, setEditToolId] = useState<number | null>(null);

  const [novaUnidade, setNovaUnidade] = useState({ codigo: "", nome: "" });

  const uid = unidadeFiltro === "" ? undefined : Number(unidadeFiltro);

  const saveToken = (e: FormEvent) => {
    e.preventDefault();
    setAdminToken(tokenInput.trim());
    setOkMsg("Token salvo");
    void refreshAll();
  };

  const refreshUnidades = useCallback(async () => {
    const u = await fetchUnidades();
    setUnidades(u.items || []);
  }, []);

  const refreshMetrics = useCallback(async () => {
    const [r, f] = await Promise.all([fetchResumo(), fetchFunil()]);
    setResumo(r);
    setFunil(f);
  }, []);

  const refreshConversas = useCallback(async () => {
    const c = await fetchConversas(60, {
      unidade_id: uid,
      status: statusFiltro || undefined,
    });
    setConversas(c.items || []);
  }, [uid, statusFiltro]);

  const refreshClientes = useCallback(async () => {
    const c = await fetchClientes({
      q: clienteBusca.trim() || undefined,
      unidade_id: uid,
      limite: 100,
    });
    setClientes(c.items || []);
  }, [uid, clienteBusca]);

  const refreshPlanos = useCallback(async () => {
    const p = await fetchPlanos(uid);
    setPlanos(p.items || []);
  }, [uid]);

  const refreshPromos = useCallback(async () => {
    const p = await fetchPromocoes(uid);
    setPromos(p.items || []);
  }, [uid]);

  const refreshConfig = useCallback(async () => {
    const c = await fetchConfigIa(uid);
    setIaForm({
      nome_ia: c.nome_ia || "Eva",
      tom_voz: c.tom_voz || "",
      pode_emoji: !!c.pode_emoji,
      llm_provider: c.llm_provider || "openai",
      openai_model: c.openai_model || "gpt-4.1-mini",
      llm_temperature: Number(c.llm_temperature ?? 0.3),
      openai_api_key: "",
      transcription_api_key: "",
      rag_provider: c.rag_provider || "webhook",
      rag_webhook_url: c.rag_webhook_url || "",
      rag_webhook_token: "",
    });
    setIaMasks({
      openai: c.openai_api_key_mask || "",
      transcription: c.transcription_api_key_mask || "",
      rag_token: c.rag_webhook_token_mask || "",
    });
  }, [uid]);

  const refreshTools = useCallback(async () => {
    try {
      const synced = await syncCatalogoFerramentas();
      setTools(synced.items || []);
    } catch {
      const t = await fetchFerramentas(uid);
      setTools(t.items || []);
    }
  }, [uid]);

  const refreshIntegracao = useCallback(async () => {
    const cfg = await fetchConfigChatwoot(uid);
    setCwForm({
      inbound_enabled: !!cfg.inbound_enabled,
      inbox_id: cfg.inbox_id || "",
      inbound_mode: cfg.inbound_mode || "allowlist",
      allowlist_phones: cfg.allowlist_phones || "",
      buffer_enabled: !!cfg.buffer_enabled,
      public_base_url: cfg.public_base_url || "",
      webhook_token: "",
    });
    setCwMeta({
      webhook_url: cfg.webhook_url || "",
      envio_ok: !!cfg.envio_resposta_configurado,
      token_mask: cfg.webhook_token_mask || "",
      token_configured: !!cfg.webhook_token_configured,
    });
    try {
      const inb = await fetchInboxes();
      if (inb.ok) setInboxes(mapInboxes(inb.data));
    } catch {
      /* lista de inboxes opcional — depende do token Chatwoot no .env */
    }
    try {
      const ex = await fetchExemploPayloadChatwoot();
      setCwTestPayload(JSON.stringify(ex.payload, null, 2));
    } catch {
      /* opcional */
    }
  }, [uid]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const h = await fetchHealth();
      setApiOk(!!h.ok);
      await refreshUnidades();
      if (tab === "chat") {
        /* só health + token — chat é interativo */
      }
      if (tab === "metricas") await refreshMetrics();
      if (tab === "conversas") {
        await refreshConversas();
        const [a, t, l] = await Promise.all([fetchAgents(), fetchTeams(), fetchLabels()]);
        setAgents(mapAgents(a.data));
        setTeams(mapTeams(t.data));
        setLabelOptions(mapLabelTitles(l.data));
      }
      if (tab === "clientes") await refreshClientes();
      if (tab === "planos") await refreshPlanos();
      if (tab === "promocoes") await refreshPromos();
      if (tab === "config") await refreshConfig();
      if (tab === "integracao") await refreshIntegracao();
      if (tab === "ferramentas") await refreshTools();
    } catch (err) {
      setApiOk(false);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [
    tab,
    refreshUnidades,
    refreshMetrics,
    refreshConversas,
    refreshClientes,
    refreshPlanos,
    refreshPromos,
    refreshConfig,
    refreshIntegracao,
    refreshTools,
  ]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const maxFunil = useMemo(
    () => Math.max(1, ...(funil?.etapas.map((e) => e.quantidade) || [1])),
    [funil],
  );

  async function onSelectConversa(c: Conversa) {
    setSel(c);
    setMensagensConv([]);
    try {
      const [t, m] = await Promise.all([
        fetchTurnos(c.id_cliente),
        fetchMensagensCliente(c.id_cliente, 80),
      ]);
      setTurnos(t.items || []);
      setMensagensConv(m.items || []);
    } catch {
      setTurnos([]);
      setMensagensConv([]);
    }
  }

  function clienteFormFromDetail(c: Cliente) {
    return {
      nome: c.nome || "",
      cpf: c.cpf || "",
      email: c.email || "",
      telefone: c.telefone || "",
      data_nascimento: c.data_nascimento || "",
      rg: c.rg || "",
      cep: c.cep || "",
      rua: c.rua || "",
      numero: c.numero || "",
      complemento: c.complemento || "",
      cidade: c.cidade || "",
      bairro: c.bairro || "",
      metodo_pagamento: c.metodo_pagamento || "",
    };
  }

  async function onSelectCliente(c: Cliente) {
    setSelCliente(null);
    try {
      const full = await fetchCliente(c.id_cliente);
      setSelCliente(full);
      setClienteForm(clienteFormFromDetail(full));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveCliente(e: FormEvent) {
    e.preventDefault();
    if (!selCliente) return;
    setError("");
    try {
      const saved = await patchCliente(selCliente.id_cliente, clienteForm);
      setSelCliente(saved);
      setClienteForm(clienteFormFromDetail(saved));
      setOkMsg("Cliente salvo");
      await refreshClientes();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function buscarClientes(e: FormEvent) {
    e.preventDefault();
    await refreshClientes();
  }

  async function doHandoff() {
    if (!sel?.conversation_id) {
      setError("Conversa sem conversation_id");
      return;
    }
    setError("");
    try {
      await postHandoff({
        conversation_id: String(sel.conversation_id),
        assignee_id: assigneeId ? Number(assigneeId) : null,
        team_id: teamId ? Number(teamId) : null,
        labels: labelsCsv.split(",").map((x) => x.trim()).filter(Boolean),
        status: statusHandoff,
        motivo: "Painel Eva",
      });
      setOkMsg("Handoff enviado");
      await refreshConversas();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function savePlano(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const body = {
        ...planoForm,
        valor: Number(planoForm.valor || 0),
        unidade_id: planoForm.unidade_id ?? uid ?? null,
        imagem_url: planoForm.imagem_url || "",
      };
      let saved: Plano;
      if (editPlanoId) saved = await updatePlano(editPlanoId, body);
      else saved = await createPlano(body);
      if (planoImagemFile) {
        saved = await uploadPlanoImagem(saved.id, planoImagemFile);
      }
      setEditPlanoId(null);
      setPlanoForm({ nome: "", valor: 0, ativo: true, ordem: 100, imagem_url: "" });
      setPlanoImagemFile(null);
      setPlanoImagemPreview("");
      setOkMsg("Plano salvo");
      await refreshPlanos();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function savePromo(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await upsertPromocao({
        ...promoForm,
        codigo: String(promoForm.codigo || ""),
        unidade_id: promoForm.unidade_id ?? uid ?? null,
      } as Promocao & { codigo: string });
      setPromoForm({ codigo: "", titulo: "", descricao: "", ativo: true });
      setOkMsg("Promoção salva");
      await refreshPromos();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveConfig(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const saved = await saveConfigIa({
        ...iaForm,
        unidade_id: uid ?? null,
      });
      setIaForm((f) => ({
        ...f,
        openai_api_key: "",
        transcription_api_key: "",
        rag_webhook_token: "",
        nome_ia: saved.nome_ia,
        tom_voz: saved.tom_voz,
        pode_emoji: saved.pode_emoji,
        llm_provider: saved.llm_provider,
        openai_model: saved.openai_model,
        llm_temperature: Number(saved.llm_temperature ?? 0.3),
        rag_provider: saved.rag_provider || "webhook",
        rag_webhook_url: saved.rag_webhook_url || "",
      }));
      setIaMasks({
        openai: saved.openai_api_key_mask || "",
        transcription: saved.transcription_api_key_mask || "",
        rag_token: saved.rag_webhook_token_mask || "",
      });
      setOkMsg("Configuração IA salva");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function saveIntegracao(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const saved = await saveConfigChatwoot({
        ...cwForm,
        unidade_id: uid ?? null,
      });
      setCwMeta({
        webhook_url: saved.webhook_url || "",
        envio_ok: !!saved.envio_resposta_configurado,
        token_mask: saved.webhook_token_mask || "",
        token_configured: !!saved.webhook_token_configured,
      });
      setCwForm((f) => ({ ...f, webhook_token: "" }));
      setOkMsg("Integração Chatwoot salva");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function runTestParse() {
    setError("");
    setCwTestResult(null);
    try {
      const payload = JSON.parse(cwTestPayload) as Record<string, unknown>;
      const r = await testParseChatwoot(payload);
      setCwTestResult(r);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function copyWebhookUrl() {
    if (!cwMeta.webhook_url) return;
    void navigator.clipboard.writeText(cwMeta.webhook_url);
    setOkMsg("URL copiada");
  }

  function addParam() {
    setToolForm((f) => ({
      ...f,
      parametros: [
        ...f.parametros,
        { nome: "", tipo: "texto", descricao: "", obrigatorio: false, ordem: f.parametros.length },
      ],
    }));
  }

  function updateParam(i: number, patch: Partial<FerramentaParam>) {
    setToolForm((f) => ({
      ...f,
      parametros: f.parametros.map((p, idx) => (idx === i ? { ...p, ...patch } : p)),
    }));
  }

  function removeParam(i: number) {
    setToolForm((f) => ({
      ...f,
      parametros: f.parametros.filter((_, idx) => idx !== i),
    }));
  }

  async function saveTool(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const body = {
        ...toolForm,
        unidade_id: toolForm.integracao === "unidade" ? toolForm.unidade_id ?? uid ?? null : null,
      };
      if (editToolId) await updateFerramenta(editToolId, body);
      else await createFerramenta(body);
      setEditToolId(null);
      setToolForm(emptyTool());
      setOkMsg("Ferramenta salva");
      await refreshTools();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  function editTool(t: Ferramenta) {
    setEditToolId(t.id);
    setToolForm({
      tool_key: t.tool_key,
      nome: t.nome,
      descricao: t.descricao,
      webhook_url: t.webhook_url,
      integracao: t.integracao || (t.unidade_id ? "unidade" : "global"),
      unidade_id: t.unidade_id,
      destaque_dashboard: t.destaque_dashboard,
      ativo: t.ativo,
      parametros: t.parametros || [],
    });
  }

  async function saveUnidade(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createUnidade({ ...novaUnidade, ativo: true });
      setNovaUnidade({ codigo: "", nome: "" });
      setOkMsg("Unidade criada");
      await refreshUnidades();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function enviarChat(texto?: string) {
    const mensagem = (texto ?? chatInput).trim();
    if (!mensagem || chatBusy) return;
    setChatInput("");
    setError("");
    setChatMsgs((m) => [...m, { who: "cliente", text: mensagem }]);
    setChatBusy(true);
    try {
      const r = await postChat({
        mensagem,
        id_cliente: chatId.trim() || "teste-local",
        conversation_id: chatConversationId.trim() || undefined,
        buffer: false,
      });
      const bolhas =
        r.outputs && r.outputs.length > 0
          ? r.outputs.filter((b) => String(b).trim())
          : r.resposta
            ? [r.resposta]
            : ["(sem resposta)"];
      const fase = r.estado?.fase || "—";
      const aguardando = r.estado?.aguardando || "—";
      const acao = r.decisao?.acao || "";
      setChatEstado(`${fase} · aguardando=${aguardando}${acao ? ` · ${acao}` : ""}`);
      const imgs = (r.imagens || []).filter((i) => i?.url);
      const imgsUniq = imgs.filter(
        (img, idx, arr) => arr.findIndex((x) => x.url === img.url) === idx,
      );
      setChatMsgs((m) => [
        ...m,
        ...imgsUniq.map((img) => ({
          who: "eva" as const,
          text: img.plano_nome ? `Imagem: ${img.plano_nome}` : "Imagem do plano",
          imageUrl: img.url,
        })),
        ...bolhas.map((b, i) => ({
          who: "eva" as const,
          text: String(b),
          meta: i === bolhas.length - 1 ? `fase=${fase} · aguardando=${aguardando}` : undefined,
        })),
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setChatMsgs((m) => [...m, { who: "sistema", text: `Erro: ${msg}` }]);
    } finally {
      setChatBusy(false);
    }
  }

  async function reiniciarChat() {
    setError("");
    try {
      await postReset(chatId.trim() || "teste-local");
      setChatMsgs([
        {
          who: "sistema",
          text: `Conversa reiniciada para ${chatId.trim() || "teste-local"}. Pode mandar um oi.`,
        },
      ]);
      setChatEstado("inicio");
      setOkMsg("Chat reiniciado");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">E</span>
          <div>
            <strong>Eva</strong>
            <small>Painel operacional MOV</small>
          </div>
        </div>
        <nav>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "nav-item active" : "nav-item"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className={apiOk ? "dot ok" : apiOk === false ? "dot bad" : "dot"} />
          API {apiOk ? "online" : apiOk === false ? "offline" : "…"}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <form className="token-row" onSubmit={saveToken}>
            <input
              type="password"
              placeholder="ADMIN_API_TOKEN"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
            />
            <button type="submit">Salvar token</button>
          </form>
          <div className="top-filters">
            <label>
              Unidade
              <select
                value={unidadeFiltro}
                onChange={(e) =>
                  setUnidadeFiltro(e.target.value === "" ? "" : Number(e.target.value))
                }
              >
                <option value="">Todas / global</option>
                {unidades.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.nome}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="ghost" onClick={() => void refreshAll()} disabled={loading}>
              {loading ? "Atualizando…" : "Atualizar"}
            </button>
          </div>
        </header>

        {error ? <div className="alert bad">{error}</div> : null}
        {okMsg ? (
          <div className="alert ok" onClick={() => setOkMsg("")}>
            {okMsg}
          </div>
        ) : null}

        {tab === "chat" && (
          <section className="panel chat-panel">
            <div className="chat-layout">
              <div className="chat-main">
                <div className="row-head">
                  <div>
                    <h1>Chat de testes</h1>
                    <p className="muted" style={{ margin: 0 }}>
                      Converse com a Eva como se fosse o cliente no WhatsApp.
                    </p>
                  </div>
                  <div className="chat-toolbar">
                    <label className="chat-id">
                      id_cliente
                      <input
                        value={chatId}
                        onChange={(e) => setChatId(e.target.value)}
                        placeholder="teste-local"
                      />
                    </label>
                    <label className="chat-id">
                      conversation_id
                      <input
                        value={chatConversationId}
                        onChange={(e) => setChatConversationId(e.target.value)}
                        placeholder="2969 (Chatwoot)"
                        title="Obrigatório para enviar termos/áudio via n8n"
                      />
                    </label>
                    <button type="button" className="ghost" onClick={() => void reiniciarChat()}>
                      Reiniciar
                    </button>
                  </div>
                </div>
                <div className="chat-estado">Estado: {chatEstado}</div>
                <div className="chat-log">
                  {chatMsgs.map((m, i) => (
                    <div key={i} className={`chat-bubble ${m.who}`}>
                      {m.who === "cliente" ? (
                        <div className="chat-label">CUSTOMER</div>
                      ) : m.who === "eva" ? (
                        <div className="chat-label">AI</div>
                      ) : null}
                      <div className="chat-text">{m.text}</div>
                      {m.imageUrl ? (
                        <img className="chat-plano-img" src={m.imageUrl} alt={m.text || "Plano"} />
                      ) : null}
                      {m.meta ? <div className="chat-meta">{m.meta}</div> : null}
                    </div>
                  ))}
                  {chatBusy ? (
                    <div className="chat-bubble eva typing">
                      <div className="chat-label">AI</div>
                      <div className="chat-text">digitando…</div>
                    </div>
                  ) : null}
                </div>
                <form
                  className="chat-compose"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void enviarChat();
                  }}
                >
                  <input
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="Digite como o cliente…"
                    disabled={chatBusy}
                    autoComplete="off"
                  />
                  <button type="submit" disabled={chatBusy || !chatInput.trim()}>
                    Enviar
                  </button>
                </form>
              </div>

              <aside className="chat-guide">
                <h2>Guia rápido</h2>
                <p className="muted">
                  Siga a ordem do funil. Clique numa frase para enviar. Reinicie entre cenários.
                </p>
                {GUIA_TESTE.map((bloco) => (
                  <div className="guide-block" key={bloco.titulo}>
                    <strong>{bloco.titulo}</strong>
                    <small>{bloco.dica}</small>
                    <div className="guide-chips">
                      {bloco.msgs.map((msg) => (
                        <button
                          key={msg}
                          type="button"
                          className="chip"
                          disabled={chatBusy}
                          onClick={() => void enviarChat(msg)}
                        >
                          {msg}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                <div className="guide-block">
                  <strong>Dica</strong>
                  <small>
                    Preencha <code>conversation_id</code> (Chatwoot) para testar cadastro, termos e
                    agendamento via n8n. Com cobertura em mock, qualquer cidade/bairro costuma passar.
                  </small>
                </div>
              </aside>
            </div>
          </section>
        )}

        {tab === "metricas" && (
          <section className="panel">
            <h1>Métricas</h1>
            <p className="muted">Visão do funil e desempenho operacional.</p>
            <div className="cards">
              <div className="stat">
                <span>Conversas</span>
                <strong>{resumo?.conversas ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Com IA</span>
                <strong>{resumo?.com_ia ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Transferidos</span>
                <strong>{resumo?.transferidos_humano ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Agendamentos</span>
                <strong>{resumo?.agendamentos_confirmados ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Cobertura</span>
                <strong>{resumo?.com_cobertura ?? "—"}</strong>
              </div>
              <div className="stat">
                <span>Mensagens</span>
                <strong>{resumo?.mensagens ?? "—"}</strong>
              </div>
            </div>
            {(resumo?.ferramentas_destaque || []).length > 0 && (
              <div className="cards tools-stats">
                {resumo!.ferramentas_destaque!.map((f) => (
                  <div className="stat" key={f.id}>
                    <span>{f.nome}</span>
                    <strong>{f.chamadas_sucesso}</strong>
                    <small>sucessos</small>
                  </div>
                ))}
              </div>
            )}
            <h2>Funil</h2>
            <div className="funil">
              {(funil?.etapas || []).map((e) => (
                <div key={e.fase} className="funil-row">
                  <span>{e.fase}</span>
                  <div className="bar-wrap">
                    <div
                      className="bar"
                      style={{ width: `${Math.round((e.quantidade / maxFunil) * 100)}%` }}
                    />
                  </div>
                  <strong>{e.quantidade}</strong>
                </div>
              ))}
            </div>
          </section>
        )}

        {tab === "conversas" && (
          <section className="panel split">
            <div>
              <div className="row-head">
                <h1>Conversas</h1>
                <select value={statusFiltro} onChange={(e) => setStatusFiltro(e.target.value)}>
                  <option value="">Todos status</option>
                  <option value="com_ia">Com IA</option>
                  <option value="transferido">Transferido</option>
                  <option value="finalizado">Finalizado</option>
                </select>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Cliente</th>
                      <th>Status</th>
                      <th>Fase</th>
                      <th>Cidade</th>
                      <th>Atualizado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {conversas.map((c) => (
                      <tr
                        key={c.id_cliente}
                        className={sel?.id_cliente === c.id_cliente ? "selected" : ""}
                        onClick={() => void onSelectConversa(c)}
                      >
                        <td>
                          <div>{c.nome || c.id_cliente}</div>
                          <small>{c.telefone || c.conversation_id || "—"}</small>
                        </td>
                        <td>{statusBadge(c.status)}</td>
                        <td>{c.fase}</td>
                        <td>{c.cidade || "—"}</td>
                        <td>
                          <small>{c.updated_at ? new Date(c.updated_at).toLocaleString() : "—"}</small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <aside className="detail">
              <h2>Detalhe</h2>
              {!sel ? (
                <p className="muted">Selecione uma conversa.</p>
              ) : (
                <>
                  <p>
                    <strong>{sel.nome || sel.id_cliente}</strong>
                    <br />
                    {statusBadge(sel.status)} · {sel.fase}
                  </p>
                  <p className="muted">
                    Plano: {sel.plano_confirmado || "—"}
                    <br />
                    CID: {sel.conversation_id || "—"}
                  </p>
                  <h3>Handoff</h3>
                  <label>
                    Atendente
                    <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
                      <option value="">—</option>
                      {agents.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Time
                    <select value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                      <option value="">—</option>
                      {teams.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Labels
                    <input
                      value={labelsCsv}
                      onChange={(e) => setLabelsCsv(e.target.value)}
                      list="labels-dl"
                    />
                    <datalist id="labels-dl">
                      {labelOptions.map((l) => (
                        <option key={l} value={l} />
                      ))}
                    </datalist>
                  </label>
                  <label>
                    Status
                    <select value={statusHandoff} onChange={(e) => setStatusHandoff(e.target.value)}>
                      <option value="open">open</option>
                      <option value="pending">pending</option>
                      <option value="resolved">resolved</option>
                    </select>
                  </label>
                  <button type="button" onClick={() => void doHandoff()}>
                    Transferir agora
                  </button>
                  <h3>Histórico de mensagens</h3>
                  <ul className="msg-timeline">
                    {mensagensConv.length === 0 ? (
                      <li className="muted">Nenhuma mensagem registrada ainda.</li>
                    ) : (
                      mensagensConv.slice(-30).map((m) => (
                        <li
                          key={m.id}
                          className={m.remetente === "cliente" ? "msg-cliente" : "msg-eva"}
                        >
                          <small>
                            {m.remetente === "cliente" ? "Cliente" : "Eva"}
                            {m.created_at
                              ? ` · ${new Date(m.created_at).toLocaleString()}`
                              : ""}
                          </small>
                          <div>{m.mensagem}</div>
                        </li>
                      ))
                    )}
                  </ul>
                  <h3>Turnos recentes</h3>
                  <ul className="turnos">
                    {turnos.slice(0, 8).map((t, i) => {
                      const row = t as Record<string, unknown>;
                      return (
                        <li key={i}>
                          <small>
                            {String(row.acao || row.fase || "")} —{" "}
                            {String(row.created_at || "").slice(0, 19)}
                          </small>
                        </li>
                      );
                    })}
                  </ul>
                </>
              )}
            </aside>
          </section>
        )}

        {tab === "clientes" && (
          <section className="panel clientes-panel">
            <h1>Clientes</h1>
            <p className="muted">
              Cadastro estruturado de cada cliente — a IA grava aqui o que aprende na conversa
              (nome, CPF, endereço, plano, etc.).
            </p>
            <div className="clientes-layout">
              <aside className="clientes-list">
                <form className="clientes-search" onSubmit={(e) => void buscarClientes(e)}>
                  <input
                    value={clienteBusca}
                    onChange={(e) => setClienteBusca(e.target.value)}
                    placeholder="Buscar nome, telefone, CPF ou e-mail"
                  />
                  <button type="submit">Buscar</button>
                </form>
                <ul>
                  {clientes.map((c) => (
                    <li
                      key={c.id_cliente}
                      className={
                        selCliente?.id_cliente === c.id_cliente ? "client-item active" : "client-item"
                      }
                      onClick={() => void onSelectCliente(c)}
                    >
                      <strong>{rotuloCliente(c)}</strong>
                      <small>
                        {c.telefone || c.id_cliente}
                        {c.status ? ` · ${c.status}` : ""}
                      </small>
                    </li>
                  ))}
                  {clientes.length === 0 && (
                    <li className="muted" style={{ padding: "12px" }}>
                      Nenhum cliente encontrado.
                    </li>
                  )}
                </ul>
              </aside>

              <div className="clientes-detail">
                {!selCliente ? (
                  <p className="muted">Selecione um cliente na lista.</p>
                ) : (
                  <>
                    <div className="row-head">
                      <div>
                        <h2>{rotuloCliente(selCliente)}</h2>
                        <p className="muted">
                          ID: {selCliente.id_cliente} · {statusBadge(selCliente.status)} · fase{" "}
                          {selCliente.fase}
                          {selCliente.aguardando ? ` · aguardando ${selCliente.aguardando}` : ""}
                        </p>
                      </div>
                    </div>

                    <form className="form-grid client-form" onSubmit={(e) => void saveCliente(e)}>
                      <h3 className="span2">Identificação</h3>
                      <label>
                        Nome
                        <input
                          value={clienteForm.nome}
                          onChange={(e) => setClienteForm({ ...clienteForm, nome: e.target.value })}
                          placeholder="Preenchido pela IA na conversa"
                        />
                      </label>
                      <label>
                        CPF
                        <input
                          value={clienteForm.cpf}
                          onChange={(e) => setClienteForm({ ...clienteForm, cpf: e.target.value })}
                        />
                      </label>
                      <label>
                        E-mail
                        <input
                          value={clienteForm.email}
                          onChange={(e) => setClienteForm({ ...clienteForm, email: e.target.value })}
                        />
                      </label>
                      <label>
                        Telefone
                        <input
                          value={clienteForm.telefone}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, telefone: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Data de nascimento
                        <input
                          value={clienteForm.data_nascimento}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, data_nascimento: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        RG
                        <input
                          value={clienteForm.rg}
                          onChange={(e) => setClienteForm({ ...clienteForm, rg: e.target.value })}
                        />
                      </label>

                      <h3 className="span2">Endereço</h3>
                      <label>
                        CEP
                        <input
                          value={clienteForm.cep}
                          onChange={(e) => setClienteForm({ ...clienteForm, cep: e.target.value })}
                        />
                      </label>
                      <label>
                        Rua
                        <input
                          value={clienteForm.rua}
                          onChange={(e) => setClienteForm({ ...clienteForm, rua: e.target.value })}
                        />
                      </label>
                      <label>
                        Número
                        <input
                          value={clienteForm.numero}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, numero: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Complemento
                        <input
                          value={clienteForm.complemento}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, complemento: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Cidade
                        <input
                          value={clienteForm.cidade}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, cidade: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Bairro
                        <input
                          value={clienteForm.bairro}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, bairro: e.target.value })
                          }
                        />
                      </label>

                      <h3 className="span2">Plano e operação</h3>
                      <label>
                        Plano confirmado
                        <input readOnly value={fmtCampo(selCliente.plano_confirmado)} />
                      </label>
                      <label>
                        Plano apresentado
                        <input readOnly value={fmtCampo(selCliente.plano_apresentado)} />
                      </label>
                      <label>
                        Método pagamento
                        <input
                          value={clienteForm.metodo_pagamento}
                          onChange={(e) =>
                            setClienteForm({ ...clienteForm, metodo_pagamento: e.target.value })
                          }
                        />
                      </label>
                      <label>
                        Cobertura
                        <input readOnly value={fmtCampo(selCliente.tem_cobertura)} />
                      </label>
                      <label>
                        Cadastro completo
                        <input readOnly value={fmtCampo(selCliente.cadastro_completo)} />
                      </label>
                      <label>
                        Termos enviados
                        <input readOnly value={fmtCampo(selCliente.termos_enviados)} />
                      </label>
                      <label>
                        Agendamento
                        <input
                          readOnly
                          value={fmtCampo(
                            selCliente.data_agendamento
                              ? `${selCliente.data_agendamento} ${selCliente.horario_escolhido || ""}`.trim()
                              : selCliente.agendamento_confirmado,
                          )}
                        />
                      </label>

                      <h3 className="span2">Chatwoot / IXC</h3>
                      <label>
                        Conversation ID
                        <input readOnly value={fmtCampo(selCliente.conversation_id)} />
                      </label>
                      <label>
                        Contact ID
                        <input readOnly value={fmtCampo(selCliente.contact_id)} />
                      </label>
                      <label>
                        Cliente IXC
                        <input readOnly value={fmtCampo(selCliente.ixc_cliente_id)} />
                      </label>
                      <label>
                        Contrato / OS
                        <input
                          readOnly
                          value={fmtCampo(
                            [selCliente.id_contrato_ixc, selCliente.os_id].filter(Boolean).join(" / ") ||
                              null,
                          )}
                        />
                      </label>

                      <div className="actions span2">
                        <button type="submit">Salvar cadastro</button>
                      </div>
                    </form>

                    <p className="muted">
                      Início:{" "}
                      {selCliente.created_at
                        ? new Date(selCliente.created_at).toLocaleString()
                        : "—"}{" "}
                      · Atualizado:{" "}
                      {selCliente.updated_at
                        ? new Date(selCliente.updated_at).toLocaleString()
                        : "—"}
                    </p>
                  </>
                )}
              </div>
            </div>
          </section>
        )}

        {tab === "planos" && (
          <section className="panel">
            <h1>Planos</h1>
            <p className="muted">
              Catálogo da Eva · a IA usa estes planos (não o webhook). Marque o plano inicial.
            </p>
            <form className="form-grid" onSubmit={savePlano}>
              <label>
                Nome
                <input
                  required
                  value={planoForm.nome || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, nome: e.target.value })}
                />
              </label>
              <label>
                Valor (R$)
                <input
                  type="number"
                  step="0.01"
                  required
                  value={planoForm.valor ?? 0}
                  onChange={(e) => setPlanoForm({ ...planoForm, valor: Number(e.target.value) })}
                />
              </label>
              <label>
                Valor pontualidade (opcional)
                <input
                  type="number"
                  step="0.01"
                  value={planoForm.valor_pontualidade ?? ""}
                  onChange={(e) =>
                    setPlanoForm({
                      ...planoForm,
                      valor_pontualidade: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                  placeholder="Ex: 119"
                />
              </label>
              <label>
                Velocidade
                <input
                  value={planoForm.velocidade || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, velocidade: e.target.value })}
                />
              </label>
              <label>
                Modalidade
                <input
                  value={planoForm.modalidade || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, modalidade: e.target.value })}
                />
              </label>
              <label className="span2">
                Imagem do plano (PNG)
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
                  onChange={(e) => {
                    const f = e.target.files?.[0] || null;
                    setPlanoImagemFile(f);
                    if (f) setPlanoImagemPreview(URL.createObjectURL(f));
                    else setPlanoImagemPreview("");
                  }}
                />
                <small className="field-hint">
                  Envie um PNG (ou JPG/WEBP). A imagem fica salva na plataforma — sem link externo.
                </small>
                {(planoImagemPreview || planoForm.imagem_url) && (
                  <img
                    className="plano-thumb"
                    src={planoImagemPreview || planoForm.imagem_url || ""}
                    alt="Prévia do plano"
                  />
                )}
              </label>
              <label className="span2">
                Descrição (texto que a IA apresenta)
                <textarea
                  value={planoForm.descricao || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, descricao: e.target.value })}
                  rows={6}
                  placeholder="Texto comercial completo com ✅ benefícios…"
                />
              </label>
              <label className="span2">
                Benefícios (checklist; um por linha)
                <textarea
                  value={planoForm.beneficios || ""}
                  onChange={(e) => setPlanoForm({ ...planoForm, beneficios: e.target.value })}
                  rows={4}
                />
              </label>
              <label className="span2">
                Condição pontualidade
                <input
                  value={planoForm.condicao_valor_pontualidade || ""}
                  onChange={(e) =>
                    setPlanoForm({ ...planoForm, condicao_valor_pontualidade: e.target.value })
                  }
                  placeholder="Pagando até o vencimento…"
                />
              </label>
              <label>
                Ordem
                <input
                  type="number"
                  value={planoForm.ordem ?? 100}
                  onChange={(e) => setPlanoForm({ ...planoForm, ordem: Number(e.target.value) })}
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!!planoForm.ativo}
                  onChange={(e) => setPlanoForm({ ...planoForm, ativo: e.target.checked })}
                />
                Ativo
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!!planoForm.destaque}
                  onChange={(e) => setPlanoForm({ ...planoForm, destaque: e.target.checked })}
                />
                Plano inicial (IA apresenta primeiro)
              </label>
              <div className="actions span2">
                <button type="submit">{editPlanoId ? "Atualizar" : "Criar plano"}</button>
                {editPlanoId ? (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => {
                      setEditPlanoId(null);
                      setPlanoForm({
                        nome: "",
                        valor: 0,
                        ativo: true,
                        ordem: 100,
                        imagem_url: "",
                        descricao: "",
                        beneficios: "",
                        valor_pontualidade: null,
                        condicao_valor_pontualidade: "",
                      });
                      setPlanoImagemFile(null);
                      setPlanoImagemPreview("");
                    }}
                  >
                    Cancelar
                  </button>
                ) : null}
              </div>
            </form>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Nome</th>
                    <th>Valor</th>
                    <th>Inicial</th>
                    <th>Img</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {planos.map((p) => (
                    <tr key={p.id}>
                      <td>
                        {p.nome}
                        {!p.ativo ? " (inativo)" : ""}
                      </td>
                      <td>
                        R$ {Number(p.valor).toFixed(2)}
                        {p.valor_pontualidade != null
                          ? ` · pont. R$ ${Number(p.valor_pontualidade).toFixed(2)}`
                          : ""}
                      </td>
                      <td>{p.destaque ? "★ sim" : "—"}</td>
                      <td>
                        {p.imagem_url ? (
                          <img className="plano-thumb-sm" src={p.imagem_url} alt={p.nome} />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="row-actions">
                        {!p.destaque ? (
                          <button
                            type="button"
                            className="ghost"
                            onClick={async () => {
                              try {
                                await setPlanoInicial(p.id);
                                setOkMsg(`${p.nome} definido como plano inicial`);
                                await refreshPlanos();
                              } catch (err) {
                                setError(err instanceof Error ? err.message : String(err));
                              }
                            }}
                          >
                            Definir inicial
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="ghost"
                          onClick={() => {
                            setEditPlanoId(p.id);
                            setPlanoForm(p);
                            setPlanoImagemFile(null);
                            setPlanoImagemPreview("");
                          }}
                        >
                          Editar
                        </button>
                        <button
                          type="button"
                          className="ghost danger"
                          onClick={() =>
                            void deletePlano(p.id).then(refreshPlanos).catch((err) =>
                              setError(err instanceof Error ? err.message : String(err)),
                            )
                          }
                        >
                          Excluir
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "promocoes" && (
          <section className="panel">
            <h1>Promoções</h1>
            <form className="form-grid" onSubmit={savePromo}>
              <label>
                Código
                <input
                  required
                  value={promoForm.codigo || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, codigo: e.target.value })}
                />
              </label>
              <label>
                Título
                <input
                  value={promoForm.titulo || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, titulo: e.target.value })}
                />
              </label>
              <label className="span2">
                Descrição
                <textarea
                  value={promoForm.descricao || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, descricao: e.target.value })}
                />
              </label>
              <label>
                Válido até
                <input
                  value={promoForm.valido_ate || ""}
                  onChange={(e) => setPromoForm({ ...promoForm, valido_ate: e.target.value })}
                  placeholder="YYYY-MM-DD"
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={!!promoForm.ativo}
                  onChange={(e) => setPromoForm({ ...promoForm, ativo: e.target.checked })}
                />
                Ativa
              </label>
              <div className="actions span2">
                <button type="submit">Salvar promoção</button>
              </div>
            </form>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Código</th>
                    <th>Título</th>
                    <th>Unidade</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {promos.map((p) => (
                    <tr key={p.id}>
                      <td>{p.codigo}</td>
                      <td>{p.titulo}</td>
                      <td>{p.unidade_id ?? "global"}</td>
                      <td>
                        <button
                          type="button"
                          className="ghost danger"
                          onClick={() =>
                            void deletePromocao(p.id).then(refreshPromos).catch((err) =>
                              setError(err instanceof Error ? err.message : String(err)),
                            )
                          }
                        >
                          Excluir
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {tab === "config" && (
          <section className="panel">
            <h1>Configurações IA</h1>
            <p className="muted">
              Motor OpenAI, identidade e chaves. Escopo: {uid ? `unidade #${uid}` : "global"}.
            </p>
            <form className="form-grid config-ia" onSubmit={saveConfig}>
              <label className="span2">
                Nome da IA
                <input
                  value={iaForm.nome_ia}
                  onChange={(e) => setIaForm({ ...iaForm, nome_ia: e.target.value })}
                />
              </label>
              <label className="span2">
                Tom de voz
                <textarea
                  value={iaForm.tom_voz}
                  onChange={(e) => setIaForm({ ...iaForm, tom_voz: e.target.value })}
                  rows={2}
                />
              </label>
              <label className="check span2" style={{ marginTop: 0 }}>
                <input
                  type="checkbox"
                  checked={iaForm.pode_emoji}
                  onChange={(e) => setIaForm({ ...iaForm, pode_emoji: e.target.checked })}
                />
                Pode usar emoji nas respostas
              </label>

              <label>
                Provedor
                <select
                  value={iaForm.llm_provider}
                  onChange={(e) => setIaForm({ ...iaForm, llm_provider: e.target.value })}
                >
                  <option value="openai">OpenAI</option>
                  <option value="ollama">Ollama (local)</option>
                </select>
              </label>
              <label>
                Modelo
                <select
                  value={iaForm.openai_model}
                  onChange={(e) => setIaForm({ ...iaForm, openai_model: e.target.value })}
                >
                  <option value="gpt-4.1-mini">gpt-4.1-mini</option>
                  <option value="gpt-4o-mini">gpt-4o-mini</option>
                  <option value="gpt-4o">gpt-4o</option>
                  <option value="gpt-4.1">gpt-4.1</option>
                </select>
              </label>
              <label>
                Temperatura
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={iaForm.llm_temperature}
                  onChange={(e) =>
                    setIaForm({ ...iaForm, llm_temperature: Number(e.target.value) })
                  }
                />
              </label>

              <label className="span2">
                API Key OpenAI{" "}
                {iaMasks.openai ? (
                  <span className="key-mask">(atual: {iaMasks.openai})</span>
                ) : (
                  <span className="key-mask muted-inline">(não configurada)</span>
                )}
                <input
                  type="password"
                  value={iaForm.openai_api_key}
                  onChange={(e) => setIaForm({ ...iaForm, openai_api_key: e.target.value })}
                  placeholder="•••• cole nova key para rotacionar"
                  autoComplete="off"
                />
              </label>

              <label className="span2">
                API Key transcrição de áudio{" "}
                {iaMasks.transcription ? (
                  <span className="key-mask">(atual: {iaMasks.transcription})</span>
                ) : (
                  <span className="key-mask muted-inline">(ainda não usada)</span>
                )}
                <input
                  type="password"
                  value={iaForm.transcription_api_key}
                  onChange={(e) =>
                    setIaForm({ ...iaForm, transcription_api_key: e.target.value })
                  }
                  placeholder="•••• cole nova key para rotacionar"
                  autoComplete="off"
                />
                <small className="field-hint">
                  Reserva para quando o cliente mandar áudio: transcreve pra texto antes da Eva
                  processar. Pode ser Groq/Whisper — implementação em seguida.
                </small>
              </label>

              <div className="config-box span2">
                <strong>RAG / conhecimento</strong>
                <small className="field-hint">
                  A Eva consulta este webhook do painel (não depende mais só do .env).
                </small>
                <label>
                  Modo RAG
                  <select
                    value={iaForm.rag_provider}
                    onChange={(e) => setIaForm({ ...iaForm, rag_provider: e.target.value })}
                  >
                    <option value="webhook">Webhook n8n (produção)</option>
                    <option value="mock">Mock local (teste)</option>
                    <option value="none">Desligada</option>
                  </select>
                </label>
                <label>
                  RAG webhook URL
                  <input
                    value={iaForm.rag_webhook_url}
                    onChange={(e) =>
                      setIaForm({
                        ...iaForm,
                        rag_webhook_url: e.target.value,
                        rag_provider: e.target.value.trim() ? "webhook" : iaForm.rag_provider,
                      })
                    }
                    placeholder="https://n8n.../webhook/RAG_VENDAS"
                  />
                </label>
                <label>
                  RAG webhook token{" "}
                  {iaMasks.rag_token ? (
                    <span className="key-mask">(atual: {iaMasks.rag_token})</span>
                  ) : null}
                  <input
                    type="password"
                    value={iaForm.rag_webhook_token}
                    onChange={(e) =>
                      setIaForm({ ...iaForm, rag_webhook_token: e.target.value })
                    }
                    placeholder="•••• cole novo token para rotacionar"
                    autoComplete="off"
                  />
                </label>
              </div>

              <div className="actions span2">
                <button type="submit">Salvar</button>
              </div>
            </form>
          </section>
        )}

        {tab === "integracao" && (
          <section className="panel">
            <h1>Integração Chatwoot</h1>
            <p className="muted">
              Receba mensagens do WhatsApp (Meta) direto do Chatwoot, filtre pela caixa de entrada da
              IA e responda pela ferramenta <code>enviar_mensagem</code>.
            </p>

            <div className="config-box" style={{ marginBottom: "1rem" }}>
              <strong>Status</strong>
              <ul className="muted" style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
                <li>
                  Entrada:{" "}
                  {cwForm.inbound_enabled ? (
                    <span className="badge badge-com_ia">Ativa</span>
                  ) : (
                    <span className="badge badge-finalizado">Desligada</span>
                  )}
                </li>
                <li>
                  Envio de respostas:{" "}
                  {cwMeta.envio_ok ? (
                    <span>OK (ferramenta ou .env)</span>
                  ) : (
                    <span className="muted-inline">
                      Configure a ferramenta <em>enviar_mensagem</em> na aba Ferramentas
                    </span>
                  )}
                </li>
              </ul>
            </div>

            <form className="form-grid config-ia" onSubmit={saveIntegracao}>
              <label className="check span2">
                <input
                  type="checkbox"
                  checked={cwForm.inbound_enabled}
                  onChange={(e) => setCwForm({ ...cwForm, inbound_enabled: e.target.checked })}
                />
                Receber mensagens do Chatwoot (webhook inbound)
              </label>

              <label className="span2">
                URL do webhook (cole no Chatwoot → Configurações → Webhooks)
                <div className="row-head" style={{ gap: "0.5rem", marginTop: "0.35rem" }}>
                  <input readOnly value={cwMeta.webhook_url} />
                  <button type="button" className="secondary" onClick={copyWebhookUrl}>
                    Copiar
                  </button>
                </div>
                <small className="field-hint">
                  Evento recomendado: <strong>message_created</strong> apenas. A Eva ignora outgoing,
                  notas privadas, inbox errado e conversas com time humano.
                </small>
              </label>

              <label>
                Caixa de entrada (inbox)
                <select
                  value={cwForm.inbox_id}
                  onChange={(e) => setCwForm({ ...cwForm, inbox_id: e.target.value })}
                >
                  <option value="">— selecione —</option>
                  {inboxes.map((box) => (
                    <option key={box.id} value={String(box.id)}>
                      {box.label}
                    </option>
                  ))}
                </select>
                <small className="field-hint">
                  Só mensagens desta inbox chegam na IA. Lista vem da API Chatwoot (.env token).
                </small>
              </label>

              <label>
                Modo de entrada
                <select
                  value={cwForm.inbound_mode}
                  onChange={(e) => setCwForm({ ...cwForm, inbound_mode: e.target.value })}
                >
                  <option value="allowlist">Allowlist (teste)</option>
                  <option value="open">Aberto (produção)</option>
                  <option value="closed">Fechado</option>
                </select>
              </label>

              <label className="span2">
                Allowlist (telefones de teste, CSV)
                <input
                  value={cwForm.allowlist_phones}
                  onChange={(e) => setCwForm({ ...cwForm, allowlist_phones: e.target.value })}
                  placeholder="93992219098, 93991234567"
                  disabled={cwForm.inbound_mode !== "allowlist"}
                />
              </label>

              <label>
                URL pública da API
                <input
                  value={cwForm.public_base_url}
                  onChange={(e) => setCwForm({ ...cwForm, public_base_url: e.target.value })}
                  placeholder="https://api.seudominio.com"
                />
                <small className="field-hint">
                  Usada para montar a URL do webhook. Em local: http://127.0.0.1:8001
                </small>
              </label>

              <label>
                Token do webhook (opcional)
                {cwMeta.token_configured ? (
                  <span className="key-mask"> (atual: {cwMeta.token_mask})</span>
                ) : null}
                <input
                  type="password"
                  value={cwForm.webhook_token}
                  onChange={(e) => setCwForm({ ...cwForm, webhook_token: e.target.value })}
                  placeholder="Header X-Webhook-Token"
                  autoComplete="off"
                />
              </label>

              <label className="check span2">
                <input
                  type="checkbox"
                  checked={cwForm.buffer_enabled}
                  onChange={(e) => setCwForm({ ...cwForm, buffer_enabled: e.target.checked })}
                />
                Agrupar mensagens rápidas (debounce ~3,5s antes de responder)
              </label>

              <div className="actions span2">
                <button type="submit">Salvar integração</button>
              </div>
            </form>

            <div className="config-box span2" style={{ marginTop: "1.5rem" }}>
              <strong>Testar payload do Chatwoot</strong>
              <small className="field-hint">
                Cole o JSON que o Chatwoot envia (ou use o exemplo) e veja como a Eva interpreta.
              </small>
              <textarea
                value={cwTestPayload}
                onChange={(e) => setCwTestPayload(e.target.value)}
                rows={14}
                style={{ width: "100%", marginTop: "0.5rem", fontFamily: "monospace", fontSize: "0.85rem" }}
              />
              <div className="actions" style={{ marginTop: "0.5rem" }}>
                <button type="button" onClick={() => void runTestParse()}>
                  Testar parse
                </button>
              </div>
              {cwTestResult && (
                <pre
                  style={{
                    marginTop: "0.75rem",
                    padding: "0.75rem",
                    background: "var(--surface-2, #1a1a1a)",
                    borderRadius: "6px",
                    overflow: "auto",
                    fontSize: "0.85rem",
                  }}
                >
                  {JSON.stringify(cwTestResult, null, 2)}
                </pre>
              )}
            </div>
          </section>
        )}

        {tab === "ferramentas" && (
          <section className="panel tool-panel">
            <div className="tool-layout">
              <form className="tool-form" onSubmit={saveTool}>
                <h1>{editToolId ? "Editar ferramenta" : "Criar ferramenta"}</h1>
                <div className="seg">
                  <button
                    type="button"
                    className={toolForm.integracao !== "unidade" ? "active" : ""}
                    onClick={() => setToolForm({ ...toolForm, integracao: "global", unidade_id: null })}
                  >
                    Personalizada
                  </button>
                  <button
                    type="button"
                    className={toolForm.integracao === "unidade" ? "active" : ""}
                    onClick={() => setToolForm({ ...toolForm, integracao: "unidade" })}
                  >
                    Por unidade
                  </button>
                </div>
                <label>
                  Chave da ferramenta
                  <input
                    required
                    value={toolForm.tool_key}
                    onChange={(e) => setToolForm({ ...toolForm, tool_key: e.target.value })}
                    placeholder="transferir_atendimento"
                  />
                </label>
                <label>
                  Nome da ferramenta
                  <input
                    required
                    value={toolForm.nome}
                    onChange={(e) => setToolForm({ ...toolForm, nome: e.target.value })}
                  />
                </label>
                <label>
                  Descrição
                  <textarea
                    value={toolForm.descricao}
                    onChange={(e) => setToolForm({ ...toolForm, descricao: e.target.value })}
                    rows={3}
                  />
                </label>
                <label>
                  URL do webhook
                  <input
                    value={toolForm.webhook_url}
                    onChange={(e) => setToolForm({ ...toolForm, webhook_url: e.target.value })}
                    placeholder="https://..."
                  />
                </label>
                {toolForm.integracao === "unidade" && (
                  <label>
                    Unidade
                    <select
                      value={toolForm.unidade_id ?? ""}
                      onChange={(e) =>
                        setToolForm({
                          ...toolForm,
                          unidade_id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    >
                      <option value="">Selecione</option>
                      {unidades.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.nome}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <div className="checks-row">
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={toolForm.destaque_dashboard}
                      onChange={(e) =>
                        setToolForm({ ...toolForm, destaque_dashboard: e.target.checked })
                      }
                    />
                    Destaque no dashboard
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={toolForm.ativo}
                      onChange={(e) => setToolForm({ ...toolForm, ativo: e.target.checked })}
                    />
                    Ativa
                  </label>
                </div>

                <div className="params-head">
                  <h2>Parâmetros</h2>
                  <button type="button" className="ghost" onClick={addParam}>
                    + Parâmetro
                  </button>
                </div>
                {toolForm.parametros.map((p, i) => (
                  <div className="param-row" key={i}>
                    <input
                      placeholder="Nome"
                      value={p.nome}
                      onChange={(e) => updateParam(i, { nome: e.target.value })}
                    />
                    <select
                      value={p.tipo}
                      onChange={(e) => updateParam(i, { tipo: e.target.value })}
                    >
                      <option value="texto">Texto</option>
                      <option value="numero">Número</option>
                      <option value="bool">Bool</option>
                    </select>
                    <input
                      placeholder="Descrição"
                      value={p.descricao}
                      onChange={(e) => updateParam(i, { descricao: e.target.value })}
                    />
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={p.obrigatorio}
                        onChange={(e) => updateParam(i, { obrigatorio: e.target.checked })}
                      />
                      Obrigatório
                    </label>
                    <button type="button" className="ghost danger" onClick={() => removeParam(i)}>
                      ×
                    </button>
                  </div>
                ))}

                <div className="actions">
                  <button type="submit">{editToolId ? "Atualizar" : "Criar ferramenta"}</button>
                  {editToolId ? (
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => {
                        setEditToolId(null);
                        setToolForm(emptyTool());
                      }}
                    >
                      Cancelar
                    </button>
                  ) : null}
                </div>
              </form>

              <div className="tool-list">
                <h2>Cadastradas</h2>
                {tools.map((t) => (
                  <div className="tool-card" key={t.id}>
                    <div>
                      <strong>{t.nome}</strong>
                      <small>{t.tool_key}</small>
                      <p>{t.descricao || "Sem descrição"}</p>
                      <small>
                        {t.parametros?.length || 0} params · {t.chamadas_sucesso} sucessos
                        {t.destaque_dashboard ? " · destaque" : ""}
                      </small>
                    </div>
                    <div className="row-actions">
                      <button type="button" className="ghost" onClick={() => editTool(t)}>
                        Editar
                      </button>
                      <button
                        type="button"
                        className="ghost danger"
                        onClick={() =>
                          void deleteFerramenta(t.id).then(refreshTools).catch((err) =>
                            setError(err instanceof Error ? err.message : String(err)),
                          )
                        }
                      >
                        Excluir
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {tab === "unidades" && (
          <section className="panel">
            <h1>Unidades</h1>
            <p className="muted">Filiais / cidades operacionais.</p>
            <form className="form-grid narrow" onSubmit={saveUnidade}>
              <label>
                Código
                <input
                  required
                  value={novaUnidade.codigo}
                  onChange={(e) => setNovaUnidade({ ...novaUnidade, codigo: e.target.value })}
                />
              </label>
              <label>
                Nome
                <input
                  required
                  value={novaUnidade.nome}
                  onChange={(e) => setNovaUnidade({ ...novaUnidade, nome: e.target.value })}
                />
              </label>
              <div className="actions span2">
                <button type="submit">Criar unidade</button>
              </div>
            </form>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Código</th>
                    <th>Nome</th>
                    <th>Ativo</th>
                  </tr>
                </thead>
                <tbody>
                  {unidades.map((u) => (
                    <tr key={u.id}>
                      <td>{u.codigo}</td>
                      <td>{u.nome}</td>
                      <td>{u.ativo ? "sim" : "não"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
